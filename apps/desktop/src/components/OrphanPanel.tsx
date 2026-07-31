/**
 * Entities nothing in the project refers to.
 *
 * The dangerous thing about this screen is not the query, it is the wording.
 * "Dead code" invites deletion; what HANA actually knows is that *it* found no
 * reference, reading the folder statically. Anything invoked from a scheduler,
 * from another application, by dynamic SQL, or from code outside the analysed
 * folder is invisible to it.
 *
 * So the caveat is not a footnote. It sits above the list, before anything has
 * been read, and it comes from the engine rather than being retyped here — one
 * wording, so the CLI and this panel cannot drift into saying different things.
 */

import type { EntityHit, OrphanReport } from '@hana/shared-types';

import styles from './OrphanPanel.module.css';

interface Props {
  report: OrphanReport | null;
  loading: boolean;
  onSelect: (entity: EntityHit) => void;
  onOpenEvidence: (path: string, line: number | null) => void;
}

const KIND_LABELS: Record<string, string> = {
  OracleTable: 'Tablas que nadie lee',
  OracleView: 'Vistas que nadie lee',
  OracleColumn: 'Columnas que nadie lee',
  OracleProcedure: 'Procedimientos que nadie llama',
  OracleFunction: 'Funciones que nadie llama',
  ApexItem: 'Items APEX sin uso',
};

export function OrphanPanel({
  report,
  loading,
  onSelect,
  onOpenEvidence,
}: Props): JSX.Element {
  if (loading) {
    return <p className={styles.placeholder}>Buscando referencias…</p>;
  }
  if (!report) {
    return <p className={styles.placeholder}>Sin datos todavía.</p>;
  }

  return (
    <div className={styles.wrapper}>
      {/* Above the list on purpose: it has to be read before the names are. */}
      <p className={styles.caveat}>{report.caveat}</p>

      {report.total === 0 ? (
        <p className={styles.placeholder}>
          Todo lo que HANA sabe leer está referenciado por algo.
        </p>
      ) : (
        <div className={styles.scroll}>
          {Object.entries(report.by_type)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([kind, hits]) => (
              <section key={kind} className={styles.group}>
                <h3 className={styles.groupHead}>
                  {KIND_LABELS[kind] ?? kind}
                  <span className={styles.groupCount}>{hits.length}</span>
                </h3>
                <ul className={styles.list}>
                  {hits.map((hit) => (
                    <li key={hit.id} className={styles.row}>
                      <button
                        className={styles.rowName}
                        onClick={() => onSelect(hit)}
                      >
                        {hit.name}
                      </button>
                      {hit.qualified_name && (
                        <span className={styles.qualified}>
                          {hit.qualified_name}
                        </span>
                      )}
                      {hit.file_path && (
                        <button
                          className={styles.where}
                          onClick={() =>
                            onOpenEvidence(hit.file_path!, hit.start_line)
                          }
                          title="Abrir donde está declarado"
                        >
                          {hit.file_path}:{hit.start_line}
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            ))}

          {report.truncated && (
            <p className={styles.truncated}>
              La lista está recortada por el límite: hay más candidatos de los
              que se ven aquí.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
