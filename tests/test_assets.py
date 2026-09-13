"""Project asset store and HTTP endpoints (v0.12 Round 3 Commit 1, §6.2).

Media bytes here are synthetic but structurally valid: the store sniffs the
decoded container type (magic bytes), so these fixtures exercise the same
code paths as real files without shipping third-party media.
"""
from __future__ import annotations

import http.client
import json
import struct
import threading
import zlib
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import beatscope.server as server_module
from beatscope.assets import (
    AssetError,
    AssetStore,
    IMAGE_MAX_BYTES,
    sniff_asset,
)
from beatscope.project import ProjectManager
from beatscope.web_api import WebApi

ROOT = Path(__file__).resolve().parents[1]
ABA_RHYTHM = json.loads((ROOT / "tests" / "fixtures" / "structure" / "aba.rhythm.json").read_text(encoding="utf-8"))
PROJECT_ID = "62bce8192088"


# ---------------------------------------------------------------------------
# synthetic media builders


def png_bytes(width: int = 4, height: int = 3, padding: int = 0) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"\x00" + b"\x00\x00\x00" * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw * height))
        + b"\x00" * padding
        + chunk(b"IEND", b"")
    )


def jpeg_bytes(width: int = 7, height: int = 5) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def webp_bytes(width: int = 9, height: int = 6) -> bytes:
    payload = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    riff = b"WEBP" + payload
    return b"RIFF" + struct.pack("<I", len(riff)) + riff


