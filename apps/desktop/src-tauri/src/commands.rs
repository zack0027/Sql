//! Tauri commands — the surface the webview is allowed to call.
//!
//! Two responsibilities live here and nowhere else:
//!
//! * **The allowed-roots check.** A project's folder becomes readable only when
//!   the user opens it. Every scan re-verifies that the root is still on the
//!   list, so a compromised webview cannot point the scanner at `C:\Users`.
//! * **The scan itself.** Walking and hashing happen natively (`hana-fs`); the
//!   resulting inventory is handed to the engine, which owns the database.

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};

use hana_fs::{scan_project, ScanPolicy, ScannedFile};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, State};

use crate::sidecar::Sidecar;

/// Application state shared by every command.
pub struct AppState {
    pub sidecar: Arc<Sidecar>,
    /// Folders the user has explicitly opened. Nothing outside them is read.
    pub allowed_roots: Mutex<HashSet<PathBuf>>,
    /// Set while a scan is running so `cancel_analysis` can stop it natively.
    pub scan_cancel: Mutex<Option<Arc<AtomicBool>>>,
}

impl AppState {
    pub fn new(sidecar: Arc<Sidecar>) -> Self {
        Self {
            sidecar,
            allowed_roots: Mutex::new(HashSet::new()),
            scan_cancel: Mutex::new(None),
        }
    }

    fn allow(&self, root: PathBuf) {
        if let Ok(mut roots) = self.allowed_roots.lock() {
            roots.insert(root);
        }
    }

    fn is_allowed(&self, root: &PathBuf) -> bool {
        self.allowed_roots
            .lock()
            .map(|roots| roots.contains(root))
            .unwrap_or(false)
    }
}

type CommandResult<T> = Result<T, String>;

/// Run a blocking engine call off the UI thread.
async fn call(sidecar: Arc<Sidecar>, method: &'static str, params: Value) -> CommandResult<Value> {
    tauri::async_runtime::spawn_blocking(move || sidecar.request(method, params))
        .await
        .map_err(|error| format!("fallo interno del host: {error}"))?
}

/// Query methods the webview may invoke.
///
/// A single passthrough command keeps fourteen near-identical wrappers out of
/// this file, but it must not become a way to reach *any* engine method: that
/// would let a compromised webview call `project.delete` through a command
/// meant for reading. The allowlist is the whole point — every name here is
/// read-only.
const QUERY_METHODS: &[&str] = &[
    "query.search",
    "query.resolve",
    "query.entity",
    "query.uses",
    "query.dependents",
    "query.dependencies",
    "query.tables_of_file",
    "query.entities_in_file",
    "query.reports_using_table",
    "query.images_of_report",
    "query.changes",
    "query.errors",
    "query.low_confidence",
    "query.neighborhood",
    "query.er_model",
    "query.report_structure",
    "query.freshness",
    "query.impact",
    "query.orphans",
    // Reading what a person recorded is a query like any other. *Writing* one
    // is not, and goes through `set_annotation` / `clear_annotation` below —
    // this list stays read-only, which is the only thing making it a safeguard.
    "annotation.list",
];

/// Run one read-only query against the knowledge graph.
#[tauri::command]
pub async fn run_query(
    state: State<'_, AppState>,
    method: String,
    params: Value,
) -> CommandResult<Value> {
    let allowed = QUERY_METHODS
        .iter()
        .find(|candidate| **candidate == method)
        .ok_or_else(|| format!("consulta no permitida: {method}"))?;

    let sidecar = Arc::clone(&state.sidecar);
    // `allowed` is a &'static str from the table, which is what `call` needs and
    // also guarantees the string sent to the engine is one we compiled in.
    let name: &'static str = allowed;
    tauri::async_runtime::spawn_blocking(move || sidecar.request(name, params))
        .await
        .map_err(|error| format!("fallo interno del host: {error}"))?
}

/// Record a person's verdict on an entity or a relationship.
///
/// Its own command rather than a name in `QUERY_METHODS`, because this one
/// writes. Keeping the passthrough strictly read-only is what makes the
/// allowlist mean anything.
#[tauri::command]
pub async fn set_annotation(
    state: State<'_, AppState>,
    project_id: String,
    target_kind: String,
    target_id: String,
    verdict: String,
    note: Option<String>,
) -> CommandResult<Value> {
    call(
        Arc::clone(&state.sidecar),
        "annotation.set",
        json!({
            "project_id": project_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "verdict": verdict,
            "note": note,
        }),
    )
    .await
}

/// Withdraw a verdict.
#[tauri::command]
pub async fn clear_annotation(
    state: State<'_, AppState>,
    project_id: String,
    target_kind: String,
    target_key: String,
) -> CommandResult<Value> {
    call(
        Arc::clone(&state.sidecar),
        "annotation.clear",
        json!({
            "project_id": project_id,
            "target_kind": target_kind,
            "target_key": target_key,
        }),
    )
    .await
}

