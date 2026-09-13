/**
 * Project asset client (plan §6.1). Local Studio talks to the bounded
 * asset endpoints; the static demo has no upload surface and returns null
 * capabilities so the UI removes the affordance instead of showing a dead
 * button (§3.7).
 */
import { Texture } from 'pixi.js';
import { assetStore, type ProjectAsset } from './store';
import { decodeAsset, validateAssetFile, type DecodedAsset } from './decode';

export interface AssetClient {
  readonly available: boolean;
  list(): Promise<ProjectAsset[]>;
  upload(file: File): Promise<ProjectAsset>;
  remove(assetId: string, confirmed: boolean): Promise<{ deleted: boolean; inUse: string[] }>;
  /** Decode every manifest entry into the shared store (best effort). */
  warm(): Promise<void>;
}

async function readBytes(file: File): Promise<Uint8Array> {
  return new Uint8Array(await file.arrayBuffer());
}

function textureFromDecoded(decoded: DecodedAsset): Texture {
  if (decoded.kind === 'image') return Texture.from(decoded.bitmap);
  // Pixi uploads the current video frame each render while the element is
  // the texture source; the muted element's clock is set by the evaluator.
  return Texture.from(decoded.video);
}

export class LocalStudioAssetClient implements AssetClient {
  readonly available = true;
  constructor(private projectId: string) {}

  private base(): string {
    return `/api/projects/${encodeURIComponent(this.projectId)}/assets`;
  }

  async list(): Promise<ProjectAsset[]> {
    const res = await fetch(this.base());
    if (!res.ok) return [];
    const body = (await res.json()) as { assets?: ProjectAsset[] };
    const assets = body.assets ?? [];
    assetStore.setManifest(assets);
    return assets;
  }

  async upload(file: File): Promise<ProjectAsset> {
    const bytes = await readBytes(file);
    const sniffed = validateAssetFile(file, bytes); // client-side pre-flight
    const decoded = await decodeAsset(file, sniffed);
    const res = await fetch(this.base(), {
      method: 'POST',
      headers: {
        'Content-Type': sniffed.mime,
        'X-Filename': encodeURIComponent(file.name),
      },
      body: file,
    });
    const body = (await res.json().catch(() => ({}))) as { asset?: ProjectAsset; error?: string };
    if (!res.ok || !body.asset) {
      throw new Error(body.error ?? `asset upload failed (${res.status})`);
    }
    assetStore.register(body.asset.asset_id, textureFromDecoded(decoded), decoded.kind === 'video' ? decoded : null);
    await this.list();
    return body.asset;
  }

  async remove(assetId: string, confirmed: boolean): Promise<{ deleted: boolean; inUse: string[] }> {
    const res = await fetch(`${this.base()}/${encodeURIComponent(assetId)}${confirmed ? '?confirm=1' : ''}`, {
      method: 'DELETE',
    });
    const body = (await res.json().catch(() => ({}))) as { deleted?: boolean; in_use?: string[] };
    if (res.status === 409) return { deleted: false, inUse: body.in_use ?? [] };
    if (!res.ok) throw new Error(`asset delete failed (${res.status})`);
    await this.list();
    return { deleted: true, inUse: [] };
  }

  async warm(): Promise<void> {
    const assets = await this.list();
    for (const asset of assets) {
      const src = `asset:${asset.asset_id}`;
      if (assetStore.textureFor(src)) continue;
      try {
        const res = await fetch(`${this.base()}/${encodeURIComponent(asset.asset_id)}`);
        if (!res.ok) continue;
        const blob = await res.blob();
        const file = new File([blob], asset.display_name, { type: asset.mime });
        const bytes = new Uint8Array(await blob.arrayBuffer());
        const sniffed = validateAssetFile(file, bytes);
        const decoded = await decodeAsset(file, sniffed);
        assetStore.register(asset.asset_id, textureFromDecoded(decoded), decoded.kind === 'video' ? decoded : null);
      } catch {
        // a failed decode leaves no texture: the layer shows missing state
      }
    }
  }
}

export const UNAVAILABLE_ASSETS: AssetClient = {
  available: false,
  async list() {
    return [];
  },
  async upload() {
    throw new Error('asset upload is unavailable in the static demo');
  },
  async remove() {
    return { deleted: false, inUse: [] };
  },
  async warm() {
    return;
  },
};
