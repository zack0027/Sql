/**
 * The project explorer: files on the left, graph in the middle, evidence on the
 * right.
 *
 * The right-hand panel is the point of the whole product. Every relation it
 * lists carries the file, the line and the fragment that prove it, and says
 * plainly whether the fact was confirmed by syntax or inferred from a
 * convention. Nothing is shown that HANA cannot justify.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react';

import type { EntityHit, UsageHit } from '@hana/shared-types';

import { CodeViewer } from '../components/CodeViewer';
import { ErDiagram } from '../components/ErDiagram';
import { GraphCanvas } from '../components/GraphCanvas';
import { ReportPreview } from '../components/ReportPreview';
import {
  buildFileTree,
  colorOf,
  flattenTree,
  relationLabel,
  type TreeNode,
  type TreeRow,
} from '../lib/graph';
import { formatBytes } from '../lib/format';
import { useResizable } from '../lib/useResizable';
import {
  ACTIVE_TAB_ATTRIBUTE,
  useSlidingIndicator,
} from '../lib/useSlidingIndicator';
import { useVirtualRows } from '../lib/useVirtualRows';
import { useExplorerStore } from '../state/explorer';
import { useAppStore } from '../state/store';
import styles from './ExplorerView.module.css';

/** Milliseconds between one card's entrance and the next. */
const STAGGER = 40;

/** CSS custom property the stylesheet reads as an animation delay. */
function stagger(index: number): CSSProperties {
  // Past a dozen items the cascade stops reading as a cascade and starts
  // reading as a wait, so the delay is capped rather than scaled.
  return { '--delay': `${Math.min(index, 12) * STAGGER}ms` } as CSSProperties;
}

