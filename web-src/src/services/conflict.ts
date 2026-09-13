/**
 * Direction save conflicts (plan §10.2). The server refuses a PUT whose
 * If-Match ETag no longer matches (412) or that carries no precondition at
 * all (428); both surface here with the server's current ETag so the
 * editor can re-read and reconcile instead of clobbering the other writer.
 */
export class DirectionConflictError extends Error {
  readonly currentEtag: string | null;

  constructor(message: string, currentEtag: string | null = null) {
    super(message);
    this.name = 'DirectionConflictError';
    this.currentEtag = currentEtag;
  }
}
