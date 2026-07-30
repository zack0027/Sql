/**
 * What the centre panel is describing.
 *
 * The rule the tabs used to break: some followed the selection and some always
 * showed the whole project, with nothing on screen to say which. An empty
 * warnings tab meant "this project is clean", never "this file is clean", and
 * there was no way to tell the two apart.
 */

import { describe, expect, it } from 'vitest';

import type { EntityHit, UsageHit } from '@hana/shared-types';

import { erFocusOf } from './explorer';

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
