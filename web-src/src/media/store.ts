/**
 * Project asset store (plan §6.2): decoded textures live here, referenced
 * from layer props as `asset:<asset_id>`. The store is the AssetResolver the
 * renderer consults; a reference that no longer resolves reports missing and
 * the media-slice system paints the placeholder instead of vanishing.
 */
import { Texture } from 'pixi.js';
import type { AssetResolver } from '../systems/registry';
import type { DecodedVideo } from './decode';

export interface ProjectAsset {
  asset_id: string;
  sha256: string;
  mime: string;
  kind: 'image' | 'video';
  width: number;
  height: number;
  duration: number | null;
  display_name: string;
  bytes: number;
}

export class AssetStore implements AssetResolver {
  private textures = new Map<string, Texture>();
  private videos = new Map<string, DecodedVideo>();
  private manifest = new Map<string, ProjectAsset>();
  private loaded = false;
  private revision = 0;

  setManifest(entries: ProjectAsset[]): void {
    const nextIds = new Set(entries.map((entry) => entry.asset_id));
    for (const id of [...this.textures.keys()]) {
      if (nextIds.has(id)) continue;
      this.dropDecoded(id);
    }
    this.manifest.clear();
    for (const entry of entries) this.manifest.set(entry.asset_id, entry);
    this.loaded = true;
    this.revision += 1;
  }

  register(assetId: string, texture: Texture, decodedVideo: DecodedVideo | null = null): void {
    this.dropDecoded(assetId);
    this.textures.set(assetId, texture);
    if (decodedVideo) this.videos.set(assetId, decodedVideo);
    this.revision += 1;
  }

  private dropDecoded(assetId: string): void {
    const texture = this.textures.get(assetId);
    if (texture) texture.destroy(true);
    this.textures.delete(assetId);
    const decoded = this.videos.get(assetId);
    if (decoded) {
      decoded.video.pause();
      decoded.video.removeAttribute('src');
      decoded.video.load();
      URL.revokeObjectURL(decoded.objectUrl);
    }
    this.videos.delete(assetId);
  }

  /** Drop decoded textures; the manifest stays so missing state is honest. */
  clearTextures(): void {
    for (const id of [...this.textures.keys()]) this.dropDecoded(id);
    this.revision += 1;
  }

  clear(): void {
    this.clearTextures();
    this.manifest.clear();
    this.loaded = false;
  }

  textureFor(src: string): Texture | null {
    if (!src.startsWith('asset:')) return null;
    return this.textures.get(src.slice('asset:'.length)) ?? null;
  }

  missingAsset(src: string): boolean {
    if (src.startsWith('missing-asset:')) return true;
    if (!src.startsWith('asset:')) return false;
    const id = src.slice('asset:'.length);
    if (this.textures.has(id)) return false;
    // before the manifest loads we cannot say; after it loads, absence is real
    return this.loaded && !this.manifest.has(id);
  }

  entry(assetId: string): ProjectAsset | null {
    return this.manifest.get(assetId) ?? null;
  }

  list(): ProjectAsset[] {
    return [...this.manifest.values()];
  }

  cacheKey(): string {
    return String(this.revision);
  }

  mediaDuration(src: string): number | null {
    if (!src.startsWith('asset:')) return null;
    return this.videos.get(src.slice('asset:'.length))?.duration ?? null;
  }

  seekMedia(src: string, time: number): void {
    if (!src.startsWith('asset:') || !Number.isFinite(time)) return;
    const decoded = this.videos.get(src.slice('asset:'.length));
    if (!decoded || decoded.video.readyState < HTMLMediaElement.HAVE_METADATA) return;
    const target = Math.max(0, Math.min(time, Math.max(0, decoded.duration - 1e-6)));
    if (Math.abs(decoded.video.currentTime - target) > 1 / 60) decoded.video.currentTime = target;
  }
}

export const assetStore = new AssetStore();
