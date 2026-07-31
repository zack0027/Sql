/**
 * What has failed, how often, and what fixed it.
 *
 * This is the one screen where HANA holds knowledge no analyzer could ever
 * find. The engine reads the logs; a person writes down the remedy; and the two
 * meet because an error's identity is its code and the object it names, so the
 * note written the first night is waiting on the tenth.
 *
 * The recurrence count leads each row. It is the thing that turns a list of
 * failures into a priority order — twenty-three sightings of one error deserve
 * an afternoon in a way that one sighting of another does not.
 *
 * Two honesty details worth keeping:
 *
 * A remedy that did **not** work is shown, struck through rather than hidden.
 * Knowing which afternoon somebody already wasted is worth as much as knowing
 * what finally worked.
 *
 * A log always names objects with their schema and source code usually does
 * not, so the two are never merged into one entity. What HANA can say is that
 * they are probably the same thing — and it says exactly that, as an inference
 * with its own confidence, not as a link presented as fact.
 */

import { useState } from 'react';

import type { AffectedEntity, Incident } from '@hana/shared-types';

import styles from './IncidentPanel.module.css';

interface Props {
  incidents: Incident[];
  loading: boolean;
  onSolve: (errorId: string, description: string, worked: boolean) => void;
  onOpenEvidence: (path: string, line: number | null) => void;
}

export function IncidentPanel({
  incidents,
  loading,
  onSolve,
  onOpenEvidence,
}: Props): JSX.Element {
  if (loading) {
    return <p className={styles.placeholder}>Leyendo los logs…</p>;
  }
  if (incidents.length === 0) {
    return (
      <p className={styles.placeholder}>
        Ningún error en los logs analizados.
        <span className={styles.hint}>
          HANA lee archivos .log, .err, .trc y .out, y también cualquier archivo
          que contenga códigos de error de Oracle. Copia un log dentro de la
          carpeta del proyecto y vuelve a analizar.
        </span>
      </p>
    );
  }

  return (
    <div className={styles.scroll}>
      {incidents.map((incident) => (
        <Row
          key={incident.id}
          incident={incident}
          onSolve={onSolve}
          onOpenEvidence={onOpenEvidence}
        />
      ))}
    </div>
  );
}

function Row({
  incident,
  onSolve,
  onOpenEvidence,
}: {
  incident: Incident;
  onSolve: (errorId: string, description: string, worked: boolean) => void;
  onOpenEvidence: (path: string, line: number | null) => void;
}): JSX.Element {
  const [writing, setWriting] = useState(false);
  const [text, setText] = useState('');
  const [worked, setWorked] = useState(true);

  const submit = () => {
    if (!text.trim()) return;
    onSolve(incident.id, text.trim(), worked);
    setText('');
    setWriting(false);
  };

  return (
    <section className={styles.incident}>
      <header className={styles.head}>
        <span className={styles.code}>{incident.name}</span>
        <span
          className={incident.times_seen > 1 ? styles.recurring : styles.once}
          title={`Visto ${incident.times_seen} ${
            incident.times_seen === 1 ? 'vez' : 'veces'
          }`}
        >
          ×{incident.times_seen}
        </span>
        {incident.file_path && (
          <button
            className={styles.where}
            onClick={() => onOpenEvidence(incident.file_path!, incident.start_line)}
          >
            {incident.file_path}:{incident.start_line}
          </button>
        )}
      </header>

      {incident.message && <p className={styles.message}>{incident.message}</p>}

      {incident.affects.length > 0 && (
        <div className={styles.affects}>
          {incident.affects.map((target) => (
            <Affected
              key={target.id}
              target={target}
              onOpenEvidence={onOpenEvidence}
            />
          ))}
        </div>
      )}

      {incident.solutions.length > 0 && (
        <ul className={styles.solutions}>
          {incident.solutions.map((solution) => (
            <li
              key={solution.id}
              className={solution.worked ? styles.worked : styles.failed}
            >
              <span className={styles.verdictMark}>
                {solution.worked ? 'Resuelto' : 'No funcionó'}
              </span>
              <span className={styles.solutionText}>{solution.description}</span>
            </li>
          ))}
        </ul>
      )}

      {writing ? (
        <div className={styles.writer}>
          <textarea
            className={styles.textarea}
            placeholder="Qué se hizo. Con detalle: dentro de seis meses lo vas a agradecer."
            value={text}
            rows={3}
            onChange={(event) => setText(event.target.value)}
          />
          <label className={styles.toggle}>
            <input
              type="checkbox"
              checked={worked}
              onChange={(event) => setWorked(event.target.checked)}
            />
            Funcionó
          </label>
          <div className={styles.writerActions}>
            <button className={styles.save} onClick={submit}>
              Guardar
            </button>
            <button className={styles.cancel} onClick={() => setWriting(false)}>
              Cancelar
            </button>
          </div>
        </div>
      ) : (
        <button className={styles.add} onClick={() => setWriting(true)}>
          {incident.solutions.length ? 'Añadir otra nota' : '¿Qué lo resolvió?'}
        </button>
      )}
    </section>
  );
}

function Affected({
  target,
  onOpenEvidence,
}: {
  target: AffectedEntity;
  onOpenEvidence: (path: string, line: number | null) => void;
}): JSX.Element {
  return (
    <div className={styles.target}>
      <span className={styles.targetKind}>{target.entity_type}</span>
      <span className={styles.targetName}>
        {target.qualified_name ?? target.name}
      </span>

      {target.probably_same_as.map((same) => (
        <span key={same.id} className={styles.same} title={same.reason}>
          ≈{' '}
          <button
            className={styles.sameLink}
            onClick={() =>
              same.file_path && onOpenEvidence(same.file_path, same.start_line)
            }
          >
            {same.qualified_name ?? same.name}
          </button>{' '}
          en {same.file_path}:{same.start_line}
          <span className={styles.sameFlag}>
            inferido {same.confidence.toFixed(2)}
          </span>
        </span>
      ))}
    </div>
  );
}
