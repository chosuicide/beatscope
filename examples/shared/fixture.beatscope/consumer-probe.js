// BeatScope consumer probe — self-verification for Agent handoff packages.
//
// Dependency-free ESM (v0.9 plan section 6): no imports, no network, no
// filesystem at module scope. The probe inspects an already-imported
// package namespace against `beatscope-package.json`, canonicalizes
// frames for comparison, and replays checkpoint suites. It never
// recreates runtime mathematics — it only calls the package's own
// exports and compares results.
//
// A small Node CLI is attached at the bottom (guarded, so browsers and
// bundlers never load node builtins):
//
//     node consumer-probe.js [packageRoot] [--checkpoints <file>]
//
// It prints one JSON report and exits 0 when every probe passed, 1
// otherwise. Byte-level integrity is validated by the repository's
// Python tooling; the probe verifies runtime behavior.

const MANIFEST_SCHEMA = "beatscope-package-1";
const CHECKPOINT_SCHEMA = "beatscope-consumer-checkpoints-1";
const DURATION_TOLERANCE = 1e-6;

// ------------------------------------------------------------ canonicalization

function isPlainObject(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function canonicalizeValue(value, seen) {
  const type = typeof value;
  if (value === null) return null;
  if (type === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError(`frame value is not finite: ${String(value)}`);
    }
    return value === 0 ? 0 : value; // normalize -0
  }
  if (type === "string" || type === "boolean") return value;
  if (type === "bigint" || type === "symbol" || type === "function" || type === "undefined") {
    throw new TypeError(`frame value is not JSON-serializable: ${type}`);
  }
  if (type !== "object") {
    throw new TypeError(`frame value is not JSON-serializable: ${type}`);
  }
  if (seen.has(value)) throw new TypeError("frame value is cyclic");
  seen.add(value);
  try {
    if (Array.isArray(value)) {
      return value.map((item) => canonicalizeValue(item, seen));
    }
    if (!isPlainObject(value)) {
      throw new TypeError(`frame value is not a plain object: ${describe(value)}`);
    }
    const canonical = {};
    for (const key of Object.keys(value).sort()) {
      canonical[key] = canonicalizeValue(value[key], seen);
    }
    return canonical;
  } finally {
    seen.delete(value);
  }
}

/**
 * v0.8's public runtime uses positive Infinity as the no-previous-onset
 * sentinel. Preserve that runtime contract, but normalize the one documented
 * carrier to null in checkpoint JSON. Other non-finite values remain errors.
 */
function normalizeRuntimeSentinels(value, seen = new Set()) {
  if (!Array.isArray(value) && !isPlainObject(value)) return value;
  if (seen.has(value)) throw new TypeError("frame value is cyclic");
  seen.add(value);
  try {
    if (Array.isArray(value)) return value.map((item) => normalizeRuntimeSentinels(item, seen));
    const normalized = {};
    for (const [key, item] of Object.entries(value)) {
      normalized[key] = item === Number.POSITIVE_INFINITY && (key === "age" || key === "onsetAge")
        ? null
        : normalizeRuntimeSentinels(item, seen);
    }
    return normalized;
  } finally {
    seen.delete(value);
  }
}

function describe(value) {
  const tag = Object.prototype.toString.call(value);
  const label = typeof value.constructor === "function" ? value.constructor.name : "Object";
  return `${label}${tag === "[object Object]" ? "" : ` ${tag}`}`;
}

function canonicalFrameObject(moduleNamespace, time, options) {
  const name = options && typeof options.frameFunction === "string" ? options.frameFunction : "getBeatScopeFrame";
  const frameFunction = moduleNamespace ? moduleNamespace[name] : undefined;
  if (typeof frameFunction !== "function") {
    throw new TypeError(`package does not export the frame function "${name}"`);
  }
  const frame = normalizeRuntimeSentinels(frameFunction(time, options ? options.frameOptions : undefined));
  return canonicalizeValue(frame, new Set());
}