/// Largest file the viewer will load. Beyond this the editor is useless anyway
/// and the webview would stall trying to render it.
const MAX_VIEWABLE_BYTES: u64 = 4 * 1024 * 1024;

/// Read one file of an open project, for the code viewer.
///
/// This is the only command that returns file *contents*, so it repeats the
/// whole boundary rather than trusting the caller: the path must resolve inside
/// a root the user opened this session. A project id is not authorisation, and
/// neither is a path the webview happens to know.
#[tauri::command]
pub async fn read_project_file(
    state: State<'_, AppState>,
    project_id: String,
    relative_path: String,
) -> CommandResult<Value> {
    let project = call(
        Arc::clone(&state.sidecar),
        "project.get",
        json!({ "project_id": project_id }),
    )
    .await?;

    let root_path = project
        .get("root_path")
        .and_then(Value::as_str)
        .ok_or("el proyecto no tiene ruta")?;
    let root = jarvis_root(root_path)?;

    if !state.is_allowed(&root) {
        return Err(format!(
            "la carpeta {} no está autorizada en esta sesión; ábrela de nuevo",
            root.display()
        ));
    }

    let candidate = root.join(relative_path.replace('/', std::path::MAIN_SEPARATOR_STR));
    if !hana_fs::is_within(&root, &candidate) {
        // A crafted `../` or a symlink would otherwise read outside the project.
        return Err("la ruta queda fuera del proyecto".to_string());
    }

    let metadata =
        std::fs::metadata(&candidate).map_err(|error| format!("no se pudo leer: {error}"))?;
    if metadata.len() > MAX_VIEWABLE_BYTES {
        return Err(format!(
            "el archivo mide {:.1} MB; el visor admite hasta {} MB",
            metadata.len() as f64 / (1024.0 * 1024.0),
            MAX_VIEWABLE_BYTES / (1024 * 1024)
        ));
    }

    let bytes = std::fs::read(&candidate).map_err(|error| format!("no se pudo leer: {error}"))?;
    // Oracle and MOCA exports are routinely cp1252; decoding lossily shows the
    // file instead of refusing it over one bad byte.
    let text = match String::from_utf8(bytes.clone()) {
        Ok(value) => value,
        Err(_) => bytes.iter().map(|byte| *byte as char).collect(),
    };

    Ok(json!({
        "relative_path": relative_path,
        "absolute_path": candidate.to_string_lossy(),
        "size_bytes": metadata.len(),
        "content": text,
    }))
}

