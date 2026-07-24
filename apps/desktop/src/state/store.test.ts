/**
 * Store behaviour against the mock engine.
 *
 * These cover the states the home screen renders — loading, empty, analysing,
 * analysed, error — without needing the native shell.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MockEngineClient } from '../api/mock';
import { setClient } from '../api/client';
import { useAppStore } from './store';

const INITIAL = useAppStore.getState();

function resetStore(): void {
  useAppStore.setState(
    {
      ...INITIAL,
      ready: false,
      native: false,
      engine: null,
      projects: [],
      activeProjectId: null,
      stats: {},
      files: {},
      history: {},
      progress: null,
      analyzing: false,
      lastRun: null,
      error: null,
    },
    true,
  );
}

describe('app store', () => {
  beforeEach(() => {
    resetStore();
    setClient(new MockEngineClient());
  });

  it('starts empty and becomes ready', async () => {
    expect(useAppStore.getState().ready).toBe(false);

    await useAppStore.getState().initialize();

    const state = useAppStore.getState();
    expect(state.ready).toBe(true);
    expect(state.projects).toHaveLength(0);
    expect(state.engine?.offline).toBe(true);
    expect(state.engine?.model_provider).toBe('disabled');
  });

  it('opens a folder and selects the new project', async () => {
    await useAppStore.getState().initialize();
    const project = await useAppStore.getState().openFolder();

    expect(project).not.toBeNull();
    const state = useAppStore.getState();
    expect(state.projects).toHaveLength(1);
    expect(state.activeProjectId).toBe(project?.id);
    expect(state.stats[project!.id].files).toBeGreaterThan(0);
  });

  it('does not duplicate a project when the same folder is opened twice', async () => {
    await useAppStore.getState().initialize();
    const first = await useAppStore.getState().openPath('/demo/proyecto');
    const second = await useAppStore.getState().openPath('/demo/proyecto');

    expect(first?.id).toBe(second?.id);
    expect(useAppStore.getState().projects).toHaveLength(1);
  });

  it('reports progress while analysing and clears it afterwards', async () => {
    await useAppStore.getState().initialize();
    const project = await useAppStore.getState().openPath('/demo/proyecto');

    const phases: string[] = [];
    const unsubscribe = useAppStore.subscribe((state) => {
      if (state.progress) phases.push(state.progress.phase);
    });

    await useAppStore.getState().analyze(project!.id);
    unsubscribe();

    expect(phases).toContain('scanning');
    expect(phases).toContain('analyzing');

    const state = useAppStore.getState();
    expect(state.analyzing).toBe(false);
    expect(state.progress).toBeNull();
    expect(state.lastRun?.status).toBe('completed');
    expect(state.lastRun?.files_added).toBeGreaterThan(0);
  });

  it('reports no changes on a second analysis', async () => {
    await useAppStore.getState().initialize();
    const project = await useAppStore.getState().openPath('/demo/proyecto');

    await useAppStore.getState().analyze(project!.id);
    await useAppStore.getState().analyze(project!.id);

    const run = useAppStore.getState().lastRun;
    expect(run?.files_added).toBe(0);
    expect(run?.files_modified).toBe(0);
    expect(run?.files_unchanged).toBeGreaterThan(0);
  });

  it('refuses to start a second analysis while one is running', async () => {
    const client = new MockEngineClient();
    const analyzeSpy = vi.spyOn(client, 'analyze');
    setClient(client);

    await useAppStore.getState().initialize();
    const project = await useAppStore.getState().openPath('/demo/proyecto');

    // Double-clicking "Analizar" must not launch two runs over one database.
    await Promise.all([
      useAppStore.getState().analyze(project!.id),
      useAppStore.getState().analyze(project!.id),
    ]);

    expect(analyzeSpy).toHaveBeenCalledTimes(1);
  });

  it('surfaces engine failures instead of throwing', async () => {
    const broken = new MockEngineClient();
    vi.spyOn(broken, 'status').mockRejectedValue(new Error('el motor no arrancó'));
    setClient(broken);

    await useAppStore.getState().initialize();

    const state = useAppStore.getState();
    expect(state.ready).toBe(true);
    expect(state.error).toBe('el motor no arrancó');
  });

  it('clears a dismissed error', async () => {
    const broken = new MockEngineClient();
    vi.spyOn(broken, 'status').mockRejectedValue(new Error('fallo'));
    setClient(broken);

    await useAppStore.getState().initialize();
    expect(useAppStore.getState().error).toBe('fallo');

    useAppStore.getState().dismissError();
    expect(useAppStore.getState().error).toBeNull();
  });

  it('removes a project and deselects it', async () => {
    await useAppStore.getState().initialize();
    const project = await useAppStore.getState().openPath('/demo/proyecto');

    await useAppStore.getState().removeProject(project!.id);

    const state = useAppStore.getState();
    expect(state.projects).toHaveLength(0);
    expect(state.activeProjectId).toBeNull();
  });
});