/**
 * Evaluate the package frame at `time` and return its canonical form:
 * recursively key-sorted, `-0` normalized to `0`, non-finite numbers,
 * functions, symbols, bigints, cycles, and non-plain objects rejected.
 * JSON.stringify of the result is the canonical serialization, because
 * object keys are inserted in sorted order.
 */
export function canonicalFrame(moduleNamespace, time, options) {
  return canonicalFrameObject(moduleNamespace, time, options);
}

/** Canonical serialization of one frame: the exact bytes compared and hashed. */
export function canonicalFrameJson(moduleNamespace, time, options) {
  return JSON.stringify(canonicalFrameObject(moduleNamespace, time, options));
}

// -------------------------------------------------------------------- sha256
// Compact FIPS 180-4 implementation so checkpoint parity works anywhere the
// package runs. The repository tests cross-check it against node:crypto.

const SHA256_K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

function rotateRight(value, bits) {
  return ((value >>> bits) | (value << (32 - bits))) >>> 0;
}

function sha256OfBytes(bytes) {
  const bitLength = bytes.length * 8;
  const paddedLength = (((bytes.length + 8) >> 6) + 1) << 6;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000));
  view.setUint32(paddedLength - 4, bitLength >>> 0);

  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;
  const w = new Int32Array(64);

  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let i = 0; i < 16; i += 1) w[i] = view.getInt32(offset + i * 4);
    for (let i = 16; i < 64; i += 1) {
      const x = w[i - 15];
      const y = w[i - 2];
      const s0 = rotateRight(x, 7) ^ rotateRight(x, 18) ^ (x >>> 3);
      const s1 = rotateRight(y, 17) ^ rotateRight(y, 19) ^ (y >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;
    for (let i = 0; i < 64; i += 1) {
      const s1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + s1 + ch + SHA256_K[i] + w[i]) | 0;
      const s0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (s0 + maj) | 0;
      h = g;
      g = f;
      f = e;
      e = (d + t1) | 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) | 0;
    }
    h0 = (h0 + a) | 0;
    h1 = (h1 + b) | 0;
    h2 = (h2 + c) | 0;
    h3 = (h3 + d) | 0;
    h4 = (h4 + e) | 0;
    h5 = (h5 + f) | 0;
    h6 = (h6 + g) | 0;
    h7 = (h7 + h) | 0;
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map((word) => (word >>> 0).toString(16).padStart(8, "0"))
    .join("");
}

/** SHA-256 hex digest of a string's UTF-8 bytes. */
export function sha256Hex(text) {
  return sha256OfBytes(new TextEncoder().encode(text));
}

// --------------------------------------------------------------- inspection

function declaredFunctionNames(manifest) {
  const functions = isPlainObject(manifest.functions) ? manifest.functions : {};
  const names = new Set();
  for (const value of Object.values(functions)) {
    if (typeof value === "string" && value.trim()) names.add(value.trim());
  }
  return names;
}

function moduleDuration(moduleNamespace) {
  const rhythm = moduleNamespace ? moduleNamespace.RHYTHM_MAP : undefined;
  if (!isPlainObject(rhythm) || typeof rhythm.duration !== "number" || !Number.isFinite(rhythm.duration)) {
    return null;
  }
  return rhythm.duration;
}

/**
 * Inspect an imported package namespace against its manifest.
 * Returns `{ ok, errors, checks, manifest, probed }`; `ok` is true only
 * when every declared export exists, behaves deterministically, accepts
 * finite seconds (rejecting or clamping invalid ones), and agrees with
 * the manifest duration.
 */