fn jarvis_root(path: &str) -> CommandResult<PathBuf> {
    hana_fs::resolve_project_root(path).map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn engine_status(state: State<'_, AppState>) -> CommandResult<Value> {
    call(Arc::clone(&state.sidecar), "engine.status", json!({})).await
}

#[tauri::command]
pub async fn list_projects(state: State<'_, AppState>, limit: Option<u32>) -> CommandResult<Value> {
    call(
        Arc::clone(&state.sidecar),
        "project.list",
        json!({ "limit": limit.unwrap_or(20) }),
    )
    .await
}

/// Register a folder as a project and add it to the allowed roots.
///
/// This is the only command that widens what HANA may read, and it does so
/// only for the folder the user chose in the OS dialog.
#[tauri::command]
pub async fn open_project(
    state: State<'_, AppState>,
    path: String,
    name: Option<String>,
) -> CommandResult<Value> {
    let root = hana_fs::resolve_project_root(&path).map_err(|error| error.to_string())?;

    let project = call(
        Arc::clone(&state.sidecar),
        "project.open",
        json!({ "path": root.to_string_lossy(), "name": name }),
    )
    .await?;

    state.allow(root);
    Ok(project)
}

#[tauri::command]
pub async fn delete_project(
    state: State<'_, AppState>,
    project_id: String,
) -> CommandResult<Value> {
    call(
        Arc::clone(&state.sidecar),
        "project.delete",
        json!({ "project_id": project_id }),
    )
    .await
}

#[tauri::command]
pub async fn project_stats(
    state: State<'_, AppState>,
    project_id: String,
) -> CommandResult<Value> {
    call(
        Arc::clone(&state.sidecar),
        "project.stats",
        json!({ "project_id": project_id }),
    )
    .await
}

#[tauri::command]
pub async fn project_files(
    state: State<'_, AppState>,
    project_id: String,
) -> CommandResult<Value> {
    call(
        Arc::clone(&state.sidecar),
        "project.files",
        json!({ "project_id": project_id }),
    )
    .await
}

#[tauri::command]
pub async fn scan_policy(state: State<'_, AppState>, project_id: String) -> CommandResult<Value> {
    call(
        Arc::clone(&state.sidecar),
        "project.scan_policy.get",
        json!({ "project_id": project_id }),
    )
    .await
}

/// Replace a project's scan policy.
///
/// Sent through as opaque JSON rather than a typed struct: the engine owns the
/// policy's shape and validates it (`ScanPolicy.from_dict` drops unknown keys),
/// and mirroring the fields here would create a second definition to keep in
/// step with the first.
#[tauri::command]
pub async fn set_scan_policy(
    state: State<'_, AppState>,
    project_id: String,
    policy: Value,
) -> CommandResult<Value> {
    call(
        Arc::clone(&state.sidecar),
        "project.scan_policy.set",
        json!({ "project_id": project_id, "policy": policy }),
    )
    .await
}

#[tauri::command]
pub async fn analysis_history(
    state: State<'_, AppState>,
    project_id: String,
    limit: Option<u32>,
) -> CommandResult<Value> {
    call(
        Arc::clone(&state.sidecar),
        "analysis.history",
        json!({ "project_id": project_id, "limit": limit.unwrap_or(25) }),
    )
    .await
}

/// Scan the project natively, then hand the inventory to the engine.
///
/// The split is deliberate: Rust does the walking, hashing and cancellation
/// (fast, and it is the process that holds the OS permissions), the engine does
/// the diffing, analysis and persistence.
#[tauri::command]
pub async fn analyze_project(
    app: AppHandle,
    state: State<'_, AppState>,
    project_id: String,
) -> CommandResult<Value> {
    let sidecar = Arc::clone(&state.sidecar);

    let project = call(
        Arc::clone(&sidecar),
        "project.get",
        json!({ "project_id": project_id }),
    )
    .await?;

    let root_path = project
        .get("root_path")
        .and_then(Value::as_str)
        .ok_or("el proyecto no tiene ruta")?
        .to_string();

    let root = hana_fs::resolve_project_root(&root_path).map_err(|error| error.to_string())?;
    if !state.is_allowed(&root) {
        // Reopening the project is what re-grants access, and it goes through the
        // OS dialog. A stale project id alone is not authorisation.
        return Err(format!(
            "la carpeta {} no está autorizada en esta sesión; ábrela de nuevo",
            root.display()
        ));
    }

    let policy_json = call(
        Arc::clone(&sidecar),
        "project.scan_policy.get",
        json!({ "project_id": project_id }),
    )
    .await?;
    let policy: ScanPolicy = serde_json::from_value(policy_json).unwrap_or_default();

    let cancel = Arc::new(AtomicBool::new(false));
    if let Ok(mut slot) = state.scan_cancel.lock() {
        *slot = Some(Arc::clone(&cancel));
    }

    let scan_app = app.clone();
    let scan_project_id = project_id.clone();
    let scan_cancel = Arc::clone(&cancel);
    let report = tauri::async_runtime::spawn_blocking(move || {
        scan_project(
            &root,
            &policy,
            Some(&|progress| {
                // Mirrors the engine's ProgressEvent shape so the UI has one
                // listener for both native and engine-side phases.
                let _ = scan_app.emit(
                    "hana://progress",
                    json!({
                        "project_id": scan_project_id,
                        "run_id": Value::Null,
                        "phase": "scanning",
                        "current": progress.files_seen,
                        "total": 0,
                        "message": progress.current_path,
                    }),
                );
            }),
            Some(scan_cancel),
        )
    })
    .await
    .map_err(|error| format!("fallo interno del host: {error}"))?
    .map_err(|error| error.to_string())?;

    if let Ok(mut slot) = state.scan_cancel.lock() {
        *slot = None;
    }

    if report.cancelled {
        return Err("análisis cancelado durante el escaneo".to_string());
    }

    // Skipped files travel too: the user must be able to see that a 40 MB export
    // exists and was deliberately not read.
    let inventory: Vec<&ScannedFile> = report.files.iter().chain(report.skipped.iter()).collect();

    call(
        sidecar,
        "analysis.run",
        json!({
            "project_id": project_id,
            "trigger": "desktop",
            "scanned_files": inventory,
        }),
    )
    .await
}

#[tauri::command]
pub async fn cancel_analysis(
    state: State<'_, AppState>,
    project_id: String,
) -> CommandResult<Value> {
    // Stop the native scan first, then tell the engine. Either phase may be the
    // one currently running.
    if let Ok(slot) = state.scan_cancel.lock() {
        if let Some(flag) = slot.as_ref() {
            flag.store(true, std::sync::atomic::Ordering::Relaxed);
        }
    }
    call(
        Arc::clone(&state.sidecar),
        "analysis.cancel",
        json!({ "project_id": project_id }),
    )
    .await
}
