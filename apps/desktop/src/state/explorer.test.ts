/**
 * What the centre panel is describing.
 *
 * The rule the tabs used to break: some followed the selection and some always
 * showed the whole project, with nothing on screen to say which. An empty
 * warnings tab meant "this project is clean", never "this file is clean", and
 * there was no way to tell the two apart.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import type { EntityHit, UsageHit } from '@hana/shared-types';

import { setClient } from '../api/client';
import { MockEngineClient } from '../api/mock';
import { erFocusOf, useExplorerStore } from './explorer';

function entity(id: string, type: EntityHit['entity_type']): EntityHit {
  return {
    id,
    entity_type: type,
    name: id,
    normalized_name: id.toUpperCase(),
    qualified_name: null,
    confidence: 1,
    verification_status: 'confirmed',
    file_path: 'sql/a.sql',
    start_line: 1,
  };
}

function usage(hit: EntityHit): UsageHit {
  return {
    entity: hit,
    relation_type: 'QUERY_READS_TABLE',
    direction: 'outgoing',
    evidence: {
      file_path: 'sql/a.sql',
      absolute_path: '/demo/sql/a.sql',
      start_line: 1,
      end_line: 1,
      snippet: 'from uc_insp_ent',
      analyzer: 'sql',
      confidence: 1,
      status: 'confirmed',
    },
  };
}

const TABLE = entity('E_TABLE', 'OracleTable');
const ITEM = entity('E_ITEM', 'ApexItem');

describe('erFocusOf', () => {
  it('centres the diagram on a selected table', () => {
    expect(
      erFocusOf({ scope: 'selection', selected: TABLE, fileTables: [] }),
    ).toBe('E_TABLE');
  });

  it('falls back to a table used by the selected file', () => {
    expect(
      erFocusOf({ scope: 'selection', selected: null, fileTables: [usage(TABLE)] }),
    ).toBe('E_TABLE');
  });

  it('prefers the entity over the file it came from', () => {
    // Clicking a table in the graph is a more specific answer than "some table
    // this file happens to touch".
    const other = entity('E_OTHER', 'OracleTable');
    expect(
      erFocusOf({
        scope: 'selection',
        selected: TABLE,
        fileTables: [usage(other)],
      }),
    ).toBe('E_TABLE');
  });

  it('does not try to focus on something that is not a table', () => {
    // Asking for the join partners of an APEX item narrows the diagram to
    // nothing, and an empty diagram reads as a bug rather than as an answer.
    expect(
      erFocusOf({ scope: 'selection', selected: ITEM, fileTables: [] }),
    ).toBeNull();
  });

  it('ignores non-table entities when picking from a file', () => {
    expect(
      erFocusOf({ scope: 'selection', selected: null, fileTables: [usage(ITEM)] }),
    ).toBeNull();
  });

  it('shows the whole project when the scope says so', () => {
    expect(
      erFocusOf({ scope: 'project', selected: TABLE, fileTables: [usage(TABLE)] }),
    ).toBeNull();
  });

  it('shows the whole project when nothing is selected', () => {
    expect(
      erFocusOf({ scope: 'selection', selected: null, fileTables: [] }),
    ).toBeNull();
  });
});

/**
 * Impact is the one tab whose answer is a chain rather than a list, so the
 * things worth pinning down are the chain's length, where it stops, and whether
 * it passed through a guess on the way.
 */
describe('impact', () => {
  const INITIAL = useExplorerStore.getState();

  beforeEach(() => {
    useExplorerStore.setState({ ...INITIAL, projectId: 'P' }, true);
    setClient(new MockEngineClient());
  });

  async function impactOf(id: string, type: EntityHit['entity_type']) {
    useExplorerStore.setState({ selected: entity(id, type) });
    await useExplorerStore.getState().loadImpact();
    return useExplorerStore.getState().impact;
  }

  it('reaches the report two hops from a column', async () => {
    const report = await impactOf('E_COLUMN', 'OracleColumn');
    const jasper = report!.nodes.find((node) => node.entity.id === 'E_REPORT');
    expect(jasper?.depth).toBe(2);
    expect(jasper?.path).toEqual(['E_COLUMN', 'E_TABLE', 'E_REPORT']);
  });

  it('marks a path that crossed an inference', async () => {
    const report = await impactOf('E_COLUMN', 'OracleColumn');
    const page = report!.nodes.find((node) => node.entity.id === 'E_PAGE');
    expect(page?.inferred_in_path).toBe(true);
    expect(page?.min_confidence).toBeCloseTo(0.9);
  });

  it('leaves a fully confirmed path unmarked', async () => {
    const report = await impactOf('E_COLUMN', 'OracleColumn');
    const jasper = report!.nodes.find((node) => node.entity.id === 'E_REPORT');
    expect(jasper?.inferred_in_path).toBe(false);
    expect(jasper?.min_confidence).toBe(1);
  });

  it('stops where the depth says', async () => {
    useExplorerStore.setState({ impactDepth: 1 });
    const report = await impactOf('E_COLUMN', 'OracleColumn');
    expect(report!.nodes.every((node) => node.depth === 1)).toBe(true);
    expect(report!.nodes.some((node) => node.entity.id === 'E_REPORT')).toBe(false);
  });

  it('asks the other question when reversed', async () => {
    useExplorerStore.setState({ impactReverse: true });
    const report = await impactOf('E_REPORT', 'JasperReport');
    const ids = report!.nodes.map((node) => node.entity.id);
    expect(ids).toContain('E_TABLE');
  });

  it('groups the results by kind', async () => {
    const report = await impactOf('E_COLUMN', 'OracleColumn');
    expect(report!.by_type.JasperReport).toBe(1);
    expect(report!.by_type.ApexPage).toBe(1);
  });

  it('has nothing to say when nothing is selected', async () => {
    useExplorerStore.setState({ selected: null, impact: null });
    await useExplorerStore.getState().loadImpact();
    expect(useExplorerStore.getState().impact).toBeNull();
  });

  it('never lists the entity you asked about', async () => {
    const report = await impactOf('E_COLUMN', 'OracleColumn');
    expect(report!.nodes.some((node) => node.entity.id === 'E_COLUMN')).toBe(false);
  });
});
