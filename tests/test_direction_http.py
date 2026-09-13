"""HTTP contract for direction/workspace sidecars (plan §6.1/§10.2).

Pins optimistic concurrency (428/409/422 with stable codes), lazy
derivation (X-Direction-Derived, sidecar persisted), ETag/304 behavior,
and the reconciliation flow two editors follow after a conflict.
"""
from __future__ import annotations

import copy
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import beatscope.server as server_module
from beatscope.project import ProjectManager
from beatscope.web_api import WebApi

ROOT = Path(__file__).resolve().parents[1]
ABA_RHYTHM = json.loads((ROOT / "tests" / "fixtures" / "visual" / "visual-aba.rhythm.json").read_text(encoding="utf-8"))
PROJECT_ID = "62bce8192088"
DIRECTION_URL = f"/api/projects/{PROJECT_ID}/direction"
WORKSPACE_URL = f"/api/projects/{PROJECT_ID}/workspace"


class DirectionServer:
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

    def seed_project(self, *, keep_segments: bool = True) -> dict:
        rhythm = copy.deepcopy(ABA_RHYTHM)
        if not keep_segments:
            rhythm["patterns"].pop("segments", None)
        p_dir = self.project_manager.get_project_dir(PROJECT_ID)
        (p_dir / "rhythm.json").write_text(json.dumps(rhythm), encoding="utf-8")
        return rhythm

    def sidecar(self) -> bytes:
        return (self.project_manager.get_project_dir(PROJECT_ID) / "direction.json").read_bytes()


def _get_doc(server: DirectionServer):
    status, headers, body = server.request("GET", DIRECTION_URL)
    assert status == 200
    return json.loads(body.decode("utf-8")), headers


