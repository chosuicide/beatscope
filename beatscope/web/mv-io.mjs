/** A pipe can close instead of draining. Bound and clean up every pending write. */
export function writeChunk(stream, bytes, timeout = 30000) {
  return new Promise((resolve, reject) => {
    let timer;
    const finish = error => {
      clearTimeout(timer);
      stream.off('close', closed);
      stream.off('error', finish);
      if (error) reject(error); else resolve();
    };
    const closed = () => finish(new Error('Encoder pipe closed'));
    if (stream.destroyed || stream.writableEnded) return closed();
    timer = setTimeout(() => finish(new Error('Encoder pipe write timed out')), timeout);
    stream.once('close', closed);
    stream.once('error', finish);
    try { stream.write(bytes, finish); } catch (error) { finish(error); }
  });
}

export function acceptsChunk(headers, host, token) {
  return headers.host === host && headers['x-beathi-render'] === token
    && headers['content-type'] === 'application/octet-stream'
    && (!headers.origin || headers.origin === `http://${host}`);
}
