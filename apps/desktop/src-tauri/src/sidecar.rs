//! Supervision of the Python engine process.
//!
//! The engine runs as a child process speaking JSON-Lines over stdin/stdout. This
//! module owns its lifetime, correlates requests with responses, and forwards the
//! engine's unsolicited events to the webview.
//!
//! No sockets are opened. The child inherits no network capability it would not
//! otherwise have, and the only channel between it and the UI is this pipe.

use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};

/// How long a single engine call may take before the UI gets an error instead of
/// hanging. Analysis runs report progress, so a silent minute means trouble.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(600);

/// Event name the frontend listens on for analysis progress.
const PROGRESS_EVENT: &str = "hana://progress";

/// Lines of engine stderr kept for the error message.
///
/// A Python traceback is about a dozen lines and its last line is the one that
/// names the failure, so the tail is what matters.
const STDERR_MEMORY: usize = 40;

/// What the reader thread reports when the engine's output ends.
const ENGINE_STOPPED: &str = "el motor se detuvo";

/// How long the engine has to announce itself before the app gives up on it.
///
/// Generous: a frozen binary has to unpack itself on first run, and an antivirus
/// scanning it can add several seconds on a machine that has never seen it.
const READY_TIMEOUT: Duration = Duration::from_secs(30);

/// Windows' `STILL_ACTIVE`: not an exit code, a statement that there isn't one.
const STILL_ACTIVE: i32 = 259;

type Pending = Arc<Mutex<HashMap<String, Sender<Result<Value, String>>>>>;

/// The engine's last words, for when it dies.
type Chatter = Arc<Mutex<VecDeque<String>>>;

pub struct Sidecar {
    child: Mutex<Child>,
    stdin: Mutex<ChildStdin>,
    pending: Pending,
    next_id: AtomicU64,
    /// Tail of the engine's stderr, so a dead engine can say why.
    stderr_tail: Chatter,
    /// Where that stderr is also being written, to be sent to whoever can help.
    log_path: PathBuf,
    /// The command line actually used, quoted back when it fails.
    launched: String,
    /// Set when the engine never announced itself; returned to every caller.
    startup_error: Mutex<Option<String>>,
    /// Handed to the watchdog once, by `watch_startup`.
    ready_rx: Mutex<Option<Receiver<()>>>,
    /// The bundled engine was missing and the development path was tried.
    fell_back: bool,
}

impl Sidecar {
    /// Start the engine and begin pumping its output.
    pub fn spawn(app: AppHandle, database_path: PathBuf) -> Result<Self, String> {
        let (program, args, fell_back) = resolve_engine_command();

        let mut command = Command::new(&program);
        command
            .args(&args)
            .arg(database_path.to_string_lossy().to_string())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            // Unbuffered stdout, otherwise responses sit in the child's buffer.
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8");

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }

        let mut child = command.spawn().map_err(|error| {
            format!("no se pudo iniciar el motor ({}): {error}", program)
        })?;

        let stdin = child.stdin.take().ok_or("el motor no expuso stdin")?;
        let stdout = child.stdout.take().ok_or("el motor no expuso stdout")?;
        let stderr = child.stderr.take();

        let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
        let (ready_tx, ready_rx) = channel::<()>();

        // Reader: responses go to whoever is waiting, events go to the webview.
        {
            let pending = Arc::clone(&pending);
            let app = app.clone();
            std::thread::Builder::new()
                .name("hana-sidecar-reader".into())
                .spawn(move || {
                    // Read raw bytes and decode lossily rather than using
                    // `lines()`, whose UTF-8 error would end the loop. One
                    // undecodable byte used to tear down the whole connection:
                    // every pending request failed with "the engine stopped"
                    // and the analysis hung forever. A bad line is skipped; only
                    // a closed pipe ends the stream.
                    let mut reader = BufReader::new(stdout);
                    let mut buffer: Vec<u8> = Vec::new();
                    loop {
                        buffer.clear();
                        match reader.read_until(b'\n', &mut buffer) {
                            Ok(0) => break, // the child closed its output
                            Ok(_) => {}
                            Err(_) => break,
                        }
                        let line = String::from_utf8_lossy(&buffer).to_string();
                        if line.trim().is_empty() {
                            continue;
                        }
                        let Ok(frame) = serde_json::from_str::<Value>(&line) else {
                            continue;
                        };
                        if frame.get("event").and_then(Value::as_str) == Some("ready") {
                            let _ = ready_tx.send(());
                        }
                        dispatch(&app, &pending, frame);
                    }
                    // The child died: unblock every waiter rather than let the UI
                    // hang forever.
                    let mut waiting = pending.lock().unwrap();
                    for (_, sender) in waiting.drain() {
                        let _ = sender.send(Err(ENGINE_STOPPED.to_string()));
                    }
                })
                .map_err(|error| error.to_string())?;
        }