export function ExplorerView({ onBack }: { onBack: () => void }): JSX.Element {
  const project = useAppStore((state) =>
    state.projects.find((item) => item.id === state.activeProjectId),
  );
  const explorer = useExplorerStore();
  const [filter, setFilter] = useState('');
  const left = useResizable('hana.panel.left', 280, { min: 200, max: 520, side: 'left' });
  const right = useResizable('hana.panel.right', 380, { min: 280, max: 680, side: 'right' });
  const tabs = useSlidingIndicator<HTMLDivElement>(explorer.tab);

  useEffect(() => {
    if (project && explorer.projectId !== project.id) {
      void explorer.open(project.id);
    }
  }, [project, explorer]);

  const filtering = filter.trim() !== '';
  const tree = useMemo(() => {
    const files = filtering
      ? explorer.files.filter((file) =>
          file.relative_path.toLowerCase().includes(filter.toLowerCase()),
        )
      : explorer.files;
    return buildFileTree(files);
  }, [explorer.files, filter, filtering]);

  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const initialisedFor = useRef<string | null>(null);

  // Top-level folders open, deeper ones closed: enough to see the shape of the
  // project without arriving as a wall of rows. Done once per project, so a
  // re-analysis does not collapse what the user opened. The first path segment
  // is the top level, which is cheaper than rebuilding the tree to ask it.
  useEffect(() => {
    const projectId = explorer.projectId;
    if (!projectId || explorer.files.length === 0) return;
    if (initialisedFor.current === projectId) return;
    initialisedFor.current = projectId;

    const roots = new Set<string>();
    for (const item of explorer.files) {
      const slash = item.relative_path.indexOf('/');
      if (slash > 0) roots.add(item.relative_path.slice(0, slash));
    }
    setExpanded(roots);
  }, [explorer.projectId, explorer.files]);

  const toggle = useCallback((path: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(path)) next.add(path);
      return next;
    });
  }, []);

  const rows = useMemo(
    // While filtering everything is open: a match buried in a closed folder
    // would look like no match at all.
    () => flattenTree(tree, (node) => filtering || expanded.has(node.path)),
    [tree, expanded, filtering],
  );

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <button className={styles.back} onClick={onBack}>
          ← Proyectos
        </button>
        <div className={styles.title}>
          <strong>{project?.name ?? 'Proyecto'}</strong>
          <span className={styles.path}>{project?.root_path}</span>
        </div>
        <SearchBox />
      </header>

      {explorer.error && (
        <div className={styles.banner}>
          <span>{explorer.error}</span>
          <button onClick={explorer.dismissError} aria-label="Cerrar">
            ×
          </button>
        </div>
      )}

      <StaleBanner />


      <div
        className={styles.body}
        style={{
          gridTemplateColumns: `${left.width}px 4px minmax(0, 1fr) 4px ${right.width}px`,
        }}
      >
        {/* ---- left: files ------------------------------------------------ */}
        <aside className={styles.left}>
          <div className={styles.panelHead}>
            <span>Archivos</span>
            <span className={styles.count}>{explorer.files.length}</span>
          </div>
          <input
            className={styles.filter}
            placeholder="Filtrar por ruta o extensión…"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
          <FileTree rows={rows} expanded={expanded} onToggle={toggle} />
        </aside>

        <div
          className={`${styles.handle} ${left.dragging ? styles.handleActive : ''}`}
          onPointerDown={left.onPointerDown}
          onDoubleClick={left.reset}
          title="Arrastra para redimensionar · doble clic para restablecer"
        />

        {/* ---- centre: graph / code / file / issues ----------------------- */}
        <main className={styles.centre}>
          <div className={styles.tabs} ref={tabs}>
            {(
              [
                ['graph', 'Grafo'],
                ['er', 'Diagrama ER'],
                ['report', 'Reporte'],
                ['code', 'Código'],
                ['file', 'Archivo'],
                ['issues', `Avisos (${explorer.issues.length})`],
                ['changes', `Cambios (${explorer.changes?.changes.length ?? 0})`],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                className={`${styles.tab} ${explorer.tab === key ? styles.tabActive : ''}`}
                {...{ [ACTIVE_TAB_ATTRIBUTE]: explorer.tab === key }}
                onClick={() => explorer.setTab(key)}
              >
                {label}
              </button>
            ))}
            <span className={styles.tabIndicator} aria-hidden="true" />
            <ScopeSwitch />
          </div>

          {explorer.tab === 'graph' && (
            <GraphCanvas
              graph={explorer.graph}
              focusId={explorer.selected?.id ?? null}
              expanded={explorer.expanded}
              loading={explorer.loadingGraph}
              onSelect={(id) => {
                const node = explorer.graph?.nodes.find((item) => item.entity.id === id);
                if (node) void explorer.selectEntity(node.entity);
              }}
              onExpand={(id) => void explorer.expandNode(id)}
            />
          )}

          {explorer.tab === 'er' && (
            <ErDiagram
              model={explorer.er}
              loading={explorer.loadingEr}
              onOpenEvidence={(path, line) => void explorer.openEvidence(path, line)}
            />
          )}

          {explorer.tab === 'report' && (
            <ReportPreview report={explorer.report} loading={explorer.loadingReport} />
          )}

          {explorer.tab === 'code' && <CodePanel />}
          {explorer.tab === 'file' && <FilePanel />}
          {explorer.tab === 'issues' && <IssuesPanel />}
          {explorer.tab === 'changes' && <ChangesPanel />}
        </main>

        <div
          className={`${styles.handle} ${right.dragging ? styles.handleActive : ''}`}
          onPointerDown={right.onPointerDown}
          onDoubleClick={right.reset}
          title="Arrastra para redimensionar · doble clic para restablecer"
        />

        {/* ---- right: details -------------------------------------------- */}
        <aside className={styles.right}>
          <DetailsPanel />
        </aside>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

/**
 * Says when the graph on screen was built by an older analyzer.
 *
 * The pipeline already re-reads these files on the next run, so this changes no
 * behaviour — it removes a silence. Without it the user meets a missing band or
 * an empty diagram and has no way to tell an absence in their code from an
 * absence in HANA's reading of it, which is the difference between "my report is
 * fine" and hunting a bug that is not there.
 */