def mp4_bytes(duration: float = 12.5, timescale: int = 1000, width: int = 640, height: int = 360) -> bytes:
    def box(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", 8 + len(payload)) + kind + payload

    # version+flags, creation, modification, timescale, duration
    mvhd = box(
        b"mvhd",
        b"\x00" * 4 + b"\x00" * 8 + struct.pack(">II", timescale, int(duration * timescale)) + b"\x00" * 80,
    )
    tkhd = box(b"tkhd", b"\x00" * 76 + struct.pack(">II", width << 16, height << 16))
    return box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2") + box(b"moov", mvhd + box(b"trak", tkhd))


def _ebml(eid: bytes, payload: bytes) -> bytes:
    return eid + b"\x01" + len(payload).to_bytes(7, "big") + payload


def webm_bytes(duration: float = 5.0, timecode_scale: int = 1_000_000, width: int = 640, height: int = 360) -> bytes:
    units = duration * 1e9 / timecode_scale
    info = _ebml(b"\x15\x49\xa9\x66", _ebml(b"\x2a\xd7\xb1", timecode_scale.to_bytes(4, "big")) + _ebml(b"\x44\x89", struct.pack(">d", units)))
    video = _ebml(b"\xe0", _ebml(b"\xb0", width.to_bytes(2, "big")) + _ebml(b"\xba", height.to_bytes(2, "big")))
    tracks = _ebml(b"\x16\x54\xae\x6b", _ebml(b"\xae", video))
    segment = _ebml(b"\x18\x53\x80\x67", info + tracks)
    header = _ebml(b"\x1a\x45\xdf\xa3", b"\x42\x86\x81\x01")
    return header + segment


# ---------------------------------------------------------------------------
# sniffing


def test_sniff_decodes_all_supported_types():
    assert sniff_asset(png_bytes(4, 3))["width"] == 4
    assert sniff_asset(png_bytes(4, 3))["height"] == 3
    assert sniff_asset(jpeg_bytes(7, 5))["mime"] == "image/jpeg"
    assert (sniff_asset(jpeg_bytes(7, 5))["width"], sniff_asset(jpeg_bytes(7, 5))["height"]) == (7, 5)
    assert sniff_asset(webp_bytes(9, 6))["mime"] == "image/webp"
    assert (sniff_asset(webp_bytes(9, 6))["width"], sniff_asset(webp_bytes(9, 6))["height"]) == (9, 6)
    mp4 = sniff_asset(mp4_bytes(12.5))
    assert mp4["kind"] == "video" and mp4["mime"] == "video/mp4"
    assert abs(mp4["duration"] - 12.5) < 1e-6
    assert (mp4["width"], mp4["height"]) == (640, 360)
    webm = sniff_asset(webm_bytes(5.0))
    assert webm["kind"] == "video" and webm["mime"] == "video/webm"
    assert abs(webm["duration"] - 5.0) < 1e-6
    assert (webm["width"], webm["height"]) == (640, 360)


def test_sniff_rejects_unknown_bytes():
    with pytest.raises(AssetError) as err:
        sniff_asset(b"#!/bin/sh\necho not media\n")
    assert err.value.code == "asset/unsupported-type"


# ---------------------------------------------------------------------------
# store behavior


def test_store_adds_dedupes_and_never_leaks_paths(tmp_path):
    store = AssetStore(tmp_path / "project", PROJECT_ID)
    entry = store.add(r"C:\Users\someone\Pictures\paper.png", png_bytes(4, 3))
    assert entry["asset_id"] == entry["sha256"]
    assert entry["display_name"] == "paper.png"
    assert "/" not in entry["display_name"] and "\\" not in entry["display_name"]
    assert entry["bytes"] == len(png_bytes(4, 3))
    # identical bytes dedupe to one manifest entry and one file
    again = store.add("copy.png", png_bytes(4, 3))
    assert again["asset_id"] == entry["asset_id"]
    assert len(store.manifest()) == 1
    files = list((tmp_path / "project" / "assets").glob("*.png"))
    assert len(files) == 1


def test_store_rejects_oversize_image_and_long_video(tmp_path):
    store = AssetStore(tmp_path / "project", PROJECT_ID)
    with pytest.raises(AssetError) as err:
        store.add("huge.png", png_bytes(1, 1, padding=IMAGE_MAX_BYTES))
    assert err.value.code == "asset/too-large"
    with pytest.raises(AssetError) as err:
        store.add("long.mp4", mp4_bytes(duration=90.0))
    assert err.value.code == "asset/too-long"
    assert store.manifest() == []


def test_store_enforces_project_budget(tmp_path, monkeypatch):
    import beatscope.assets as assets_module

    monkeypatch.setattr(assets_module, "PROJECT_ASSET_BUDGET_BYTES", 100)
    store = AssetStore(tmp_path / "project", PROJECT_ID)
    store.add("one.png", png_bytes(2, 2))
    with pytest.raises(AssetError) as err:
        store.add("two.png", png_bytes(2, 3))
    assert err.value.code == "asset/budget"


def test_store_delete_removes_bytes_and_entry(tmp_path):
    store = AssetStore(tmp_path / "project", PROJECT_ID)
    entry = store.add("a.png", png_bytes())
    assert store.delete(entry["asset_id"]) is True
    assert store.manifest() == []
    assert list((tmp_path / "project" / "assets").glob("*.png")) == []
    assert store.delete(entry["asset_id"]) is False


def test_manifest_survives_corruption(tmp_path):
    store = AssetStore(tmp_path / "project", PROJECT_ID)
    store.add("a.png", png_bytes())
    (tmp_path / "project" / "assets" / "manifest.json").write_text("{not json", encoding="utf-8")
    assert store.manifest() == []


def test_referenced_by_reports_scene_and_layer():
    asset_id = "ab" * 32
    direction = {
        "scenes": [
            {"id": "scene-01", "layers": [{"id": "lay-01", "props": {"src": f"asset:{asset_id}"}}]},
            {"id": "scene-02", "layers": [{"id": "lay-02", "props": {"src": "demo-media/fog-ridge.png"}}]},
        ]
    }
    assert AssetStore.referenced_by(direction, asset_id) == ["scene-01/lay-01"]
    assert AssetStore.referenced_by(direction, "cd" * 32) == []


# ---------------------------------------------------------------------------
# HTTP endpoints


class AssetServer:
    def __init__(self, tmp_path):
        self.project_manager = ProjectManager(cache_root=tmp_path / "cache")
        self._original_api = server_module.WEB_API
        server_module.WEB_API = WebApi(self.project_manager)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        conn = http.client.HTTPConnection(*self.server.server_address)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def close(self):
        server_module.WEB_API = self._original_api
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def seed_project(self):
        p_dir = self.project_manager.get_project_dir(PROJECT_ID)
        (p_dir / "rhythm.json").write_text(json.dumps(ABA_RHYTHM), encoding="utf-8")


@pytest.fixture
def asset_server(tmp_path):
    server = AssetServer(tmp_path)
    server.seed_project()
    yield server
    server.close()


def test_http_asset_round_trip(asset_server):
    base = f"/api/projects/{PROJECT_ID}/assets"
    status, _, body = asset_server.request("GET", base)
    assert status == 200 and json.loads(body)["assets"] == []

    image = png_bytes(6, 4)
    status, _, body = asset_server.request(
        "POST", base, body=image, headers={"Content-Type": "image/png", "X-Filename": "grain.png"}
    )
    assert status == 201
    entry = json.loads(body)["asset"]
    assert entry["mime"] == "image/png" and entry["width"] == 6 and entry["height"] == 4

    status, headers, fetched = asset_server.request("GET", f"{base}/{entry['asset_id']}")
    assert status == 200 and fetched == image
    assert headers["Cache-Control"].endswith("immutable")
    assert headers["Content-Type"] == "image/png"

    status, _, body = asset_server.request("GET", base)
    listing = json.loads(body)
    assert len(listing["assets"]) == 1 and listing["used_bytes"] == len(image)

    status, _, body = asset_server.request("DELETE", f"{base}/{entry['asset_id']}")
    assert status == 200 and json.loads(body)["deleted"] is True
    status, _, _ = asset_server.request("GET", f"{base}/{entry['asset_id']}")
    assert status == 404


def test_http_rejects_renamed_executable(asset_server):
    base = f"/api/projects/{PROJECT_ID}/assets"
    status, _, body = asset_server.request(
        "POST", base, body=b"MZ\x90\x00binary", headers={"X-Filename": "photo.png"}
    )
    assert status == 422
    assert json.loads(body)["error"] == "asset/unsupported-type"


def test_http_delete_in_use_requires_confirmation(asset_server):
    base = f"/api/projects/{PROJECT_ID}/assets"
    _, _, body = asset_server.request("POST", base, body=png_bytes(), headers={"X-Filename": "a.png"})
    asset_id = json.loads(body)["asset"]["asset_id"]

    # reference the asset from the direction sidecar
    p_dir = asset_server.project_manager.get_project_dir(PROJECT_ID)
    direction = {
        "schema": "beatscope-direction-1",
        "version": "0.12.0",
        "project_id": PROJECT_ID,
        "project_title": "Asset test",
        "source_rhythm_sha256": ABA_RHYTHM["source"]["sha256"],
        "composition": {"primary_ratio": "16:9", "width": 1920, "height": 1080, "background": "#F5F1E8"},
        "theme": {},
        "assets": [],
        "scenes": [
            {
                "id": "scene-01",
                "title": "Scene 01",
                "family": "section",
                "anchor": {"kind": "bars", "start_bar": 1, "end_bar": 5},
                "start_time": 0.0,
                "end_time": 4.0,
                "transition_out": "hold-through",
                "layers": [
                    {
                        "id": "lay-01",
                        "kind": "media-slice",
                        "label": "Still",
                        "visible": True,
                        "locked": False,
                        "opacity": 1.0,
                        "blend": "normal",
                        "transform": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0},
                        "props": {"src": f"asset:{asset_id}", "full": True},
                    }
                ],
                "responses": [],
            }
        ],
        "transitions": [],
        "diagnostics": {},
    }
    (p_dir / "direction.json").write_text(json.dumps(direction), encoding="utf-8")

    status, _, body = asset_server.request("DELETE", f"{base}/{asset_id}")
    assert status == 409
    payload = json.loads(body)
    assert payload["error"] == "asset/in-use" and payload["in_use"] == ["scene-01/lay-01"]

    status, _, body = asset_server.request("DELETE", f"{base}/{asset_id}?confirm=1")
    assert status == 200 and json.loads(body)["deleted"] is True


def test_http_put_direction_rejects_missing_asset(asset_server):
    direction_url = f"/api/projects/{PROJECT_ID}/direction"
    status, headers, body = asset_server.request("GET", direction_url)
    assert status == 200
    etag = headers["ETag"]
    doc = json.loads(body)
    doc["scenes"][0]["layers"].append({
        "id": "lay-asset",
        "kind": "media-slice",
        "label": "Missing",
        "visible": True,
        "locked": False,
        "opacity": 1.0,
        "blend": "normal",
        "transform": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "rotation": 0.0},
        "props": {"src": "asset:" + "ff" * 32, "full": True},
    })
    status, _, body = asset_server.request(
        "PUT",
        direction_url,
        body=json.dumps(doc).encode("utf-8"),
        headers={"Content-Type": "application/json", "If-Match": etag},
    )
    assert status == 422
    errors = json.loads(body)["errors"]
    assert any(e.startswith("direction/asset-missing") for e in errors)


def test_http_unknown_project_has_no_asset_surface(asset_server):
    status, _, _ = asset_server.request("GET", "/api/projects/" + "0" * 12 + "/assets")
    assert status == 404
