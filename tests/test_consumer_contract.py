"""Consumer handoff contract tests (v0.9 plan sections 4, 5, 6, 9, and 18.1).

The frozen fixture under ``examples/shared/`` is the shared ground truth:
its package is a byte-exact v0.9 export carrying the self-describing
contract (manifest, AGENT.md, probe), its checkpoints pin factual frame
state that the probe can replay bit for bit, and its lock content-addresses
both. The manifest validator is additionally exercised with synthetic
documents so rejection rules never depend on export behavior.
"""
from __future__ import annotations

import hashlib
import io
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
    MANIFEST_MEMBER,
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
from beatscope.exports import PACKAGE_VERSION, generate_codex_export

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = REPO_ROOT / "examples" / "shared"
FIXTURE_DIR = SHARED_DIR / "fixture.beatscope"
CHECKPOINTS_PATH = SHARED_DIR / "checkpoints.json"
LOCK_PATH = SHARED_DIR / "fixture-lock.json"
GENERATOR_PATH = Path(__file__).parent / "fixtures" / "consumer" / "generate_consumer.py"
PROBE_SOURCE_PATH = REPO_ROOT / "beatscope" / "runtime" / "consumer-probe.js"
PROBE_SIZE_BUDGET = 24 * 1024
AGENT_WORD_BUDGET = 900

# The v0.8.1 handoff member set, kept as the historical baseline; commit 2
# deliberately extends it with the self-describing contract members.
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
V090_CONTRACT_MEMBERS = frozenset({"beatscope-package.json", "AGENT.md", "consumer-probe.js"})
V090_MEMBERS = V081_MEMBERS | V090_CONTRACT_MEMBERS

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


def _unpacked_export() -> tuple[dict[str, bytes], dict]:
    """One fresh export, unpacked, with its parsed manifest."""
    archive = zipfile.ZipFile(io.BytesIO(generate_codex_export(_rhythm_for_export())))
    members = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}
    manifest = json.loads(members[MANIFEST_MEMBER].decode("utf-8"))
    return members, manifest


# --------------------------------------------------------- frozen fixture


def test_frozen_fixture_matches_lock():
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert validate_fixture_lock(lock) == []
    members = _fixture_members()
    assert set(members) == V090_MEMBERS
    content_digest = package_member_digest(
        {name: data for name, data in members.items() if name != MANIFEST_MEMBER}
    )
    assert lock["package_sha256"] == content_digest
    assert lock["rhythm_sha256"] == sha256_hex(members["rhythm-map.json"])
    assert lock["checkpoint_sha256"] == sha256_hex(CHECKPOINTS_PATH.read_bytes())
    checkpoints = json.loads(CHECKPOINTS_PATH.read_text(encoding="utf-8"))
    assert validate_checkpoints(checkpoints, members) == []
    manifest = json.loads(members[MANIFEST_MEMBER].decode("utf-8"))
    assert validate_manifest(manifest, members) == []
    assert manifest["package_version"] == PACKAGE_VERSION


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


def test_export_member_set_matches_v090_contract():
    """v0.8.1 members plus the self-describing contract, nothing else."""
    archive = zipfile.ZipFile(io.BytesIO(generate_codex_export(_rhythm_for_export())))
    assert set(archive.namelist()) == V090_MEMBERS


def test_export_manifest_is_valid_honest_and_deterministic():
    members, manifest = _unpacked_export()
    assert manifest["schema"] == MANIFEST_SCHEMA
    assert manifest["package_version"] == PACKAGE_VERSION
    assert validate_manifest(manifest, members) == []
    rhythm_map = json.loads(members["rhythm-map.json"].decode("utf-8"))
    assert manifest_duration_errors(manifest, rhythm_map) == []
    # Capabilities describe what the package actually carries.
    assert manifest["capabilities"]["scenes"] is ("visual-recipe.json" in members)
    assert manifest["capabilities"]["structure"] is bool(rhythm_map.get("patterns", {}).get("segments"))
    assert manifest["capabilities"]["module_worker"] is ("worker-example.js" in members)
    assert manifest["functions"]["frame"] == "getBeatScopeFrame"
    assert manifest["functions"]["timing"] == "getVisualState"
    # Two exports of the same input are byte-identical, manifest included.
    assert generate_codex_export(_rhythm_for_export()) == generate_codex_export(_rhythm_for_export())