function StaleBanner(): JSX.Element | null {
  const freshness = useExplorerStore((state) => state.freshness);
  const projectId = useExplorerStore((state) => state.projectId);
  const openExplorer = useExplorerStore((state) => state.open);
  const analyze = useAppStore((state) => state.analyze);
  const analyzing = useAppStore((state) => state.analyzing);

  if (!freshness || freshness.stale === 0 || !projectId) return null;

  return (
    <div className={styles.staleBanner}>
      <span>
        <strong>{freshness.stale}</strong>{' '}
        {freshness.stale === 1 ? 'archivo se analizó' : 'archivos se analizaron'}{' '}
        con una versión anterior de los analizadores. Vuelve a analizar para que
        HANA lea lo que antes no sabía extraer.
      </span>
      <button
        className={styles.staleAction}
        disabled={analyzing}
        onClick={async () => {
          await analyze(projectId);
          await openExplorer(projectId);
        }}
      >
        {analyzing ? 'Analizando…' : 'Volver a analizar'}
      </button>
    </div>
  );
}

/**
 * Whether the centre panel describes what you clicked, or the whole project.
 *
 * The tabs used to mix the two without saying so: the graph and the report
 * followed the selection while the diagram, the warnings and the changes always
 * showed everything. That is a difficult thing to notice and an easy thing to be
 * misled by — an empty warnings tab meant "this project is clean", never "this
 * file is clean". Now it is one setting, stated on screen.
 */
function ScopeSwitch(): JSX.Element {
  const scope = useExplorerStore((state) => state.scope);
  const setScope = useExplorerStore((state) => state.setScope);
  const selected = useExplorerStore((state) => state.selected);
  const selectedFile = useExplorerStore((state) => state.selectedFile);

  const what = selected?.name ?? selectedFile?.relative_path ?? null;

  return (
    <div className={styles.scopeSwitch}>
      <button
        className={`${styles.scopeOption} ${
          scope === 'selection' ? styles.scopeActive : ''
        }`}
        onClick={() => setScope('selection')}
        title={
          what
            ? `Mostrar solo lo relacionado con ${what}`
            : 'Las pestañas seguirán a lo que selecciones'
        }
      >
        Selección
      </button>
      <button
        className={`${styles.scopeOption} ${
          scope === 'project' ? styles.scopeActive : ''
        }`}
        onClick={() => setScope('project')}
        title="Mostrar todo el proyecto"
      >
        Proyecto
      </button>
    </div>
  );
}

