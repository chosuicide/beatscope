"""Consumer validation command tests (v0.9 plan sections 7, 8, and 15).

``validate-handoff`` and ``validate-consumer`` are read-only gates: the
frozen fixture must pass in both directory and ZIP form, hostile
archives (traversal, duplicates, case collisions, symlinks, oversized
members, smuggled audio) must fail safely before any JavaScript runs,
and the report/exit-code contract must stay stable. Node-dependent
checks reuse the same packaged probe the consumer receives.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from beatscope import consumer_validation as cv
from beatscope.consumer_contract import (
    MANIFEST_MEMBER,
    canonical_manifest_bytes,
    sha256_hex,
)
from beatscope.consumer_validation import (
    ConsumerUsageError,
    format_report,
    validate_consumer,
    validate_consumers_all,
    validate_handoff,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = REPO_ROOT / "examples" / "shared"
FIXTURE_DIR = SHARED_DIR / "fixture.beatscope"
CHECKPOINTS_PATH = SHARED_DIR / "checkpoints.json"

REPORT_KEYS = {"schema", "command", "target", "ok", "exit_code", "checks", "summary"}
CHECK_KEYS = {"name", "status", "required", "errors", "notes"}


def _fixture_members() -> dict[str, bytes]:
    return {
        path.relative_to(FIXTURE_DIR).as_posix(): path.read_bytes()
        for path in sorted(FIXTURE_DIR.rglob("*"))
        if path.is_file()
    }


def _zip_fixture(destination: Path, overrides: dict[str, bytes | None] | None = None) -> Path:
    members = _fixture_members()
    for name, value in (overrides or {}).items():
        if value is None:
            members.pop(name, None)
        else:
            members[name] = value
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return destination


def _copy_package(destination: Path) -> Path:
    shutil.copytree(FIXTURE_DIR, destination)
    shutil.copy2(CHECKPOINTS_PATH, destination.parent / "checkpoints.json")
    return destination


def _consumer_example(
    root: Path,
    name: str,
    *,
    playback: bool = False,
    package_path: str = "../packages/fixture.beatscope",
    sources: dict[str, str] | None = None,
) -> Path:
    example = root / name
    example.mkdir(parents=True, exist_ok=True)
    (example / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    for relative, text in (sources or {}).items():
        target = example / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (example / "beatscope-consumer.json").write_text(
        json.dumps(
            {
                "schema": "beatscope-consumer-1",
                "name": name,
                "framework": "vanilla",
                "entry_page": "index.html",
                "package_path": package_path,
                "clock": "audio.currentTime",
                "debug_hook": "__BEATSCOPE_CONSUMER__",
                "capabilities": {
                    "playback": playback,
                    "seek": playback,
                    "offline_frame": False,
                    "reduced_motion": True,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return example


def _status_by_name(report: dict) -> dict[str, dict]:
    return {check["name"]: check for check in report["checks"]}


def test_frozen_fixture_passes_every_check_in_directory_form():
    report = validate_handoff(FIXTURE_DIR)
    assert report["schema"] == "beatscope-consumer-report-1"
    assert report["command"] == "validate-handoff"
    assert report["exit_code"] == 0 and report["ok"] is True
    statuses = {check["name"]: check["status"] for check in report["checks"]}
    assert statuses == {
        "safety": "passed",
        "manifest": "passed",
        "integrity": "passed",
        "rhythm-map": "passed",
        "visual-artifacts": "passed",
        "node-probe": "passed",
        "checkpoints": "passed",
        "worker-smoke": "passed",
        "leakage": "passed",
    }
    summary = report["summary"]
    assert summary["failed"] == 0 and summary["unavailable"] == 0
    assert summary["total"] == len(report["checks"])


def test_report_shape_is_stable():
    report = validate_handoff(FIXTURE_DIR)
    assert set(report) == REPORT_KEYS
    for check in report["checks"]:
        assert set(check) == CHECK_KEYS
        assert check["status"] in ("passed", "failed", "skipped", "unavailable")
        assert isinstance(check["required"], bool)
    assert set(report["summary"]) == {"total", "passed", "failed", "skipped", "unavailable"}


def test_zip_form_passes_with_beside_checkpoints(tmp_path):
    zip_path = _zip_fixture(tmp_path / "fixture.beatscope.zip")
    shutil.copy2(CHECKPOINTS_PATH, tmp_path / "checkpoints.json")
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 0, format_report(report)
    statuses = _status_by_name(report)
    assert statuses["node-probe"]["status"] == "passed"
    assert statuses["checkpoints"]["status"] == "passed"
    assert any("zip:" in note for note in statuses["safety"]["notes"])


def test_zip_form_without_checkpoints_skips_determinism(tmp_path):
    zip_path = _zip_fixture(tmp_path / "fixture.beatscope.zip")
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 0
    skipped = _status_by_name(report)["checkpoints"]
    assert skipped["status"] == "skipped" and skipped["required"] is False
    assert "no checkpoints file" in skipped["notes"][0]


def test_zip_rejects_traversal_member_before_running_javascript(tmp_path, monkeypatch):
    zip_path = tmp_path / "evil.zip"
    members = _fixture_members()
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        archive.writestr("../evil.txt", b"smuggled")
    spawned = []
    original_run = subprocess.run
    monkeypatch.setattr(
        cv.subprocess,
        "run",
        lambda *args, **kwargs: spawned.append(args) or original_run(*args, **kwargs),
    )
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 1
    safety = _status_by_name(report)["safety"]
    assert "zip:unsafe-path:../evil.txt" in safety["errors"]
    assert spawned == [], "JavaScript must never run when archive safety fails"
    assert not (tmp_path / "evil.txt").exists()


def test_zip_rejects_duplicate_members(tmp_path):
    zip_path = tmp_path / "dup.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, data in _fixture_members().items():
            archive.writestr(name, data)
        archive.writestr("rhythm-map.json", b"duplicate")
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 1
    assert any(
        error.startswith("zip:duplicate-members:")
        for error in _status_by_name(report)["safety"]["errors"]
    )


def test_zip_rejects_case_colliding_members(tmp_path):
    zip_path = tmp_path / "case.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, data in _fixture_members().items():
            archive.writestr(name, data)
        archive.writestr("RHYTHM-MAP.JSON", b"colliding")
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 1
    assert any(
        error.startswith("zip:case-collision:")
        for error in _status_by_name(report)["safety"]["errors"]
    )


def test_zip_rejects_symlink_member(tmp_path):
    zip_path = tmp_path / "link.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, data in _fixture_members().items():
            archive.writestr(name, data)
        info = zipfile.ZipInfo("link.js")
        info.external_attr = (0o120777 << 16) | 0o0
        archive.writestr(info, "../../../target.js")
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 1
    assert any(
        error.startswith("zip:symlink-member:")
        for error in _status_by_name(report)["safety"]["errors"]
    )


def test_zip_enforces_member_count_and_size_caps(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "MAX_MEMBER_COUNT", 4)
    zip_path = tmp_path / "many.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for index in range(6):
            archive.writestr(f"member-{index}.txt", b"x")
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 1
    assert any("too-many-members" in error for error in _status_by_name(report)["safety"]["errors"])

    monkeypatch.setattr(cv, "MAX_MEMBER_BYTES", 16)
    zip_path = tmp_path / "big.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("big.bin", b"x" * 32)
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 1
    assert any("member-too-large" in error for error in _status_by_name(report)["safety"]["errors"])

    monkeypatch.setattr(cv, "MAX_MEMBER_BYTES", 32 * 1024 * 1024)
    monkeypatch.setattr(cv, "MAX_TOTAL_BYTES", 48)
    zip_path = tmp_path / "total.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for index in range(4):
            archive.writestr(f"part-{index}.bin", b"x" * 20)
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 1
    assert any("total-too-large" in error for error in _status_by_name(report)["safety"]["errors"])


def test_directory_rejects_symlink_member(tmp_path):
    package = tmp_path / "package"
    shutil.copytree(FIXTURE_DIR, package)
    link = package / "link.js"
    try:
        link.symlink_to(FIXTURE_DIR / "visual-state.js")
    except OSError:
        pytest.skip("symlink creation unavailable on this platform")
    report = validate_handoff(package)
    assert report["exit_code"] == 1
    assert any(
        error.startswith("dir:symlink-member:")
        for error in _status_by_name(report)["safety"]["errors"]
    )


def test_missing_member_fails_integrity_and_skips_node(tmp_path):
    zip_path = _zip_fixture(tmp_path / "missing.zip", overrides={"visual-state.js": None})
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 1
    statuses = _status_by_name(report)
    assert statuses["integrity"]["status"] == "failed"
    assert any("phantom-member" in error for error in statuses["integrity"]["errors"])
    assert statuses["manifest"]["status"] == "failed"
    assert statuses["node-probe"]["status"] == "skipped"
    assert statuses["worker-smoke"]["status"] == "skipped"


def test_tampered_manifest_still_gets_probe_diagnostics(tmp_path):
    zip_path = _zip_fixture(tmp_path / "tampered.zip")
    with zipfile.ZipFile(zip_path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members[MANIFEST_MEMBER])
    manifest["duration"] += 1.0
    rebuilt = tmp_path / "tampered-duration.zip"
    with zipfile.ZipFile(rebuilt, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, json.dumps(manifest).encode() if name == MANIFEST_MEMBER else data)
    report = validate_handoff(rebuilt)
    assert report["exit_code"] == 1
    statuses = _status_by_name(report)
    assert statuses["manifest"]["status"] == "failed"
    assert statuses["node-probe"]["status"] == "failed"
    assert any("duration" in error for error in statuses["node-probe"]["errors"])


def test_corrupted_member_fails_integrity(tmp_path):
    zip_path = tmp_path / "corrupt.zip"
    overrides = {"README.md": b"# rewritten\n"}
    members = _fixture_members()
    for name, value in overrides.items():
        members[name] = value
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 1
    integrity = _status_by_name(report)["integrity"]
    assert "integrity:sha256-mismatch:README.md" in integrity["errors"]


def test_tampered_checkpoints_are_caught_by_the_probe_replay(tmp_path):
    package = _copy_package(tmp_path / "fixture.beatscope")
    checkpoints = json.loads((package.parent / "checkpoints.json").read_text(encoding="utf-8"))
    checkpoints["times"][3] += 0.0005
    (package.parent / "checkpoints.json").write_text(json.dumps(checkpoints), encoding="utf-8")
    report = validate_handoff(package)
    assert report["exit_code"] == 1
    statuses = _status_by_name(report)
    replay_errors = statuses["checkpoints"]["errors"]
    assert any(error.startswith("replay:") for error in replay_errors), replay_errors


def test_worker_smoke_detects_a_broken_worker(tmp_path):
    package = _copy_package(tmp_path / "fixture.beatscope")
    worker_path = package / "worker-example.js"
    worker_path.write_text("export const broken = true;\n", encoding="utf-8")
    # Keep integrity green so the smoke test itself is what fails.
    manifest_path = package / MANIFEST_MEMBER
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["integrity"]["members"]["worker-example.js"] = sha256_hex(worker_path.read_bytes())
    manifest_path.write_bytes(canonical_manifest_bytes(manifest))
    report = validate_handoff(package)
    assert report["exit_code"] == 1
    statuses = _status_by_name(report)
    assert statuses["integrity"]["status"] == "passed"
    assert statuses["worker-smoke"]["status"] == "failed"


def test_smuggled_audio_member_fails_leakage(tmp_path):
    zip_path = _zip_fixture(tmp_path / "audio.zip", overrides={"song.wav": b"RIFF\x00\x00"})
    report = validate_handoff(zip_path)
    assert report["exit_code"] == 1
    leakage = _status_by_name(report)["leakage"]
    assert "leakage:audio-member:song.wav" in leakage["errors"]


def test_leakage_scan_flags_paths_and_usernames():
    members = {
        "clean.js": b"export const ok = 1;\n",
        "drive.js": b"const cache = 'D:\\\\Private\\\\song.wav';\n",
        "home.js": b"const base = '/home/dev/project';\n",
        "users.js": b"const base = '/Users/dev/project';\n",
        "name.js": f"const who = '{cv.getpass.getuser()}';\n".encode(),
        "track.wav": b"RIFF",
    }
    report = cv._leakage_check(members)
    assert report["status"] == "failed"
    assert "leakage:audio-member:track.wav" in report["errors"]
    assert "leakage:drive-path:drive.js" in report["errors"]
    assert "leakage:home-path:home.js" in report["errors"]
    assert "leakage:home-path:users.js" in report["errors"]
    assert "leakage:username:name.js" in report["errors"]
    assert not any(error.startswith("leakage:clean") for error in report["errors"])


def test_leakage_scan_ignores_url_colon_slash():
    report = cv._leakage_check({"clean.js": b"const url = 'https://example.com/a';\n"})
    assert report["status"] == "passed"


def test_probe_unavailable_without_node(tmp_path, monkeypatch):
    monkeypatch.setattr(cv.shutil, "which", lambda name: None)
    report = validate_handoff(FIXTURE_DIR)
    assert report["exit_code"] == 2
    statuses = _status_by_name(report)
    assert statuses["node-probe"]["status"] == "unavailable"
    assert statuses["node-probe"]["required"] is True
    assert statuses["worker-smoke"]["status"] == "unavailable"
    # node-probe, worker-smoke, and the checkpoints replay all need Node.
    assert report["summary"]["unavailable"] == 3


def test_usage_errors_for_missing_and_non_package_targets(tmp_path):
    with pytest.raises(ConsumerUsageError):
        validate_handoff(tmp_path / "does-not-exist.zip")
    plain = tmp_path / "plain.txt"
    plain.write_text("not a package", encoding="utf-8")
    with pytest.raises(ConsumerUsageError):
        validate_handoff(plain)


def test_materialization_never_overwrites_existing_files(tmp_path):
    destination = tmp_path / "package"
    destination.mkdir()
    (destination / "README.md").write_bytes(b"original")
    errors = cv._materialize_members({"README.md": b"new"}, destination)
    assert errors == ["materialize:exists:README.md"]
    assert (destination / "README.md").read_bytes() == b"original"


def test_child_env_drops_secrets(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("MY_API_TOKEN", "supersecret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "supersecret")
    monkeypatch.setenv("HOME", "/home/dev")
    env = cv._child_env()
    assert env["PATH"] == "/usr/bin"
    assert env["NODE_OPTIONS"] == ""
    assert "MY_API_TOKEN" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "HOME" not in env


def test_consumer_example_passes_all_layers(tmp_path):
    root = tmp_path / "examples"
    _copy_package(root / "packages" / "fixture.beatscope")
    example = _consumer_example(root, "canvas-fake")
    report = validate_consumer(example, validation_root=root)
    assert report["command"] == "validate-consumer"
    assert report["exit_code"] == 0, format_report(report)
    statuses = _status_by_name(report)
    assert statuses["declaration"]["status"] == "passed"
    assert statuses["handoff"]["status"] == "passed"
    assert statuses["node-probe"]["status"] == "passed"
    assert statuses["static"]["status"] == "passed"
    assert statuses["browser"]["status"] == "skipped"
    assert statuses["visual-snapshot"]["required"] is False


def test_consumer_rejects_package_path_escaping_the_validation_root(tmp_path):
    root = tmp_path / "examples"
    example = _consumer_example(root, "canvas-fake", package_path="../../elsewhere/fixture.beatscope")
    report = validate_consumer(example, validation_root=root)
    assert report["exit_code"] == 1
    declaration = _status_by_name(report)["declaration"]
    assert any("escapes-validation-root" in error for error in declaration["errors"])
    assert _status_by_name(report)["handoff"]["status"] == "skipped"


def test_consumer_rejects_invalid_declaration(tmp_path):
    root = tmp_path / "examples"
    example = _consumer_example(root, "canvas-fake")
    declaration = json.loads((example / "beatscope-consumer.json").read_text(encoding="utf-8"))
    del declaration["capabilities"]["playback"]
    (example / "beatscope-consumer.json").write_text(json.dumps(declaration), encoding="utf-8")
    report = validate_consumer(example, validation_root=root)
    assert report["exit_code"] == 1
    assert any(
        "capabilities.playback:must-be-a-boolean" in error
        for error in _status_by_name(report)["declaration"]["errors"]
    )


def test_consumer_static_layer_flags_copied_runtime_and_wall_clock(tmp_path):
    root = tmp_path / "examples"
    _copy_package(root / "packages" / "fixture.beatscope")
    example = _consumer_example(
        root,
        "canvas-fake",
        sources={
            "visual-state.js": "export const copy = 1;\n",
            "app.js": "import { x } from 'beatscope/web';\nconst now = Date.now();\n",
        },
    )
    report = validate_consumer(example, validation_root=root)
    assert report["exit_code"] == 1
    static = _status_by_name(report)["static"]
    assert "static:copied-runtime:visual-state.js" in static["errors"]
    assert "static:forbidden-import:app.js:1" in static["errors"]
    assert "static:Date.now:app.js:2" in static["errors"]


def test_consumer_playback_requires_the_browser_flag(tmp_path):
    root = tmp_path / "examples"
    _copy_package(root / "packages" / "fixture.beatscope")
    example = _consumer_example(root, "canvas-fake", playback=True)
    report = validate_consumer(example, validation_root=root)
    assert report["exit_code"] == 2
    browser = _status_by_name(report)["browser"]
    assert browser["status"] == "skipped" and browser["required"] is True
    assert any("--browser" in note for note in browser["notes"])


def test_consumer_browser_tooling_is_unavailable_not_passed(tmp_path):
    root = tmp_path / "examples"
    _copy_package(root / "packages" / "fixture.beatscope")
    example = _consumer_example(root, "canvas-fake", playback=True)
    report = validate_consumer(example, validation_root=root, browser=True)
    assert report["exit_code"] == 2
    browser = _status_by_name(report)["browser"]
    assert browser["status"] == "unavailable" and browser["required"] is True


def test_consumer_node_probe_fails_without_checkpoints(tmp_path):
    root = tmp_path / "examples"
    shutil.copytree(FIXTURE_DIR, root / "packages" / "fixture.beatscope")
    example = _consumer_example(root, "canvas-fake")
    report = validate_consumer(example, validation_root=root)
    assert report["exit_code"] == 1
    probe = _status_by_name(report)["node-probe"]
    assert "checkpoints:none-found-beside-package" in probe["errors"]


def test_consumers_all_aggregates_reports(tmp_path):
    root = tmp_path / "examples"
    _copy_package(root / "packages" / "fixture.beatscope")
    _consumer_example(root, "canvas-good")
    _consumer_example(root, "canvas-bad", package_path="../packages/missing.beatscope")
    report = validate_consumers_all(root, validation_root=root)
    assert report["all"] is True
    assert report["exit_code"] == 1
    assert report["summary"] == {"consumers": 2, "passed": 1, "failed": 1, "environment": 0}


def test_format_report_is_actionable():
    report = validate_handoff(FIXTURE_DIR)
    text = format_report(report)
    assert text.startswith("validate-handoff:")
    assert "[ok] node-probe" in text
    assert text.endswith("exit 0: all required checks passed")
