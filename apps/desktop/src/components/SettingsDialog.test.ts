import { describe, expect, it } from 'vitest';

import { parseLines } from './SettingsDialog';

describe('parseLines', () => {
  it('reads one entry per line', () => {
    expect(parseLines('.git\nnode_modules')).toEqual(['.git', 'node_modules']);
  });

  it('drops blank lines', () => {
    // A trailing newline is what a textarea leaves behind; an empty ignore
    // pattern would match nothing, or everything, depending on the walker.
    expect(parseLines('.git\n\n\nbuild\n')).toEqual(['.git', 'build']);
  });

  it('trims stray whitespace', () => {
    expect(parseLines('  dist  \n\ttarget')).toEqual(['dist', 'target']);
  });

  it('an empty box means no entries, not one empty entry', () => {
    expect(parseLines('')).toEqual([]);
    expect(parseLines('   \n  ')).toEqual([]);
  });
});