def test_export_manifest_integrity_covers_every_member():
    members, manifest = _unpacked_export()
    listed = manifest["integrity"]["members"]
    assert set(listed) == set(members) - {MANIFEST_MEMBER}
    for name, digest in listed.items():
        assert digest == sha256_hex(members[name]), name
    assert MANIFEST_MEMBER not in listed


def test_export_manifest_and_agent_document_leak_nothing():
    members, _ = _unpacked_export()
    for name in (MANIFEST_MEMBER, "AGENT.md", "BEATSCOPE.md", "README.md"):
        text = members[name].decode("utf-8")
        assert "\\" not in text, f"{name} carries a backslash path"
        for drive in ("E:", "D:", "C:", "/home/", "/Users/", "/tmp/"):
            assert drive not in text, f"{name} leaks {drive}"
        for key in ("created_at", "generated_at", "timestamp", "hostname", "username"):
            assert key not in text, f"{name} leaks {key}"


def test_agent_document_routes_the_agent():
    members, manifest = _unpacked_export()
    agent = members["AGENT.md"].decode("utf-8")
    assert len(agent.split()) <= AGENT_WORD_BUDGET
    # Plan section 5: the routing anchors every Agent needs.
    for anchor in (
        "beatscope-package.json",
        manifest["functions"]["frame"],
        "audio.currentTime",
        "frame / fps",
        "re-analyse",
        "seek",
        "reduced motion",
        "consumer-probe.js",
        "frame.timing",
        "frame.scene",
        "instruments",
        "SKILL.md",
    ):
        assert anchor in agent, f"AGENT.md is missing {anchor!r}"
    assert "import { getBeatScopeFrame } from './visual-state.js';" in agent


def test_probe_ships_in_package_and_stays_dependency_free():
    members, manifest = _unpacked_export()
    assert members["consumer-probe.js"] == PROBE_SOURCE_PATH.read_bytes()
    source = members["consumer-probe.js"].decode("utf-8")
    assert len(members["consumer-probe.js"]) <= PROBE_SIZE_BUDGET
    for export_name in ("inspectPackage", "canonicalFrame", "runCheckpointSuite", "assertSeekDeterminism"):
        assert f"export function {export_name}" in source or f"export async function {export_name}" in source
    # Dependency-free: no static imports; node builtins only behind the CLI guard.
    assert "\nimport " not in source and not source.startswith("import ")
    assert manifest["probe"] == "consumer-probe.js"
    assert manifest["entry"] == "visual-state.js"


def test_legacy_export_honestly_reduces_capabilities():
    minimal = {
        "schema_version": "3.0",
        "source": {"display_name": "hand-built.wav", "duration": 12.5, "sample_rate": 44100, "channels": 2},
        "tempo": {"global_bpm": 100.0},
        "grid": {"origin": 0.0, "time_signature": [4, 4], "default_subdivision": 16},
        "beats": [{"time": index * 0.6, "strength": 1.0} for index in range(21)],
    }
    archive = zipfile.ZipFile(io.BytesIO(generate_codex_export(minimal)))
    members = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}
    manifest = json.loads(members[MANIFEST_MEMBER].decode("utf-8"))
    assert manifest["capabilities"]["scenes"] is False
    assert manifest["capabilities"]["structure"] is False
    assert set(manifest["functions"]) == {"timing"}
    assert set(manifest["files"]) == {"rhythm"}
    assert "visual-recipe.json" not in members and "scene-director.js" not in members
    assert validate_manifest(manifest, members) == []
    # A map without a project id gets a stable content-derived one.
    assert manifest["project_id"] and len(manifest["project_id"]) == 12