function SearchBox(): JSX.Element {
  const { searchText, searchResults, searching, search, selectEntity } =
    useExplorerStore();
  const [open, setOpen] = useState(false);

  return (
    <div className={styles.searchWrap}>
      <input
        className={styles.search}
        placeholder="Buscar tabla, columna, item APEX, reporte…"
        value={searchText}
        onChange={(event) => {
          setOpen(true);
          void search(event.target.value);
        }}
        onFocus={() => setOpen(true)}
      />
      {open && searchText.trim() !== '' && (
        <div className={styles.results}>
          {searching && <p className={styles.muted}>Buscando…</p>}
          {!searching && searchResults.length === 0 && (
            <p className={styles.muted}>Sin coincidencias.</p>
          )}
          {searchResults.map((hit) => (
            <button
              key={hit.id}
              className={styles.result}
              onClick={() => {
                setOpen(false);
                void selectEntity(hit);
              }}
            >
              <span className={styles.dot} style={{ background: colorOf(hit.entity_type) }} />
              <span className={styles.resultName}>{hit.name}</span>
              <span className={styles.resultType}>{hit.entity_type}</span>
              {hit.file_path && (
                <span className={styles.resultPath}>
                  {hit.file_path}
                  {hit.start_line ? `:${hit.start_line}` : ''}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Height of one row, in pixels. Pinned in the stylesheet — the windowing
 *  arithmetic below is wrong the moment the two disagree. */
const ROW_HEIGHT = 24;

function FileTree({
  rows,
  expanded,
  onToggle,
}: {
  rows: TreeRow[];
  expanded: ReadonlySet<string>;
  onToggle: (path: string) => void;
}): JSX.Element {
  const window = useVirtualRows(rows.length, ROW_HEIGHT);

  if (rows.length === 0) {
    return (
      <div className={styles.tree}>
        <p className={styles.muted}>Sin archivos que mostrar.</p>
      </div>
    );
  }

  return (
    <div className={styles.tree} ref={window.ref} onScroll={window.onScroll}>
      {/* Full height so the scrollbar describes the whole list, not the slice. */}
      <div style={{ height: window.totalHeight, position: 'relative' }}>
        <div style={{ transform: `translateY(${window.offsetY}px)` }}>
          {rows.slice(window.start, window.end).map((row) => (
            <TreeBranch
              key={row.node.path}
              node={row.node}
              depth={row.depth}
              open={expanded.has(row.node.path)}
              onToggle={onToggle}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function TreeBranch({
  node,
  depth,
  open,
  onToggle,
}: {
  node: TreeNode;
  depth: number;
  open: boolean;
  onToggle: (path: string) => void;
}): JSX.Element {
  const selectFile = useExplorerStore((state) => state.selectFile);
  const selectedFile = useExplorerStore((state) => state.selectedFile);

  if (!node.isDirectory && node.file) {
    const file = node.file;
    const selected = selectedFile?.id === file.id;
    return (
      <button
        className={`${styles.file} ${selected ? styles.fileSelected : ''}`}
        style={{ paddingLeft: 10 + depth * 14 }}
        onClick={() => void selectFile(file)}
        title={file.relative_path}
      >
        <span className={styles.fileName}>{node.name}</span>
        <span className={styles.fileMeta}>
          {file.skip_reason ? (
            <span className={styles.skipped}>{file.skip_reason}</span>
          ) : file.is_modified ? (
            <span className={styles.modified}>pendiente</span>
          ) : null}
        </span>
      </button>
    );
  }

  return (
    <button
      className={styles.folder}
      style={{ paddingLeft: 10 + depth * 14 }}
      onClick={() => onToggle(node.path)}
      title={node.path}
    >
      <span className={styles.chevron}>{open ? '▾' : '▸'}</span>
      <span className={styles.fileName}>{node.name}</span>
    </button>
  );
}

function CodePanel(): JSX.Element {
  const { source, loadingSource, highlight, fileEntities, selectedFile } =
    useExplorerStore();

  if (loadingSource) {
    return <p className={styles.placeholder}>Abriendo el archivo…</p>;
  }
  if (!source) {
    // A file *is* selected but there is nothing to show: it was skipped, and
    // saying which reason is more use than repeating the generic invitation.
    if (selectedFile?.skip_reason) {
      return (
        <p className={styles.placeholder}>
          {selectedFile.relative_path} no se puede mostrar como texto
          ({selectedFile.skip_reason}).
        </p>
      );
    }
    return (
      <p className={styles.placeholder}>
        Selecciona un archivo del árbol, o pulsa la evidencia de cualquier
        relación para abrirlo en la línea que la prueba.
      </p>
    );
  }

  const markers = fileEntities
    .filter((item) => item.file_path === source.path && item.start_line)
    .map((item) => ({ line: item.start_line as number, label: `${item.entity_type} ${item.name}` }));

  return (
    <div className={styles.codeWrap}>
      <div className={styles.codeHead}>
        <span className={styles.codePath}>{source.path}</span>
        {highlight && (
          <span className={styles.codeLine}>
            línea {highlight.start}
            {highlight.end !== highlight.start ? `–${highlight.end}` : ''}
          </span>
        )}
        <span className={styles.readonly}>solo lectura</span>
      </div>
      <CodeViewer
        path={source.path}
        content={source.content}
        highlightStart={highlight?.start ?? null}
        highlightEnd={highlight?.end ?? null}
        markers={markers}
      />
    </div>
  );
}

function FilePanel(): JSX.Element {
  const { selectedFile, fileEntities, fileTables } = useExplorerStore();

  if (!selectedFile) {
    return <p className={styles.placeholder}>Selecciona un archivo del árbol.</p>;
  }

  return (
    <div className={styles.scroll}>
      <h3 className={styles.sectionTitle}>{selectedFile.relative_path}</h3>
      <div className={styles.metaGrid}>
        <Meta label="Tipo" value={selectedFile.detected_type} />
        <Meta label="Tamaño" value={formatBytes(selectedFile.size_bytes)} />
        <Meta label="Estado" value={selectedFile.analysis_status} />
        <Meta label="Omitido" value={selectedFile.skip_reason ?? '—'} />
      </div>

      <h4 className={styles.subTitle}>Tablas que toca ({fileTables.length})</h4>
      {fileTables.length === 0 ? (
        <p className={styles.muted}>Ninguna.</p>
      ) : (
        fileTables.map((hit, index) => (
          <UsageRow key={index} hit={hit} index={index} />
        ))
      )}

      <h4 className={styles.subTitle}>Entidades detectadas ({fileEntities.length})</h4>
      {fileEntities.length === 0 ? (
        <p className={styles.muted}>Ninguna.</p>
      ) : (
        <div className={styles.chips}>
          {fileEntities.map((entity) => (
            <EntityChip key={entity.id} entity={entity} />
          ))}
        </div>
      )}
    </div>
  );
}

function IssuesPanel(): JSX.Element {
  const { issues, scope, selectedFile } = useExplorerStore();

  // Filtered here rather than refetched: the whole list already arrived with the
  // project, and a round trip to drop rows would be slower and no more correct.
  const path = scope === 'selection' ? selectedFile?.relative_path : undefined;
  const shown = path
    ? issues.filter((issue) => issue.relative_path === path)
    : issues;

  if (shown.length === 0) {
    return (
      <p className={styles.placeholder}>
        {path
          ? `${path} no tiene avisos del analizador.`
          : 'Sin avisos del analizador.'}
      </p>
    );
  }
  return (
    <div className={styles.scroll}>
      {path && (
        <p className={styles.muted}>
          {shown.length} de {issues.length} avisos · solo {path}
        </p>
      )}
      {shown.map((issue, index) => (
        <div key={index} className={styles.issue} style={stagger(index)}>
          <div className={styles.issueHead}>
            <span
              className={
                issue.severity === 'error' ? styles.sevError : styles.sevWarning
              }
            >
              {issue.severity}
            </span>
            <code>{issue.code}</code>
            <span className={styles.issuePath}>{issue.relative_path ?? '(proyecto)'}</span>
          </div>
          <p className={styles.issueText}>{issue.message}</p>
        </div>
      ))}
    </div>
  );
}

/** What the last analysis changed — the "qué cambió" question, answered. */
function ChangesPanel(): JSX.Element {
  const { changes, openEvidence, scope, selectedFile } = useExplorerStore();

  if (!changes || changes.changes.length === 0) {
    return (
      <p className={styles.placeholder}>
        {changes?.run_id
          ? 'La última ejecución no encontró cambios.'
          : 'Este proyecto todavía no se ha analizado.'}
      </p>
    );
  }

  const path = scope === 'selection' ? selectedFile?.relative_path : undefined;
  const visible = path
    ? changes.changes.filter((change) => change.relative_path === path)
    : changes.changes;

  if (visible.length === 0) {
    return (
      <p className={styles.placeholder}>
        {path} no cambió en la última ejecución.
      </p>
    );
  }

  const order: Record<string, number> = { added: 0, modified: 1, deleted: 2, unchanged: 3 };
  const sorted = [...visible].sort(
    (a, b) =>
      (order[a.change_kind] ?? 9) - (order[b.change_kind] ?? 9) ||
      a.relative_path.localeCompare(b.relative_path),
  );

  return (
    <div className={styles.scroll}>
      <p className={styles.muted}>
        Ejecución {changes.run_id?.slice(0, 12)} · {sorted.length} archivos
        {path && ` de ${changes.changes.length}`}
      </p>
      {sorted.map((change) => (
        <button
          key={change.relative_path}
          className={styles.changeRow}
          // A deleted file has nothing left to open.
          disabled={change.change_kind === 'deleted'}
          onClick={() => void openEvidence(change.relative_path, 1)}
        >
          <span className={styles[`kind_${change.change_kind}`] ?? styles.kind_unchanged}>
            {change.change_kind}
          </span>
          <span className={styles.changePath}>{change.relative_path}</span>
          <span className={styles.changeType}>{change.detected_type}</span>
        </button>
      ))}
    </div>
  );
}

function DetailsPanel(): JSX.Element {
  const { selected, incoming, outgoing, loadingDetails } = useExplorerStore();

  if (!selected) {
    return (
      <div className={styles.scroll}>
        <p className={styles.placeholder}>
          Busca una entidad o selecciónala en el grafo para ver de dónde sale cada
          afirmación.
        </p>
      </div>
    );
  }

  return (
    <div className={styles.scroll}>
      <div className={styles.detailHead}>
        <span className={styles.dot} style={{ background: colorOf(selected.entity_type) }} />
        <div>
          <div className={styles.detailName}>{selected.name}</div>
          <div className={styles.detailType}>{selected.entity_type}</div>
        </div>
      </div>

      <Meta label="Nombre normalizado" value={selected.normalized_name} />
      {selected.qualified_name && <Meta label="Calificado" value={selected.qualified_name} />}
      <Meta
        label="Confianza"
        value={`${selected.confidence.toFixed(2)} · ${selected.verification_status}`}
        highlight={selected.verification_status !== 'confirmed'}
      />
      {selected.file_path && (
        <Meta
          label="Definida en"
          value={`${selected.file_path}${selected.start_line ? `:${selected.start_line}` : ''}`}
        />
      )}

      {loadingDetails && <p className={styles.muted}>Cargando relaciones…</p>}

      <h4 className={styles.subTitle}>Depende de ella ({incoming.length})</h4>
      {incoming.length === 0 ? (
        <p className={styles.muted}>Nada.</p>
      ) : (
        incoming.map((hit, index) => (
          <UsageRow key={`in-${index}`} hit={hit} index={index} />
        ))
      )}

      <h4 className={styles.subTitle}>Depende de ({outgoing.length})</h4>
      {outgoing.length === 0 ? (
        <p className={styles.muted}>Nada.</p>
      ) : (
        outgoing.map((hit, index) => (
          <UsageRow key={`out-${index}`} hit={hit} index={index} />
        ))
      )}
    </div>
  );
}

/** One relation, with the evidence that proves it. */
function UsageRow({ hit, index = 0 }: { hit: UsageHit; index?: number }): JSX.Element {
  const { selectEntity, openEvidence } = useExplorerStore();
  const inferred = hit.evidence.status !== 'confirmed';
  const where = hit.evidence.file_path;

  return (
    <div className={styles.usage} style={stagger(index)}>
      <div className={styles.usageHead}>
        <span className={styles.relation}>{relationLabel(hit.relation_type)}</span>
        <button className={styles.usageName} onClick={() => void selectEntity(hit.entity)}>
          {hit.entity.name}
        </button>
      </div>
      <div className={styles.evidence}>
        {/* The whole promise of the product in one click: land on the line. */}
        <button
          className={styles.evidenceWhere}
          disabled={!where}
          onClick={() =>
            where &&
            void openEvidence(where, hit.evidence.start_line, hit.evidence.end_line)
          }
          title={where ? 'Abrir en el visor' : undefined}
        >
          {where ?? '(sin archivo)'}
          {hit.evidence.start_line ? `:${hit.evidence.start_line}` : ''}
        </button>
        <span className={inferred ? styles.inferred : styles.confirmed}>
          {inferred
            ? `inferido ${hit.evidence.confidence.toFixed(2)}`
            : 'confirmado'}
        </span>
        <span className={styles.analyzer}>{hit.evidence.analyzer}</span>
      </div>
      {hit.evidence.snippet && (
        <pre className={styles.snippet}>{hit.evidence.snippet}</pre>
      )}
    </div>
  );
}

function EntityChip({ entity }: { entity: EntityHit }): JSX.Element {
  const { selectEntity } = useExplorerStore();
  return (
    <button className={styles.chip} onClick={() => void selectEntity(entity)}>
      <span className={styles.dot} style={{ background: colorOf(entity.entity_type) }} />
      {entity.name}
    </button>
  );
}

function Meta({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}): JSX.Element {
  return (
    <div className={styles.metaRow}>
      <span className={styles.metaLabel}>{label}</span>
      <span className={highlight ? styles.metaHighlight : styles.metaValue}>{value}</span>
    </div>
  );
}
