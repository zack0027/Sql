/**
 * Scan policy for one project.
 *
 * The policy decides what HANA is allowed to read, so this screen is the one
 * place where a user choice can widen the program's reach into their disk. It
 * shows the whole policy rather than a curated subset, and says out loud what
 * each field costs — particularly following symbolic links, which is how a scan
 * escapes the folder that was chosen.
 *
 * Nothing here is applied retroactively: the policy is read at the start of the
 * next analysis. Saying so is the difference between a setting that looks broken
 * and one the user knows to follow with a re-analysis.
 */

import { useEffect, useState } from 'react';

import type { ScanPolicy } from '@hana/shared-types';

import { getClient } from '../api/client';
import styles from './SettingsDialog.module.css';

interface Props {
  projectId: string;
  projectName: string;
  onClose: () => void;
}

/** A textarea holds one entry per line; blank lines are not entries. */
function toLines(values: string[]): string {
  return values.join('\n');
}

export function parseLines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '');
}

const MIB = 1024 * 1024;

export function SettingsDialog({ projectId, projectName, onClose }: Props): JSX.Element {
  const [policy, setPolicy] = useState<ScanPolicy | null>(null);
  const [directories, setDirectories] = useState('');
  const [files, setFiles] = useState('');
  const [sizeMib, setSizeMib] = useState('5');
  const [depth, setDepth] = useState('24');
  const [followSymlinks, setFollowSymlinks] = useState(false);
  const [hashBinaries, setHashBinaries] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = (loaded: ScanPolicy): void => {
    setPolicy(loaded);
    setDirectories(toLines(loaded.ignored_directories));
    setFiles(toLines(loaded.ignored_files));
    setSizeMib(String(Math.round((loaded.max_file_size_bytes / MIB) * 10) / 10));
    setDepth(String(loaded.max_depth));
    setFollowSymlinks(loaded.follow_symlinks);
    setHashBinaries(loaded.hash_binary_files);
  };

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const client = await getClient();
        const loaded = await client.scanPolicy(projectId);
        if (!cancelled) load(loaded);
      } catch (problem) {
        if (!cancelled) setError(String(problem));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const save = async (): Promise<void> => {
    if (!policy) return;
    const megabytes = Number(sizeMib);
    const levels = Number(depth);
    // Checked here as well as in the engine: a zero limit scans nothing and
    // looks exactly like an empty project.
    if (!Number.isFinite(megabytes) || megabytes <= 0) {
      setError('El tamaño máximo debe ser un número mayor que cero.');
      return;
    }
    if (!Number.isInteger(levels) || levels <= 0) {
      setError('La profundidad debe ser un número entero mayor que cero.');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const client = await getClient();
      const stored = await client.setScanPolicy(projectId, {
        ...policy,
        ignored_directories: parseLines(directories),
        ignored_files: parseLines(files),
        max_file_size_bytes: Math.round(megabytes * MIB),
        max_depth: levels,
        follow_symlinks: followSymlinks,
        hash_binary_files: hashBinaries,
      });
      load(stored);
      setSaved(true);
    } catch (problem) {
      setError(String(problem));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-label="Configuración del escaneo"
        onClick={(event) => event.stopPropagation()}
      >
        <header className={styles.head}>
          <div>
            <h2 className={styles.title}>Configuración del escaneo</h2>
            <p className={styles.subtitle}>{projectName}</p>
          </div>
          <button className={styles.close} onClick={onClose} aria-label="Cerrar">
            ×
          </button>
        </header>

        {error && <p className={styles.error}>{error}</p>}

        {!policy ? (
          <p className={styles.muted}>Leyendo la configuración…</p>
        ) : (
          <div className={styles.body}>
            <label className={styles.field}>
              <span className={styles.label}>Carpetas ignoradas</span>
              <span className={styles.hint}>
                Una por línea. Se comparan por nombre, a cualquier profundidad.
              </span>
              <textarea
                className={styles.textarea}
                rows={7}
                value={directories}
                onChange={(event) => setDirectories(event.target.value)}
              />
            </label>

            <label className={styles.field}>
              <span className={styles.label}>Archivos ignorados</span>
              <span className={styles.hint}>
                Patrones tipo <code>*.pyc</code>, uno por línea.
              </span>
              <textarea
                className={styles.textarea}
                rows={7}
                value={files}
                onChange={(event) => setFiles(event.target.value)}
              />
            </label>

            <div className={styles.row}>
              <label className={styles.field}>
                <span className={styles.label}>Tamaño máximo por archivo (MB)</span>
                <span className={styles.hint}>
                  Los mayores se inventarían, pero no se leen ni se analizan.
                </span>
                <input
                  className={styles.input}
                  type="number"
                  min="0.1"
                  step="0.1"
                  value={sizeMib}
                  onChange={(event) => setSizeMib(event.target.value)}
                />
              </label>

              <label className={styles.field}>
                <span className={styles.label}>Profundidad máxima</span>
                <span className={styles.hint}>
                  Niveles de carpeta por debajo de la raíz del proyecto.
                </span>
                <input
                  className={styles.input}
                  type="number"
                  min="1"
                  step="1"
                  value={depth}
                  onChange={(event) => setDepth(event.target.value)}
                />
              </label>
            </div>

            <label className={styles.check}>
              <input
                type="checkbox"
                checked={hashBinaries}
                onChange={(event) => setHashBinaries(event.target.checked)}
              />
              <span>
                <strong>Calcular el hash de archivos binarios</strong>
                <span className={styles.hint}>
                  Permite detectar que un <code>.jasper</code> o una imagen cambió.
                  Nunca se analiza su contenido.
                </span>
              </span>
            </label>

            <label className={`${styles.check} ${styles.danger}`}>
              <input
                type="checkbox"
                checked={followSymlinks}
                onChange={(event) => setFollowSymlinks(event.target.checked)}
              />
              <span>
                <strong>Seguir enlaces simbólicos</strong>
                <span className={styles.hint}>
                  Un enlace es la forma de que el escaneo salga de la carpeta que
                  elegiste. Aun activado, HANA descarta lo que resuelva fuera de la
                  raíz del proyecto.
                </span>
              </span>
            </label>
          </div>
        )}

        <footer className={styles.foot}>
          <span className={styles.note}>
            {saved
              ? 'Guardado. Se aplica en el próximo análisis.'
              : 'Los cambios se aplican en el próximo análisis.'}
          </span>
          <button className={styles.ghost} onClick={onClose}>
            Cerrar
          </button>
          <button
            className={styles.primary}
            disabled={!policy || saving}
            onClick={() => void save()}
          >
            {saving ? 'Guardando…' : 'Guardar'}
          </button>
        </footer>
      </div>
    </div>
  );
}
