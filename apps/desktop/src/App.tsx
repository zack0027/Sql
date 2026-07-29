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
import styles from './App.module.css';

export function App(): JSX.Element {
  const [exploring, setExploring] = useState(false);
  const resetExplorer = useExplorerStore((state) => state.reset);

  /*
   * The view is keyed so React remounts it on the switch, which restarts the
   * entrance animations inside — otherwise the explorer's panels would only
   * slide in the very first time it was ever opened.
   *
   * Deliberately not a cross-fade of both views at once: the explorer holds a
   * Monaco instance and an SVG graph, and keeping two of those alive to overlap
   * them for a quarter of a second is a poor trade.
   */
  return (
    <div key={exploring ? 'explorer' : 'home'} className={styles.view}>
      {exploring ? (
        <ExplorerView
          onBack={() => {
            resetExplorer();
            setExploring(false);
          }}
        />
      ) : (
        <HomeView onExplore={() => setExploring(true)} />
      )}
    </div>
  );
}
