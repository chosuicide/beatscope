import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const modulePath = resolve(process.argv[2]);
const errors = [];
const checks = {};
try {
  const consumer = await import(pathToFileURL(modulePath).href);
  if (typeof consumer.frameAt !== "function") throw new Error("offline adapter must export frameAt(frame, fps, startFrame)");
  const atSecond = [24, 30, 60].map((fps) => consumer.frameAt(fps, fps));
  checks.fpsInvariant = JSON.stringify(atSecond[0]) === JSON.stringify(atSecond[1]) && JSON.stringify(atSecond[1]) === JSON.stringify(atSecond[2]);
  checks.deterministic = JSON.stringify(consumer.frameAt(91, 30)) === JSON.stringify(consumer.frameAt(91, 30));
  checks.negativeClamp = JSON.stringify(consumer.frameAt(-10, 30)) === JSON.stringify(consumer.frameAt(0, 30));
  checks.validDuration = Number.isFinite(consumer.duration) && consumer.duration > 0;
  for (const [name, passed] of Object.entries(checks)) if (!passed) errors.push(`offline:${name}:failed`);
} catch (error) {
  errors.push(`offline:${error?.message || String(error)}`);
}
process.stdout.write(JSON.stringify({ ok: errors.length === 0, checks, errors }));
process.exitCode = errors.length ? 1 : 0;
