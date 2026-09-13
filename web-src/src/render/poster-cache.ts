/**
 * Deterministic poster cache (plan §3.2/§10.5).
 *
 * Inactive boards never render live: each one shows a cached poster texture
 * generated at its representative time. The cache is keyed by scene id and
 * invalidated only for scenes affected by an edit; eviction is least-recently
 * used and happens before the estimated GPU texture budget is exceeded.
 *
 * LRU order uses a monotonic access counter, never wall-clock time — the
 * cache is presentation state, but determinism costs nothing here.
 */
import type { Texture } from 'pixi.js';

export interface PosterEntry<T extends Texture = Texture> {
  sceneId: string;
  key: string;
  texture: T;
  bytes: number;
  lastUsed: number;
}

export interface PosterCacheOptions<T extends Texture = Texture> {
  /** Estimated GPU budget in bytes (plan §10.5: 256 MiB). */
  budgetBytes?: number;
  /** Create the poster texture for a scene (renderer-specific). */
  create(sceneId: string, key: string): { texture: T; width: number; height: number } | null;
  /** Destroy a texture that leaves the cache. */
  destroy(texture: T): void;
}

/** bytes = w * h * 4 channels * resolution^2 (conservative estimate). */
export function estimateTextureBytes(width: number, height: number, resolution = 1): number {
  return Math.max(0, Math.round(width * height * 4 * resolution * resolution));
}

export class PosterCache<T extends Texture = Texture> {
  private entries = new Map<string, PosterEntry<T>>();
  private clock = 0;
  private bytes = 0;
  readonly budgetBytes: number;
  private options: PosterCacheOptions<T>;

  constructor(options: PosterCacheOptions<T>) {
    this.options = options;
    this.budgetBytes = options.budgetBytes ?? 256 * 1024 * 1024;
  }

  private touch(entry: PosterEntry<T>): PosterEntry<T> {
    this.clock += 1;
    entry.lastUsed = this.clock;
    return entry;
  }

  /** Poster for a scene at `key` (doc revision + representative time), or null. */
  get(sceneId: string, key: string): T | null {
    const entry = this.entries.get(sceneId);
    if (!entry || entry.key !== key) return null;
    this.touch(entry);
    return entry.texture;
  }

  /** True when a valid poster exists for this scene/key without touching LRU. */
  has(sceneId: string, key: string): boolean {
    const entry = this.entries.get(sceneId);
    return !!entry && entry.key === key;
  }

  /**
   * Generate (or reuse) the poster for a scene. Returns the texture or null
   * when the renderer could not produce one (WebGL loss, empty scene).
   */
  ensure(sceneId: string, key: string): T | null {
    const existing = this.get(sceneId, key);
    if (existing) return existing;
    this.invalidate([sceneId]);
    const created = this.options.create(sceneId, key);
    if (!created) return null;
    const entry: PosterEntry<T> = {
      sceneId,
      key,
      texture: created.texture,
      bytes: estimateTextureBytes(created.width, created.height),
      lastUsed: 0,
    };
    this.entries.set(sceneId, entry);
    this.bytes += entry.bytes;
    this.touch(entry);
    this.evict();
    return entry.texture;
  }

  /** Drop posters for the given scenes (only these re-render). */
  invalidate(sceneIds: Iterable<string>): void {
    for (const sceneId of sceneIds) {
      const entry = this.entries.get(sceneId);
      if (!entry) continue;
      this.entries.delete(sceneId);
      this.bytes -= entry.bytes;
      this.options.destroy(entry.texture);
    }
  }

  clear(): void {
    for (const entry of this.entries.values()) this.options.destroy(entry.texture);
    this.entries.clear();
    this.bytes = 0;
  }

  private evict(): void {
    while (this.bytes > this.budgetBytes && this.entries.size > 0) {
      let oldest: PosterEntry<T> | null = null;
      for (const entry of this.entries.values()) {
        if (!oldest || entry.lastUsed < oldest.lastUsed) oldest = entry;
      }
      if (!oldest) break;
      this.entries.delete(oldest.sceneId);
      this.bytes -= oldest.bytes;
      this.options.destroy(oldest.texture);
    }
  }

  get stats(): { count: number; bytes: number; budgetBytes: number } {
    return { count: this.entries.size, bytes: this.bytes, budgetBytes: this.budgetBytes };
  }
}
