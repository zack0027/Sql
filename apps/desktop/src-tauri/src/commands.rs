//! Tauri commands — the surface the webview is allowed to call.
//!
//! Two responsibilities live here and nowhere else:
//!
//! * **The allowed-roots check.** A project's folder becomes readable only when
//!   the user opens it. Every scan re-verifies that the root is still on the
//!   list, so a compromised webview cannot point the scanner at `C:\Users`.
//! * **The scan itself.** Walking and hashing happen natively (`jarvis-fs`); the
//!   resulting inventory is handed to the engine, which owns the database.

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};

use jarvis_fs::{scan_project, ScanPolicy, ScannedFile};
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
/// This is the only command that widens what JARVIS may read, and it does so
/// only for the folder the user chose in the OS dialog.
#[tauri::command]
pub async fn open_project(
    state: State<'_, AppState>,
    path: String,
    name: Option<String>,
) -> CommandResult<Value> {
    let root = jarvis_fs::resolve_project_root(&path).map_err(|error| error.to_string())?;

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

    let root = jarvis_fs::resolve_project_root(&root_path).map_err(|error| error.to_string())?;
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
                    "jarvis://progress",
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
