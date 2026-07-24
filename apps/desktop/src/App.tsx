/**
 * Application shell.
 *
 * Etapa 1 has one view. Etapa 3 adds the project explorer (file tree, graph,
 * details) behind a router; the shell exists so that swap is local.
 */

import { HomeView } from './views/HomeView';

export function App(): JSX.Element {
  return <HomeView />;
}
