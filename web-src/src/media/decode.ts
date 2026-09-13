/**
 * Client-side media validation and decoding (plan §6.2).
 *
 * Files are rejected by decoded type as well as extension: the magic bytes
 * decide, so a renamed executable never reaches the decoder. Limits mirror
 * the server so the UI can explain a refusal before uploading.
 */
export const IMAGE_MAX_BYTES = 25 * 1024 * 1024;
export const VIDEO_MAX_BYTES = 100 * 1024 * 1024;
export const VIDEO_MAX_SECONDS = 60;
export const PROJECT_ASSET_BUDGET_BYTES = 500 * 1024 * 1024;

export type AssetKind = 'image' | 'video';

export interface SniffedAsset {
  kind: AssetKind;
  mime: string;
  extension: string;
}

export class AssetRejected extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function ascii(bytes: Uint8Array, offset: number, length: number): string {
  return String.fromCharCode(...bytes.slice(offset, offset + length));
}

/** Decode the container type from magic bytes; null when unsupported. */
export function sniffAsset(bytes: Uint8Array): SniffedAsset | null {
  if (bytes.length >= 8 && bytes[0] === 0x89 && ascii(bytes, 1, 3) === 'PNG' && bytes[4] === 0x0d) {
    return { kind: 'image', mime: 'image/png', extension: 'png' };
  }
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return { kind: 'image', mime: 'image/jpeg', extension: 'jpg' };
  }
  if (
    bytes.length >= 12 &&
    ascii(bytes, 0, 4) === 'RIFF' &&
    ascii(bytes, 8, 4) === 'WEBP'
  ) {
    return { kind: 'image', mime: 'image/webp', extension: 'webp' };
  }
  if (bytes.length >= 12 && ascii(bytes, 4, 4) === 'ftyp') {
    return { kind: 'video', mime: 'video/mp4', extension: 'mp4' };
  }
  if (bytes.length >= 4 && bytes[0] === 0x1a && bytes[1] === 0x45 && bytes[2] === 0xdf && bytes[3] === 0xa3) {
    return { kind: 'video', mime: 'video/webm', extension: 'webm' };
  }
  return null;
}

/** Throws AssetRejected with a stable code when the file is unusable. */
export function validateAssetFile(file: File, bytes: Uint8Array): SniffedAsset {
  const sniffed = sniffAsset(bytes);
  if (!sniffed) {
    throw new AssetRejected('asset/unsupported-type', `unsupported media type: ${file.name}`);
  }
  if (sniffed.kind === 'image' && bytes.length > IMAGE_MAX_BYTES) {
    throw new AssetRejected('asset/too-large', `images are limited to ${IMAGE_MAX_BYTES / 1024 / 1024} MiB`);
  }
  if (sniffed.kind === 'video' && bytes.length > VIDEO_MAX_BYTES) {
    throw new AssetRejected('asset/too-large', `videos are limited to ${VIDEO_MAX_BYTES / 1024 / 1024} MiB`);
  }
  return sniffed;
}

export interface DecodedImage {
  kind: 'image';
  bitmap: ImageBitmap;
  width: number;
  height: number;
  duration: null;
}

export interface DecodedVideo {
  kind: 'video';
  video: HTMLVideoElement;
  objectUrl: string;
  width: number;
  height: number;
  duration: number;
}

export type DecodedAsset = DecodedImage | DecodedVideo;

/** Decode an accepted file; rejects by decoded duration as well (§6.2). */
export async function decodeAsset(file: File, sniffed: SniffedAsset): Promise<DecodedAsset> {
  if (sniffed.kind === 'image') {
    const bitmap = await createImageBitmap(file);
    return { kind: 'image', bitmap, width: bitmap.width, height: bitmap.height, duration: null };
  }
  const url = URL.createObjectURL(file);
  try {
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.preload = 'metadata';
    video.src = url;
    await new Promise<void>((resolve, reject) => {
      video.onloadedmetadata = () => resolve();
      video.onerror = () => reject(new AssetRejected('asset/decode-failed', `could not decode ${file.name}`));
    });
    if (!Number.isFinite(video.duration) || video.duration <= 0) {
      throw new AssetRejected('asset/decode-failed', `could not read the duration of ${file.name}`);
    }
    if (video.duration > VIDEO_MAX_SECONDS) {
      throw new AssetRejected('asset/too-long', `videos are limited to ${VIDEO_MAX_SECONDS} seconds`);
    }
    return { kind: 'video', video, objectUrl: url, width: video.videoWidth, height: video.videoHeight, duration: video.duration };
  } finally {
    // The object URL stays alive for a decoded video; AssetStore owns and
    // revokes it when the project/texture is replaced.
    if (sniffed.kind !== 'video') URL.revokeObjectURL(url);
  }
}

/** Small deterministic thumbnail (max side `max`), used by the dock/inspector. */
export async function makeThumbnail(decoded: DecodedAsset, max = 160): Promise<ImageBitmap | null> {
  const source: CanvasImageSource =
    decoded.kind === 'image' ? decoded.bitmap : decoded.video;
  const scale = Math.min(1, max / Math.max(decoded.width, decoded.height));
  const w = Math.max(1, Math.round(decoded.width * scale));
  const h = Math.max(1, Math.round(decoded.height * scale));
  try {
    return await createImageBitmap(source, { resizeWidth: w, resizeHeight: h, resizeQuality: 'medium' });
  } catch {
    return null;
  }
}
