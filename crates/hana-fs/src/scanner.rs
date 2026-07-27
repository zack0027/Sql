//! The directory walk and SHA-256 hashing.
//!
//! Produces exactly the record shape `hana_engine.domain.models.ScannedFile`
//! parses. Note what is *absent*: no `detected_type`. File typing belongs to the
//! engine, which derives it from the path, so the extension table exists in one
//! language only.

use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::policy::{ScanPolicy, BINARY_SNIFF_BYTES};
use crate::security::{is_within, resolve_project_root, SecurityError};

const HASH_CHUNK_BYTES: usize = 1024 * 1024;

/// Why the scanner declined to hash or analyse a file.
///
/// Serialised in snake_case to match `hana_engine.domain.types.SkipReason`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SkipReason {
    IgnoredDirectory,
    TooLarge,
    TooDeep,
    Binary,
    SymlinkEscape,
    Unreadable,
}

/// One file as the scanner saw it on disk.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScannedFile {
    pub relative_path: String,
    pub absolute_path: String,
    pub extension: String,
    pub size_bytes: u64,
    /// `None` when the file was skipped and therefore never read.
    pub content_hash: Option<String>,
    pub modified_at: Option<String>,
    pub skip_reason: Option<SkipReason>,
}

impl ScannedFile {
    pub fn is_skipped(&self) -> bool {
        self.skip_reason.is_some()
    }
}

/// Progress emitted while walking, so the UI can show real counts.
#[derive(Debug, Clone, Serialize)]
pub struct ScanProgress {
    pub files_seen: usize,
    pub current_path: String,
}

/// The outcome of one walk.
#[derive(Debug, Default, Serialize)]
pub struct ScanReport {
    pub root: String,
    pub files: Vec<ScannedFile>,
    pub skipped: Vec<ScannedFile>,
    pub directories_visited: usize,
    pub bytes_hashed: u64,
    pub errors: Vec<String>,
    pub cancelled: bool,
}

impl ScanReport {
    pub fn total_seen(&self) -> usize {
        self.files.len() + self.skipped.len()
    }
}

/// Hash a file in chunks. Returns `(sha256_hex, bytes_read)`.
///
/// Chunked so a large export cannot balloon memory.
pub fn hash_file(path: &Path) -> std::io::Result<(String, u64)> {
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; HASH_CHUNK_BYTES];
    let mut total: u64 = 0;

    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
        total += read as u64;
    }

    Ok((format!("{:x}", hasher.finalize()), total))
}

fn looks_binary(path: &Path) -> bool {
    let mut file = match File::open(path) {
        Ok(handle) => handle,
        Err(_) => return true,
    };
    let mut head = vec![0_u8; BINARY_SNIFF_BYTES];
    match file.read(&mut head) {
        Ok(read) => head[..read].contains(&0),
        Err(_) => true,
    }
}

fn iso_timestamp(time: SystemTime) -> Option<String> {
    let duration = time.duration_since(UNIX_EPOCH).ok()?;
    let secs = duration.as_secs() as i64;
    let micros = duration.subsec_micros();

    // Civil-from-days (Howard Hinnant's algorithm): avoids a date-time crate for
    // the single timestamp format the engine consumes.
    let days = secs.div_euclid(86_400);
    let time_of_day = secs.rem_euclid(86_400);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if m <= 2 { y + 1 } else { y };

    Some(format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:06}Z",
        year,
        m,
        d,
        time_of_day / 3600,
        (time_of_day % 3600) / 60,
        time_of_day % 60,
        micros
    ))
}

fn extension_of(path: &Path) -> String {
    path.extension()
        .and_then(|value| value.to_str())
        .map(|value| format!(".{}", value.to_lowercase()))
        .unwrap_or_default()
}

fn relative_path(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        // The engine keys files by relative path; forward slashes keep a project
        // scanned on Windows identical to the same project on Linux.
        .replace('\\', "/")
}

