import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

// Tauri serves the built assets from disk, so relative URLs are required.
// Port 5183 is fixed because tauri.conf.json points `devUrl` at it.
export default defineConfig({
  plugins: [react()],
  base: './',
  clearScreen: false,
  resolve: {
    alias: {
      '@jarvis/shared-types': fileURLToPath(
        new URL('../../packages/shared-types/src/index.ts', import.meta.url),
      ),
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5183,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    target: 'esnext',
    sourcemap: true,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
});
