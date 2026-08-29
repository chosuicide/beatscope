/**
 * BeatScope MCP runtime worker: one JSON request per stdin line, one JSON
 * response per stdout line (plan section 19.2). Wraps the shared JavaScript
 * runtime so Python never recomputes beat phase, energy interpolation, or
 * onset impulses - the web player, the Codex export, and MCP stay one
 * source of truth.
 *
 * Request:  {"id":1,"op":"at","project":"0a1b2c3d4e5f","path":".../rhythm.json",
 *            "fingerprint":"171...:3098","time":42.5}
 * Response: {"id":1,"ok":true,"result":{...}}   or   {"id":1,"ok":false,"error":"..."}
 *
 * JSON.stringify serializes Infinity/NaN as null, which is exactly the
 * documented transport rule for onset age before the first onset.
 */
import { readFileSync, statSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { createTrack } from '../runtime/runtime.js';

const tracks = new Map();

function fingerprintOf(path) {
  const stat = statSync(path, { bigint: true });
  return `${stat.mtimeNs}:${stat.size}`;
}

function getTrack(projectId, path, fingerprint) {
  const cached = tracks.get(projectId);
  if (cached && cached.fingerprint === fingerprint) return cached.track;
  const rhythm = JSON.parse(readFileSync(path, 'utf8'));
  const track = createTrack(rhythm);
  tracks.set(projectId, { fingerprint, track });
  return track;
}

function respond(message) {
  process.stdout.write(JSON.stringify(message) + '\n');
}

function requireTrack(request) {
  return getTrack(request.project, request.path, request.fingerprint);
}

const interface_ = createInterface({ input: process.stdin, crlfDelay: Infinity });
interface_.on('line', (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  let request;
  try {
    request = JSON.parse(trimmed);
  } catch (error) {
    respond({ id: 0, ok: false, error: `malformed request: ${error.message}` });
    return;
  }
  const { id, op } = request;
  try {
    let result;
    switch (op) {
      case 'ping':
        result = { pong: true, node: process.version };
        break;
      case 'at':
        result = requireTrack(request).at(Number(request.time) || 0);
        break;
      case 'between':
        result = requireTrack(request).between(Number(request.start) || 0, Number(request.end) || 0);
        break;
      case 'quantize':
        result = requireTrack(request).quantize(
          Number(request.time) || 0,
          request.subdivision ?? undefined,
          request.bpm ? { bpm: request.bpm, origin: request.origin } : null,
        );
        break;
      case 'next_cue':
        result = requireTrack(request).nextCue(Number(request.time) || 0, request.type || 'accent');
        break;
      case 'shutdown':
        respond({ id, ok: true, result: { bye: true } });
        process.exit(0);
        break;
      default:
        throw new Error(`unknown op: ${op}`);
    }
    respond({ id, ok: true, result });
  } catch (error) {
    respond({ id, ok: false, error: error.message });
  }
});

process.stderr.write('beatscope runtime worker ready\n');
