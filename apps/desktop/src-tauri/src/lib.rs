//! HANA desktop shell.
//!
//! The host's job is narrow on purpose: start the engine, expose a small set of
//! commands, own the filesystem boundary, and get out of the way. All knowledge
//! lives in the engine; all rendering lives in the webview.

mod commands;
mod sidecar;

use std::path::PathBuf;
use std::sync::Arc;

use tauri::Manager;

use commands::AppState;
use sidecar::Sidecar;

/// Filename of the knowledge base inside the app-data directory.
const DATABASE_FILENAME: &str = "hana.db";

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let database_path = database_path(app.handle())?;
            if let Some(parent) = database_path.parent() {
                std::fs::create_dir_all(parent)?;
            }

            let sidecar = Arc::new(
                Sidecar::spawn(app.handle().clone(), database_path)
                    .map_err(std::io::Error::other)?,
            );
            app.manage(AppState::new(sidecar));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::engine_status,
            commands::list_projects,
            commands::open_project,
            commands::delete_project,
            commands::project_stats,
            commands::project_files,
            commands::scan_policy,
            commands::analysis_history,
            commands::analyze_project,
            commands::cancel_analysis,
        ])
        .on_window_event(|window, event| {
            // The engine is a child process; letting it outlive the window would
            // leave an orphan holding the database.
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.app_handle().try_state::<AppState>() {
                    state.sidecar.shutdown();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error al iniciar HANA Knowledge Engine");
}

/// Where the knowledge base lives.
///
/// `HANA_DATA_DIR` wins when set (development and tests); otherwise the OS
/// per-user app-data folder, so the database never sits next to the executable
/// in Program Files.
fn database_path(app: &tauri::AppHandle) -> Result<PathBuf, Box<dyn std::error::Error>> {
    if let Ok(custom) = std::env::var("HANA_DATA_DIR") {
        return Ok(PathBuf::from(custom).join(DATABASE_FILENAME));
    }
    let directory = app.path().app_data_dir()?;
    Ok(directory.join(DATABASE_FILENAME))
}