fn skipped_record(root: &Path, path: &Path, reason: SkipReason) -> ScannedFile {
    ScannedFile {
        relative_path: relative_path(root, path),
        absolute_path: path.to_string_lossy().to_string(),
        extension: extension_of(path),
        size_bytes: 0,
        content_hash: None,
        modified_at: None,
        skip_reason: Some(reason),
    }
}

/// Walk `root`, hashing every readable file the policy allows.
///
/// `on_progress` is called on the walking thread and must be cheap. `cancel`
/// is polled between entries so a long scan can be stopped from the UI.
pub fn scan_project(
    root: impl AsRef<Path>,
    policy: &ScanPolicy,
    on_progress: Option<&dyn Fn(ScanProgress)>,
    cancel: Option<Arc<AtomicBool>>,
) -> Result<ScanReport, SecurityError> {
    let root = resolve_project_root(root)?;
    let mut report = ScanReport {
        root: root.to_string_lossy().to_string(),
        ..Default::default()
    };

    let mut stack: Vec<(PathBuf, usize)> = vec![(root.clone(), 0)];

    while let Some((directory, depth)) = stack.pop() {
        if is_cancelled(&cancel) {
            report.cancelled = true;
            return Ok(report);
        }
        report.directories_visited += 1;

        let entries = match fs::read_dir(&directory) {
            Ok(iterator) => iterator,
            Err(error) => {
                report
                    .errors
                    .push(format!("{}: {}", directory.display(), error));
                continue;
            }
        };

        let mut paths: Vec<PathBuf> = Vec::new();
        for entry in entries {
            match entry {
                Ok(item) => paths.push(item.path()),
                Err(error) => report
                    .errors
                    .push(format!("{}: {}", directory.display(), error)),
            }
        }
        // Deterministic order: two scans of an unchanged project must produce
        // the same inventory in the same sequence.
        paths.sort();

        for path in paths {
            if is_cancelled(&cancel) {
                report.cancelled = true;
                return Ok(report);
            }

            let metadata = match fs::symlink_metadata(&path) {
                Ok(value) => value,
                Err(error) => {
                    report.errors.push(format!("{}: {}", path.display(), error));
                    continue;
                }
            };

            let name = path
                .file_name()
                .map(|value| value.to_string_lossy().to_string())
                .unwrap_or_default();

            if metadata.file_type().is_symlink() {
                // Refused unless the policy allows following *and* the target
                // stays inside the project.
                if !policy.follow_symlinks || !is_within(&root, &path) {
                    let record = skipped_record(&root, &path, SkipReason::SymlinkEscape);
                    emit(on_progress, &report, &record);
                    report.skipped.push(record);
                    continue;
                }
            }

            let resolved = match fs::metadata(&path) {
                Ok(value) => value,
                Err(error) => {
                    report.errors.push(format!("{}: {}", path.display(), error));
                    continue;
                }
            };

            if resolved.is_dir() {
                if policy.ignores_directory(&name) {
                    continue;
                }
                if depth + 1 > policy.max_depth {
                    let record = skipped_record(&root, &path, SkipReason::TooDeep);
                    emit(on_progress, &report, &record);
                    report.skipped.push(record);
                    continue;
                }
                stack.push((path, depth + 1));
                continue;
            }

            if !resolved.is_file() {
                continue; // sockets, FIFOs and devices are not our business
            }
            if policy.ignores_file(&name) {
                continue;
            }

            let record = scan_file(&root, &path, &resolved, policy, &mut report);
            emit(on_progress, &report, &record);
            if record.is_skipped() && record.content_hash.is_none() {
                report.skipped.push(record);
            } else if record.is_skipped() {
                // Binary files are hashed (a changed report image must be
                // detectable) but still flagged so nothing reads them as text.
                report.skipped.push(record);
            } else {
                report.files.push(record);
            }
        }
    }

    Ok(report)
}