        // Engine stderr is a diagnostic channel, never protocol.
        //
        // It used to go to `eprintln!`, which in a windowed Windows build goes
        // nowhere at all: when the engine died on someone else's machine, the
        // only thing they saw was "the pipe is being closed", and the traceback
        // that said why had been written to a handle nobody owned. So it is kept
        // in memory for the error message and written to a file they can send.
        let stderr_tail: Chatter = Arc::new(Mutex::new(VecDeque::with_capacity(STDERR_MEMORY)));
        let log_path = database_path.with_file_name("engine.log");

        if let Some(stderr) = stderr {
            let tail = Arc::clone(&stderr_tail);
            // Truncated per run: the interesting failure is this one, and an
            // ever-growing log in the user's profile is its own bug.
            let mut file = std::fs::File::create(&log_path).ok();
            std::thread::Builder::new()
                .name("hana-sidecar-stderr".into())
                .spawn(move || {
                    for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                        if let Some(file) = file.as_mut() {
                            let _ = writeln!(file, "{line}");
                            let _ = file.flush();
                        }
                        if let Ok(mut tail) = tail.lock() {
                            if tail.len() == STDERR_MEMORY {
                                tail.pop_front();
                            }
                            tail.push_back(line);
                        }
                    }
                })
                .ok();
        }

        let sidecar = Self {
            child: Mutex::new(child),
            stdin: Mutex::new(stdin),
            pending,
            next_id: AtomicU64::new(1),
            stderr_tail,
            log_path,
            launched: format!("{program} {}", args.join(" ")).trim_end().to_string(),
            startup_error: Mutex::new(None),
            ready_rx: Mutex::new(Some(ready_rx)),
            fell_back,
        };

        Ok(sidecar)
    }

    /// Watch for the engine's greeting, and remember if it never comes.
    ///
    /// Deliberately not done inside `spawn`: that runs in Tauri's setup, and
    /// blocking there would leave the application's state unregistered for the
    /// whole timeout — the window is already on screen by then and its first
    /// calls would fail for a second, unrelated reason. So the wait happens on
    /// its own thread, and the verdict lands in `startup_error` for whoever asks
    /// next.
    ///
    /// Failing outright was the other option and it is worse: a windowed
    /// application that aborts its setup leaves nothing on screen at all.
    pub fn watch_startup(self: &Arc<Self>) {
        let Some(ready_rx) = self.ready_rx.lock().ok().and_then(|mut slot| slot.take()) else {
            return;
        };
        let sidecar = Arc::clone(self);
        std::thread::Builder::new()
            .name("hana-sidecar-startup".into())
            .spawn(move || {
                if ready_rx.recv_timeout(READY_TIMEOUT).is_ok() {
                    return;
                }
                let reason = sidecar.startup_reason(sidecar.fell_back);
                if let Ok(mut slot) = sidecar.startup_error.lock() {
                    *slot = Some(reason);
                }
            })
            .ok();
    }

    /// Lead with what the reader can act on.
    ///
    /// A missing engine binary has essentially one cause in the wild — the
    /// application was launched without the rest of its folder, usually by
    /// double-clicking inside the .zip — and naming that is worth more than any
    /// exit code.
    fn startup_reason(&self, fell_back: bool) -> String {
        if fell_back {
            format!(
                "Falta hana-engine.exe junto a la aplicación. \
                 Descomprime la carpeta completa y ejecuta hana-desktop.exe \
                 desde ahí; abrirlo dentro del .zip no funciona. \
                 (se recurrió a «{}», que es la vía de desarrollo: {})",
                self.launched,
                self.diagnosis()
            )
        } else {
            format!(
                "El motor no arrancó. Se ejecutó «{}». {}",
                self.launched,
                self.diagnosis()
            )
        }
    }

    /// Why the engine is not answering — as much as can honestly be said.
    ///
    /// Called when a request fails, because by then the useful facts (did the
    /// process exit? with what? what did it print?) are the ones the raw I/O
    /// error leaves out. "The pipe is being closed" is true and useless; "the
    /// engine exited with code 1" plus its last line is something a person can
    /// act on.
    fn diagnosis(&self) -> String {
        let status = self
            .child
            .lock()
            .ok()
            .and_then(|mut child| child.try_wait().ok().flatten());

        let mut parts = Vec::new();
        match status.and_then(|status| status.code()) {
            // 259 is STILL_ACTIVE, Windows' sentinel for "this process has not
            // exited". Reporting it as an exit code invents a failure that never
            // happened. It shows up here because the frozen engine is a
            // PyInstaller one-file build: the executable we launched is a
            // bootloader that unpacks itself and runs the real interpreter as a
            // *second* process. When the inner one dies the pipes break, while
            // the outer one is still winding down.
            Some(STILL_ACTIVE) => parts.push(
                "el proceso interno del motor murió; el lanzador seguía cerrándose"
                    .to_string(),
            ),
            Some(code) => parts.push(format!("el motor terminó con código {code}")),
            None if status.is_some() => {
                parts.push("el motor fue terminado por el sistema".to_string())
            }
            None => parts.push("el motor sigue vivo pero no responde".to_string()),
        }

        let said = self.stderr_tail.lock().ok().map(|tail| {
            // The last lines, not the first: a traceback names its failure at
            // the end.
            tail.iter()
                .rev()
                .take(6)
                .map(String::as_str)
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect::<Vec<_>>()
                .join(" · ")
        });

        match said.as_deref() {
            Some("") | None => parts.push(
                // The absence is the evidence. Python that fails on its own
                // leaves a traceback; silence means something outside the
                // process ended it — an antivirus, a policy, or the machine
                // running out of memory.
                "no dejó ningún mensaje, lo que apunta a que algo externo lo \
                 cerró (antivirus, política del equipo o falta de memoria)"
                    .to_string(),
            ),
            Some(text) => parts.push(format!("dijo: {text}")),
        }

        parts.push(format!("detalle completo en {}", self.log_path.display()));
        parts.join(". ")
    }

    /// Send a request and block until the engine answers.
    ///
    /// Callers must run this off the UI thread (`spawn_blocking`).
    pub fn request(&self, method: &str, params: Value) -> Result<Value, String> {
        // An engine that never started cannot be asked anything, and the reason
        // it did not start is more useful than any error the attempt produces.
        if let Ok(problem) = self.startup_error.lock() {
            if let Some(reason) = problem.as_ref() {
                return Err(reason.clone());
            }
        }

        let id = self.next_id.fetch_add(1, Ordering::Relaxed).to_string();
        let (sender, receiver): (_, Receiver<Result<Value, String>>) = channel();

        self.pending
            .lock()
            .map_err(|_| "estado del motor corrupto".to_string())?
            .insert(id.clone(), sender);

        let payload = json!({ "id": id, "method": method, "params": params });
        let line = format!("{payload}\n");

        {
            let mut stdin = self
                .stdin
                .lock()
                .map_err(|_| "estado del motor corrupto".to_string())?;
            // A write failure here almost always means the child is gone, and
            // the OS error alone ("the pipe is being closed") describes the
            // symptom rather than the cause.
            if let Err(error) = stdin.write_all(line.as_bytes()).and_then(|_| stdin.flush()) {
                self.pending.lock().ok().and_then(|mut map| map.remove(&id));
                return Err(format!(
                    "el motor no está disponible ({error}). {}",
                    self.diagnosis()
                ));
            }
        }

        match receiver.recv_timeout(REQUEST_TIMEOUT) {
            // The reader thread reports a dead engine with a bare sentinel; it
            // has no access to the exit status, so the detail is added here.
            Ok(Err(reason)) if reason == ENGINE_STOPPED => {
                Err(format!("{reason}. {}", self.diagnosis()))
            }
            Ok(result) => result,
            Err(_) => {
                self.pending.lock().ok().and_then(|mut map| map.remove(&id));
                Err(format!(
                    "el motor no respondió a '{method}' a tiempo. {}",
                    self.diagnosis()
                ))
            }
        }
    }

    /// Stop the engine. Best effort: the process is killed if it does not exit.
    pub fn shutdown(&self) {
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

impl Drop for Sidecar {
    fn drop(&mut self) {
        self.shutdown();
    }
}

fn dispatch(app: &AppHandle, pending: &Pending, frame: Value) {
    if let Some(event) = frame.get("event").and_then(Value::as_str) {
        if event == "progress" {
            let data = frame.get("data").cloned().unwrap_or(Value::Null);
            let _ = app.emit(PROGRESS_EVENT, data);
        }
        return;
    }

    let Some(id) = frame.get("id").and_then(Value::as_str) else {
        return;
    };
    let Some(sender) = pending.lock().ok().and_then(|mut map| map.remove(id)) else {
        return;
    };

    let outcome = if frame.get("ok").and_then(Value::as_bool).unwrap_or(false) {
        Ok(frame.get("result").cloned().unwrap_or(Value::Null))
    } else {
        Err(frame
            .get("error")
            .and_then(|error| error.get("message"))
            .and_then(Value::as_str)
            .unwrap_or("error desconocido del motor")
            .to_string())
    };

    let _ = sender.send(outcome);
}

/// Decide how to launch the engine.
///
/// Three cases, in order:
/// 1. `HANA_ENGINE_CMD` — an explicit override, used by integration tests.
/// 2. A bundled `hana-engine` binary next to the executable — the packaged app.
/// 3. `python -m hana_engine.ipc.server` — the development checkout.
///
/// The third element says the bundled engine was missing and Python was tried
/// instead. That distinction is the whole diagnosis when a packaged copy fails
/// on someone else's machine: the fallback quietly succeeds on a developer's
/// machine, where the package is installed, and fails everywhere else.
fn resolve_engine_command() -> (String, Vec<String>, bool) {
    if let Ok(custom) = std::env::var("HANA_ENGINE_CMD") {
        let mut parts = custom.split_whitespace().map(str::to_string);
        if let Some(program) = parts.next() {
            return (program, parts.collect(), false);
        }
    }

    if let Some(bundled) = bundled_engine_path() {
        return (bundled.to_string_lossy().to_string(), Vec::new(), false);
    }

    let python = std::env::var("HANA_PYTHON").unwrap_or_else(|_| {
        if cfg!(windows) {
            "python".to_string()
        } else {
            "python3".to_string()
        }
    });
    (
        python,
        vec!["-m".to_string(), "hana_engine.ipc.server".to_string()],
        true,
    )
}

/// Locate the frozen engine that ships with the application.
///
/// Tauri copies an `externalBin` next to the executable with the target-triple
/// suffix stripped, so the plain name is checked first. During `tauri dev` the
/// binary can still be sitting in `binaries/` under its full name, so the
/// directory is also scanned by prefix rather than hard-coding a triple this
/// crate has no clean way to know at runtime.
fn bundled_engine_path() -> Option<PathBuf> {
    let executable = std::env::current_exe().ok()?;
    let directory = executable.parent()?;

    let plain = directory.join(if cfg!(windows) {
        "hana-engine.exe"
    } else {
        "hana-engine"
    });
    if plain.is_file() {
        return Some(plain);
    }

    for folder in [directory, &directory.join("binaries")] {
        let Ok(entries) = std::fs::read_dir(folder) else {
            continue;
        };
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if name.starts_with("hana-engine") && entry.path().is_file() {
                return Some(entry.path());
            }
        }
    }

    None
}
