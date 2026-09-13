import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Writable } from 'node:stream';
import { acceptsChunk, writeChunk } from '../beatscope/web/mv-io.mjs';
import { createMusicGrid } from '../beatscope/web/music-grid.mjs';
import { createFrameEncoder } from '../beatscope/web/mv-encode.mjs';

test('measured grid tracks tempo changes and nonzero origin without moving onsets', () => {
  const beats = Array.from({length: 8}, (_, i) => ({time: i < 4 ? 0.2 + i * 0.5 : 2.2 + (i - 4) * 0.25, bar: 1 + Math.floor(i / 4), beat_in_bar: i % 4 + 1}));
  const source = {source: {duration: 3.2}, beats, tempo: {global_bpm: 120}, grid: {bars: 2}};
  const before = JSON.stringify(source), grid = createMusicGrid(source);
  assert.equal(grid.timeAtStep(16), 2.2);
  assert.equal(grid.timeAtStep(20), 2.45);
  assert.equal(grid.barAtTime(2.3), 2);
  for (const time of [0.2, 0.739, 1.613, 2.483, 2.7, 3.1]) assert.ok(Math.abs(grid.timeAtStep(grid.stepAtTime(time)) - time) < 1e-12);
  assert.equal(JSON.stringify(source), before);
  assert.equal(createMusicGrid({source: {duration: 20}, tempo: {global_bpm: 120}}).barAtTime(3), null);
  assert.equal(createMusicGrid({source: {duration: 20}, beats: [{time: 1}]}).available, false);
});

test('encoder pipe rejects close and timeout instead of hanging; listeners are removed', async () => {
  const sink = new Writable({write(chunk, encoding, done) { done(); }});
  await writeChunk(sink, Buffer.from('ok'));
  assert.equal(sink.listenerCount('close'), 0);
  const stalled = new Writable({write() {}});
  await assert.rejects(writeChunk(stalled, Buffer.from('x'), 10), /timed out/);
  const pending = writeChunk(stalled, Buffer.from('y'));
  stalled.destroy();
  await assert.rejects(pending, /closed/);
  assert.equal(stalled.listenerCount('close'), 0);
});

test('render chunk endpoint requires the job token, exact host and content type', () => {
  const headers = {host: '127.0.0.1:123', 'x-beathi-render': 'secret', 'content-type': 'application/octet-stream', origin: 'http://127.0.0.1:123'};
  assert.equal(acceptsChunk(headers, headers.host, 'secret'), true);
  for (const patch of [{'x-beathi-render': ''}, {host: 'evil.test'}, {origin: 'https://evil.test'}, {'content-type': 'text/plain'}]) assert.equal(acceptsChunk({...headers, ...patch}, headers.host, 'secret'), false);
});

test('VideoEncoder errors propagate before queue waiting and VideoFrames always close', async () => {
  let callbacks, closed = 0;
  const oldEncoder = globalThis.VideoEncoder, oldFrame = globalThis.VideoFrame;
  try {
    globalThis.VideoEncoder = class {
      static async isConfigSupported() { return {supported: true}; }
      constructor(config) { callbacks = config; }
      encodeQueueSize = 0;
      configure() {}
      encode() { throw new Error('encode failed'); }
    };
    globalThis.VideoFrame = class { close() { closed++; } };
    const encoder = await createFrameEncoder({canvas: {width: 1080, height: 1080}});
    await assert.rejects(encoder.encode(0), /encode failed/);
    assert.equal(closed, 1);
    callbacks.error(new Error('device lost'));
    await assert.rejects(encoder.encode(1), /device lost/);
    await assert.rejects(encoder.finish(), /device lost/);
  } finally { globalThis.VideoEncoder = oldEncoder; globalThis.VideoFrame = oldFrame; }
});
