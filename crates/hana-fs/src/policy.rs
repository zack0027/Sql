//! Scan limits.
//!
//! This mirrors `hana_engine.indexing.policy.ScanPolicy` field for field. The
//! shared invariants are written down in `docs/SCAN_CONTRACT.md`; changing one
//! side without the other is a bug.

use serde::{Deserialize, Serialize};

/// Directories skipped unless the user removes them from the project settings.
pub const DEFAULT_IGNORED_DIRECTORIES: &[&str] = &[
    ".git",
    "node_modules",
    "target",
    "dist",
    "build",
    ".next",
    ".venv",
    "venv",
    "__pycache__",
    ".idea",
    ".vscode",
    "coverage",
];

/// Filename patterns skipped by default. Only a leading `*` wildcard is
/// supported, which covers every pattern the engine actually ships.
pub const DEFAULT_IGNORED_FILES: &[&str] = &[
    "*.pyc", "*.pyo", "*.class", "*.o", "*.so", "*.dll", "*.exe", "*.lock",
    ".DS_Store", "Thumbs.db",
];

/// 5 MiB.
pub const DEFAULT_MAX_FILE_SIZE_BYTES: u64 = 5 * 1024 * 1024;

/// Depth in path components below the project root.
pub const DEFAULT_MAX_DEPTH: usize = 24;

/// Bytes read when deciding whether a file is binary.
pub const BINARY_SNIFF_BYTES: usize = 8192;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScanPolicy {
    pub ignored_directories: Vec<String>,
    pub ignored_files: Vec<String>,
    pub max_file_size_bytes: u64,
    pub max_depth: usize,
    /// Off by default: following a symlink is how a scan escapes the folder the
    /// user chose. Even when enabled, the resolved target must still be inside
    /// the project root.
    pub follow_symlinks: bool,
    pub hash_binary_files: bool,
    #[serde(default)]
    pub extra_ignored_directories: Vec<String>,
}

impl Default for ScanPolicy {
    fn default() -> Self {
        Self {
            ignored_directories: DEFAULT_IGNORED_DIRECTORIES
                .iter()
                .map(|s| (*s).to_string())
                .collect(),
            ignored_files: DEFAULT_IGNORED_FILES
                .iter()
                .map(|s| (*s).to_string())
                .collect(),
            max_file_size_bytes: DEFAULT_MAX_FILE_SIZE_BYTES,
            max_depth: DEFAULT_MAX_DEPTH,
            follow_symlinks: false,
            hash_binary_files: true,
            extra_ignored_directories: Vec::new(),
        }
    }
}

impl ScanPolicy {
    pub fn ignores_directory(&self, name: &str) -> bool {
        self.ignored_directories.iter().any(|item| item == name)
            || self
                .extra_ignored_directories
                .iter()
                .any(|item| item == name)
    }

    pub fn ignores_file(&self, name: &str) -> bool {
        self.ignored_files
            .iter()
            .any(|pattern| matches_pattern(pattern, name))
    }
}

/// Match a filename against a pattern supporting a single leading `*`.
///
/// Kept intentionally small: the default list only needs suffix matching, and a
/// full glob engine would be one more dependency to audit.
fn matches_pattern(pattern: &str, name: &str) -> bool {
    match pattern.strip_prefix('*') {
        Some(suffix) => name.ends_with(suffix),
        None => pattern == name,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_ignore_list_matches_the_specification() {
        let policy = ScanPolicy::default();
        for name in [
            ".git",
            "node_modules",
            "target",
            "dist",
            "build",
            ".next",
            ".venv",
            "venv",
            "__pycache__",
            ".idea",
            ".vscode",
            "coverage",
        ] {
            assert!(policy.ignores_directory(name), "{name} should be ignored");
        }
        assert!(!policy.ignores_directory("src"));
    }

    #[test]
    fn suffix_patterns_match() {
        let policy = ScanPolicy::default();
        assert!(policy.ignores_file("module.pyc"));
        assert!(policy.ignores_file(".DS_Store"));
        assert!(!policy.ignores_file("guardar.sql"));
    }

    #[test]
    fn extra_ignores_are_honoured() {
        let policy = ScanPolicy {
            extra_ignored_directories: vec!["legacy".to_string()],
            ..Default::default()
        };
        assert!(policy.ignores_directory("legacy"));
    }

    #[test]
    fn round_trips_through_json_like_the_engine_sends_it() {
        let policy = ScanPolicy::default();
        let json = serde_json::to_string(&policy).unwrap();
        let parsed: ScanPolicy = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.max_depth, DEFAULT_MAX_DEPTH);
        assert!(!parsed.follow_symlinks);
    }
}
