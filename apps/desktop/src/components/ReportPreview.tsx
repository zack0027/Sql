/**
 * A Jasper report, previewed piece by piece.
 *
 * Not a rendering of the report — HANA does not run JasperReports and does not
 * evaluate the expressions it finds. This is a **structural** preview: each band
 * drawn to scale in its printing order, with the elements placed where the JRXML
 * puts them and labelled with the expression they will show.
 *
 * That distinction matters. A picture that looked like the finished report would
 * imply HANA had executed something; what it can honestly show is the layout and
 * where each value comes from, which is what you need when a field lands in the
 * wrong band or a parameter is not reaching the page.
 */

import { useMemo, useState, type CSSProperties } from 'react';

import type { ReportBand, ReportElement, ReportStructure } from '@hana/shared-types';

import styles from './ReportPreview.module.css';

interface Props {
  report: ReportStructure | null;
  loading: boolean;
}

/** Human names, in printing order — the order Jasper lays them out. */
const SECTION_LABELS: Record<string, string> = {
  background: 'Fondo',
  title: 'Título',
  pageHeader: 'Cabecera de página',
  columnHeader: 'Cabecera de columna',
  groupHeader: 'Cabecera de grupo',
  detail: 'Detalle',
  groupFooter: 'Pie de grupo',
  columnFooter: 'Pie de columna',
  pageFooter: 'Pie de página',
  lastPageFooter: 'Pie de última página',
  summary: 'Resumen',
  noData: 'Sin datos',
};

const KIND_LABELS: Record<string, string> = {
  textField: 'campo',
  staticText: 'texto',
  image: 'imagen',
  subreport: 'subreporte',
  line: 'línea',
  rectangle: 'rectángulo',
  ellipse: 'elipse',
  chart: 'gráfico',
  crosstab: 'tabla cruzada',
  frame: 'marco',
};

/** Page width Jasper assumes by default; used to scale the preview. */
const ASSUMED_WIDTH = 555;

export function ReportPreview({ report, loading }: Props): JSX.Element {
  const [zoom, setZoom] = useState(1);
  const [selected, setSelected] = useState<ReportElement | null>(null);

  const totals = useMemo(() => {
    if (!report) return { elements: 0, references: 0 };
    const references = new Set<string>();
    let elements = 0;
    for (const band of report.bands) {
      elements += band.elements.length;
      band.elements.forEach((element) =>
        element.references.forEach((reference) => references.add(reference)),
      );
    }
    return { elements, references: references.size };
  }, [report]);

  if (loading) {
    return <p className={styles.placeholder}>Leyendo la estructura del reporte…</p>;
  }
  if (!report) {
    return (
      <p className={styles.placeholder}>
        Selecciona un reporte Jasper — en el buscador o en el grafo — para ver
        cómo está compuesto.
      </p>
    );
  }
  if (report.bands.length === 0) {
    // An empty preview has two very different causes, and saying the wrong one
    // sends the user to look for a bug in their report. Knowledge produced by an
    // older analyzer is not evidence about the file.
    return report.stale ? (
      <p className={styles.placeholder}>
        {report.name} lo leyó una versión anterior de HANA, que todavía no
        extraía las bandas. Vuelve a analizar el proyecto y aparecerán; el
        archivo no tiene nada malo.
      </p>
    ) : (
      <p className={styles.placeholder}>
        {report.name}: el analizador no encontró bandas en este reporte.
      </p>
    );
  }

  return (
    <div className={styles.wrapper}>
      <div className={styles.toolbar}>
        <strong className={styles.name}>{report.name}</strong>
        <span className={styles.count}>
          {report.bands.length} piezas · {totals.elements} elementos ·{' '}
          {totals.references} referencias
        </span>
        <button className={styles.tool} onClick={() => setZoom((z) => Math.min(2, z * 1.15))}>
          +
        </button>
        <button className={styles.tool} onClick={() => setZoom((z) => Math.max(0.4, z / 1.15))}>
          −
        </button>
        {/* Never let this be mistaken for the printed report. */}
        <span className={styles.caveat}>vista estructural · no se ejecuta el reporte</span>
      </div>

      <div className={styles.scroll}>
        <div className={styles.page} style={{ width: ASSUMED_WIDTH * zoom }}>
          {report.bands.map((band, index) => (
            <Band
              key={`${band.section}-${index}`}
              band={band}
              index={index}
              zoom={zoom}
              selected={selected}
              onSelect={setSelected}
            />
          ))}
        </div>

        {selected && (
          <aside className={styles.inspector}>
            <div className={styles.inspectorHead}>
              <span>{KIND_LABELS[selected.kind] ?? selected.kind}</span>
              <button onClick={() => setSelected(null)} aria-label="Cerrar">
                ×
              </button>
            </div>
            <Row label="Posición" value={`x=${selected.x ?? '?'} · y=${selected.y ?? '?'}`} />
            <Row
              label="Tamaño"
              value={`${selected.width ?? '?'} × ${selected.height ?? '?'}`}
            />
            {selected.text && (
              <>
                <div className={styles.inspectorLabel}>Expresión</div>
                <pre className={styles.expression}>{selected.text}</pre>
              </>
            )}
            {selected.references.length > 0 && (
              <>
                <div className={styles.inspectorLabel}>De dónde salen los datos</div>
                <div className={styles.chips}>
                  {selected.references.map((reference) => (
                    <span key={reference} className={styles.chip}>
                      {reference}
                    </span>
                  ))}
                </div>
              </>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

function Band({
  band,
  index,
  zoom,
  selected,
  onSelect,
}: {
  band: ReportBand;
  index: number;
  zoom: number;
  selected: ReportElement | null;
  onSelect: (element: ReportElement) => void;
}): JSX.Element {
  // A band with no declared height still needs room for its label.
  const height = Math.max(band.height ?? 0, 24);

  return (
    <section
      className={styles.band}
      style={{ '--delay': `${Math.min(index, 10) * 45}ms` } as CSSProperties}
    >
      <header className={styles.bandHead}>
        <span className={styles.bandName}>
          {SECTION_LABELS[band.section] ?? band.section}
          {band.group && <span className={styles.bandGroup}> · {band.group}</span>}
        </span>
        <span className={styles.bandMeta}>
          {band.height ?? '?'} px · {band.elements.length} elementos
        </span>
      </header>

      <div className={styles.canvas} style={{ height: height * zoom }}>
        {band.elements.length === 0 && <span className={styles.emptyBand}>banda vacía</span>}
        {band.elements.map((element, index) => (
          <button
            key={index}
            className={`${styles.element} ${styles[`kind_${element.kind}`] ?? ''} ${
              selected === element ? styles.elementSelected : ''
            }`}
            style={{
              left: (element.x ?? 0) * zoom,
              top: (element.y ?? 0) * zoom,
              width: Math.max((element.width ?? 60) * zoom, 14),
              height: Math.max((element.height ?? 16) * zoom, 12),
            }}
            onClick={() => onSelect(element)}
            title={element.text || element.kind}
          >
            <span className={styles.elementText}>{element.text || element.kind}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div className={styles.inspectorRow}>
      <span className={styles.inspectorLabel}>{label}</span>
      <span className={styles.inspectorValue}>{value}</span>
    </div>
  );
}
