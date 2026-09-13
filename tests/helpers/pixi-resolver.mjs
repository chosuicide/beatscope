/**
 * Bare-specifier resolution for node tests: the compiled test output lives
 * in tests/.generated, where Node cannot find web-src/node_modules. This
 * hook resolves `pixi.js` against web-src/package.json so render modules can
 * be imported in Node exactly as the browser bundles them.
 *
 * Usage: node --import ./tests/helpers/pixi-resolver.mjs tests/<file>.js
 */
import { register } from 'node:module';

register(new URL('./pixi-resolver-hooks.mjs', import.meta.url));
