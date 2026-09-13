/**
 * In-page H.264 encoder (WebCodecs).
 *
 * The rendered canvas goes straight into a VideoFrame, so no screenshot ever
 * leaves the browser: only the compressed elementary stream (Annex B) is
 * posted back to the worker, which muxes it with FFmpeg (`-c:v copy`). That
 * removes the per-frame PNG encode/decode round trip, which was the bulk of
 * the render cost.
 *
 * Returns null when the browser cannot encode, so the caller can fall back to
 * the screenshot+FFmpeg path instead of failing.
 */
const CODECS = ['avc1.640028', 'avc1.4d002a', 'avc1.42e02a']; // High 4.0, Main 4.2, Baseline 4.2

export async function createFrameEncoder({ canvas, fps = 30, bitrate = 8_000_000, token = '', onError }) {
  if (typeof VideoEncoder === 'undefined' || typeof VideoFrame === 'undefined') return null;
  const base = {
    width: canvas.width,
    height: canvas.height,
    framerate: fps,
    bitrate,
    latencyMode: 'quality',
    avc: { format: 'annexb' },
  };
  let config = null;
  for (const codec of CODECS) {
    const candidate = { ...base, codec };
    try {
      const support = await VideoEncoder.isConfigSupported(candidate);
      if (support && support.supported) { config = candidate; break; }
    } catch {
      /* try the next profile */
    }
  }
  if (!config) return null;

  const pending = [];
  let failure = null;
  const check = () => { if (failure) throw failure; };
  const encoder = new VideoEncoder({
    output: (chunk) => {
      const bytes = new Uint8Array(chunk.byteLength);
      chunk.copyTo(bytes);
      pending.push(bytes);
    },
    error: (error) => { failure = error; if (onError) onError(error); },
  });
  encoder.configure(config);

  const drain = async () => {
    while (pending.length) {
      check();
      const bytes = pending.shift();
      const response = await fetch('/chunk', { method: 'POST', body: bytes,
        headers: { 'Content-Type': 'application/octet-stream', 'X-Beathi-Render': token }, signal: AbortSignal.timeout(30000) });
      if (!response.ok) throw new Error(`chunk rejected (${response.status})`);
    }
  };
  const idle = () => new Promise((resolve) => setTimeout(resolve, 1));

  let index = 0;
  return {
    codec: config.codec,
    bitrate,
    /** Render one frame and hand it to the encoder. */
    async encode(timeSeconds) {
      // keep the queue bounded: the encoder (or its hardware) sets the pace
      const deadline = Date.now() + 30000;
      while (encoder.encodeQueueSize > 8) {
        check();
        if (Date.now() > deadline) throw new Error('Video encoder queue timed out');
        await idle();
      }
      check();
      const frame = new VideoFrame(canvas, {
        timestamp: Math.round(timeSeconds * 1e6),
        duration: Math.round(1e6 / fps),
      });
      try { encoder.encode(frame, { keyFrame: index % Math.max(1, Math.round(fps * 2)) === 0 }); }
      finally { frame.close(); }
      index += 1;
      await drain();
    },
    /** Flush the encoder and return the number of encoded frames. */
    async finish() {
      check();
      await encoder.flush();
      check();
      await drain();
      encoder.close();
      return index;
    },
  };
}
