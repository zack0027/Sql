//! Supervision of the Python engine process.
//!
//! The engine runs as a child process speaking JSON-Lines over stdin/stdout. This
//! module owns its lifetime, correlates requests with responses, and forwards the
//! engine's unsolicited events to the webview.
//!
//! No sockets are opened. The child inherits no network capability it would not
//! otherwise have, and the only channel between it and the UI is this pipe.

use std::collections::HashMap;
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

type Pending = Arc<Mutex<HashMap<String, Sender<Result<Value, String>>>>>;

pub struct Sidecar {
    child: Mutex<Child>,
    stdin: Mutex<ChildStdin>,
    pending: Pending,
    next_id: AtomicU64,
}

impl Sidecar {
    /// Start the engine and begin pumping its output.
    pub fn spawn(app: AppHandle, database_path: PathBuf) -> Result<Self, String> {
        let (program, args) = resolve_engine_command();

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
                        dispatch(&app, &pending, frame);
                    }
                    // The child died: unblock every waiter rather than let the UI
                    // hang forever.
                    let mut waiting = pending.lock().unwrap();
                    for (_, sender) in waiting.drain() {
                        let _ = sender.send(Err("el motor se detuvo".to_string()));
                    }
                })
                .map_err(|error| error.to_string())?;
        }

        // Engine stderr is a diagnostic channel, never protocol. Surfacing it in
        // the host log is what makes a Python traceback findable.
        if let Some(stderr) = stderr {
            std::thread::Builder::new()
                .name("hana-sidecar-stderr".into())
                .spawn(move || {
                    for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                        eprintln!("[engine] {line}");
                    }
                })
                .ok();
        }

        Ok(Self {
            child: Mutex::new(child),
            stdin: Mutex::new(stdin),
            pending,
            next_id: AtomicU64::new(1),
        })
    }

    /// Send a request and block until the engine answers.
    ///
    /// Callers must run this off the UI thread (`spawn_blocking`).
    pub fn request(&self, method: &str, params: Value) -> Result<Value, String> {
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
            stdin
                .write_all(line.as_bytes())
                .and_then(|_| stdin.flush())
                .map_err(|error| format!("no se pudo escribir al motor: {error}"))?;
        }

        match receiver.recv_timeout(REQUEST_TIMEOUT) {
            Ok(result) => result,
            Err(_) => {
                self.pending.lock().ok().and_then(|mut map| map.remove(&id));
                Err(format!("el motor no respondió a '{method}' a tiempo"))
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
fn resolve_engine_command() -> (String, Vec<String>) {
    if let Ok(custom) = std::env::var("HANA_ENGINE_CMD") {
        let mut parts = custom.split_whitespace().map(str::to_string);
        if let Some(program) = parts.next() {
            return (program, parts.collect());
        }
    }

    if let Some(bundled) = bundled_engine_path() {
        return (bundled.to_string_lossy().to_string(), Vec::new());
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