fn scan_file(
    root: &Path,
    path: &Path,
    metadata: &fs::Metadata,
    policy: &ScanPolicy,
    report: &mut ScanReport,
) -> ScannedFile {
    if !is_within(root, path) {
        return skipped_record(root, path, SkipReason::SymlinkEscape);
    }

    let mut record = ScannedFile {
        relative_path: relative_path(root, path),
        absolute_path: path.to_string_lossy().to_string(),
        extension: extension_of(path),
        size_bytes: metadata.len(),
        content_hash: None,
        modified_at: metadata.modified().ok().and_then(iso_timestamp),
        skip_reason: None,
    };

    if metadata.len() > policy.max_file_size_bytes {
        record.skip_reason = Some(SkipReason::TooLarge);
        return record;
    }

    let binary = looks_binary(path);
    if binary && !policy.hash_binary_files {
        record.skip_reason = Some(SkipReason::Binary);
        return record;
    }

    match hash_file(path) {
        Ok((digest, read)) => {
            report.bytes_hashed += read;
            record.content_hash = Some(digest);
            if binary {
                record.skip_reason = Some(SkipReason::Binary);
            }
        }
        Err(error) => {
            report.errors.push(format!("{}: {}", path.display(), error));
            record.skip_reason = Some(SkipReason::Unreadable);
        }
    }

    record
}

fn emit(on_progress: Option<&dyn Fn(ScanProgress)>, report: &ScanReport, record: &ScannedFile) {
    if let Some(callback) = on_progress {
        callback(ScanProgress {
            files_seen: report.total_seen() + 1,
            current_path: record.relative_path.clone(),
        });
    }
}

