/**
 * Runtime asset client binding. App installs the capability adapter once the
 * boot probe resolves; components read it through `assetClient()` instead of
 * threading services through every prop (plan §3.7).
 */
import { UNAVAILABLE_ASSETS, type AssetClient } from './client';

let current: AssetClient = UNAVAILABLE_ASSETS;

export function setAssetClient(client: AssetClient): void {
  current = client;
}

export function assetClient(): AssetClient {
  return current;
}