@pytest.mark.skipif(_node_missing(), reason="node is required to run the packaged probe")
def test_probe_cli_passes_on_unpacked_fixture(tmp_path: Path):
    result = subprocess.run(
        [
            "node",
            str(FIXTURE_DIR / "consumer-probe.js"),
            str(FIXTURE_DIR),
            "--checkpoints",
            str(CHECKPOINTS_PATH),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["errors"] == []
    assert report["checkpoints"]["ok"] is True
    assert report["checkpoints"]["times"] == len(json.loads(CHECKPOINTS_PATH.read_text(encoding="utf-8"))["times"])


@pytest.mark.skipif(_node_missing(), reason="node is required to run the packaged probe")
def test_probe_cli_detects_manifest_tampering(tmp_path: Path):
    tampered_dir = tmp_path / "fixture.beatscope"
    shutil.copytree(FIXTURE_DIR, tampered_dir)
    manifest_path = tampered_dir / MANIFEST_MEMBER
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["duration"] = manifest["duration"] + 1.0
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = subprocess.run(
        ["node", str(tampered_dir / "consumer-probe.js"), str(tampered_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(tmp_path),
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert any("duration:mismatch" in error for error in report["errors"])


def test_no_committed_audio_anywhere_under_examples():
    # The invariant is about what enters Git, so walk the tracked file
    # list: ignored trees (node_modules and friends) are not violations.
    tracked = subprocess.run(
        ["git", "ls-files", "examples"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert tracked, "examples must contain committed files"
    for relative in tracked:
        assert Path(relative).suffix.lower() not in AUDIO_SUFFIXES, f"audio must not enter Git: {relative}"


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


# ------------------------------------------------- evaluation replay gates


def _eval_module(filename: str, name: str):
    """Load an evaluation helper module (directory names are not packages)."""
    import importlib.util

    path = REPO_ROOT / "evaluations" / "agent-interoperability" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EVAL_DIR = REPO_ROOT / "evaluations" / "agent-interoperability"


def test_frozen_task_stays_stable_and_routable():
    task = (EVAL_DIR / "TASK.md").read_text(encoding="utf-8")
    # Plan section 13.1: the frozen instructions, byte for byte.
    for anchor in (
        "Build an original audio-reactive visual using the supplied BeatScope package.",
        "Use the package's frame API as the only musical timing source.",
        "Support play,\npause, seek, replay, and reduced motion.",
        "Do not copy the BeatScope player.",
        "Run the supplied validation command and report any unsupported requirement.",
        "<TARGET_FRAMEWORK>",
    ):
        assert anchor in task, f"TASK.md lost anchor {anchor!r}"
    digest = hashlib.sha256((EVAL_DIR / "TASK.md").read_bytes()).hexdigest()
    assert is_sha256_hex(digest)


def test_run_index_is_schema_shaped_and_hash_pinned():
    index = json.loads((EVAL_DIR / "runs" / "index.json").read_text(encoding="utf-8"))
    assert index["schema"] == "beatscope-agent-run-index-1"
    assert isinstance(index["runs"], list)
    task_sha256 = hashlib.sha256((EVAL_DIR / "TASK.md").read_bytes()).hexdigest()
    lock = json.loads((REPO_ROOT / "examples" / "shared" / "fixture-lock.json").read_text(encoding="utf-8"))
    for run in index["runs"]:
        assert run["schema"] == "beatscope-agent-run-1"
        assert run["task_sha256"] == task_sha256, "run record predates the frozen task"
        assert run["package_sha256"] == lock["package_sha256"], "run record predates the frozen fixture"
        assert run["validator"]["failed"] >= 0


def test_recorder_rejects_private_or_underdocumented_records():
    recorder = _eval_module("record_run.py", "beatscope_record_run")
    record = {
        "schema": "beatscope-agent-run-1",
        "agent": "codex",
        "model_family": "recorded-by-operator",
        "date": "2026-09-01",
        "task_sha256": "a" * 64,
        "package_sha256": "b" * 64,
        "framework": "canvas",
        "attempts": 1,
        "human_interventions": 0,
        "validator": {"required": 6, "passed": 6, "failed": 0, "unavailable": 0},
    }
    assert recorder.structural_errors(dict(record)) == []

    smuggled = dict(record)
    smuggled["hidden_prompt"] = "the whole private transcript"
    assert any("forbidden-keys" in error for error in recorder.structural_errors(smuggled))

    credentialed = dict(record)
    credentialed["artistic_note"] = "used key sk-abc123 during the run"
    assert recorder.secret_errors(credentialed), "credential-shaped text must be rejected"

    undocumented = dict(record)
    undocumented["human_interventions"] = 2
    assert any("human_repairs" in error for error in recorder.structural_errors(undocumented))


def test_recorder_writes_append_only_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    recorder = _eval_module("record_run.py", "beatscope_record_run_writes")
    monkeypatch.setattr(recorder, "RUNS_DIR", tmp_path / "runs")
    record = {
        "schema": "beatscope-agent-run-1",
        "agent": "codex",
        "model_family": "recorded-by-operator",
        "date": "2026-09-01",
        "task_sha256": hashlib.sha256((EVAL_DIR / "TASK.md").read_bytes()).hexdigest(),
        "package_sha256": json.loads((REPO_ROOT / "examples" / "shared" / "fixture-lock.json").read_text(encoding="utf-8"))[
            "package_sha256"
        ],
        "framework": "canvas",
        "attempts": 1,
        "human_interventions": 0,
        "validator": {"required": 6, "passed": 6, "failed": 0, "unavailable": 0},
    }
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(record), encoding="utf-8")

    assert recorder.main(["--record", str(candidate)]) == 2  # review not confirmed
    assert recorder.main(["--record", str(candidate), "--confirm-review"]) == 0
    index = json.loads((tmp_path / "runs" / "index.json").read_text(encoding="utf-8"))
    assert len(index["runs"]) == 1
    assert index["runs"][0]["framework"] == "canvas"
    # Evidence is append-only: the same record never overwrites itself.
    assert recorder.main(["--record", str(candidate), "--confirm-review"]) == 1


def test_checked_in_reports_are_normalized_and_honest():
    reports_dir = EVAL_DIR / "reports"
    expected = {
        "handoff-fixture.json",
        "canvas-particles.json",
        "threejs-geometry.json",
        "remotion-composition.json",
    }
    assert {path.name for path in reports_dir.glob("*.json")} == expected

    handoff = json.loads((reports_dir / "handoff-fixture.json").read_text(encoding="utf-8"))
    assert handoff["schema"] == "beatscope-consumer-report-1"
    assert handoff["ok"] is True and handoff["exit_code"] == 0
    assert handoff["target"] == "examples/shared/fixture.beatscope"

    for name in ("canvas-particles", "threejs-geometry", "remotion-composition"):
        report = json.loads((reports_dir / f"{name}.json").read_text(encoding="utf-8"))
        assert report["target"] == f"examples/{name}"
        status = {check["name"]: check["status"] for check in report["checks"]}
        for layer in ("declaration", "handoff", "node-probe", "static"):
            assert status[layer] == "passed", (name, layer)
        assert report["summary"]["failed"] == 0
        requested = "offline" if name == "remotion-composition" else "browser"
        irrelevant = "browser" if requested == "offline" else "offline"
        assert status[requested] == "passed"
        assert status[irrelevant] == "skipped"


@pytest.mark.skipif(_node_missing(), reason="node is required to replay probe-backed reports")
def test_checked_in_reports_replay_byte_identically():
    """CI's replay gate: regenerated evidence equals the checked-in bytes."""
    recorder = _eval_module("record_reports.py", "beatscope_record_reports")
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        fresh_dir = Path(tmp) / "reports"
        fresh_dir.mkdir()
        for name, report in recorder.collect_reports():
            fresh_dir.joinpath(name).write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        for path in sorted((EVAL_DIR / "reports").glob("*.json")):
            assert path.read_bytes() == fresh_dir.joinpath(path.name).read_bytes(), path.name


def test_conformance_table_replays_from_checked_in_evidence():
    generator = _eval_module("generate_conformance.py", "beatscope_generate_conformance")
    regenerated = generator.build_markdown()
    checked_in = (EVAL_DIR / "conformance.md").read_text(encoding="utf-8")
    assert regenerated == checked_in
    # With zero recorded runs the cross-Agent claim must stay pending.
    assert "PENDING" in regenerated


def test_ci_never_calls_remote_agents():
    """Plan section 13: CI replays checked-in outputs, never model APIs."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for forbidden in (
        "api.openai.com",
        "api.anthropic.com",
        "api.deepseek.com",
        "api.mistral.ai",
        "openrouter.ai",
        "generativelanguage.googleapis.com",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "run-agent",
    ):
        assert forbidden not in workflow, f"CI must not reference {forbidden}"
