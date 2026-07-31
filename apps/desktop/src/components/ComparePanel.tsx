/**
 * Two environments, compared by their graphs.
 *
 * Not a text diff. Two copies of the same code come back reordered and
 * reformatted, and a line-based comparison marks everything as changed. What
 * matters is whether the same things exist and still relate the same way.
 *
 * The warning is the important part of this screen. Comparing two folders that
 * are not versions of the same code produces a report saying almost everything
 * appeared and disappeared — which reads like a catastrophic difference between
 * environments when it is really the wrong two projects. So it goes above the
 * results, and the results are dimmed behind it.
 */

import type { ComparisonReport, Project } from '@hana/shared-types';

import styles from './ComparePanel.module.css';

interface Props {
  report: ComparisonReport | null;
  projects: Project[];
  currentId: string | null;
  againstId: string | null;
  loading: boolean;
  onPick: (projectId: string) => void;
}

export function ComparePanel({
  report,
  projects,
  currentId,
  againstId,
  loading,
  onPick,
}: Props): JSX.Element {
  const others = projects.filter((project) => project.id !== currentId);

  return (
    <div className={styles.wrapper}>
      <div className={styles.toolbar}>
        <span className={styles.label}>Comparar con</span>
        <select
          className={styles.picker}
          value={againstId ?? ''}
          onChange={(event) => onPick(event.target.value)}
        >
          <option value="">elige un proyecto…</option>
          {others.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
        {report && (
          <span className={styles.tally}>
            {report.shared_entities} entidades en común ·{' '}
            {report.shared_relations} afirmaciones
          </span>
        )}
      </div>

      {others.length === 0 && (
        <p className={styles.placeholder}>
          Solo hay un proyecto abierto. Abre la otra versión —el DEV o el PROD—
          desde la pantalla de inicio y vuelve aquí.
        </p>
      )}

      {loading && <p className={styles.placeholder}>Comparando los dos grafos…</p>}

      {!loading && report?.warning && (
        <p className={styles.warning}>{report.warning}</p>
      )}

      {!loading && report && (
        <div className={styles.scroll}>
          <Side
            title={`Solo en ${report.left.name}`}
            entities={report.entities_only_left}
            relations={report.relations_only_left}
          />
          <Side
            title={`Solo en ${report.right.name}`}
            entities={report.entities_only_right}
            relations={report.relations_only_right}
          />

          {isEmpty(report) && (
            <p className={styles.placeholder}>
              Los dos grafos dicen lo mismo.
            </p>
          )}

          {report.truncated && (
            <p className={styles.truncated}>
              Alguna lista quedó recortada por el límite: hay más diferencias de
              las que se ven aquí.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function isEmpty(report: ComparisonReport): boolean {
  return (
    Object.keys(report.entities_only_left).length === 0 &&
    Object.keys(report.entities_only_right).length === 0 &&
    Object.keys(report.relations_only_left).length === 0 &&
    Object.keys(report.relations_only_right).length === 0
  );
}

function Side({
  title,
  entities,
  relations,
}: {
  title: string;
  entities: ComparisonReport['entities_only_left'];
  relations: ComparisonReport['relations_only_left'];
}): JSX.Element | null {
  const hasEntities = Object.keys(entities).length > 0;
  const hasRelations = Object.keys(relations).length > 0;
  if (!hasEntities && !hasRelations) return null;

  return (
    <section className={styles.side}>
      <h3 className={styles.sideHead}>{title}</h3>

      {Object.entries(entities)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([kind, hits]) => (
          <div key={kind} className={styles.group}>
            <h4 className={styles.groupHead}>
              {kind}
              <span className={styles.groupCount}>{hits.length}</span>
            </h4>
            <ul className={styles.list}>
              {hits.map((hit) => (
                <li key={hit.id ?? hit.normalized_name} className={styles.row}>
                  <span className={styles.rowName}>{hit.name}</span>
                  {hit.file_path && (
                    <span className={styles.where}>
                      {hit.file_path}:{hit.start_line}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}

      {Object.entries(relations)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([kind, claims]) => (
          <div key={kind} className={styles.group}>
            <h4 className={styles.groupHead}>
              {kind.toLowerCase()}
              <span className={styles.groupCount}>{claims.length}</span>
            </h4>
            <ul className={styles.list}>
              {claims.map((claim) => (
                <li key={claim.key} className={styles.row}>
                  <span className={styles.rowName}>
                    {claim.source_name} → {claim.target_name}
                  </span>
                  {claim.file_path && (
                    <span className={styles.where}>
                      {claim.file_path}:{claim.start_line}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
    </section>
  );
}
