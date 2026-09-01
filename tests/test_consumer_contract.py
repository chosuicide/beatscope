"""Consumer handoff contract tests (v0.9 plan sections 4, 6, 9, and 18.1).

The frozen fixture under ``examples/shared/`` is the pre-implementation
baseline: its package is a byte-exact v0.8.1 export, its checkpoints pin
factual frame state, and its lock content-addresses both. The manifest
validation is exercised with synthetic documents because the export does
not emit ``beatscope-package.json`` until the next commit deliberately
changes that behavior.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from beatscope.consumer_contract import (
    CHECKPOINT_SCHEMA,
    FIXTURE_LOCK_SCHEMA,
    MANIFEST_SCHEMA,
    canonical_manifest_bytes,
    is_sha256_hex,
    manifest_duration_errors,
    package_member_digest,
    sha256_hex,
    validate_checkpoints,
    validate_fixture_lock,
    validate_manifest,
    valid_member_path,
)
from beatscope.exports import generate_codex_export

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = REPO_ROOT / "examples" / "shared"
FIXTURE_DIR = SHARED_DIR / "fixture.beatscope"
CHECKPOINTS_PATH = SHARED_DIR / "checkpoints.json"
LOCK_PATH = SHARED_DIR / "fixture-lock.json"
GENERATOR_PATH = Path(__file__).parent / "fixtures" / "consumer" / "generate_consumer.py"

# The exact v0.8.1 handoff member set. Commit 2 adds the manifest, the
# Agent routing document, and the probe; this pin makes that delta visible
# and intentional instead of incidental.
V081_MEMBERS = frozenset(
    {
        "BEATSCOPE.md",
        "README.md",
        "SKILL.md",
        "beatscope-runtime.js",
        "rhythm-map.json",
        "scene-director.js",
        "visual-recipe-data.js",
        "visual-recipe.json",
        "visual-state.js",
        "visual-timeline-data.js",
        "visual-timeline.json",
        "worker-example.js",
        "references/schema.md",
    }
)

AUDIO_SUFFIXES = {".wav", ".wave", ".mp3", ".flac", ".ogg", ".m4a", ".aiff", ".aif", ".opus"}


def _node_missing() -> bool:
    return shutil.which("node") is None


def _fixture_members() -> dict[str, bytes]:
    return {
        path.relative_to(FIXTURE_DIR).as_posix(): path.read_bytes()
        for path in sorted(FIXTURE_DIR.rglob("*"))
        if path.is_file()
    }


def _rhythm_for_export() -> dict:
    fixture = Path(__file__).parent / "fixtures" / "runtime" / "characterization-project.json"
    rhythm = json.loads(fixture.read_text(encoding="utf-8"))
    rhythm["project_id"] = "0a1b2c3d4e5f"
    rhythm["source"]["display_name"] = "characterization.wav"
    return rhythm


# --------------------------------------------------------- frozen fixture


def test_frozen_fixture_matches_lock():
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert validate_fixture_lock(lock) == []
    members = _fixture_members()
    assert set(members) == V081_MEMBERS
    assert lock["package_sha256"] == package_member_digest(members)
    assert lock["rhythm_sha256"] == sha256_hex(members["rhythm-map.json"])
    assert lock["checkpoint_sha256"] == sha256_hex(CHECKPOINTS_PATH.read_bytes())
    checkpoints = json.loads(CHECKPOINTS_PATH.read_text(encoding="utf-8"))
    assert validate_checkpoints(checkpoints, members) == []


def test_checkpoints_cover_required_times():
    checkpoints = json.loads(CHECKPOINTS_PATH.read_text(encoding="utf-8"))
    timeline = json.loads((FIXTURE_DIR / "visual-timeline.json").read_text(encoding="utf-8"))
    times = checkpoints["times"]
    assert times[0] == 0.0
    assert abs(times[-1] - checkpoints["duration"]) < 1e-6
    for transition in timeline["transitions"]:
        boundary = float(transition["time"])
        assert round(boundary - 0.001, 9) in times
        assert round(boundary, 9) in times
        assert round(boundary + 0.001, 9) in times
    # A beat midpoint sits strictly between two beats.
    assert len(times) > 3 * len(timeline["transitions"]) + 2
    assert len(checkpoints["seek_sequence"]) >= 3


def test_frozen_package_exports_public_v08_functions():
    shim = (FIXTURE_DIR / "visual-state.js").read_text(encoding="utf-8")
    assert "export function getVisualState" in shim
    assert "export function getSceneState" in shim
    assert "export function getBeatScopeFrame" in shim


def test_v081_export_member_set_is_unchanged():
    archive = zipfile.ZipFile(__import__("io").BytesIO(generate_codex_export(_rhythm_for_export())))
    assert set(archive.namelist()) == V081_MEMBERS


def test_no_committed_audio_anywhere_under_examples():
    for path in (REPO_ROOT / "examples").rglob("*"):
        assert path.suffix.lower() not in AUDIO_SUFFIXES, f"audio must not enter Git: {path}"


@pytest.mark.skipif(_node_missing(), reason="node is required to render checkpoint frames")
def test_fixture_regeneration_is_byte_identical(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, str(GENERATOR_PATH), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr

    def tree(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): sha256_hex(path.read_bytes())
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    assert tree(tmp_path) == tree(SHARED_DIR)


# --------------------------------------------------------- manifest rules


def _synthetic_members() -> dict[str, bytes]:
    return {
        "BEATSCOPE.md": b"# handoff\n",
        "consumer-probe.js": b"export async function inspectPackage() {}\n",
        "rhythm-map.json": b'{"duration": 30.0}\n',
        "visual-recipe.json": b'{"schema": "beatscope-visual-recipe-1"}\n',
        "visual-state.js": b"export function getVisualState(time) { return time; }\n",
        "visual-timeline.json": b'{"schema": "beatscope-visual-timeline-1"}\n',
        "worker-example.js": b"onmessage = () => {};\n",
    }


def _synthetic_manifest(members: dict[str, bytes]) -> dict:
    return {
        "schema": MANIFEST_SCHEMA,
        "package_version": "0.9.0",
        "project_id": "0a1b2c3d4e5f",
        "duration": 30.0,
        "entry": "visual-state.js",
        "probe": "consumer-probe.js",
        "clock": {"unit": "seconds", "minimum": 0, "maximum": 30.0, "semantics": "media-time"},
        "capabilities": {
            "timing": True,
            "bands": True,
            "structure": True,
            "scenes": True,
            "module_worker": True,
        },
        "functions": {
            "frame": "getBeatScopeFrame",
            "timing": "getVisualState",
            "scene": "getSceneState",
        },
        "files": {
            "rhythm": "rhythm-map.json",
            "recipe": "visual-recipe.json",
            "timeline": "visual-timeline.json",
        },
        "integrity": {
            "algorithm": "sha256",
            "members": {name: sha256_hex(data) for name, data in members.items()},
        },
    }


def test_manifest_accepts_full_document():
    members = _synthetic_members()
    manifest = _synthetic_manifest(members)
    assert validate_manifest(manifest, members) == []


def test_manifest_shape_only_validation_without_members():
    manifest = _synthetic_manifest(_synthetic_members())
    # Without members, document-shape rules still apply but existence and
    # hash coverage cannot.
    assert validate_manifest(manifest) == []


def test_manifest_rejects_unsafe_paths():
    members = _synthetic_members()
    for bad in ("../escape.js", "/absolute.js", "C:\\evil.js", "https://evil.js", "..", "", "./here.js"):
        manifest = _synthetic_manifest(members)
        manifest["entry"] = bad
        errors = validate_manifest(manifest, members)
        assert any("entry:invalid-path" in error for error in errors), (bad, errors)


def test_manifest_rejects_capability_file_disagreement():
    members = _synthetic_members()
    base = _synthetic_manifest(members)

    # scenes true but the scene files are gone
    manifest = json.loads(json.dumps(base))
    manifest["files"].pop("recipe")
    manifest["integrity"]["members"].pop("visual-recipe.json")
    errors = validate_manifest(manifest, members)
    assert any("files.recipe-timeline:required-with-scenes" in error for error in errors)

    # scenes true but the frame function is gone
    manifest = json.loads(json.dumps(base))
    manifest["functions"].pop("frame")
    errors = validate_manifest(manifest, members)
    assert any("functions.frame:required-with-scenes" in error for error in errors)

    # scenes false while scene files and functions remain declared
    manifest = json.loads(json.dumps(base))
    manifest["capabilities"]["scenes"] = False
    errors = validate_manifest(manifest, members)
    assert any("files.recipe-timeline:requires-scenes" in error for error in errors)
    assert any("functions.frame:requires-scenes" in error for error in errors)

    # module_worker false while the worker member ships
    manifest = json.loads(json.dumps(base))
    manifest["capabilities"]["module_worker"] = False
    errors = validate_manifest(manifest, members)
    assert any("capabilities.module_worker:required-with-worker-example.js" in error for error in errors)

    # timing false while the rhythm file ships
    manifest = json.loads(json.dumps(base))
    manifest["capabilities"]["timing"] = False
    errors = validate_manifest(manifest, members)
    assert any("capabilities.timing:required-with-rhythm-file" in error for error in errors)

    # unknown function name
    manifest = json.loads(json.dumps(base))
    manifest["functions"]["vibe"] = "getVibe"
    errors = validate_manifest(manifest, members)
    assert any("functions.vibe:unknown" in error for error in errors)


def test_manifest_accepts_honest_legacy_reduction():
    """A minimal handoff declares only what it carries (plan section 4.1)."""
    members = {
        name: data
        for name, data in _synthetic_members().items()
        if name not in ("visual-recipe.json", "visual-timeline.json")
    }
    manifest = _synthetic_manifest(members)
    manifest["capabilities"]["scenes"] = False
    manifest["functions"] = {"timing": "getVisualState"}
    manifest["files"] = {"rhythm": "rhythm-map.json"}
    assert validate_manifest(manifest, members) == []


def test_manifest_rejects_missing_declared_members():
    members = _synthetic_members()
    manifest = _synthetic_manifest(members)
    reduced = {name: data for name, data in members.items() if name != "worker-example.js"}
    errors = validate_manifest(manifest, reduced)
    assert any("entry:missing-member" not in error for error in errors)
    assert any("integrity:worker-example.js:missing-member" in error for error in errors)


def test_manifest_rejects_bad_integrity():
    members = _synthetic_members()
    manifest = _synthetic_manifest(members)
    manifest["integrity"]["algorithm"] = "md5"
    assert any("integrity.algorithm" in error for error in validate_manifest(manifest, members))

    manifest = _synthetic_manifest(members)
    manifest["integrity"]["members"]["visual-state.js"] = "0" * 64
    assert any("hash-mismatch" in error for error in validate_manifest(manifest, members))

    manifest = _synthetic_manifest(members)
    manifest["integrity"]["members"]["visual-state.js"] = "zz" * 32
    assert any("invalid-digest" in error for error in validate_manifest(manifest, members))

    manifest = _synthetic_manifest(members)
    manifest["integrity"]["members"].pop("BEATSCOPE.md")
    assert any("uncovered" in error for error in validate_manifest(manifest, members))


def test_manifest_rejects_clock_and_duration_drift():
    members = _synthetic_members()
    manifest = _synthetic_manifest(members)
    manifest["clock"]["maximum"] = 29.0
    assert any("clock.maximum:duration-mismatch" in error for error in validate_manifest(manifest, members))

    manifest = _synthetic_manifest(members)
    manifest["duration"] = -1.0
    assert any("duration:negative" in error for error in validate_manifest(manifest, members))

    manifest = _synthetic_manifest(members)
    manifest["duration"] = 30.5
    rhythm_map = json.loads(members["rhythm-map.json"].decode("utf-8"))
    errors = manifest_duration_errors(manifest, rhythm_map)
    assert errors and "duration:mismatch" in errors[0]
    manifest["duration"] = 30.0
    assert manifest_duration_errors(manifest, rhythm_map) == []


def test_manifest_rejects_forbidden_provenance_keys():
    members = _synthetic_members()
    manifest = _synthetic_manifest(members)
    manifest["environment"] = {"generated_at": "2026-09-01T00:00:00Z", "hostname": "dev-box"}
    errors = validate_manifest(manifest, members)
    assert any("forbidden-key" in error and "generated_at" in error for error in errors)
    assert any("forbidden-key" in error and "hostname" in error for error in errors)


def test_manifest_requires_known_capability_flags():
    members = _synthetic_members()
    manifest = _synthetic_manifest(members)
    manifest["capabilities"].pop("scenes")
    assert any("capabilities.scenes:missing" in error for error in validate_manifest(manifest, members))
    manifest = _synthetic_manifest(members)
    manifest["capabilities"]["cloud_sync"] = "yes"
    assert any("not-boolean" in error for error in validate_manifest(manifest, members))


def test_canonical_manifest_bytes_are_deterministic():
    members = _synthetic_members()
    first = dict(reversed(list(_synthetic_manifest(members).items())))
    second = _synthetic_manifest(members)
    assert canonical_manifest_bytes(first) == canonical_manifest_bytes(second)
    raw = canonical_manifest_bytes(second)
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    assert json.loads(raw.decode("utf-8"))["schema"] == MANIFEST_SCHEMA


def test_package_digest_is_layout_independent():
    members = _synthetic_members()
    shuffled = dict(reversed(list(members.items())))
    assert package_member_digest(members) == package_member_digest(shuffled)
    altered = dict(members)
    altered["BEATSCOPE.md"] = b"# handoff changed\n"
    assert package_member_digest(members) != package_member_digest(altered)


def test_valid_member_path_rules():
    for good in ("visual-state.js", "references/schema.md", "a/b/c.json"):
        assert valid_member_path(good), good
    for bad in ("", "../up.js", "a/../b.js", "/root.js", "C:\\x.js", "http://x", "a//b", ".", None, 5):
        assert not valid_member_path(bad), bad


# ------------------------------------------------------ checkpoint rules


def test_checkpoints_reject_tampering():
    members = _fixture_members()
    checkpoints = json.loads(CHECKPOINTS_PATH.read_text(encoding="utf-8"))
    assert validate_checkpoints(checkpoints, members) == []

    tampered = dict(checkpoints)
    tampered["package_sha256"] = "f" * 64
    assert any("member-mismatch" in error for error in validate_checkpoints(tampered, members))

    tampered = dict(checkpoints)
    tampered["times"] = list(checkpoints["times"])
    tampered["times"][3] = 0.0  # breaks the ascending rule
    assert any("not-ascending" in error for error in validate_checkpoints(tampered, members))

    tampered = dict(checkpoints)
    tampered["times"] = [0.0, checkpoints["duration"] + 5.0]
    assert any("past-duration" in error for error in validate_checkpoints(tampered, members))

    tampered = dict(checkpoints)
    tampered["frames_sha256"] = "nope"
    assert any("frames_sha256" in error for error in validate_checkpoints(tampered, members))

    tampered = dict(checkpoints)
    tampered["schema"] = "something-else"
    assert any("schema" in error for error in validate_checkpoints(tampered, members))


def test_checkpoints_require_zero_start_and_seek_sequence():
    assert validate_checkpoints({"schema": CHECKPOINT_SCHEMA}) != []
    assert validate_checkpoints([]) != []


# ------------------------------------------------------------ fixture lock


def test_fixture_lock_rejects_tampering():
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert validate_fixture_lock(lock) == []
    tampered = dict(lock)
    tampered["package_sha256"] = "deadbeef"
    assert any("package_sha256" in error for error in validate_fixture_lock(tampered))
    tampered = dict(lock)
    tampered["schema"] = "wrong"
    assert any("schema" in error for error in validate_fixture_lock(tampered))


# ------------------------------------------------- evaluation rubric/schema


def test_rubric_weights_sum_to_one_hundred():
    rubric = json.loads((REPO_ROOT / "evaluations" / "agent-interoperability" / "rubric.json").read_text(encoding="utf-8"))
    assert rubric["schema"] == "beatscope-agent-rubric-1"
    weights = rubric["weights"]
    assert len(weights) == 8
    assert sum(weights.values()) == 100
    for category in rubric["categories"]:
        assert category["weight"] == weights[category["id"]]
        assert category["evidence"]
    assert rubric["human_notes"]["score_effect"] == 0


def test_run_record_schema_covers_the_frozen_shape():
    schema = json.loads((REPO_ROOT / "evaluations" / "agent-interoperability" / "schema.json").read_text(encoding="utf-8"))
    run = schema["$defs"]["agent-run"]
    assert run["properties"]["schema"]["const"] == "beatscope-agent-run-1"
    for field in ("agent", "model_family", "date", "task_sha256", "package_sha256", "framework", "attempts", "human_interventions", "validator"):
        assert field in run["required"], field
    assert schema["$defs"]["sha256"]["pattern"]


def test_sample_run_record_matches_schema_contract():
    schema = json.loads((REPO_ROOT / "evaluations" / "agent-interoperability" / "schema.json").read_text(encoding="utf-8"))
    run = schema["$defs"]["agent-run"]
    sample = {
        "schema": "beatscope-agent-run-1",
        "agent": "codex",
        "model_family": "recorded-by-operator",
        "date": "2026-09-01",
        "task_sha256": "a" * 64,
        "package_sha256": "b" * 64,
        "framework": "canvas",
        "attempts": 1,
        "human_interventions": 0,
        "validator": {"required": 18, "passed": 18, "failed": 0, "unavailable": 0},
    }
    # Minimal structural check without a jsonschema dependency: every
    # required field present, no additional properties beyond the schema.
    for field in run["required"]:
        assert field in sample
    allowed = set(run["properties"])
    assert set(sample) <= allowed
    assert is_sha256_hex(sample["task_sha256"])
