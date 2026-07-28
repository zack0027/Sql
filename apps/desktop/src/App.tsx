/**
 * Application shell.
 *
 * Two views, switched by whether a project is being explored. Deliberately not a
 * router: a desktop window has no URL worth preserving, so a router would be a
 * dependency bought for a single boolean.
 */

import { useState } from 'react';

import { useExplorerStore } from './state/explorer';
import { ExplorerView } from './views/ExplorerView';
import { HomeView } from './views/HomeView';

export function App(): JSX.Element {
  const [exploring, setExploring] = useState(false);
  const resetExplorer = useExplorerStore((state) => state.reset);

  if (exploring) {
    return (
      <ExplorerView
        onBack={() => {
          resetExplorer();
          setExploring(false);
        }}
      />
    );
  }

  return <HomeView onExplore={() => setExploring(true)} />;
}
