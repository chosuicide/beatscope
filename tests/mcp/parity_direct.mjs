/**
 * Direct-runtime parity helper (plan section 23.3): load a rhythm project
 * through the shared runtime exactly like the web player does and print one
 * JSON state per requested time. The MCP parity test compares these lines
 * against beatscope_get_visual_state responses.
 *
 *   node parity_direct.mjs <rhythm.json> <time> [<time> ...]
 */
import { readFileSync } from 'node:fs';
import { createTrack } from '../../beatscope/runtime/runtime.js';

const [fixture, ...times] = process.argv.slice(2);
if (!fixture || times.length === 0) {
  process.stderr.write('usage: node parity_direct.mjs <rhythm.json> <time>...\n');
  process.exit(2);
}

const track = createTrack(JSON.parse(readFileSync(fixture, 'utf8')));
for (const time of times) {
  process.stdout.write(JSON.stringify(track.at(Number(time))) + '\n');
}