def test_get_derives_persists_and_leaves_rhythm_untouched(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        rhythm = server.seed_project()
        rhythm_bytes = (server.project_manager.get_project_dir(PROJECT_ID) / "rhythm.json").read_bytes()
        status, headers, body = server.request("GET", DIRECTION_URL)
        assert status == 200
        assert headers["X-Direction-Derived"] == "segments"
        assert headers["ETag"].startswith('"') and headers["ETag"].endswith('"')
        document = json.loads(body.decode("utf-8"))
        assert document["schema"] == "beatscope-direction-1"
        assert [s["id"] for s in document["scenes"]] == ["scene-01", "scene-02", "scene-03"]
        assert document["scenes"][0]["anchor"] == {"kind": "bars", "start_bar": 1, "end_bar": 9}
        # sidecar holds exactly the served bytes
        assert server.sidecar() == body
        # Rhythm IR bytes never change during derivation
        assert (server.project_manager.get_project_dir(PROJECT_ID) / "rhythm.json").read_bytes() == rhythm_bytes
        assert "segments" in rhythm["patterns"]
    finally:
        server.close()


def test_get_304_via_if_none_match(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        server.seed_project()
        _, headers, _ = server.request("GET", DIRECTION_URL)
        etag = headers["ETag"]
        status, headers304, body = server.request("GET", DIRECTION_URL, headers={"If-None-Match": etag})
        assert status == 304
        assert body == b""
        assert headers304["ETag"] == etag
        assert "X-Direction-Derived" not in headers304
    finally:
        server.close()


def test_get_bars_fallback_marks_derivation_mode(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        server.seed_project(keep_segments=False)
        _, headers, body = server.request("GET", DIRECTION_URL)
        assert headers["X-Direction-Derived"] == "bars"
        document = json.loads(body.decode("utf-8"))
        assert document["scenes"][0]["title"] == "Scene 01"
    finally:
        server.close()


def test_get_unknown_project_404(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        status, _, body = server.request("GET", DIRECTION_URL)
        assert status == 404
        assert json.loads(body)["error"] == "Project not found"
    finally:
        server.close()


def test_put_without_if_match_428(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        server.seed_project()
        doc, _ = _get_doc(server)
        status, _, body = server.request("PUT", DIRECTION_URL, body=json.dumps(doc).encode())
        assert status == 428
        payload = json.loads(body)
        assert payload["error"] == "direction/precondition-required"
        assert payload["current_etag"].startswith('"')
    finally:
        server.close()


def test_put_stale_etag_409_with_current_etag(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        server.seed_project()
        doc, headers = _get_doc(server)
        status, _, body = server.request(
            "PUT", DIRECTION_URL,
            body=json.dumps(doc).encode(),
            headers={"If-Match": '"0000000000000000000000000000000000000000000000000000000000000000"'},
        )
        assert status == 409
        payload = json.loads(body)
        assert payload["error"] == "direction_conflict"
        assert payload["current_etag"] == headers["ETag"]
    finally:
        server.close()


def test_put_invalid_document_422_leaves_sidecar(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        server.seed_project()
        doc, headers = _get_doc(server)
        etag = headers["ETag"]
        doc["composition"]["primary_ratio"] = "4:3"
        status, _, body = server.request(
            "PUT", DIRECTION_URL, body=json.dumps(doc).encode(), headers={"If-Match": etag},
        )
        assert status == 422
        payload = json.loads(body)
        assert payload["error"] == "direction/invalid"
        assert any(code.startswith("direction/ratio") for code in payload["errors"])
        # the sidecar was not clobbered by the refused write
        _, headers_after, _ = server.request("GET", DIRECTION_URL)
        assert headers_after["ETag"] == etag
    finally:
        server.close()


def test_put_roundtrip_stores_canonical_bytes(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        server.seed_project()
        doc, headers = _get_doc(server)
        doc["project_title"] = "雾中之雾"
        status, _, body = server.request(
            "PUT", DIRECTION_URL, body=json.dumps(doc).encode(), headers={"If-Match": headers["ETag"]},
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "ok"
        status, headers2, body2 = server.request("GET", DIRECTION_URL)
        assert status == 200
        assert headers2["ETag"] == payload["etag"]
        stored = json.loads(body2.decode("utf-8"))
        assert stored["project_title"] == "雾中之雾"
        assert body2 == server.sidecar()
    finally:
        server.close()


def test_two_editor_reconciliation_flow(tmp_path):
    """Editor B refuses on stale ETag, re-reads and re-applies (§10.2)."""
    server = DirectionServer(tmp_path)
    try:
        server.seed_project()
        doc_a, headers = _get_doc(server)
        shared_etag = headers["ETag"]

        # editor A wins the write
        doc_a["scenes"][0]["title"] = "Editor A title"
        status_a, _, body_a = server.request(
            "PUT", DIRECTION_URL, body=json.dumps(doc_a).encode(), headers={"If-Match": shared_etag},
        )
        assert status_a == 200
        etag_a = json.loads(body_a)["etag"]

        # editor B still holds the shared pre-A ETag and is refused
        doc_b, _ = _get_doc(server)
        assert doc_b["scenes"][0]["title"] == "Editor A title"
        doc_b_stale = copy.deepcopy(doc_b)
        doc_b_stale["scenes"][0]["title"] = "Editor B title"
        status_b, _, body_b = server.request(
            "PUT", DIRECTION_URL, body=json.dumps(doc_b_stale).encode(), headers={"If-Match": shared_etag},
        )
        assert status_b == 409
        assert json.loads(body_b)["current_etag"] == etag_a

        # B re-reads on top of A and writes again
        doc_b_fresh, headers_b = _get_doc(server)
        assert headers_b["ETag"] == etag_a
        doc_b_fresh["scenes"][1]["title"] = "Editor B title"
        status_b2, _, body_b2 = server.request(
            "PUT", DIRECTION_URL, body=json.dumps(doc_b_fresh).encode(), headers={"If-Match": etag_a},
        )
        assert status_b2 == 200
        status_final, _, body_final = server.request("GET", DIRECTION_URL)
        assert status_final == 200
        titles = [s["title"] for s in json.loads(body_final)["scenes"]]
        assert titles[:2] == ["Editor A title", "Editor B title"]
    finally:
        server.close()


def test_workspace_roundtrip_is_separate_and_etag_guarded(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        rhythm = server.seed_project()
        status, headers, body = server.request("GET", WORKSPACE_URL)
        assert status == 200
        workspace = json.loads(body)
        assert workspace["schema"] == "beathi-workspace-1"
        assert workspace["source_rhythm_sha256"] == rhythm["source"]["sha256"]
        workspace["camera"] = {"x": 12.5, "y": -3.0, "zoom": 0.75}
        status, _, saved = server.request(
            "PUT", WORKSPACE_URL, json.dumps(workspace).encode(),
            {"Content-Type": "application/json", "If-Match": headers["ETag"]},
        )
        assert status == 200
        saved_etag = json.loads(saved)["etag"]
        status, _, conflict = server.request(
            "PUT", WORKSPACE_URL, json.dumps(workspace).encode(),
            {"Content-Type": "application/json", "If-Match": headers["ETag"]},
        )
        assert status == 409
        assert json.loads(conflict) == {"error": "workspace_conflict", "current_etag": saved_etag}
        workspace_path = server.project_manager.get_project_dir(PROJECT_ID) / "workspace.json"
        assert workspace_path.is_file()
        assert workspace_path.name != "direction.json"
    finally:
        server.close()


def test_corrupt_sidecar_is_refused_but_reconcilable(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        server.seed_project()
        # a corrupt sidecar (e.g. truncated write) still carries its ETag
        p_dir = server.project_manager.get_project_dir(PROJECT_ID)
        (p_dir / "direction.json").write_bytes(b'{"schema": "beatscope-direction-1", "scen')
        status, headers, body = server.request("GET", DIRECTION_URL)
        assert status == 422
        assert headers["X-Direction-Invalid"] == "1"
        assert headers["ETag"].startswith('"')
        payload = json.loads(body)
        assert payload["error"] == "direction/invalid"

        # recovery: PUT the derived document using the corrupt ETag
        rhythm = json.loads((p_dir / "rhythm.json").read_text(encoding="utf-8"))
        from beatscope.direction import build_direction_document, derive_scenes_from_structure
        scenes, _ = derive_scenes_from_structure(rhythm)
        fresh = build_direction_document(rhythm, scenes)
        status2, _, body2 = server.request(
            "PUT", DIRECTION_URL, body=json.dumps(fresh).encode(), headers={"If-Match": headers["ETag"]},
        )
        assert status2 == 200
        status3, headers3, _ = server.request("GET", DIRECTION_URL)
        assert status3 == 200
        assert "X-Direction-Invalid" not in headers3
    finally:
        server.close()


def test_put_unknown_project_404(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        status, _, body = server.request(
            "PUT", DIRECTION_URL, body=b"{}", headers={"If-Match": '"x"'},
        )
        assert status == 404
    finally:
        server.close()
