import { serializeComposition, validateComposition, type Composition } from './model';

export type SaveState = 'saved' | 'saving' | 'conflict' | 'error';
export interface Draft { etag: string; document: Composition }

function tabSuffix() {
  if (typeof sessionStorage === 'undefined') return '';
  let id = sessionStorage.getItem('beatscope:composition-tab');
  if (!id) { id = crypto.randomUUID(); sessionStorage.setItem('beatscope:composition-tab', id); }
  return ':' + id;
}

/** One writer per loaded document. Never advance ETag after a refused write. */
export class CompositionWriter {
  private pending: string | null = null;
  private active: Promise<void> | null = null;
  private stopped = false;
  private disposed = false;
  private latest: string;
  readonly draftKey: string;
  get version() { return this.etag; }
  constructor(private url: string, private etag: string, doc: Composition,
    private notify: (state: SaveState, detail?: string) => void,
    private request: typeof fetch = fetch,
    private storage: Pick<Storage, 'setItem' | 'getItem' | 'removeItem'> = localStorage) {
    this.latest = serializeComposition(doc);
    this.draftKey = 'beatscope:composition:' + doc.project_id + tabSuffix();
  }
  enqueue(doc: Composition) {
    if (this.disposed) return;
    this.pending = this.latest = serializeComposition(doc);
    if (!this.storeDraft()) return;
    this.start();
  }
  private storeDraft() {
    try { this.storage.setItem(this.draftKey, JSON.stringify({ etag: this.etag, document: JSON.parse(this.latest) })); return true; }
    catch { this.stopped = true; this.notify('error', 'Local recovery storage is full or unavailable. Export your document before leaving.'); return false; }
  }
  private start() {
    if (this.active || this.stopped || this.disposed) return;
    this.active = this.run().finally(() => { this.active = null; if (this.pending && !this.stopped && !this.disposed) this.start(); });
  }
  private async run() {
    while (this.pending && !this.stopped && !this.disposed) {
      const sent = this.pending; this.pending = null; this.notify('saving');
      try {
        const response = await this.request.call(globalThis, this.url, { method: 'PUT', headers: { 'Content-Type': 'application/json', 'If-Match': this.etag }, body: sent });
        if (!response.ok) {
          this.pending ??= this.latest; this.stopped = true;
          this.notify(response.status === 409 ? 'conflict' : 'error', response.status === 409
            ? 'Another editor saved this project. Your draft is safe; reload to compare before replacing it.' : 'Save failed (' + response.status + '). Your local draft is retained.');
          return;
        }
        const nextEtag = response.headers.get('ETag');
        if (!nextEtag) throw Error('Save response has no version.');
        this.etag = nextEtag;
        if (this.pending) { if (!this.storeDraft()) return; }
        else {
          // Do not erase a different tab's newer draft.
          const stored = this.storage.getItem(this.draftKey);
          if (stored && serializeComposition(JSON.parse(stored).document) === sent) this.storage.removeItem(this.draftKey);
          if (!this.disposed) this.notify('saved');
        }
      } catch (error) {
        this.pending ??= this.latest; this.stopped = true;
        if (!this.disposed) this.notify('error', String(error));
      }
    }
  }
  retry() { if (!this.disposed) { this.stopped = false; if (this.storeDraft()) this.start(); } }
  async flush() { while (this.active) await this.active; }
  dispose() { this.disposed = true; }
}

export function readDraft(storage: Pick<Storage, 'getItem'>, key: string): Draft | null {
  try {
    const value = JSON.parse(storage.getItem(key) ?? 'null');
    if (!value || typeof value.etag !== 'string' || validateComposition(value.document).length) return null;
    return value;
  } catch { return null; }
}
