/**
 * Encoder comparison on real template frames: for each setting, wall time,
 * output size, and PSNR against the lossless PNG frames.
 */
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { once } from 'node:events';

const root = path.resolve(process.argv[2]);
const OUT = path.join(root, 'bench-out');
const input = JSON.parse(fs.readFileSync(path.join(root, 'input.json')));
const plan = JSON.parse(fs.readFileSync(path.join(root, 'plan.json')));
const fps = plan.fps || 30;
const frames = fs.readdirSync(path.join(OUT, 'png')).length;
const ffmpeg = process.env.BEATSCOPE_FFMPEG || 'ffmpeg';

const settings = [
  ['x264 slower crf20 film (current)', ['-c:v', 'libx264', '-preset', 'slower', '-crf', '20', '-tune', 'film']],
  ['amf balanced cqp 18/20          ', ['-c:v', 'h264_amf', '-quality', 'balanced', '-rc', 'cqp', '-qp_i', '18', '-qp_p', '20', '-qp_b', '20']],
  ['amf speed    cqp 18/20          ', ['-c:v', 'h264_amf', '-quality', 'speed', '-rc', 'cqp', '-qp_i', '18', '-qp_p', '20', '-qp_b', '20']],
  ['amf quality  cqp 18/20          ', ['-c:v', 'h264_amf', '-quality', 'quality', '-rc', 'cqp', '-qp_i', '18', '-qp_p', '20', '-qp_b', '20']],
];

async function encode(label, codecArgs) {
  const target = path.join(OUT, `${label.replace(/[^a-z0-9]+/gi, '-')}.mp4`);
  const args = ['-y', '-v', 'error', '-framerate', String(fps), '-i', path.join(OUT, 'png', '%03d.png'),
    '-i', input.audio, '-map', '0:v:0', '-map', '1:a:0', '-af', 'atrim=duration=2,asetpts=PTS-STARTPTS',
    ...codecArgs, '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-t', '2', '-movflags', '+faststart', target];
  const child = spawn(ffmpeg, args, { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
  let stderr = '';
  child.stderr.on('data', (b) => { stderr = (stderr + b).slice(-1500); });
  const start = Date.now();
  const [code] = await once(child, 'close');
  const elapsed = Date.now() - start;
  if (code !== 0) return { label, error: stderr.trim() || 'encode failed' };
  const size = fs.statSync(target).size / 1e6;
  // PSNR against the lossless source frames
  const probe = spawn(ffmpeg, ['-v', 'info', '-i', target, '-framerate', String(fps), '-i', path.join(OUT, 'png', '%03d.png'),
    '-lavfi', 'psnr', '-f', 'null', '-'], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
  let text = '';
  probe.stderr.on('data', (b) => { text += b; });
  await once(probe, 'close');
  const line = text.split('\n').filter((l) => l.includes('average')).pop() || '';
  const average = /average:([0-9.]+)/.exec(line);
  const minmax = /min:([0-9.]+)\s+max:([0-9.]+)/.exec(line);
  return { label, ms: elapsed / frames, size, psnr: average ? Number(average[1]) : null, min: minmax ? Number(minmax[1]) : null };
}

console.log(`encoding ${frames} lossless frames (2.0 s) — time is ms/frame of video`);
const rows = [];
for (const [label, args] of settings) rows.push(await encode(label, args));
console.log('\nsetting                ms/frame   size MB   PSNR avg   PSNR min');
for (const row of rows) {
  if (row.error) { console.log(`${row.label}  FAILED: ${row.error.split('\n')[0]}`); continue; }
  console.log(`${row.label}   ${row.ms.toFixed(1).padStart(6)}   ${row.size.toFixed(2).padStart(6)}   ${(row.psnr ?? 0).toFixed(2).padStart(8)}   ${(row.min ?? 0).toFixed(2).padStart(8)}`);
}
