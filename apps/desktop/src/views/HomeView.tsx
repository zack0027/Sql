/**
 * Home screen.
 *
 * Shows the engine's real state — projects it knows, entities and relationships
 * it has stored, when each project was last analysed — and provides the two
 * actions Etapa 1 supports: open a folder, and analyse it.
 */

import { useEffect, useMemo, useState, type CSSProperties } from 'react';

import { Mark } from '../components/Mark';
import { SettingsDialog } from '../components/SettingsDialog';
import { useActiveProject, useAppStore } from '../state/store';
import {
  formatBytes,
  formatCount,
  formatRelativeTime,
  truncatePath,
} from '../lib/format';
import { useCountUp } from '../lib/useCountUp';
import styles from './HomeView.module.css';

/** Milliseconds between one card's entrance and the next. */
const STAGGER = 55;

/** CSS custom property the stylesheet reads as an animation delay. */
function stagger(index: number): CSSProperties {
  return { '--delay': `${index * STAGGER}ms` } as CSSProperties;
}

const PHASE_LABELS: Record<string, string> = {
  scanning: 'Escaneando',
  diffing: 'Comparando',
  inventory: 'Inventariando',
  analyzing: 'Analizando',
  finalizing: 'Finalizando',
};

export function HomeView({ onExplore }: { onExplore?: () => void }): JSX.Element {
  const {
    ready,
    native,
    engine,
    projects,
    activeProjectId,
    stats,
    files,
    progress,
    analyzing,
    lastRun,
    error,
    initialize,
    openFolder,
    selectProject,
    analyze,
    cancelAnalysis,
    removeProject,
    dismissError,
  } = useAppStore();

  const activeProject = useActiveProject();
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  const activeStats = activeProjectId ? stats[activeProjectId] : undefined;
  const activeFiles = activeProjectId ? files[activeProjectId] : undefined;

  const totalBytes = useMemo(
    () => (activeFiles ?? []).reduce((sum, file) => sum + file.size_bytes, 0),
    [activeFiles],
  );

  const topEntityTypes = useMemo(() => {
    const byType = activeStats?.entities_by_type ?? {};
    return Object.entries(byType)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8);
  }, [activeStats]);

  if (!ready) {
    return (
      <div className={styles.shell}>
        <div className={styles.empty} style={{ margin: 'auto', border: 'none' }}>
          <span className={styles.emptyText}>Iniciando el motor…</span>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <Mark />
          <div>
            <h1 className={styles.title}>HANA</h1>
            <p className={styles.subtitle}>
              Motor de conocimiento técnico local · análisis estático · sin conexión
            </p>
          </div>
        </div>

        <div className={styles.headerActions}>
          {analyzing ? (
            <button className={styles.ghost} onClick={() => void cancelAnalysis()}>
              Cancelar análisis
            </button>
          ) : (
            <button
              className={styles.ghost}
              disabled={!activeProjectId}
              onClick={() => activeProjectId && void analyze(activeProjectId)}
            >
              Analizar proyecto
            </button>
          )}
          <button
            className={styles.ghost}
            disabled={!activeProjectId || analyzing}
            onClick={() => setSettingsOpen(true)}
            title="Qué carpetas y archivos entran en el escaneo"
          >
            Configuración
          </button>
          <button className={styles.primary} onClick={() => void openFolder()}>
            Abrir proyecto
          </button>
        </div>
      </header>

      {settingsOpen && activeProjectId && (
        <SettingsDialog
          projectId={activeProjectId}
          projectName={activeProject?.root_path ?? ''}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {error && (
        <div className={styles.banner}>
          <span>{error}</span>
          <button className={styles.bannerClose} onClick={dismissError} aria-label="Cerrar">
            ×
          </button>
        </div>
      )}

      {!native && (
        <div className={`${styles.banner} ${styles.noticeBanner}`}>
          <span>
            Modo navegador: los datos mostrados son simulados. Ejecuta{' '}
            <code>pnpm tauri:dev</code> para conectar el motor real.
          </span>
        </div>
      )}

      <div className={styles.body}>
        <div className={styles.column}>
          <section className={styles.panel} style={stagger(0)}>
            <h2 className={styles.sectionTitle}>
              Estado del motor
              <span className={styles.count}>v{engine?.version ?? '—'}</span>
            </h2>
            <div className={styles.statGrid}>
              <Stat label="Proyectos" value={engine?.projects} delay={0} />
              <Stat label="Entidades" value={engine?.entities} delay={STAGGER} />
              <Stat
                label="Relaciones"
                value={engine?.relationships}
                delay={STAGGER * 2}
              />
              <Stat
                label="Analizadores"
                value={engine?.analyzers.length}
                delay={STAGGER * 3}
              />
            </div>
          </section>

          {(analyzing || progress) && (
            <section className={styles.panel}>
              <div className={styles.progress}>
                <div className={styles.progressHead}>
                  <span className={styles.progressPhase}>
                    {PHASE_LABELS[progress?.phase ?? ''] ?? 'Procesando'}
                  </span>
                  <span className={styles.count}>
                    {progress && progress.total > 0
                      ? `${progress.current}/${progress.total}`
                      : ''}
                  </span>
                </div>
                <div className={styles.track}>
                  {progress && progress.total > 0 ? (
                    <div
                      className={styles.fill}
                      style={{
                        width: `${Math.min(100, (progress.current / progress.total) * 100)}%`,
                      }}
                    />
                  ) : (
                    <div className={`${styles.fill} ${styles.fillPulse}`} />
                  )}
                </div>
                <span className={styles.progressMessage}>{progress?.message ?? ''}</span>
              </div>
            </section>
          )}

          <section className={styles.panel} style={stagger(1)}>
            <h2 className={styles.sectionTitle}>
              Proyectos recientes
              <span className={styles.count}>{projects.length}</span>
            </h2>

            {projects.length === 0 ? (
              <div className={styles.empty}>
                <span className={styles.emptyTitle}>Ningún proyecto todavía</span>
                <span className={styles.emptyText}>
                  Selecciona una carpeta con archivos SQL, PL/SQL, JRXML, MOCA, JSON o
                  código. HANA la escanea localmente, calcula el hash de cada archivo y
                  construye el grafo de conocimiento sin enviar nada fuera del equipo.
                </span>
                <button className={styles.primary} onClick={() => void openFolder()}>
                  Abrir proyecto
                </button>
              </div>
            ) : (
              <div className={styles.projectList}>
                {projects.map((project, index) => (
                  <button
                    key={project.id}
                    className={`${styles.project} ${
                      project.id === activeProjectId ? styles.projectActive : ''
                    }`}
                    style={stagger(index)}
                    onClick={() => void selectProject(project.id)}
                  >
                    <div className={styles.projectMain}>
                      <div className={styles.projectName}>{project.name}</div>
                      {/* Truncated from the left: the tail of a path is the
                          part that identifies the project. Doing it in JS keeps
                          separators in place — a CSS `direction: rtl` trick
                          moves a leading slash to the end. */}
                      <div className={styles.projectPath} title={project.root_path}>
                        {truncatePath(project.root_path, 64)}
                      </div>
                    </div>
                    <div className={styles.projectMeta}>
                      <span className={styles.badge}>{project.project_type}</span>
                      <span
                        className={`${styles.badge} ${
                          project.status === 'error'
                            ? styles.badgeError
                            : project.last_analysis_at
                              ? styles.badgeReady
                              : styles.badgeNever
                        }`}
                      >
                        {project.last_analysis_at
                          ? formatRelativeTime(project.last_analysis_at)
                          : 'sin analizar'}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>

        <div className={styles.column}>
          <section className={styles.panel} style={stagger(2)}>
            <h2 className={styles.sectionTitle}>Proyecto seleccionado</h2>
            {!activeProject ? (
              <span className={styles.emptyText}>
                Selecciona un proyecto para ver su inventario.
              </span>
            ) : (
              <>
                <Detail label="Nombre" value={activeProject.name} />
                <Detail label="Tipo" value={activeProject.project_type} />
                <Detail label="Estado" value={activeProject.status} />
                <Detail
                  label="Último análisis"
                  value={
                    activeProject.last_analysis_at
                      ? formatRelativeTime(activeProject.last_analysis_at)
                      : 'nunca'
                  }
                />
                <Detail label="Archivos" value={formatCount(activeStats?.files)} />
                <Detail label="Tamaño" value={formatBytes(totalBytes)} />
                <Detail label="Entidades" value={formatCount(activeStats?.entities)} />
                <Detail
                  label="Relaciones"
                  value={formatCount(activeStats?.relationships)}
                />
                <Detail label="Evidencias" value={formatCount(activeStats?.evidence)} />
                <Detail
                  label="Errores de análisis"
                  value={formatCount(activeStats?.errors)}
                />

                {topEntityTypes.length > 0 && (
                  <div className={styles.typeList}>
                    {topEntityTypes.map(([type, count], index) => (
                      <span
                        key={type}
                        className={styles.typeChip}
                        style={stagger(index)}
                      >
                        {type} <strong>{count}</strong>
                      </span>
                    ))}
                  </div>
                )}

                <div
                  style={{
                    marginTop: 14,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <button
                    className={styles.danger}
                    onClick={() => void removeProject(activeProject.id)}
                  >
                    Quitar del motor
                  </button>
                  {/* Only offered once there is knowledge to explore: an empty
                      graph would be a dead end, not a feature. */}
                  <button
                    className={styles.primary}
                    disabled={!onExplore || (activeStats?.entities ?? 0) === 0}
                    onClick={() => onExplore?.()}
                  >
                    Explorar el grafo →
                  </button>
                </div>
              </>
            )}
          </section>

          {lastRun && (
            <section className={styles.panel} style={stagger(3)}>
              <h2 className={styles.sectionTitle}>Último análisis</h2>
              <Detail label="Resultado" value={lastRun.status} />
              <Detail label="Archivos escaneados" value={formatCount(lastRun.files_scanned)} />
              <Detail label="Nuevos" value={formatCount(lastRun.files_added)} />
              <Detail label="Modificados" value={formatCount(lastRun.files_modified)} />
              <Detail label="Sin cambios" value={formatCount(lastRun.files_unchanged)} />
              <Detail label="Eliminados" value={formatCount(lastRun.files_deleted)} />
              <Detail label="Analizados" value={formatCount(lastRun.files_analyzed)} />
              <Detail label="Entidades nuevas" value={formatCount(lastRun.entities_created)} />
              <Detail
                label="Relaciones nuevas"
                value={formatCount(lastRun.relationships_created)}
              />
              <Detail label="Errores" value={formatCount(lastRun.error_count)} />
            </section>
          )}
        </div>
      </div>

      <footer className={styles.footer}>
        <div className={styles.footerGroup}>
          <span>
            <span
              className={`${styles.dot} ${
                analyzing ? styles.dotBusy : engine ? '' : styles.dotIdle
              }`}
            />
            {analyzing ? 'Analizando' : engine ? 'Motor listo' : 'Motor no disponible'}
          </span>
          <span>FTS5 {engine?.fts5_available ? 'activo' : 'no disponible'}</span>
          <span>Modelo local: {engine?.model_provider ?? 'disabled'}</span>
        </div>
        <div className={styles.footerGroup}>
          <span title={engine?.database_path}>
            {engine?.database_path ?? 'sin base de conocimiento'}
          </span>
        </div>
      </footer>
    </div>
  );
}

function Stat({
  label,
  value,
  delay = 0,
}: {
  label: string;
  value: number | null | undefined;
  delay?: number;
}): JSX.Element {
  const shown = useCountUp(value);
  return (
    <div className={styles.stat} style={{ '--delay': `${delay}ms` } as CSSProperties}>
      <div className={styles.statValue}>{formatCount(shown)}</div>
      <div className={styles.statLabel}>{label}</div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div className={styles.detailRow}>
      <span className={styles.detailKey}>{label}</span>
      <span className={styles.detailValue}>{value}</span>
    </div>
  );
}
