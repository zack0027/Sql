/**
 * Read-only source viewer.
 *
 * Monaco is loaded lazily and configured as a *viewer*, never an editor: the
 * product promises it does not modify the files it analyses, so the component
 * that shows them cannot be able to write. `readOnly` is set, the context menu
 * is off, and nothing here has a save path.
 *
 * Its job is to make evidence checkable. Given a line, it scrolls there, marks
 * the range and keeps it visible — so "this relation is proved at line 22" can
 * be confirmed with one glance rather than taken on trust.
 */

import { useEffect, useRef, useState } from 'react';

import styles from './CodeViewer.module.css';

interface Props {
  path: string;
  content: string;
  /** 1-indexed line to reveal and highlight, if any. */
  highlightStart?: number | null;
  highlightEnd?: number | null;
  /** Extra lines to mark faintly — where entities were found. */
  markers?: Array<{ line: number; label: string }>;
}

/** Map a file extension to a Monaco language id. */
function languageOf(path: string): string {
  const extension = path.toLowerCase().split('.').pop() ?? '';
  switch (extension) {
    case 'sql':
    case 'plsql':
    case 'pks':
    case 'pkb':
    case 'prc':
    case 'fnc':
    case 'trg':
    case 'vw':
      return 'sql';
    case 'jrxml':
    case 'xml':
    case 'xsl':
    case 'xsd':
      return 'xml';
    case 'json':
    case 'jsonc':
      return 'json';
    case 'js':
    case 'mjs':
    case 'cjs':
    case 'jsx':
      return 'javascript';
    case 'ts':
    case 'tsx':
      return 'typescript';
    case 'py':
      return 'python';
    case 'html':
    case 'htm':
      return 'html';
    case 'css':
      return 'css';
    case 'md':
      return 'markdown';
    // MOCA has no Monaco grammar. SQL is the closest useful highlighting, since
    // a pipeline is mostly bracketed SQL.
    case 'mcmd':
    case 'moca':
    case 'mcom':
      return 'sql';
    default:
      return 'plaintext';
  }
}

export function CodeViewer({
  path,
  content,
  highlightStart,
  highlightEnd,
  markers = [],
}: Props): JSX.Element {
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<unknown>(null);
  const monaco = useRef<typeof import('monaco-editor') | null>(null);
  const decorations = useRef<unknown>(null);
  const [failed, setFailed] = useState<string | null>(null);

  // Create once, then feed it new content: recreating the editor per file would
  // throw away Monaco's tokenisation work on every click.
  useEffect(() => {
    let disposed = false;

    void (async () => {
      try {
        const mod = await import('monaco-editor');
        if (disposed || !host.current) return;
        monaco.current = mod;

        // Monaco owns its own colours and cannot read CSS variables, so the
        // palette is mirrored here. These literals are the same values as the
        // `--surface-*` tokens in styles/theme.css — if those move, these have
        // to move with them, or the editor becomes a rectangle from a different
        // application in the middle of the window.
        mod.editor.defineTheme('hana-dark', {
          base: 'vs-dark',
          inherit: true,
          rules: [
            { token: 'comment', foreground: '8479a6', fontStyle: 'italic' },
            { token: 'keyword', foreground: 'c4b5fd' },
            { token: 'string', foreground: '7ee8dd' },
            { token: 'number', foreground: 'fbbf24' },
            { token: 'type', foreground: '7aa2ff' },
            { token: 'tag', foreground: 'f472b6' },
            { token: 'attribute.name', foreground: 'a78bfa' },
            { token: 'attribute.value', foreground: '7ee8dd' },
            { token: 'delimiter', foreground: 'b3a9d0' },
          ],
          colors: {
            'editor.background': '#0e0c17',
            'editor.foreground': '#ece9f5',
            'editorGutter.background': '#14121f',
            'editorLineNumber.foreground': '#4a4170',
            'editorLineNumber.activeForeground': '#a78bfa',
            'editor.lineHighlightBackground': '#1c1930',
            'editor.selectionBackground': '#3d3463',
            'editorCursor.foreground': '#4fd1c5',
            'editorIndentGuide.background1': '#2a2445',
            'editorWidget.background': '#1c1930',
            'editorWidget.border': '#3d3463',
            'scrollbarSlider.background': '#3d346399',
            'scrollbarSlider.hoverBackground': '#a78bfa66',
          },
        });

        editor.current = mod.editor.create(host.current, {
          value: content,
          language: languageOf(path),
          theme: 'hana-dark',
          // A viewer, not an editor. The product does not modify what it reads.
          readOnly: true,
          domReadOnly: true,
          contextmenu: false,
          automaticLayout: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          fontSize: 12.5,
          fontFamily: "'Cascadia Code', 'Consolas', monospace",
          lineNumbersMinChars: 4,
          renderLineHighlight: 'line',
          wordWrap: 'off',
        });
      } catch (error) {
        setFailed(error instanceof Error ? error.message : String(error));
      }
    })();

    return () => {
      disposed = true;
      const instance = editor.current as { dispose?: () => void } | null;
      instance?.dispose?.();
      editor.current = null;
    };
    // Intentionally created once; content and path are pushed in below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const mod = monaco.current;
    const instance = editor.current as
      | { getModel: () => unknown; setModel: (model: unknown) => void }
      | null;
    if (!mod || !instance) return;

    const old = instance.getModel() as { dispose?: () => void } | null;
    instance.setModel(mod.editor.createModel(content, languageOf(path)));
    old?.dispose?.();
  }, [content, path]);

  useEffect(() => {
    const mod = monaco.current;
    const instance = editor.current as {
      revealLineInCenter: (line: number) => void;
      createDecorationsCollection: (items: unknown[]) => unknown;
    } | null;
    if (!mod || !instance) return;

    const items: unknown[] = [];

    if (highlightStart && highlightStart >= 1) {
      const end = Math.max(highlightStart, highlightEnd ?? highlightStart);
      items.push({
        range: new mod.Range(highlightStart, 1, end, 1),
        options: {
          isWholeLine: true,
          className: 'hanaEvidence',
          linesDecorationsClassName: 'hanaEvidenceGutter',
        },
      });
      instance.revealLineInCenter(highlightStart);
    }

    for (const marker of markers) {
      if (marker.line < 1 || marker.line === highlightStart) continue;
      items.push({
        range: new mod.Range(marker.line, 1, marker.line, 1),
        options: {
          isWholeLine: true,
          linesDecorationsClassName: 'hanaMarkerGutter',
          hoverMessage: { value: marker.label },
        },
      });
    }

    const previous = decorations.current as { clear?: () => void } | null;
    previous?.clear?.();
    decorations.current = instance.createDecorationsCollection(items);
  }, [highlightStart, highlightEnd, markers, content]);

  if (failed) {
    return (
      <div className={styles.fallback}>
        <p className={styles.fallbackNote}>
          El visor enriquecido no cargó ({failed}). Se muestra el texto plano.
        </p>
        <pre className={styles.plain}>
          {content.split('\n').map((line, index) => {
            const number = index + 1;
            const marked =
              highlightStart != null &&
              number >= highlightStart &&
              number <= (highlightEnd ?? highlightStart);
            return (
              <div key={number} className={marked ? styles.plainMarked : undefined}>
                <span className={styles.plainNumber}>{number}</span>
                {line}
              </div>
            );
          })}
        </pre>
      </div>
    );
  }

  return <div ref={host} className={styles.editor} />;
}
