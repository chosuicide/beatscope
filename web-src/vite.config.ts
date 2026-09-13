import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Build output is emitted into the Python-packaged static directory under
// web/app (plan §3.4); beatscope/web keeps the legacy Studio modules beside
// it until the Round 5 coverage-map removal. Base stays relative so the same
// build works when served at /app/ and from a Pages-style subpath.
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: '../beatscope/web/app',
    emptyOutDir: true,
    assetsDir: 'assets',
    sourcemap: false,
    target: 'es2022',
  },
});
