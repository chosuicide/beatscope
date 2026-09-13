"""Composition contract and concurrent HTTP saves, independent of legacy scenes."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from beatscope.composition import composition_bytes, new_composition, validate_composition
from tests.test_direction_http import DirectionServer, PROJECT_ID


def document():
    return new_composition(PROJECT_ID, "a" * 64, "My artwork")


@pytest.mark.parametrize("change", [
    lambda d: d.update(extra=True),
    lambda d: d.update(project_id="../invalid"),
    lambda d: d["artwork"].update(width=float("nan")),
    lambda d: d["artwork"].update(width=True),
    lambda d: d["artwork"].update(width=10 ** 500),
    lambda d: d.update(title="\ud800"),
    lambda d: d["background"].update(preset_id="not-a-solid-background"),
    lambda d: d.update(objects=[{}]),
])
def test_invalid_contract(change):
    doc = document()
    change(doc)
    assert validate_composition(doc)
    with pytest.raises(ValueError):
        composition_bytes(doc)


def test_canonical_round_trip_and_unicode_title():
    doc = new_composition(PROJECT_ID, "a" * 64, "🎵" * 200)
    assert not validate_composition(doc)
    assert len(doc["title"]) == 100
    assert composition_bytes(json.loads(composition_bytes(doc))) == composition_bytes(doc)


def test_http_round_trip_preconditions_and_racing_writers(tmp_path):
    server = DirectionServer(tmp_path)
    try:
        server.seed_project()
        folder = server.project_manager.get_project_dir(PROJECT_ID)
        original = (folder / "rhythm.json").read_bytes()
        route = f"/api/projects/{PROJECT_ID}/composition"
        status, headers, body = server.request("GET", route)
        assert status == 200
        doc = json.loads(body)
        assert not validate_composition(doc)
        assert server.request("PUT", route, body)[0] == 428
        assert server.request("PUT", route, body, {"If-Match": "*"})[0] == 409
        candidates = []
        for title in ("First editor", "Second editor"):
            edited = copy.deepcopy(doc)
            edited["title"] = title
            candidates.append(composition_bytes(edited))
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda b: server.request("PUT", route, b, {"If-Match": headers["ETag"]}), candidates))
        assert sorted(r[0] for r in results) == [200, 409]
        fresh = server.request("GET", route)
        assert fresh[2] in candidates
        assert fresh[1]["ETag"] != headers["ETag"]
        assert server.request("PUT", route, b"null", {"If-Match": fresh[1]["ETag"]})[0] == 422
        assert (folder / "rhythm.json").read_bytes() == original
        assert not (folder / "direction.json").exists()
        assert not (folder / "workspace.json").exists()
    finally:
        server.close()


def test_export_is_portable_and_hash_checked(tmp_path):
    import io
    import subprocess
    import zipfile
    from beatscope.assets import AssetStore
    from beatscope.composition_export import composition_archive
    from tests.test_direction_http import ABA_RHYTHM

    doc = new_composition(PROJECT_ID, ABA_RHYTHM["source"]["sha256"], "Portable")
    archive = composition_archive(doc, ABA_RHYTHM, AssetStore(tmp_path / "source", PROJECT_ID))
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        assert not any(name.endswith((".wav", ".mp3", ".audio")) for name in package.namelist())
        assert json.loads(package.read("composition.json")) == doc
        assert "timing/beatscope-package.json" in package.namelist()
        destination = tmp_path / "consumer"
        package.extractall(destination)
    result = subprocess.run(["node", "probe.mjs"], cwd=destination, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    (destination / "composition.json").write_text("{}")
    result = subprocess.run(["node", "probe.mjs"], cwd=destination, capture_output=True, text=True)
    assert result.returncode != 0
    assert "Integrity mismatch" in result.stderr
