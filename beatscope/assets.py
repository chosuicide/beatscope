"""Project media assets: content-addressed storage with a canonical manifest.

Rules enforced here:

- images: PNG / JPEG / WebP, at most 25 MiB each;
- video: MP4 / WebM, at most 100 MiB and 60 seconds each;
- project budget: 500 MiB;
- files are rejected by decoded container type as well as extension;
- bytes are stored content-addressed under the project directory and the
  manifest carries id, sha256, mime, dimensions, duration and display name;
- absolute local paths never appear in the manifest or API responses.

Video layers stay muted by contract; this module only stores and describes
media. BeatScope audio remains the sole playback clock.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from pathlib import Path
from typing import Any

from .project import _atomic_write_bytes

ASSETS_SCHEMA = "beatscope-assets-1"
MANIFEST_FILENAME = "manifest.json"
ASSETS_DIRNAME = "assets"

IMAGE_MAX_BYTES = 25 * 1024 * 1024
VIDEO_MAX_BYTES = 100 * 1024 * 1024
VIDEO_MAX_SECONDS = 60.0
PROJECT_ASSET_BUDGET_BYTES = 500 * 1024 * 1024

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class AssetError(ValueError):
    """Stable public failure for an unusable asset request."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# decoded-type sniffing


def _png_info(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise AssetError("asset/decode-failed", "PNG header is truncated")
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def _jpeg_info(data: bytes) -> tuple[int, int]:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if index + 4 > len(data):
            break
        length = struct.unpack(">H", data[index + 2 : index + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if index + 9 > len(data):
                break
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return int(width), int(height)
        index += 2 + length
    raise AssetError("asset/decode-failed", "JPEG frame header not found")


def _webp_info(data: bytes) -> tuple[int, int]:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    if chunk == b"VP8 " and len(data) >= 30:
        # lossy: frame tag then 16-bit dimensions with 14-bit precision
        width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return width, height
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise AssetError("asset/decode-failed", "unsupported WebP variant")


def _mp4_duration(data: bytes) -> tuple[float | None, int | None, int | None]:
    """Walk MP4 boxes for mvhd (duration/timescale) and tkhd (dimensions)."""
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None

    def walk(start: int, end: int) -> None:
        nonlocal duration_seconds, width, height
        index = start
        while index + 8 <= end:
            size = struct.unpack(">I", data[index : index + 4])[0]
            kind = data[index + 4 : index + 8]
            header = 8
            if size == 1:
                if index + 16 > end:
                    break
                size = struct.unpack(">Q", data[index + 8 : index + 16])[0]
                header = 16
            elif size == 0:
                size = end - index
            if size < header or index + size > end:
                break
            body = index + header
            body_end = index + size
            if kind == b"moov":
                walk(body, body_end)
            if kind == b"mvhd":
                version = data[body]
                if version == 1 and body + 32 <= body_end:
                    timescale = struct.unpack(">I", data[body + 20 : body + 24])[0]
                    duration = struct.unpack(">Q", data[body + 24 : body + 32])[0]
                elif body + 20 <= body_end:
                    timescale = struct.unpack(">I", data[body + 12 : body + 16])[0]
                    duration = struct.unpack(">I", data[body + 16 : body + 20])[0]
                else:
                    timescale = duration = 0
                if timescale:
                    duration_seconds = duration / timescale
            if kind == b"trak":
                walk(body, body_end)
            if kind in (b"mdia", b"minf", b"stbl"):
                walk(body, body_end)
            if kind == b"tkhd" and body_end - body >= 8:
                raw_width, raw_height = struct.unpack(">II", data[body_end - 8 : body_end])
                parsed_width, parsed_height = raw_width >> 16, raw_height >> 16
                if parsed_width > 0 and parsed_height > 0:
                    width, height = parsed_width, parsed_height
            index += size

    walk(0, len(data))
    return duration_seconds, width, height


def _ebml_element(data: bytes, start: int, end: int) -> tuple[int, int, int] | None:
    """Return (element_id, body_start, body_end) for the element at start."""
    if start >= end:
        return None
    first = data[start]
    if first == 0:
        raise AssetError("asset/decode-failed", "invalid EBML element id")
    length = 1
    mask = 0x80
    while not (first & mask):
        length += 1
        mask >>= 1
        if length > 8:
            raise AssetError("asset/decode-failed", "invalid EBML element id")
    element_id = int.from_bytes(data[start : start + length], "big")
    pos = start + length
    if pos >= end:
        return None
    size_byte = data[pos]
    size_len = 1
    mask = 0x80
    while not (size_byte & mask):
        size_len += 1
        mask >>= 1
        if size_len > 8:
            raise AssetError("asset/decode-failed", "invalid EBML size")
    raw = data[pos : pos + size_len]
    unknown = all(b == 0xFF for b in raw)
    size = 0
    for index, byte in enumerate(raw):
        size = (size << 8) | (byte if index else byte & (0xFF >> size_len))
    body_start = pos + size_len
    body_end = end if unknown else min(end, body_start + size)
    return element_id, body_start, body_end


def _webm_info(data: bytes) -> tuple[float | None, int | None, int | None]:
    root = _ebml_element(data, 0, len(data))
    if not root:
        raise AssetError("asset/decode-failed", "empty EBML header")
    segment = _ebml_element(data, root[2], len(data))
    if not segment or segment[0] != 0x18538067:
        raise AssetError("asset/decode-failed", "WebM segment not found")
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None

    def scan_dimensions(start: int, end: int) -> None:
        nonlocal width, height
        inner = start
        while inner < end:
            child = _ebml_element(data, inner, end)
            if not child:
                break
            child_id, child_start, child_end = child
            if child_id == 0xB0 and child_end > child_start:
                width = int.from_bytes(data[child_start:child_end], "big")
            elif child_id == 0xBA and child_end > child_start:
                height = int.from_bytes(data[child_start:child_end], "big")
            elif child_id in (0x1654AE6B, 0xAE, 0xE0):  # Tracks / TrackEntry / Video
                scan_dimensions(child_start, child_end)
            inner = child_end

    index = segment[1]
    while index < segment[2]:
        element = _ebml_element(data, index, segment[2])
        if not element:
            break
        element_id, body_start, body_end = element
        if element_id == 0x1549A966:  # Info
            timecode_scale = 1_000_000
            duration: float | None = None
            inner = body_start
            while inner < body_end:
                child = _ebml_element(data, inner, body_end)
                if not child:
                    break
                child_id, child_start, child_end = child
                if child_id == 0x2AD7B1 and child_end > child_start:
                    timecode_scale = int.from_bytes(data[child_start:child_end], "big")
                elif child_id == 0x4489 and child_end - child_start in (4, 8):
                    duration = (
                        struct.unpack(">f", data[child_start:child_end])[0]
                        if child_end - child_start == 4
                        else struct.unpack(">d", data[child_start:child_end])[0]
                    )
                inner = child_end
            duration_seconds = duration * timecode_scale / 1e9 if duration is not None else None
        elif element_id == 0x1654AE6B:  # Tracks
            scan_dimensions(body_start, body_end)
        index = body_end
    return duration_seconds, width, height


def sniff_asset(data: bytes) -> dict[str, Any]:
    """Decode the container type; raise AssetError for unsupported bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = _png_info(data)
        return {"kind": "image", "mime": "image/png", "extension": "png", "width": width, "height": height, "duration": None}
    if data[:3] == b"\xff\xd8\xff":
        width, height = _jpeg_info(data)
        return {"kind": "image", "mime": "image/jpeg", "extension": "jpg", "width": width, "height": height, "duration": None}
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        width, height = _webp_info(data)
        return {"kind": "image", "mime": "image/webp", "extension": "webp", "width": width, "height": height, "duration": None}
    if len(data) >= 12 and data[4:8] == b"ftyp":
        duration, width, height = _mp4_duration(data)
        return {
            "kind": "video",
            "mime": "video/mp4",
            "extension": "mp4",
            "width": width,
            "height": height,
            "duration": duration,
        }
    if data[:4] == b"\x1aE\xdf\xa3":
        duration, width, height = _webm_info(data)
        return {
            "kind": "video",
            "mime": "video/webm",
            "extension": "webm",
            "width": width,
            "height": height,
            "duration": duration,
        }
    raise AssetError("asset/unsupported-type", "unsupported media type")


# ---------------------------------------------------------------------------
# store


class AssetStore:
    """Content-addressed asset storage rooted at one project directory."""

    def __init__(self, project_dir: str | Path, project_id: str):
        self.project_dir = Path(project_dir)
        self.project_id = project_id
        self.assets_dir = self.project_dir / ASSETS_DIRNAME
        self.manifest_path = self.assets_dir / MANIFEST_FILENAME

    # -- manifest

    def manifest(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(raw, dict) or raw.get("schema") != ASSETS_SCHEMA:
            return []
        entries = raw.get("assets")
        if not isinstance(entries, list):
            return []
        return [entry for entry in entries if isinstance(entry, dict) and _HEX64.match(str(entry.get("asset_id", "")))]

    def _write_manifest(self, entries: list[dict[str, Any]]) -> None:
        payload = json.dumps(
            {"schema": ASSETS_SCHEMA, "project_id": self.project_id, "assets": entries},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8") + b"\n"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(self.manifest_path, payload)

    def total_bytes(self) -> int:
        return sum(int(entry.get("bytes", 0)) for entry in self.manifest())

    # -- reads

    def path_for(self, asset_id: str) -> Path | None:
        if not _HEX64.match(asset_id):
            return None
        for entry in self.manifest():
            if entry["asset_id"] == asset_id:
                path = self.assets_dir / f"{asset_id}.{entry.get('extension', 'bin')}"
                return path if path.is_file() else None
        return None

    def get(self, asset_id: str) -> tuple[str, bytes] | None:
        for entry in self.manifest():
            if entry["asset_id"] != asset_id:
                continue
            path = self.assets_dir / f"{asset_id}.{entry.get('extension', 'bin')}"
            if not path.is_file():
                return None
            return str(entry.get("mime") or "application/octet-stream"), path.read_bytes()
        return None

    # -- writes

    def add(self, display_name: str, data: bytes) -> dict[str, Any]:
        if not data:
            raise AssetError("asset/empty", "asset upload is empty")
        sniffed = sniff_asset(data)  # decoded type decides, not the extension
        if sniffed["kind"] == "image" and len(data) > IMAGE_MAX_BYTES:
            raise AssetError("asset/too-large", f"images are limited to {IMAGE_MAX_BYTES} bytes")
        if sniffed["kind"] == "video":
            if len(data) > VIDEO_MAX_BYTES:
                raise AssetError("asset/too-large", f"videos are limited to {VIDEO_MAX_BYTES} bytes")
            duration = sniffed.get("duration")
            if duration is None or not math.isfinite(float(duration)):
                raise AssetError("asset/decode-failed", "could not read the video duration")
            if float(duration) > VIDEO_MAX_SECONDS:
                raise AssetError("asset/too-long", f"videos are limited to {VIDEO_MAX_SECONDS:g} seconds")
            if not all(isinstance(sniffed.get(axis), int) and sniffed[axis] > 0 for axis in ("width", "height")):
                raise AssetError("asset/decode-failed", "could not read the video dimensions")

        digest = hashlib.sha256(data).hexdigest()
        entries = self.manifest()
        for entry in entries:
            if entry["asset_id"] == digest:
                return dict(entry)  # identical content: dedupe, no new bytes

        incoming = len(data)
        if self.total_bytes() + incoming > PROJECT_ASSET_BUDGET_BYTES:
            raise AssetError("asset/budget", f"project asset budget of {PROJECT_ASSET_BUDGET_BYTES} bytes is exhausted")

        self.assets_dir.mkdir(parents=True, exist_ok=True)
        target = self.assets_dir / f"{digest}.{sniffed['extension']}"
        _atomic_write_bytes(target, data)
        entry = {
            "asset_id": digest,
            "sha256": digest,
            "mime": sniffed["mime"],
            "kind": sniffed["kind"],
            "extension": sniffed["extension"],
            "width": sniffed.get("width"),
            "height": sniffed.get("height"),
            "duration": round(float(sniffed["duration"]), 6) if sniffed.get("duration") is not None else None,
            # A browser may submit a Windows fakepath even when the server is
            # running on POSIX.  ``Path.name`` only understands the host
            # separator, so normalize both separators before retaining the
            # harmless display leaf.
            "display_name": str(display_name).replace("\\", "/").rsplit("/", 1)[-1][:120] or "asset",
            "bytes": incoming,
        }
        entries.append(entry)
        entries.sort(key=lambda item: item["asset_id"])
        self._write_manifest(entries)
        return dict(entry)

    def delete(self, asset_id: str) -> bool:
        entries = self.manifest()
        remaining = [entry for entry in entries if entry["asset_id"] != asset_id]
        if len(remaining) == len(entries):
            return False
        for entry in entries:
            if entry["asset_id"] == asset_id:
                (self.assets_dir / f"{asset_id}.{entry.get('extension', 'bin')}").unlink(missing_ok=True)
        self._write_manifest(remaining)
        return True

    # -- references

    @staticmethod
    def referenced_by(direction: dict[str, Any] | None, asset_id: str) -> list[str]:
        """Scene/layer labels whose props reference `asset:<asset_id>`."""
        needle = f"asset:{asset_id}"
        references: list[str] = []
        if not isinstance(direction, dict):
            return references
        for scene in direction.get("scenes", []):
            if not isinstance(scene, dict):
                continue
            for layer in scene.get("layers", []):
                if not isinstance(layer, dict):
                    continue
                props = layer.get("props")
                if isinstance(props, dict) and props.get("src") == needle:
                    references.append(f"{scene.get('id', '?')}/{layer.get('id', '?')}")
        return references
