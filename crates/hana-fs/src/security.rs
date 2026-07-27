//! Path containment.
//!
//! Every path the scanner is about to open passes through here first. The rule
//! is simple and absolute: a resolved path that does not live under the project
//! root is never opened.

use std::fmt;
use std::path::{Path, PathBuf};

/// Why a path was refused.
#[derive(Debug)]
pub enum SecurityError {
    /// The root does not exist or could not be canonicalised.
    RootNotFound(PathBuf),
    /// The root exists but is not a directory.
    RootNotADirectory(PathBuf),
    /// The path resolved outside the project root.
    OutsideRoot { root: PathBuf, path: PathBuf },
}

impl fmt::Display for SecurityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SecurityError::RootNotFound(path) => {
                write!(formatter, "project root does not exist: {}", path.display())
            }
            SecurityError::RootNotADirectory(path) => {
                write!(
                    formatter,
                    "project root is not a directory: {}",
                    path.display()
                )
            }
            SecurityError::OutsideRoot { root, path } => write!(
                formatter,
                "path {} is outside the project root {}",
                path.display(),
                root.display()
            ),
        }
    }
}

impl std::error::Error for SecurityError {}

/// Canonicalise a project root, rejecting anything that is not a real directory.
///
/// Canonicalising up front means every later containment check compares two
/// fully resolved paths, so `..`, symlinks and Windows junctions cannot be used
/// to slip outside.
pub fn resolve_project_root(root: impl AsRef<Path>) -> Result<PathBuf, SecurityError> {
    let raw = root.as_ref();
    let resolved = raw
        .canonicalize()
        .map_err(|_| SecurityError::RootNotFound(raw.to_path_buf()))?;
    if !resolved.is_dir() {
        return Err(SecurityError::RootNotADirectory(resolved));
    }
    Ok(resolved)
}

/// Return true when `candidate` resolves to a location inside `root`.
///
/// Compares whole path components rather than string prefixes, so
/// `/data/project-secrets` is not mistaken for a child of `/data/project`.
pub fn is_within(root: &Path, candidate: &Path) -> bool {
    let resolved = match candidate.canonicalize() {
        Ok(path) => path,
        // A path that cannot be resolved (broken symlink, race with a delete) is
        // treated as outside: refusing is always the safe answer.
        Err(_) => return false,
    };
    resolved.components().count() >= root.components().count()
        && resolved.starts_with(root)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn resolves_a_real_directory() {
        let temp = tempfile::tempdir().unwrap();
        let resolved = resolve_project_root(temp.path()).unwrap();
        assert!(resolved.is_dir());
    }

    #[test]
    fn rejects_a_missing_root() {
        let temp = tempfile::tempdir().unwrap();
        let missing = temp.path().join("nope");
        assert!(matches!(
            resolve_project_root(missing),
            Err(SecurityError::RootNotFound(_))
        ));
    }

    #[test]
    fn rejects_a_file_as_root() {
        let temp = tempfile::tempdir().unwrap();
        let file = temp.path().join("a.sql");
        fs::write(&file, "select 1 from dual;").unwrap();
        assert!(matches!(
            resolve_project_root(file),
            Err(SecurityError::RootNotFound(_)) | Err(SecurityError::RootNotADirectory(_))
        ));
    }

    #[test]
    fn accepts_a_child_path() {
        let temp = tempfile::tempdir().unwrap();
        let root = resolve_project_root(temp.path()).unwrap();
        let child = root.join("a.sql");
        fs::write(&child, "select 1 from dual;").unwrap();
        assert!(is_within(&root, &child));
    }

    #[test]
    fn rejects_a_sibling_with_a_shared_prefix() {
        // The classic string-prefix bug: `project-secrets` must not count as
        // living inside `project`.
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("project");
        let sibling = temp.path().join("project-secrets");
        fs::create_dir(&root).unwrap();
        fs::create_dir(&sibling).unwrap();
        let secret = sibling.join("creds.txt");
        fs::write(&secret, "hunter2").unwrap();

        let root = resolve_project_root(&root).unwrap();
        assert!(!is_within(&root, &secret));
    }

    #[test]
    fn rejects_dotdot_escapes() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("project");
        fs::create_dir(&root).unwrap();
        let outside = temp.path().join("outside.txt");
        fs::write(&outside, "secret").unwrap();

        let root = resolve_project_root(&root).unwrap();
        assert!(!is_within(&root, &root.join("..").join("outside.txt")));
    }

    #[cfg(unix)]
    #[test]
    fn rejects_a_symlink_pointing_outside() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("project");
        let outside = temp.path().join("outside");
        fs::create_dir(&root).unwrap();
        fs::create_dir(&outside).unwrap();
        fs::write(outside.join("secret.sql"), "select * from payroll;").unwrap();

        let link = root.join("escape");
        std::os::unix::fs::symlink(&outside, &link).unwrap();

        let root = resolve_project_root(&root).unwrap();
        assert!(!is_within(&root, &link.join("secret.sql")));
    }
}