export async function inspectPackage(manifest, moduleNamespace) {
  const errors = [];
  const checks = {};
  if (!isPlainObject(manifest)) {
    return {
      ok: false,
      errors: ["manifest:not-an-object"],
      checks: {},
      manifest: null,
      probed: { functions: [], times: [] },
    };
  }
  if (manifest.schema !== MANIFEST_SCHEMA) {
    errors.push(`schema:expected ${MANIFEST_SCHEMA}`);
  }
  const capabilities = isPlainObject(manifest.capabilities) ? manifest.capabilities : {};
  const functions = isPlainObject(manifest.functions) ? manifest.functions : {};
  const scenes = capabilities.scenes === true;
  const names = declaredFunctionNames(manifest);

  if (typeof functions.timing !== "string" || !functions.timing.trim()) {
    errors.push("functions.timing:missing");
  }
  if (scenes) {
    if (typeof functions.frame !== "string" || !functions.frame.trim()) {
      errors.push("functions.frame:required-with-scenes");
    }
    if (typeof functions.scene !== "string" || !functions.scene.trim()) {
      errors.push("functions.scene:required-with-scenes");
    }
  } else {
    if (typeof functions.frame === "string" && functions.frame.trim()) {
      errors.push("functions.frame:requires-scenes");
    }
    if (typeof functions.scene === "string" && functions.scene.trim()) {
      errors.push("functions.scene:requires-scenes");
    }
  }

  const missing = [...names].filter((name) => typeof (moduleNamespace || {})[name] !== "function");
  for (const name of missing) errors.push(`module:missing-export:${name}`);
  checks.declaredExportsPresent = missing.length === 0 && names.size > 0;

  const manifestDuration = typeof manifest.duration === "number" && Number.isFinite(manifest.duration)
    ? manifest.duration
    : null;
  const moduleDurationValue = moduleDuration(moduleNamespace);
  if (moduleDurationValue === null) {
    errors.push("module:rhythm-map-export-missing");
    checks.durationAgrees = false;
  } else if (manifestDuration === null) {
    errors.push("duration:not-finite");
    checks.durationAgrees = false;
  } else if (Math.abs(manifestDuration - moduleDurationValue) > DURATION_TOLERANCE) {
    errors.push(`duration:mismatch:${manifestDuration} vs module ${moduleDurationValue}`);
    checks.durationAgrees = false;
  } else {
    checks.durationAgrees = true;
  }

  const duration = manifestDuration !== null && manifestDuration > 0
    ? manifestDuration
    : moduleDurationValue !== null && moduleDurationValue > 0
      ? moduleDurationValue
      : 1;
  const ascending = [0, duration / 4, duration / 2, (duration * 3) / 4, duration];
  const shuffled = [duration / 2, duration, 0, (duration * 3) / 4, duration / 4];
  let orderAgrees = true;
  let stateless = true;
  let invalidInputSafe = true;
  let serializable = true;

  for (const name of names) {
    const frameFunction = (moduleNamespace || {})[name];
    if (typeof frameFunction !== "function") continue;

    const firstPass = new Map();
    for (const time of ascending) {
      try {
        firstPass.set(time, JSON.stringify(canonicalizeValue(normalizeRuntimeSentinels(frameFunction(time)), new Set())));
      } catch (error) {
        serializable = false;
        errors.push(`${name}:unserializable-output:${fmtTime(time)}:${error.message}`);
        break;
      }
    }
    if (firstPass.size === ascending.length) {
      for (const time of shuffled) {
        let second;
        try {
          second = JSON.stringify(canonicalizeValue(normalizeRuntimeSentinels(frameFunction(time)), new Set()));
        } catch (error) {
          serializable = false;
          errors.push(`${name}:unserializable-output:${fmtTime(time)}:${error.message}`);
          break;
        }
        if (firstPass.get(time) !== second) orderAgrees = false;
      }
      const repeat = JSON.stringify(canonicalizeValue(normalizeRuntimeSentinels(frameFunction(duration / 2)), new Set()));
      if (repeat !== firstPass.get(duration / 2)) stateless = false;

      for (const bad of [-1, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
        let returned = true;
        let output;
        try {
          output = normalizeRuntimeSentinels(frameFunction(bad));
        } catch {
          returned = false; // rejecting invalid input is documented behavior
        }
        if (returned) {
          try {
            canonicalizeValue(output, new Set());
          } catch (error) {
            invalidInputSafe = false;
            errors.push(`${name}:invalid-input-unclean:${fmtTime(bad)}:${error.message}`);
          }
        }
      }
    }
  }
  checks.orderAgrees = orderAgrees;
  checks.stateless = stateless;
  checks.invalidInputSafe = invalidInputSafe;
  checks.serializable = serializable;
  if (!orderAgrees) errors.push("module:query-order-disagrees");
  if (!stateless) errors.push("module:state-drift-after-seek");
  if (!invalidInputSafe) errors.push("module:invalid-input-unclean");

  return {
    ok: errors.length === 0,
    errors,
    checks,
    manifest: {
      schema: manifest.schema ?? null,
      package_version: manifest.package_version ?? null,
      duration: manifestDuration,
      capabilities,
      functions,
    },
    probed: { functions: [...names].sort(), times: ascending },
  };
}

function fmtTime(value) {
  return String(value);
}

// --------------------------------------------------------------- checkpoints

/**
 * Replay a `beatscope-consumer-checkpoints-1` document against the
 * imported package. Every recorded time is evaluated and hashed with the
 * probe's canonical serialization, the out-of-order seek sequence is
 * replayed and compared, and a second full pass confirms statelessness.
 * `options.packageSha256` (computed externally over the package bytes,
 * manifest excluded) is compared when supplied.
 */
export function runCheckpointSuite(moduleNamespace, checkpoints, options = {}) {
  if (!isPlainObject(checkpoints)) {
    return { ok: false, errors: ["checkpoints:not-an-object"], times: 0, frames_sha256: null };
  }
  const errors = [];
  if (checkpoints.schema !== CHECKPOINT_SCHEMA) {
    errors.push(`schema:expected ${CHECKPOINT_SCHEMA}`);
  }
  const times = Array.isArray(checkpoints.times) ? checkpoints.times : null;
  if (!times || times.length === 0) {
    errors.push("times:must-be-non-empty-list");
  } else {
    let previous = null;
    for (let i = 0; i < times.length; i += 1) {
      const time = times[i];
      if (typeof time !== "number" || !Number.isFinite(time)) {
        errors.push(`times[${i}]:invalid:${String(time)}`);
      } else {
        if (previous !== null && time <= previous) errors.push(`times[${i}]:not-ascending:${String(time)}`);
        previous = time;
      }
    }
  }
  const recordedHash = checkpoints.frames_sha256;
  if (typeof recordedHash !== "string" || recordedHash.length !== 64) {
    errors.push("frames_sha256:invalid");
  }
  if (options.packageSha256 !== undefined && checkpoints.package_sha256 !== options.packageSha256) {
    errors.push("package_sha256:mismatch");
  }

  let computedHash = null;
  if (times && times.length && typeof recordedHash === "string" && recordedHash.length === 64) {
    const recorded = new Map();
    const frames = [];
    for (const time of times) {
      const canonical = canonicalFrameJson(moduleNamespace, time, options);
      recorded.set(time, canonical);
      frames.push(canonicalFrameObject(moduleNamespace, time, options));
    }
    computedHash = sha256Hex(JSON.stringify(frames));
    if (computedHash !== recordedHash) errors.push("frames_sha256:mismatch");

    const sequence = Array.isArray(checkpoints.seek_sequence) ? checkpoints.seek_sequence : [];
    for (const time of sequence) {
      if (typeof time !== "number" || !Number.isFinite(time)) {
        errors.push(`seek_sequence:invalid:${String(time)}`);
        continue;
      }
      const known = recorded.get(time);
      if (known === undefined) {
        errors.push(`seek_sequence:unrecorded-time:${String(time)}`);
        continue;
      }
      if (canonicalFrameJson(moduleNamespace, time, options) !== known) {
        errors.push(`seek_sequence:drift:${String(time)}`);
      }
    }
    for (let i = 0; i < times.length; i += 1) {
      if (canonicalFrameJson(moduleNamespace, times[i], options) !== JSON.stringify(frames[i])) {
        errors.push(`frames:unstable:${String(times[i])}`);
      }
    }
  }

  return {
    ok: errors.length === 0,
    errors,
    times: times ? times.length : 0,
    seek_sequence: Array.isArray(checkpoints.seek_sequence) ? checkpoints.seek_sequence.length : 0,
    frames_sha256: computedHash,
    package_sha256: typeof checkpoints.package_sha256 === "string" ? checkpoints.package_sha256 : null,
  };
}

/**
 * Assert that a seek sequence produces identical canonical frames in
 * ascending, given, and reverse orders. Throws on the first mismatch.
 */
export function assertSeekDeterminism(moduleNamespace, sequence, options = {}) {
  if (!Array.isArray(sequence) || sequence.length === 0) {
    throw new Error("sequence:must-be-non-empty-list");
  }
  const first = new Map();
  for (const time of [...sequence].sort((a, b) => a - b)) {
    if (typeof time !== "number" || !Number.isFinite(time)) {
      throw new Error(`sequence:invalid-time:${String(time)}`);
    }
    first.set(time, canonicalFrameJson(moduleNamespace, time, options));
  }
  for (const time of sequence) {
    if (canonicalFrameJson(moduleNamespace, time, options) !== first.get(time)) {
      throw new Error(`seek-determinism:drift:${String(time)}`);
    }
  }
  for (const time of [...sequence].reverse()) {
    if (canonicalFrameJson(moduleNamespace, time, options) !== first.get(time)) {
      throw new Error(`seek-determinism:reverse-drift:${String(time)}`);
    }
  }
  return { ok: true, queries: sequence.length * 3 };
}

// ----------------------------------------------------------------- Node CLI

if (typeof process !== "undefined" && Array.isArray(process.argv) && typeof process.argv[1] === "string") {
  import("node:url")
    .then(({ pathToFileURL }) => pathToFileURL(process.argv[1]).href === import.meta.url)
    .then((isMain) => (isMain ? runCli(process.argv.slice(2)) : null))
    .then((report) => {
      if (report) {
        process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
        process.exitCode = report.ok ? 0 : 1;
      }
    })
    .catch((error) => {
      process.stdout.write(`${JSON.stringify({ ok: false, errors: [`cli:${error.message}`] }, null, 2)}\n`);
      process.exitCode = 1;
    });
}

async function runCli(argv) {
  const [{ readFileSync }, { join, resolve }, { pathToFileURL }] = await Promise.all([
    import("node:fs"),
    import("node:path"),
    import("node:url"),
  ]);
  const args = [...argv];
  let root = process.cwd();
  let checkpointsPath = null;
  while (args.length > 0) {
    const argument = args.shift();
    if (argument === "--checkpoints") {
      checkpointsPath = args.shift();
    } else if (argument === "--help" || argument === "-h") {
      return {
        ok: true,
        usage: "node consumer-probe.js [packageRoot] [--checkpoints <checkpoints.json>]",
      };
    } else if (argument) {
      root = argument;
    }
  }
  const manifestPath = join(resolve(root), "beatscope-package.json");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const entryUrl = pathToFileURL(join(resolve(root), manifest.entry)).href;
  const moduleNamespace = await import(entryUrl);
  const report = await inspectPackage(manifest, moduleNamespace);
  if (checkpointsPath) {
    const checkpoints = JSON.parse(readFileSync(resolve(checkpointsPath), "utf8"));
    report.checkpoints = runCheckpointSuite(moduleNamespace, checkpoints, {});
    report.ok = report.ok && report.checkpoints.ok;
  }
  return report;
}
