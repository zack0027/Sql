//! Secure filesystem access for the HANA Knowledge Engine.
//!
//! This crate is the security boundary between the desktop app and the user's
//! disk. It walks a project folder, enforces the limits in [`ScanPolicy`],
//! hashes what it is allowed to read, and hands the resulting inventory to the
//! Python engine.
//!
//! It deliberately depends on neither Tauri nor the engine, so it can be
//! audited and tested on its own.
//!
//! # What this crate does not do
//!
//! * It never writes to the knowledge base — the engine is the sole writer.
//! * It never executes anything it finds.
//! * It never classifies file *types*; the engine derives those from the path so
//!   the mapping lives in exactly one place.

mod policy;
mod scanner;
mod security;

pub use policy::{ScanPolicy, DEFAULT_IGNORED_DIRECTORIES, DEFAULT_IGNORED_FILES};
pub use scanner::{
    hash_file, scan_project, ScanProgress, ScanReport, ScannedFile, SkipReason,
};
pub use security::{is_within, resolve_project_root, SecurityError};
