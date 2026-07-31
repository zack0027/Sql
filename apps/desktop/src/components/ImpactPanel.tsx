/**
 * Transitive impact — what breaks if I change this?
 *
 * The calculation matters, but so does the presentation. A flat list of two
 * hundred entities is not an answer to anything, so results are grouped by kind
 * and ordered by distance, and each row says how the change reaches it.
 *
 * The line that carries the most weight here is the visual one between what is
 * confirmed and what arrives through an inference. A path crossing a 0.9 guess
 * cannot be shown the same way as one proved by syntax — the reader has to be
 * able to trust the solid part without the speculative part contaminating it.
 * That is why an inferred path is dimmed and labelled rather than merely tinted.
 *
 * And when the walk hits its limit, the panel says so. An incomplete impact
 * presented as complete is worse than no impact at all.
 */

import { useMemo } from 'react';

import type { EntityHit, ImpactNode, ImpactReport } from '@hana/shared-types';

import styles from './ImpactPanel.module.css';

interface Props {
  report: ImpactReport | null;
  selected: EntityHit | null;
  loading: boolean;
  depth: number;
  reverse: boolean;
  onDepthChange: (depth: number) => void;
  onToggleDirection: () => void;
  onSelect: (entityId: string) => void;
  onOpenEvidence: (path: string, line: number | null) => void;
}

/** Human names for the entity kinds an impact answer can contain. */
const KIND_LABELS: Record<string, string> = {
  OracleTable: 'Tablas',
  OracleColumn: 'Columnas',
  OracleView: 'Vistas',
  OracleProcedure: 'Procedimientos',
  OracleFunction: 'Funciones',
  OraclePackage: 'Paquetes',
  SqlQuery: 'Consultas',
  ApexPage: 'Páginas APEX',
  ApexItem: 'Items APEX',
  ApexProcess: 'Procesos APEX',
  JasperReport: 'Reportes',
  JasperField: 'Campos de reporte',
  JasperParameter: 'Parámetros de reporte',
  MocaCommand: 'Comandos MOCA',
  MocaVariable: 'Variables MOCA',
  JsonProperty: 'Propiedades JSON',
  JavaScriptFunction: 'Funciones JavaScript',
  PythonFunction: 'Funciones Python',
  File: 'Archivos',
};

/** Kinds worth showing first: the ones people act on. */
const KIND_ORDER = [
  'OracleTable',
  'OracleColumn',
  'OracleProcedure',
  'OracleFunction',
  'OraclePackage',
  'JasperReport',
  'ApexPage',
  'ApexItem',
  'MocaCommand',
  'SqlQuery',
];

function rank(kind: string): number {
  const index = KIND_ORDER.indexOf(kind);
  return index === -1 ? KIND_ORDER.length : index;
}

export function ImpactPanel({
  report,
  selected,
  loading,
  depth,
  reverse,
  onDepthChange,
  onToggleDirection,
  onSelect,
  onOpenEvidence,
}: Props): JSX.Element {
  const groups = useMemo(() => {
    if (!report) return [];
    const byKind = new Map<string, ImpactNode[]>();
    for (const node of report.nodes) {
      const list = byKind.get(node.entity.entity_type);
      if (list) list.push(node);
      else byKind.set(node.entity.entity_type, [node]);
    }
    return [...byKind.entries()]
      .map(([kind, nodes]) => ({
        kind,
        nodes: [...nodes].sort((a, b) => a.depth - b.depth),
      }))
      .sort((a, b) => rank(a.kind) - rank(b.kind) || a.kind.localeCompare(b.kind));
  }, [report]);

  const certain = report?.nodes.filter((node) => !node.inferred_in_path).length ?? 0;
  const guessed = (report?.nodes.length ?? 0) - certain;

  if (!selected) {
    return (
      <p className={styles.placeholder}>
        Selecciona una entidad — en el buscador o en el grafo — para ver qué se
        rompería si cambiara.
      </p>
    );
  }

  return (
    <div className={styles.wrapper}>
      <div className={styles.toolbar}>
        <strong className={styles.name}>{selected.name}</strong>
        <span className={styles.question}>
          {reverse ? 'de qué depende' : 'qué se rompe si cambia'}
        </span>

        <button
          className={styles.tool}
          onClick={onToggleDirection}
          title="Invertir la pregunta"
        >
          {reverse ? '← invertir' : 'invertir →'}
        </button>

        <label className={styles.depth}>
          saltos
          <input
            type="range"
            min={1}
            max={8}
            value={depth}
            onChange={(event) => onDepthChange(Number(event.target.value))}
          />
          <span className={styles.depthValue}>{depth}</span>
        </label>

        {report && report.nodes.length > 0 && (
          <span className={styles.tally}>
            {certain} confirmado{certain === 1 ? '' : 's'}
            {guessed > 0 && <> · {guessed} por inferencia</>}
          </span>
        )}
      </div>

      {report?.truncated && (
        // Never let a cut-off answer read as a complete one.
        <p className={styles.truncated}>
          Se alcanzó el límite de resultados. Esta lista está incompleta: hay más
          cosas afectadas de las que se ven aquí.
        </p>
      )}

      {loading && <p className={styles.placeholder}>Recorriendo el grafo…</p>}

      {!loading && report && report.nodes.length === 0 && (
        <p className={styles.placeholder}>
          Nada en el proyecto llega hasta aquí en {depth}{' '}
          {depth === 1 ? 'salto' : 'saltos'}.
          <span className={styles.caveatInline}>
            Ausencia de evidencia no es evidencia de ausencia: lo que se invoca
            dinámicamente o desde fuera del proyecto, HANA no lo ve.
          </span>
        </p>
      )}

      {!loading && report && report.nodes.length > 0 && (
        <div className={styles.scroll}>
          {groups.map((group) => (
            <section key={group.kind} className={styles.group}>
              <h3 className={styles.groupHead}>
                {KIND_LABELS[group.kind] ?? group.kind}
                <span className={styles.groupCount}>{group.nodes.length}</span>
              </h3>
              <ul className={styles.list}>
                {group.nodes.map((node) => (
                  <Row
                    key={node.entity.id}
                    node={node}
                    onSelect={onSelect}
                    onOpenEvidence={onOpenEvidence}
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function Row({
  node,
  onSelect,
  onOpenEvidence,
}: {
  node: ImpactNode;
  onSelect: (entityId: string) => void;
  onOpenEvidence: (path: string, line: number | null) => void;
}): JSX.Element {
  const { evidence } = node;
  return (
    <li
      className={`${styles.row} ${node.inferred_in_path ? styles.rowInferred : ''}`}
    >
      <span className={styles.hops} title={`${node.depth} saltos desde el origen`}>
        {node.depth}
      </span>

      <button className={styles.rowName} onClick={() => onSelect(node.entity.id)}>
        {node.entity.name}
      </button>

      <span className={styles.relation}>{node.relation_type.toLowerCase()}</span>

      {node.inferred_in_path && (
        <span className={styles.badge}>
          inferido {node.min_confidence.toFixed(2)}
        </span>
      )}

      {evidence.file_path && (
        <button
          className={styles.where}
          onClick={() => onOpenEvidence(evidence.file_path!, evidence.start_line)}
          title="Abrir el archivo en la línea que lo prueba"
        >
          {evidence.file_path}:{evidence.start_line}
        </button>
      )}
    </li>
  );
}
