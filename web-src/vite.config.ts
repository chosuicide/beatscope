import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { readFileSync } from 'node:fs';

// Build output is emitted into the Python-packaged static directory under
// web/app (plan §3.4); beatscope/web keeps the legacy Studio modules beside
// it until the Round 5 coverage-map removal. Base stays relative so the same
// build works when served at /app/ and from a Pages-style subpath.
export default defineConfig({
  base: './',
  plugins: [react(), {
    name: 'composition-portable-dependencies',
    generateBundle() {
      for (const [fileName, source] of [
        ['composition-engine.js', 'node_modules/butterchurn/lib/butterchurn.min.js'],
        ['composition-presets.js', 'node_modules/butterchurn-presets/lib/butterchurnPresets.min.js'],
        ['composition-engine-LICENSE.txt', 'node_modules/butterchurn/LICENSE'],
        ['composition-presets-LICENSE.txt', 'node_modules/butterchurn-presets/LICENSE'],
      ]) this.emitFile({ type: 'asset', fileName: 'assets/' + fileName, source: readFileSync(source) });
    },
  }],
  build: {
    outDir: '../beatscope/web/app',
    emptyOutDir: true,
    assetsDir: 'assets',
    sourcemap: false,
    target: 'es2022',
  },
});
