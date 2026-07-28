/**
 * The project explorer: files on the left, graph in the middle, evidence on the
 * right.
 *
 * The right-hand panel is the point of the whole product. Every relation it
 * lists carries the file, the line and the fragment that prove it, and says
 * plainly whether the fact was confirmed by syntax or inferred from a
 * convention. Nothing is shown that HANA cannot justify.
 */

import { useEffect, useMemo, useState } from 'react';

import type { EntityHit, UsageHit } from '@hana/shared-types';

import { CodeViewer } from '../components/CodeViewer';
import { ErDiagram } from '../components/ErDiagram';
import { GraphCanvas } from '../components/GraphCanvas';
import { ReportPreview } from '../components/ReportPreview';
import { buildFileTree, colorOf, relationLabel, type TreeNode } from '../lib/graph';
import { formatBytes } from '../lib/format';
import { useResizable } from '../lib/useResizable';
import { useExplorerStore } from '../state/explorer';
import { useAppStore } from '../state/store';
import styles from './ExplorerView.module.css';

export function ExplorerView({ onBack }: { onBack: () => void }): JSX.Element {
  const project = useAppStore((state) =>
    state.projects.find((item) => item.id === state.activeProjectId),
  );
  const explorer = useExplorerStore();
  const [filter, setFilter] = useState('');
  const left = useResizable('hana.panel.left', 280, { min: 200, max: 520, side: 'left' });
  const right = useResizable('hana.panel.right', 380, { min: 280, max: 680, side: 'right' });

  useEffect(() => {
    if (project && explorer.projectId !== project.id) {
      void explorer.open(project.id);
    }
  }, [project, explorer]);

  const tree = useMemo(() => {
    const files = filter
      ? explorer.files.filter((file) =>
          file.relative_path.toLowerCase().includes(filter.toLowerCase()),
        )
      : explorer.files;
    return buildFileTree(files);
  }, [explorer.files, filter]);

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
          <div className={styles.tree}>
            {tree.length === 0 ? (
              <p className={styles.muted}>Sin archivos que mostrar.</p>
            ) : (
              tree.map((node) => (
                <TreeBranch key={node.path} node={node} depth={0} />
              ))
            )}
          </div>
        </aside>

        <div
          className={`${styles.handle} ${left.dragging ? styles.handleActive : ''}`}
          onPointerDown={left.onPointerDown}
          onDoubleClick={left.reset}
          title="Arrastra para redimensionar · doble clic para restablecer"
        />

        {/* ---- centre: graph / code / file / issues ----------------------- */}
        <main className={styles.centre}>
          <div className={styles.tabs}>
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
                onClick={() => explorer.setTab(key)}
              >
                {label}
              </button>
            ))}
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

function TreeBranch({ node, depth }: { node: TreeNode; depth: number }): JSX.Element {
  const [open, setOpen] = useState(depth < 1);
  const { selectFile, selectedFile } = useExplorerStore();

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
    <div>
      <button
        className={styles.folder}
        style={{ paddingLeft: 10 + depth * 14 }}
        onClick={() => setOpen((value) => !value)}
      >
        <span className={styles.chevron}>{open ? '▾' : '▸'}</span>
        {node.name}
      </button>
      {open &&
        node.children.map((child) => (
          <TreeBranch key={child.path} node={child} depth={depth + 1} />
        ))}
    </div>
  );
}

function CodePanel(): JSX.Element {
  const { source, loadingSource, highlight, fileEntities } = useExplorerStore();

  if (loadingSource) {
    return <p className={styles.placeholder}>Abriendo el archivo…</p>;
  }
  if (!source) {
    return (
      <p className={styles.placeholder}>
        Pulsa la evidencia de cualquier relación para abrir el archivo en la línea
        que la prueba.
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
        fileTables.map((hit, index) => <UsageRow key={index} hit={hit} />)
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
  const { issues } = useExplorerStore();
  if (issues.length === 0) {
    return <p className={styles.placeholder}>Sin avisos del analizador.</p>;
  }
  return (
    <div className={styles.scroll}>
      {issues.map((issue, index) => (
        <div key={index} className={styles.issue}>
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
  const { changes, openEvidence } = useExplorerStore();

  if (!changes || changes.changes.length === 0) {
    return (
      <p className={styles.placeholder}>
        {changes?.run_id
          ? 'La última ejecución no encontró cambios.'
          : 'Este proyecto todavía no se ha analizado.'}
      </p>
    );
  }

  const order: Record<string, number> = { added: 0, modified: 1, deleted: 2, unchanged: 3 };
  const sorted = [...changes.changes].sort(
    (a, b) =>
      (order[a.change_kind] ?? 9) - (order[b.change_kind] ?? 9) ||
      a.relative_path.localeCompare(b.relative_path),
  );

  return (
    <div className={styles.scroll}>
      <p className={styles.muted}>
        Ejecución {changes.run_id?.slice(0, 12)} · {sorted.length} archivos
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
        incoming.map((hit, index) => <UsageRow key={`in-${index}`} hit={hit} />)
      )}

      <h4 className={styles.subTitle}>Depende de ({outgoing.length})</h4>
      {outgoing.length === 0 ? (
        <p className={styles.muted}>Nada.</p>
      ) : (
        outgoing.map((hit, index) => <UsageRow key={`out-${index}`} hit={hit} />)
      )}
    </div>
  );
}

/** One relation, with the evidence that proves it. */
function UsageRow({ hit }: { hit: UsageHit }): JSX.Element {
  const { selectEntity, openEvidence } = useExplorerStore();
  const inferred = hit.evidence.status !== 'confirmed';
  const where = hit.evidence.file_path;

  return (
    <div className={styles.usage}>
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
