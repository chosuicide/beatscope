/**
 * Direct-runtime parity helper (plan section 23.3): load a rhythm project
 * through the shared runtime exactly like the web player does and print one
 * JSON state per requested time. The MCP parity test compares these lines
 * against beatscope_get_visual_state responses.
 *
 *   node parity_direct.mjs <rhythm.json> <time> [<time> ...]
 *
 * With --scene, every line additionally carries the scene director frame
 * (the same scene-director.js the worker and the browser run), so the parity
 * test can pin the additive visual block too:
 *
 *   node parity_direct.mjs <rhythm.json> --scene <recipe.json> <timeline.json> <time>...
 */
import { readFileSync } from 'node:fs';
import { createTrack } from '../../beatscope/runtime/runtime.js';
import { createSceneDirector } from '../../beatscope/runtime/scene-director.js';

const argv = process.argv.slice(2);
const sceneMode = argv[1] === '--scene';
const [fixture, ...times] = sceneMode ? [argv[0], ...argv.slice(4)] : argv;
if (!fixture || times.length === 0 || (sceneMode && (!argv[2] || !argv[3]))) {
  process.stderr.write('usage: node parity_direct.mjs <rhythm.json> [--scene <recipe.json> <timeline.json>] <time>...\n');
  process.exit(2);
}

const track = createTrack(JSON.parse(readFileSync(fixture, 'utf8')));
const director = sceneMode
  ? createSceneDirector(
      JSON.parse(readFileSync(argv[2], 'utf8')),
      JSON.parse(readFileSync(argv[3], 'utf8')),
    )
  : null;
for (const time of times) {
  const at = track.at(Number(time));
  const line = sceneMode ? { at, scene: director.at(Number(time)) } : at;
  process.stdout.write(JSON.stringify(line) + '\n');
}
