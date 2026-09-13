/**
 * Resolve hook: map pixi.js (and its subpaths) to the web-src install so
 * compiled test modules in tests/.generated can import render code.
 * The ESM build (`lib/index.mjs`) is pinned directly because the package
 * exports map cannot be consulted from a loader hook thread.
 */
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const ROOT = new URL('../../web-src/node_modules/pixi.js/', import.meta.url);

function esmFile(relative) {
  for (const candidate of [relative, `${relative}.mjs`, `${relative}/index.mjs`]) {
    const url = new URL(candidate, ROOT);
    if (existsSync(fileURLToPath(url))) return url.href;
  }
  return null;
}

export async function resolve(specifier, context, nextResolve) {
  if (specifier === 'pixi.js') {
    return { url: esmFile('lib/index'), shortCircuit: true };
  }
  if (specifier.startsWith('pixi.js/')) {
    const resolved = esmFile(specifier.slice('pixi.js/'.length));
    if (resolved) return { url: resolved, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