fn is_cancelled(cancel: &Option<Arc<AtomicBool>>) -> bool {
    cancel
        .as_ref()
        .map(|flag| flag.load(Ordering::Relaxed))
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::fs;
    use std::path::PathBuf;

    /// Mirrors `engine/tests/conftest.py::sample_project`.
    fn sample_project() -> (tempfile::TempDir, PathBuf) {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("project");
        fs::create_dir_all(root.join("sql")).unwrap();
        fs::create_dir_all(root.join("reports/images")).unwrap();
        fs::create_dir_all(root.join("node_modules/pkg")).unwrap();
        fs::create_dir_all(root.join(".git")).unwrap();
        fs::create_dir_all(root.join("build")).unwrap();

        fs::write(
            root.join("sql/guardar_inspeccion.sql"),
            "insert into uc_insp_ent (netwgt) values (:P117_NETWGT);",
        )
        .unwrap();
        fs::write(
            root.join("reports/Usr-RptInspeccion.jrxml"),
            "<jasperReport name=\"Usr-RptInspeccion\"/>",
        )
        .unwrap();
        let mut png = vec![0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a];
        png.extend_from_slice(&[0_u8; 64]);
        fs::write(root.join("reports/images/checkboxOn.png"), png).unwrap();
        fs::write(root.join("node_modules/pkg/index.js"), "module.exports = 1;").unwrap();
        fs::write(root.join(".git/HEAD"), "ref: refs/heads/main").unwrap();
        fs::write(root.join("build/output.log"), "built").unwrap();

        (temp, root)
    }

    fn index(report: &ScanReport) -> HashMap<String, ScannedFile> {
        report
            .files
            .iter()
            .chain(report.skipped.iter())
            .map(|item| (item.relative_path.clone(), item.clone()))
            .collect()
    }

    #[test]
    fn finds_the_project_files() {
        let (_temp, root) = sample_project();
        let report = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();
        let found = index(&report);
        assert!(found.contains_key("sql/guardar_inspeccion.sql"));
        assert!(found.contains_key("reports/Usr-RptInspeccion.jrxml"));
    }

    #[test]
    fn applies_the_default_ignore_list() {
        let (_temp, root) = sample_project();
        let report = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();
        let found = index(&report);
        assert!(!found.keys().any(|path| path.starts_with("node_modules/")));
        assert!(!found.keys().any(|path| path.starts_with(".git/")));
        assert!(!found.keys().any(|path| path.starts_with("build/")));
    }

    #[test]
    fn the_ignore_list_is_configurable() {
        let (_temp, root) = sample_project();
        let policy = ScanPolicy {
            ignored_directories: vec![],
            ..Default::default()
        };
        let report = scan_project(&root, &policy, None, None).unwrap();
        let found = index(&report);
        assert!(found.contains_key("node_modules/pkg/index.js"));
    }

    #[test]
    fn hashes_are_sha256_and_stable() {
        let (_temp, root) = sample_project();
        let first = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();
        let second = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();

        let a = index(&first);
        let b = index(&second);
        let key = "sql/guardar_inspeccion.sql";
        assert_eq!(a[key].content_hash, b[key].content_hash);
        assert_eq!(a[key].content_hash.as_ref().unwrap().len(), 64);
    }

    #[test]
    fn matches_a_known_sha256_vector() {
        let temp = tempfile::tempdir().unwrap();
        let file = temp.path().join("abc.txt");
        fs::write(&file, b"abc").unwrap();
        let (digest, size) = hash_file(&file).unwrap();
        assert_eq!(
            digest,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(size, 3);
    }

    #[test]
    fn identical_content_hashes_identically() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("p");
        fs::create_dir(&root).unwrap();
        fs::write(root.join("a.sql"), "select 1 from dual;").unwrap();
        fs::write(root.join("b.sql"), "select 1 from dual;").unwrap();

        let report = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();
        let hashes: std::collections::HashSet<_> = report
            .files
            .iter()
            .map(|item| item.content_hash.clone())
            .collect();
        assert_eq!(hashes.len(), 1);
    }

    #[test]
    fn changing_a_file_changes_its_hash() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("p");
        fs::create_dir(&root).unwrap();
        let file = root.join("a.sql");
        fs::write(&file, "select 1 from dual;").unwrap();
        let before = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();

        fs::write(&file, "select 2 from dual;").unwrap();
        let after = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();

        assert_ne!(before.files[0].content_hash, after.files[0].content_hash);
    }

    #[test]
    fn binary_files_are_hashed_but_flagged() {
        let (_temp, root) = sample_project();
        let report = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();
        let found = index(&report);
        let image = &found["reports/images/checkboxOn.png"];
        assert_eq!(image.skip_reason, Some(SkipReason::Binary));
        assert!(image.content_hash.is_some());
    }

    #[test]
    fn oversized_files_are_inventoried_but_not_hashed() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("p");
        fs::create_dir(&root).unwrap();
        fs::write(root.join("big.sql"), "x".repeat(5000)).unwrap();

        let policy = ScanPolicy {
            max_file_size_bytes: 1000,
            ..Default::default()
        };
        let report = scan_project(&root, &policy, None, None).unwrap();
        let found = index(&report);
        assert_eq!(found["big.sql"].skip_reason, Some(SkipReason::TooLarge));
        assert!(found["big.sql"].content_hash.is_none());
        assert_eq!(found["big.sql"].size_bytes, 5000);
    }

    #[test]
    fn the_depth_limit_is_enforced() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("p");
        fs::create_dir_all(root.join("a/b/c/d")).unwrap();
        fs::write(root.join("a/b/c/d/deep.sql"), "select 1 from dual;").unwrap();
        fs::write(root.join("shallow.sql"), "select 1 from dual;").unwrap();

        let policy = ScanPolicy {
            max_depth: 2,
            ..Default::default()
        };
        let report = scan_project(&root, &policy, None, None).unwrap();
        let found = index(&report);
        assert!(found.contains_key("shallow.sql"));
        assert!(!found.contains_key("a/b/c/d/deep.sql"));
    }

    #[test]
    fn ignored_file_patterns_are_applied() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("p");
        fs::create_dir(&root).unwrap();
        fs::write(root.join("keep.sql"), "select 1 from dual;").unwrap();
        fs::write(root.join("drop.pyc"), [0_u8, 1, 2]).unwrap();

        let report = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();
        assert_eq!(report.files.len(), 1);
        assert_eq!(report.files[0].relative_path, "keep.sql");
    }

    #[cfg(unix)]
    #[test]
    fn symlinks_are_not_followed_by_default() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("project");
        let outside = temp.path().join("outside");
        fs::create_dir(&root).unwrap();
        fs::create_dir(&outside).unwrap();
        fs::write(outside.join("secret.sql"), "select * from payroll;").unwrap();
        fs::write(root.join("own.sql"), "select 1 from dual;").unwrap();
        std::os::unix::fs::symlink(&outside, root.join("escape")).unwrap();

        let report = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();
        assert_eq!(report.files.len(), 1);
        assert_eq!(report.files[0].relative_path, "own.sql");
        assert!(report
            .skipped
            .iter()
            .any(|item| item.skip_reason == Some(SkipReason::SymlinkEscape)));
    }

    #[cfg(unix)]
    #[test]
    fn escaping_symlinks_are_refused_even_when_following_is_enabled() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("project");
        let outside = temp.path().join("outside");
        fs::create_dir(&root).unwrap();
        fs::create_dir(&outside).unwrap();
        fs::write(outside.join("secret.sql"), "select * from payroll;").unwrap();
        std::os::unix::fs::symlink(&outside, root.join("escape")).unwrap();

        let policy = ScanPolicy {
            follow_symlinks: true,
            ..Default::default()
        };
        let report = scan_project(&root, &policy, None, None).unwrap();
        assert!(!report
            .files
            .iter()
            .any(|item| item.relative_path.contains("secret")));
    }

    #[test]
    fn relative_paths_use_forward_slashes() {
        let (_temp, root) = sample_project();
        let report = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();
        assert!(report
            .files
            .iter()
            .all(|item| !item.relative_path.contains('\\')));
    }

    #[test]
    fn progress_is_reported() {
        let (_temp, root) = sample_project();
        let seen = std::sync::Mutex::new(Vec::new());
        let report = scan_project(
            &root,
            &ScanPolicy::default(),
            Some(&|progress| seen.lock().unwrap().push(progress.current_path)),
            None,
        )
        .unwrap();
        assert_eq!(seen.lock().unwrap().len(), report.total_seen());
    }

    #[test]
    fn cancellation_stops_the_walk() {
        let (_temp, root) = sample_project();
        let flag = Arc::new(AtomicBool::new(true));
        let report = scan_project(&root, &ScanPolicy::default(), None, Some(flag)).unwrap();
        assert!(report.cancelled);
        assert!(report.files.is_empty());
    }

    #[test]
    fn a_missing_root_is_an_error_not_a_panic() {
        let temp = tempfile::tempdir().unwrap();
        let result = scan_project(temp.path().join("ghost"), &ScanPolicy::default(), None, None);
        assert!(result.is_err());
    }

    #[test]
    fn records_serialise_to_the_shape_the_engine_parses() {
        let (_temp, root) = sample_project();
        let report = scan_project(&root, &ScanPolicy::default(), None, None).unwrap();
        let json = serde_json::to_string(&report.files[0]).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();

        for key in [
            "relative_path",
            "absolute_path",
            "extension",
            "size_bytes",
            "content_hash",
            "modified_at",
            "skip_reason",
        ] {
            assert!(parsed.get(key).is_some(), "missing key {key}");
        }
    }

    #[test]
    fn timestamps_are_iso8601_utc() {
        let stamp = iso_timestamp(UNIX_EPOCH + std::time::Duration::from_secs(1_700_000_000))
            .unwrap();
        assert_eq!(&stamp[..19], "2023-11-14T22:13:20");
        assert!(stamp.ends_with('Z'));
    }
}
