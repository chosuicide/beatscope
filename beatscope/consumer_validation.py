"""Read-only validation for BeatScope handoffs and visual consumers (v0.9).

Two commands back this module:

``validate-handoff`` checks one portable package (ZIP or unpacked
directory) end to end: archive safety, manifest, integrity, rhythm and
visual documents, the packaged probe running under Node, checkpoint
determinism, the declared module worker, and a leakage scan. It never
extracts over existing files: ZIP members are read into memory, checked,
and only then written into a fresh temporary directory.

``validate-consumer`` layers consumer-specific checks on top of a
handoff validation: the ``beatscope-consumer-1`` declaration, static
source hygiene, and (for interactive examples) the browser debug hook.
Static checking is deliberately narrow — text patterns can prove a
copied runtime or a wall-clock call, not arbitrary behaviour.

Reports share the stable ``beatscope-consumer-report-1`` schema. Exit
codes: ``0`` every required check passed, ``1`` contract failure,
``2`` invalid command or environment (including a required probe that
is unavailable because Node is missing). Unavailable is never passed.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from beatscope.consumer_contract import (
    CHECKPOINT_SCHEMA,
    ENTRY_MEMBER,
    MANIFEST_MEMBER,
    PROBE_MEMBER,
    RHYTHM_MEMBER,
    RECIPE_MEMBER,
    TIMELINE_MEMBER,
    WORKER_MEMBER,
    manifest_duration_errors,
    package_member_digest,
    sha256_hex,
    valid_member_path,
    validate_checkpoints,
    validate_manifest,
)
from beatscope.exports import (
    _probe_source,
    _runtime_source,
    _scene_director_source,
    _visual_data_module,
    _visual_state_source,
    _worker_example_source,
)
from beatscope.visual_recipe_schema import (
    validate_visual_recipe,
    validate_visual_timeline,
)

REPORT_SCHEMA = "beatscope-consumer-report-1"
DECLARATION_SCHEMA = "beatscope-consumer-1"
DEBUG_HOOK_NAME = "__BEATSCOPE_CONSUMER__"
DECLARATION_MEMBER = "beatscope-consumer.json"

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_UNAVAILABLE = "unavailable"

# Safety caps (plan section 15). A legitimate package stays far below
# these; the caps only turn hostile archives into fast failures.
MAX_MEMBER_COUNT = 64
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024

NODE_TIMEOUT_SECONDS = 60.0
WORKER_TIMEOUT_SECONDS = 30.0

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"

_AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".aiff"})
_SOURCE_SUFFIXES = frozenset({".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".html"})
_SKIPPED_SOURCE_DIRS = frozenset({"node_modules", ".git", "dist", "build", ".wrangler"})

# A drive letter must not sit inside a URL scheme ("https://" keeps its
# colon preceded by letters), hence the lookbehind.
_DRIVE_PATH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
_UNIX_HOME_RE = re.compile(r"/(?:home|Users)/")
_FORBIDDEN_IMPORT_RE = re.compile(r"beatscope/web")
_DATE_NOW_RE = re.compile(r"\bDate\.now\s*\(")
_PERFORMANCE_NOW_RE = re.compile(r"\bperformance\.now\s*\(")

# A copied runtime is a fidelity hazard: consumers must import the
# package's own modules so checkpoint parity means something.
_RUNTIME_FINGERPRINT_FILES = frozenset(
    {
        "beatscope-runtime.js",
        "visual-state.js",
        "scene-director.js",
        "worker-example.js",
        "consumer-probe.js",
        "visual-recipe-data.js",
        "visual-timeline-data.js",
    }
)

# The packaged worker targets browser module Workers (`self.onmessage` /
# `self.postMessage`). Under Node's worker_threads a tiny bootstrap maps
# that exact surface onto parentPort before the worker module evaluates.
_WORKER_SMOKE_BOOTSTRAP = '''// BeatScope browser-Worker shim for Node worker_threads (generated).
import { parentPort, workerData } from 'node:worker_threads';
import { pathToFileURL } from 'node:url';

if (typeof globalThis.self === 'undefined') {
  let handler = null;
  globalThis.self = {
    get onmessage() { return handler; },
    set onmessage(value) { handler = value; },
    postMessage: (message) => parentPort.postMessage(message),
  };
  parentPort.on('message', (message) => {
    if (typeof handler === 'function') handler({ data: message });
  });
}
await import(pathToFileURL(workerData.target).href);
'''

_WORKER_SMOKE_RUNNER = '''// BeatScope worker smoke runner (generated; isolated temp cwd).
import { Worker } from 'node:worker_threads';

// Worker() needs an absolute path, not a file:// URL.
const worker = new Worker(process.argv[2], { type: 'module', workerData: { target: process.argv[3] } });
const timeoutMs = Number(process.argv[4] || 15000);
const timer = setTimeout(() => {
  console.error('worker smoke: timeout');
  process.exit(3);
}, timeoutMs);
worker.on('message', (message) => {
  if (!message || message.id !== 'beatscope-smoke') return;
  clearTimeout(timer);
  const timing = message.timing && typeof message.timing === 'object' ? message.timing : null;
  const ok = message.time === 0 && timing !== null && Number.isFinite(timing.beatPhase);
  process.stdout.write(JSON.stringify({ ok, has_timing: timing !== null, has_scene: message.scene !== undefined }));
  process.exit(ok ? 0 : 1);
});
worker.on('error', (error) => {
  clearTimeout(timer);
  console.error(`worker smoke: ${String(error)}`);
  process.exit(1);
});
worker.postMessage({ id: 'beatscope-smoke', time: 0 });
'''


class ConsumerUsageError(ValueError):
    """Invalid command or environment for a validation run (exit 2)."""


def _check(
    name: str,
    status: str,
    *,
    errors: list[str] | None = None,
    notes: list[str] | None = None,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "required": required,
        "errors": list(errors or []),
        "notes": list(notes or []),
    }


def _failed_check(name: str, errors: list[str], **kwargs: Any) -> dict[str, Any]:
    return _check(name, STATUS_FAILED, errors=errors, **kwargs)


def _summarize(checks: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(checks), "passed": 0, "failed": 0, "skipped": 0, "unavailable": 0}
    for check in checks:
        summary[check["status"]] = summary.get(check["status"], 0) + 1
    return summary


def _exit_code(checks: list[dict[str, Any]]) -> int:
    if any(check["status"] == STATUS_FAILED for check in checks):
        return 1
    if any(
        check["required"] and check["status"] in (STATUS_SKIPPED, STATUS_UNAVAILABLE)
        for check in checks
    ):
        return 2
    return 0


def _build_report(command: str, target: Path, checks: list[dict[str, Any]]) -> dict[str, Any]:
    exit_code = _exit_code(checks)
    return {
        "schema": REPORT_SCHEMA,
        "command": command,
        "target": str(target),
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "checks": checks,
        "summary": _summarize(checks),
    }


def _child_env() -> dict[str, str]:
    """A filtered environment for probe subprocesses: no secrets forwarded."""
    dropped_markers = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "KEY", "AWS_", "AZURE_", "GOOGLE_", "API_")
    env: dict[str, str] = {}
    for name, value in os.environ.items():
        upper = name.upper()
        if name in ("PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "LANG", "LC_ALL"):
            env[name] = value
            continue
        if any(marker in upper for marker in dropped_markers):
            continue
    env["NODE_OPTIONS"] = ""
    return env


def _load_zip_members(zip_path: Path) -> tuple[dict[str, bytes] | None, list[str], list[str]]:
    """Read a ZIP entirely into memory after path and size safety checks."""
    errors: list[str] = []
    notes: list[str] = []
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as error:
        return None, [f"zip:unreadable:{error}"], notes
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            errors.append(f"zip:duplicate-members:{','.join(duplicates)}")
        seen_lower: dict[str, str] = {}
        for name in names:
            lower = name.lower()
            if lower in seen_lower and seen_lower[lower] != name:
                errors.append(f"zip:case-collision:{seen_lower[lower]}|{name}")
            seen_lower[lower] = name
        total_bytes = 0
        members: dict[str, bytes] = {}
        for info in infos:
            name = info.filename
            if name.endswith("/"):
                continue
            if not valid_member_path(name):
                errors.append(f"zip:unsafe-path:{name}")
                continue
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                errors.append(f"zip:symlink-member:{name}")
                continue
            if len(members) >= MAX_MEMBER_COUNT:
                errors.append(f"zip:too-many-members:cap {MAX_MEMBER_COUNT}")
                return None, errors, notes
            if info.file_size > MAX_MEMBER_BYTES:
                errors.append(f"zip:member-too-large:{name}:{info.file_size}")
                continue
            total_bytes += info.file_size
            if total_bytes > MAX_TOTAL_BYTES:
                errors.append(f"zip:total-too-large:cap {MAX_TOTAL_BYTES}")
                return None, errors, notes
            members[name] = archive.read(info)
        if errors:
            return None, errors, notes
        notes.append(f"zip:{len(members)} members read into memory")
        return members, errors, notes


def _load_directory_members(root: Path) -> tuple[dict[str, bytes] | None, list[str], list[str]]:
    """Walk an unpacked package; the same safety rules apply as for ZIPs."""
    errors: list[str] = []
    notes: list[str] = []
    members: dict[str, bytes] = {}
    seen_lower: dict[str, str] = {}
    entries = sorted(path for path in root.rglob("*") if path.is_file())
    for path in entries:
        if path.is_symlink():
            errors.append(f"dir:symlink-member:{path.name}")
            continue
        relative = path.relative_to(root).as_posix()
        if not valid_member_path(relative):
            errors.append(f"dir:unsafe-path:{relative}")
            continue
        lower = relative.lower()
        if lower in seen_lower and seen_lower[lower] != relative:
            errors.append(f"dir:case-collision:{seen_lower[lower]}|{relative}")
        seen_lower[lower] = relative
        try:
            data = path.read_bytes()
        except OSError as error:
            errors.append(f"dir:unreadable:{relative}:{error}")
            continue
        if len(data) > MAX_MEMBER_BYTES:
            errors.append(f"dir:member-too-large:{relative}:{len(data)}")
            continue
        total = sum(len(value) for value in members.values()) + len(data)
        if total > MAX_TOTAL_BYTES:
            errors.append(f"dir:total-too-large:cap {MAX_TOTAL_BYTES}")
            return None, errors, notes
        members[relative] = data
    if len(members) > MAX_MEMBER_COUNT:
        errors.append(f"dir:too-many-members:cap {MAX_MEMBER_COUNT}")
        return None, errors, notes
    if errors:
        return None, errors, notes
    notes.append(f"directory:{len(members)} members read in place")
    return members, errors, notes


def _materialize_members(members: Mapping[str, bytes], destination: Path) -> list[str]:
    """Write validated members into a fresh temp directory (never over existing files)."""
    errors: list[str] = []
    root = destination.resolve()
    for name, data in members.items():
        candidate = destination.joinpath(*PurePosixPath(name).parts)
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            errors.append(f"materialize:escaped-root:{name}")
            continue
        if candidate.exists():
            errors.append(f"materialize:exists:{name}")
            continue
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(data)
    return errors


def _parse_manifest(members: Mapping[str, bytes] | None) -> tuple[dict[str, Any] | None, list[str]]:
    if members is None or MANIFEST_MEMBER not in members:
        return None, [f"manifest:missing-member:{MANIFEST_MEMBER}"]
    try:
        manifest = json.loads(members[MANIFEST_MEMBER].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, [f"manifest:unreadable:{error}"]
    if not isinstance(manifest, dict):
        return None, ["manifest:not-an-object"]
    return manifest, []


def _manifest_check(members: Mapping[str, bytes] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    manifest, errors = _parse_manifest(members)
    skipped = (members is None, "skipped: package safety failed")
    if members is None:
        return _check("manifest", STATUS_SKIPPED, notes=[skipped[1]], required=True), None
    if manifest is not None:
        errors.extend(validate_manifest(manifest, members))
        rhythm_errors: list[str] = []
        if RHYTHM_MEMBER in members:
            try:
                rhythm_map = json.loads(members[RHYTHM_MEMBER].decode("utf-8"))
                rhythm_errors = manifest_duration_errors(manifest, rhythm_map)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                rhythm_errors.append(f"rhythm-map:unreadable:{error}")
            errors.extend(rhythm_errors)
        else:
            errors.append(f"manifest:missing-member:{RHYTHM_MEMBER}")
    else:
        errors.extend(_parse_manifest(members)[1])
    status = STATUS_PASSED if not errors else STATUS_FAILED
    return _check("manifest", status, errors=errors), manifest


def _integrity_check(manifest: dict[str, Any] | None, members: Mapping[str, bytes] | None) -> dict[str, Any]:
    if members is None or manifest is None:
        return _check("integrity", STATUS_SKIPPED, notes=["skipped: manifest unavailable"], required=True)
    errors: list[str] = []
    declared = manifest.get("integrity")
    if not isinstance(declared, dict) or declared.get("algorithm") != "sha256":
        errors.append("integrity:algorithm-must-be-sha256")
        declared_members: Mapping[str, Any] = {}
    else:
        declared_members = declared.get("members") if isinstance(declared.get("members"), dict) else {}
    actual_names = {name for name in members if name != MANIFEST_MEMBER}
    declared_names = set(declared_members)
    for name in sorted(actual_names - declared_names):
        errors.append(f"integrity:uncovered-member:{name}")
    for name in sorted(declared_names - actual_names):
        errors.append(f"integrity:phantom-member:{name}")
    for name in sorted(actual_names & declared_names):
        expected = declared_members.get(name)
        actual = sha256_hex(members[name])
        if expected != actual:
            errors.append(f"integrity:sha256-mismatch:{name}")
    return _check("integrity", STATUS_PASSED if not errors else STATUS_FAILED, errors=errors)


def _rhythm_check(members: Mapping[str, bytes] | None) -> dict[str, Any]:
    if members is None:
        return _check("rhythm-map", STATUS_SKIPPED, notes=["skipped: package safety failed"])
    if RHYTHM_MEMBER not in members:
        return _failed_check("rhythm-map", [f"missing-member:{RHYTHM_MEMBER}"])
    errors: list[str] = []
    try:
        rhythm_map = json.loads(members[RHYTHM_MEMBER].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return _failed_check("rhythm-map", [f"unreadable:{error}"])
    if not isinstance(rhythm_map, dict):
        return _failed_check("rhythm-map", ["not-an-object"])
    if rhythm_map.get("schema_version") != "beatscope-rhythm-map-1.0":
        errors.append(f"schema_version:expected 'beatscope-rhythm-map-1.0', got {rhythm_map.get('schema_version')!r}")
    duration = rhythm_map.get("duration")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        errors.append(f"duration:must-be-positive-number, got {duration!r}")
    onsets = rhythm_map.get("onsets")
    # Silence/no-track projects are valid Rhythm IR and intentionally carry
    # no fabricated events. The validator checks the container type, not
    # whether the song happened to produce an onset.
    if not isinstance(onsets, list):
        errors.append("onsets:must-be-a-list")
    return _check("rhythm-map", STATUS_PASSED if not errors else STATUS_FAILED, errors=errors)


def _executable_trust_check(
    manifest: dict[str, Any] | None,
    members: Mapping[str, bytes] | None,
) -> dict[str, Any]:
    """Verify executable members against BeatScope's installed templates.

    A self-authored integrity map proves consistency, not trust. Before Node
    runs anything, every executable module must therefore be the exact output
    the installed BeatScope version would generate from the validated package
    data. The actual probe process uses the installed probe source as a second
    boundary; the package-supplied probe is compared but never executed.
    """
    if members is None or manifest is None:
        return _check(
            "executable-trust",
            STATUS_SKIPPED,
            notes=["skipped: manifest unavailable"],
            required=True,
        )
    errors: list[str] = []
    if manifest.get("entry") != ENTRY_MEMBER:
        errors.append(f"executable:unsupported-entry:{manifest.get('entry')!r}")
    if manifest.get("probe") != PROBE_MEMBER:
        errors.append(f"executable:unsupported-probe:{manifest.get('probe')!r}")
    try:
        rhythm = json.loads(members[RHYTHM_MEMBER].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return _failed_check("executable-trust", [f"executable:rhythm-unreadable:{error}"])

    capabilities = manifest.get("capabilities")
    scenes = bool(isinstance(capabilities, dict) and capabilities.get("scenes"))
    visual_artifacts: tuple[dict[str, Any], dict[str, Any]] | None = None
    if scenes:
        try:
            recipe = json.loads(members[RECIPE_MEMBER].decode("utf-8"))
            timeline = json.loads(members[TIMELINE_MEMBER].decode("utf-8"))
            visual_artifacts = (recipe, timeline)
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            return _failed_check("executable-trust", [f"executable:visual-unreadable:{error}"])

    expected: dict[str, bytes] = {
        "beatscope-runtime.js": _runtime_source().encode("utf-8"),
        PROBE_MEMBER: _probe_source().encode("utf-8"),
        WORKER_MEMBER: _worker_example_source().encode("utf-8"),
        ENTRY_MEMBER: _visual_state_source(rhythm, visual_artifacts).encode("utf-8"),
    }
    if visual_artifacts is not None:
        recipe, timeline = visual_artifacts
        expected.update(
            {
                "scene-director.js": _scene_director_source().encode("utf-8"),
                "visual-recipe-data.js": _visual_data_module("VISUAL_RECIPE", recipe).encode("utf-8"),
                "visual-timeline-data.js": _visual_data_module("VISUAL_TIMELINE", timeline).encode("utf-8"),
            }
        )
    for name, trusted in expected.items():
        actual = members.get(name)
        if actual is None:
            errors.append(f"executable:missing:{name}")
        elif actual != trusted:
            errors.append(f"executable:untrusted-bytes:{name}")
    return _check(
        "executable-trust",
        STATUS_PASSED if not errors else STATUS_FAILED,
        errors=errors,
    )


def _visual_check(manifest: dict[str, Any] | None, members: Mapping[str, bytes] | None) -> dict[str, Any]:
    capabilities = manifest.get("capabilities") if isinstance(manifest, dict) else None
    has_scenes = bool(isinstance(capabilities, dict) and capabilities.get("scenes"))
    if members is None or manifest is None:
        return _check("visual-artifacts", STATUS_SKIPPED, notes=["skipped: manifest unavailable"], required=False)
    if not has_scenes:
        notes = []
        for member in (RECIPE_MEMBER, TIMELINE_MEMBER):
            if member in members:
                notes.append(f"unexpected-member-despite-scenes-false:{member}")
        return _check("visual-artifacts", STATUS_SKIPPED, notes=notes, required=False)
    errors: list[str] = []
    documents: dict[str, Any] = {}
    for member in (RHYTHM_MEMBER, RECIPE_MEMBER, TIMELINE_MEMBER):
        try:
            documents[member] = json.loads(members[member].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as error:
            errors.append(f"unreadable:{member}:{error}")
    if not errors:
        errors.extend(validate_visual_recipe(documents[RECIPE_MEMBER]))
        errors.extend(
            validate_visual_timeline(documents[TIMELINE_MEMBER], documents[RHYTHM_MEMBER], documents[RECIPE_MEMBER])
        )
    return _check("visual-artifacts", STATUS_PASSED if not errors else STATUS_FAILED, errors=errors, required=False)


def _run_probe(
    root: Path,
    checkpoints_file: Path | None,
    node: str,
    workdir: Path,
    timeout: float,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Run BeatScope's trusted probe; fixed argument array, isolated cwd."""
    trusted_probe = workdir / "consumer-probe.mjs"
    trusted_probe.write_text(_probe_source(), encoding="utf-8")
    command = [
        node,
        str(trusted_probe.resolve()),
        str(root.resolve()),
    ]
    if checkpoints_file is not None:
        command.extend(["--checkpoints", str(checkpoints_file.resolve())])
    try:
        completed = subprocess.run(
            command,
            cwd=workdir,
            env=_child_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, [f"node:timeout after {timeout:g}s"]
    except OSError as error:
        return None, [f"node:spawn-failed:{error}"]
    if completed.returncode not in (0, 1):
        excerpt = (completed.stderr or completed.stdout or "").strip()[:400]
        return None, [f"node:exit-{completed.returncode}:{excerpt}"]
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        excerpt = (completed.stdout or completed.stderr or "").strip()[:400]
        return None, [f"node:unparsable-report:{excerpt}"]
    return report, []


def _probe_check(
    root: Path | None,
    checkpoints_file: Path | None,
    node: str | None,
    workdir: Path,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if node is None:
        return _check(
            "node-probe",
            STATUS_UNAVAILABLE,
            errors=["node:not-found-on-PATH"],
            notes=["install Node.js to run the packaged probe"],
        ), None
    if root is None:
        return _check("node-probe", STATUS_SKIPPED, notes=["skipped: package safety or integrity failed"]), None
    report, errors = _run_probe(root, checkpoints_file, node, workdir, timeout)
    if report is None:
        return _failed_check("node-probe", errors), None
    errors.extend(f"probe:{error}" for error in report.get("errors", []))
    if not report.get("ok") and not errors:
        errors.append("probe:package-checks-failed")
    status = STATUS_PASSED if report.get("ok") and not errors else STATUS_FAILED
    return _check("node-probe", status, errors=errors), report


def _checkpoints_check(
    checkpoints_file: Path | None,
    members: Mapping[str, bytes] | None,
    probe_report: dict[str, Any] | None,
    node: str | None,
) -> dict[str, Any]:
    if checkpoints_file is None:
        return _check(
            "checkpoints",
            STATUS_SKIPPED,
            notes=["no checkpoints file found beside the package (pass --checkpoints to require determinism)"],
            required=False,
        )
    errors: list[str] = []
    try:
        document = json.loads(checkpoints_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return _failed_check("checkpoints", [f"unreadable:{error}"], required=False)
    errors.extend(validate_checkpoints(document, members))
    suite = probe_report.get("checkpoints") if isinstance(probe_report, dict) else None
    if isinstance(suite, dict):
        errors.extend(f"replay:{error}" for error in suite.get("errors", []))
        if not suite.get("ok"):
            errors.append("replay:checkpoint-suite-failed")
    elif node is not None:
        errors.append("replay:probe-did-not-run-checkpoint-suite")
    elif members is not None:
        return _check(
            "checkpoints",
            STATUS_UNAVAILABLE,
            errors=errors,
            notes=["structural checks ran; frame parity needs Node"],
            required=False,
        )
    return _check("checkpoints", STATUS_PASSED if not errors else STATUS_FAILED, errors=errors, required=False)


def _worker_check(
    manifest: dict[str, Any] | None,
    root: Path | None,
    node: str | None,
    workdir: Path,
    timeout: float,
) -> dict[str, Any]:
    capabilities = manifest.get("capabilities") if isinstance(manifest, dict) else None
    declared = bool(isinstance(capabilities, dict) and capabilities.get("module_worker"))
    if not declared:
        notes = [] if manifest is None else ["capabilities.module_worker is false"]
        return _check("worker-smoke", STATUS_SKIPPED, notes=notes, required=False)
    if node is None:
        return _check("worker-smoke", STATUS_UNAVAILABLE, errors=["node:not-found-on-PATH"])
    if root is None:
        return _check("worker-smoke", STATUS_SKIPPED, notes=["skipped: package safety or integrity failed"])
    runner_path = workdir / "worker-smoke.mjs"
    runner_path.write_text(_WORKER_SMOKE_RUNNER, encoding="utf-8")
    bootstrap_path = workdir / "worker-bootstrap.mjs"
    bootstrap_path.write_text(_WORKER_SMOKE_BOOTSTRAP, encoding="utf-8")
    command = [
        node,
        str(runner_path.resolve()),
        str(bootstrap_path.resolve()),
        str((root / WORKER_MEMBER).resolve()),
        str(int(timeout * 1000)),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=workdir,
            env=_child_env(),
            capture_output=True,
            text=True,
            timeout=timeout + 10.0,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _failed_check("worker-smoke", [f"node:timeout after {timeout + 10.0:g}s"])
    except OSError as error:
        return _failed_check("worker-smoke", [f"node:spawn-failed:{error}"])
    if completed.returncode != 0:
        excerpt = (completed.stderr or completed.stdout or "").strip()[:400]
        return _failed_check("worker-smoke", [f"worker:exit-{completed.returncode}:{excerpt}"])
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return _failed_check("worker-smoke", ["worker:unparsable-result"])
    errors = [] if result.get("ok") else ["worker:no-deterministic-timing-response"]
    return _check("worker-smoke", STATUS_PASSED if not errors else STATUS_FAILED, errors=errors)


def _leakage_check(members: Mapping[str, bytes] | None) -> dict[str, Any]:
    if members is None:
        return _check("leakage", STATUS_SKIPPED, notes=["skipped: package safety failed"], required=False)
    errors: list[str] = []
    username = getpass.getuser()
    username_pattern = re.compile(re.escape(username), re.IGNORECASE) if len(username) >= 3 and username.isalnum() else None
    for name in sorted(members):
        if PurePosixPath(name).suffix.lower() in _AUDIO_SUFFIXES:
            errors.append(f"leakage:audio-member:{name}")
            continue
        try:
            text = members[name].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if _DRIVE_PATH_RE.search(text):
            errors.append(f"leakage:drive-path:{name}")
        if _UNIX_HOME_RE.search(text):
            errors.append(f"leakage:home-path:{name}")
        if username_pattern is not None and username_pattern.search(text):
            errors.append(f"leakage:username:{name}")
    return _check("leakage", STATUS_PASSED if not errors else STATUS_FAILED, errors=errors, required=False)


def validate_handoff(
    target: str | Path,
    *,
    checkpoints: str | Path | None = None,
    node_timeout: float = NODE_TIMEOUT_SECONDS,
    worker_timeout: float = WORKER_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Validate one BeatScope handoff package (ZIP or unpacked directory)."""
    target = Path(target)
    if not target.exists():
        raise ConsumerUsageError(f"target does not exist: {target}")
    if target.is_dir():
        is_zip = False
    elif target.is_file() and zipfile.is_zipfile(target):
        is_zip = True
    else:
        raise ConsumerUsageError(f"target is not a package directory or ZIP: {target}")

    node = shutil.which("node")
    checks: list[dict[str, Any]] = []
    if is_zip:
        members, errors, notes = _load_zip_members(target)
    else:
        members, errors, notes = _load_directory_members(target)
    checks.append(_check("safety", STATUS_PASSED if not errors else STATUS_FAILED, errors=errors, notes=notes))

    manifest: dict[str, Any] | None = None
    if members is None:
        checks.append(_check("manifest", STATUS_SKIPPED, notes=["skipped: package safety failed"]))
        checks.append(_check("integrity", STATUS_SKIPPED, notes=["skipped: package safety failed"]))
    else:
        manifest_check, manifest = _manifest_check(members)
        checks.append(manifest_check)
        checks.append(_integrity_check(manifest, members))
    checks.append(_rhythm_check(members))
    checks.append(_visual_check(manifest, members))
    checks.append(_executable_trust_check(manifest, members))

    checkpoints_file = Path(checkpoints) if checkpoints is not None else target.parent / "checkpoints.json"
    if not checkpoints_file.is_file():
        checkpoints_file = None

    # JavaScript runs only after path safety, manifest, integrity, and the
    # executable-template trust boundary all pass. Integrity alone is only
    # self-consistency: an attacker can hash their own malicious package.
    status_by_name = {check["name"]: check["status"] for check in checks}
    execute_ok = all(
        status_by_name.get(name) == STATUS_PASSED
        for name in ("safety", "manifest", "integrity", "executable-trust")
    )
    probe_report: dict[str, Any] | None = None
    with tempfile.TemporaryDirectory(prefix="beatscope-validate-") as temp:
        workdir = Path(temp) / "work"
        workdir.mkdir()
        root: Path | None = None
        if members is not None and execute_ok:
            if is_zip:
                package_dir = Path(temp) / "package"
                materialize_errors = _materialize_members(members, package_dir)
                if materialize_errors:
                    checks.append(_failed_check("extraction", materialize_errors))
                    root = None
                else:
                    root = package_dir
            else:
                root = target
        probe_check, probe_report = _probe_check(root, checkpoints_file, node, workdir, node_timeout)
        checks.append(probe_check)
        checks.append(_checkpoints_check(checkpoints_file, members, probe_report, node))
        checks.append(_worker_check(manifest, root, node, workdir, worker_timeout))
    checks.append(_leakage_check(members))
    return _build_report("validate-handoff", target, checks)


def load_declaration(example_dir: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Read and shape-check a ``beatscope-consumer-1`` declaration."""
    declaration_path = example_dir / DECLARATION_MEMBER
    if not declaration_path.is_file():
        return None, [f"declaration:missing:{DECLARATION_MEMBER}"]
    try:
        declaration = json.loads(declaration_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, [f"declaration:unreadable:{error}"]
    if not isinstance(declaration, dict):
        return None, ["declaration:not-an-object"]
    errors: list[str] = []
    if declaration.get("schema") != DECLARATION_SCHEMA:
        errors.append(f"declaration:schema-expected {DECLARATION_SCHEMA!r}")
    for field in ("name", "framework", "entry_page", "package_path", "clock"):
        value = declaration.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"declaration:{field}:must-be-a-non-empty-string")
    capabilities = declaration.get("capabilities")
    playback = isinstance(capabilities, dict) and capabilities.get("playback") is True
    # Only interactive consumers expose the browser debug hook; offline
    # compositions declare no hook rather than promising a missing one.
    if playback and declaration.get("debug_hook") != DEBUG_HOOK_NAME:
        errors.append(f"declaration:debug_hook:must-be {DEBUG_HOOK_NAME!r} for interactive consumers")
    if not playback and declaration.get("debug_hook") not in (None, DEBUG_HOOK_NAME):
        errors.append(f"declaration:debug_hook:must-be {DEBUG_HOOK_NAME!r} when present")
    if not isinstance(capabilities, dict):
        errors.append("declaration:capabilities:must-be-an-object")
    else:
        for key in ("playback", "seek", "offline_frame", "reduced_motion"):
            if not isinstance(capabilities.get(key), bool):
                errors.append(f"declaration:capabilities.{key}:must-be-a-boolean")
        if capabilities.get("offline_frame") is True:
            offline_entry = declaration.get("offline_entry")
            if not isinstance(offline_entry, str) or not offline_entry.strip():
                errors.append("declaration:offline_entry:must-be-a-non-empty-string for offline consumers")
    return declaration, errors


def _run_json_command(command: list[str], workdir: Path, timeout: float) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        completed = subprocess.run(
            command, cwd=workdir, env=_child_env(), capture_output=True,
            text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return None, [f"timeout after {timeout:g}s"]
    except OSError as error:
        return None, [f"spawn-failed:{error}"]
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        excerpt = (completed.stderr or completed.stdout or "").strip()[:400]
        return None, [f"unparsable-report:{excerpt}"]
    errors = [str(error) for error in report.get("errors", [])]
    if completed.returncode != 0 and not errors:
        errors.append(f"exit-{completed.returncode}")
    return report, errors


def _playwright_module() -> Path | None:
    configured = os.environ.get("BEATSCOPE_PLAYWRIGHT_MODULE")
    candidates = [
        Path(configured) if configured else None,
        REPO_ROOT / "tests" / "browser" / "node_modules" / "playwright" / "index.mjs",
    ]
    return next((candidate.resolve() for candidate in candidates if candidate and candidate.is_file()), None)


def _browser_check(entry_page: Path, allowed_root: Path, node: str | None, timeout: float) -> dict[str, Any]:
    if node is None:
        return _check("browser", STATUS_UNAVAILABLE, errors=["browser:node-not-found-on-PATH"])
    playwright = _playwright_module()
    if playwright is None:
        return _check(
            "browser", STATUS_UNAVAILABLE, errors=["browser:playwright-module-not-found"],
            notes=["install tests/browser dependencies or set BEATSCOPE_PLAYWRIGHT_MODULE"],
        )
    with tempfile.TemporaryDirectory(prefix="beatscope-browser-") as temp:
        workdir = Path(temp)
        audio = workdir / "probe.wav"
        with wave.open(str(audio), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\0\0" * (8000 * 12))
        report, errors = _run_json_command(
            [node, str((RUNTIME_DIR / "consumer-browser.mjs").resolve()), str(playwright),
             str(allowed_root), entry_page.relative_to(allowed_root).as_posix(), str(audio)],
            workdir, timeout,
        )
    if report is None:
        return _failed_check("browser", [f"browser:{error}" for error in errors])
    if any("Executable doesn't exist" in error for error in errors):
        return _check("browser", STATUS_UNAVAILABLE, errors=errors, notes=["install the pinned Chromium browser"])
    return _check(
        "browser", STATUS_PASSED if report.get("ok") and not errors else STATUS_FAILED,
        errors=errors, notes=[f"real Chromium checks: {', '.join(sorted(report.get('checks', {})))}"],
    )


def _offline_check(example_dir: Path, declaration: dict[str, Any], node: str | None, timeout: float) -> dict[str, Any]:
    if node is None:
        return _check("offline", STATUS_UNAVAILABLE, errors=["offline:node-not-found-on-PATH"])
    module = (example_dir / str(declaration["offline_entry"])).resolve()
    if not module.is_relative_to(example_dir.resolve()) or not module.is_file():
        return _failed_check("offline", [f"offline:entry-missing-inside-example:{declaration['offline_entry']}"])
    with tempfile.TemporaryDirectory(prefix="beatscope-offline-") as temp:
        report, errors = _run_json_command(
            [node, str((RUNTIME_DIR / "consumer-offline.mjs").resolve()), str(module)], Path(temp), timeout,
        )
    if report is None:
        return _failed_check("offline", [f"offline:{error}" for error in errors])
    return _check(
        "offline", STATUS_PASSED if report.get("ok") and not errors else STATUS_FAILED,
        errors=errors, notes=[f"frame/FPS checks: {', '.join(sorted(report.get('checks', {})))}"],
    )


def _static_check(example_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    scanned = 0
    for path in sorted(example_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(example_dir)
        if any(part in _SKIPPED_SOURCE_DIRS for part in relative.parts):
            continue
        if path.name in _RUNTIME_FINGERPRINT_FILES:
            errors.append(f"static:copied-runtime:{relative.as_posix()}")
        if path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        for line_number, line in enumerate(text.splitlines(), start=1):
            if _FORBIDDEN_IMPORT_RE.search(line):
                errors.append(f"static:forbidden-import:{relative.as_posix()}:{line_number}")
            if _DATE_NOW_RE.search(line):
                errors.append(f"static:Date.now:{relative.as_posix()}:{line_number}")
            if _PERFORMANCE_NOW_RE.search(line):
                errors.append(f"static:performance.now:{relative.as_posix()}:{line_number}")
    return _check(
        "static",
        STATUS_PASSED if not errors else STATUS_FAILED,
        errors=errors,
        notes=[f"scanned {scanned} source files"],
    )


def validate_consumer(
    target: str | Path,
    *,
    browser: bool = False,
    offline: bool = False,
    checkpoints: str | Path | None = None,
    validation_root: str | Path | None = None,
    node_timeout: float = NODE_TIMEOUT_SECONDS,
    worker_timeout: float = WORKER_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Validate one visual consumer example against its declared package.

    ``validation_root`` bounds where ``package_path`` may resolve; it
    defaults to the repository containing this module (plan section 7).
    """
    example_dir = Path(target)
    if not example_dir.is_dir():
        raise ConsumerUsageError(f"consumer example directory does not exist: {example_dir}")
    allowed_root = Path(validation_root).resolve() if validation_root is not None else REPO_ROOT.resolve()
    checks: list[dict[str, Any]] = []

    declaration, declaration_errors = load_declaration(example_dir)
    capabilities = declaration.get("capabilities", {}) if isinstance(declaration, dict) else {}
    playback = capabilities.get("playback") is True
    offline_frame = capabilities.get("offline_frame") is True

    package_path: Path | None = None
    entry_page: Path | None = None
    if declaration is not None and not declaration_errors:
        candidate_package = (example_dir / str(declaration["package_path"])).resolve()
        if not candidate_package.is_relative_to(allowed_root):
            declaration_errors.append(
                f"declaration:package_path-escapes-validation-root:{declaration['package_path']}"
            )
        elif not candidate_package.exists():
            declaration_errors.append(f"declaration:package_path-missing:{declaration['package_path']}")
        else:
            package_path = candidate_package
        entry_page = (example_dir / str(declaration["entry_page"])).resolve()
        if not entry_page.is_relative_to(example_dir.resolve()) or not entry_page.is_file():
            declaration_errors.append(
                f"declaration:entry_page-missing-inside-example:{declaration['entry_page']}"
            )
    checks.append(
        _check("declaration", STATUS_PASSED if not declaration_errors else STATUS_FAILED, errors=declaration_errors)
    )

    if package_path is None:
        checks.append(_check("handoff", STATUS_SKIPPED, notes=["skipped: declaration invalid"], required=True))
        checks.append(_check("node-probe", STATUS_SKIPPED, notes=["skipped: declaration invalid"]))
    else:
        handoff_report = validate_handoff(
            package_path,
            checkpoints=checkpoints,
            node_timeout=node_timeout,
            worker_timeout=worker_timeout,
        )
        handoff_errors: list[str] = []
        handoff_unavailable = False
        for check in handoff_report["checks"]:
            if check["status"] == STATUS_FAILED:
                handoff_errors.extend(f"handoff:{check['name']}:{error}" for error in check["errors"])
            if check["required"] and check["status"] == STATUS_UNAVAILABLE:
                handoff_unavailable = True
        if handoff_unavailable:
            checks.append(
                _check("handoff", STATUS_UNAVAILABLE, errors=handoff_errors, notes=["required probe unavailable (Node missing)"])
            )
        else:
            checks.append(_check("handoff", STATUS_FAILED if handoff_errors else STATUS_PASSED, errors=handoff_errors))
        by_name = {check["name"]: check for check in handoff_report["checks"]}
        probe_check = by_name.get("node-probe")
        checkpoints_check = by_name.get("checkpoints")
        probe_errors = list(probe_check["errors"]) if probe_check else ["handoff:node-probe-missing"]
        if probe_check is not None and probe_check["status"] == STATUS_UNAVAILABLE:
            checks.append(_check("node-probe", STATUS_UNAVAILABLE, errors=probe_errors))
        elif (
            probe_check is not None
            and probe_check["status"] == STATUS_PASSED
            and checkpoints_check is not None
            and checkpoints_check["status"] == STATUS_PASSED
        ):
            checks.append(_check("node-probe", STATUS_PASSED, notes=["canonical frames match the recorded checkpoints"]))
        elif checkpoints_check is not None and checkpoints_check["status"] == STATUS_SKIPPED:
            checks.append(_failed_check("node-probe", ["checkpoints:none-found-beside-package"]))
        else:
            if checkpoints_check is not None and checkpoints_check["status"] == STATUS_FAILED:
                probe_errors.extend(f"checkpoints:{error}" for error in checkpoints_check["errors"])
            checks.append(_failed_check("node-probe", probe_errors))

    checks.append(_static_check(example_dir))
    node = shutil.which("node")

    if not playback:
        checks.append(_check("browser", STATUS_SKIPPED, notes=["consumer declares no interactive playback"], required=False))
    elif not browser:
        checks.append(
            _check(
                "browser",
                STATUS_SKIPPED,
                notes=["interactive consumer: pass --browser to validate playback layers"],
                required=True,
            )
        )
    else:
        if entry_page is None:
            checks.append(_check("browser", STATUS_SKIPPED, notes=["skipped: declaration invalid"]))
        else:
            checks.append(_browser_check(entry_page, allowed_root, node, node_timeout))

    if not offline_frame:
        checks.append(_check("offline", STATUS_SKIPPED, notes=["consumer declares no offline rendering"], required=False))
    elif not offline:
        checks.append(
            _check(
                "offline",
                STATUS_SKIPPED,
                notes=["offline consumer: pass --offline to validate frame/FPS determinism"],
                required=True,
            )
        )
    else:
        if declaration is None:
            checks.append(_check("offline", STATUS_SKIPPED, notes=["skipped: declaration invalid"]))
        else:
            checks.append(_offline_check(example_dir, declaration, node, node_timeout))

    checks.append(
        _check("visual-snapshot", STATUS_SKIPPED, notes=["non-blocking layer; human review of composition"], required=False)
    )
    return _build_report("validate-consumer", example_dir, checks)


def validate_consumers_all(
    target: str | Path,
    **options: Any,
) -> dict[str, Any]:
    """Validate every ``beatscope-consumer.json`` example under a root."""
    root = Path(target)
    if not root.is_dir():
        raise ConsumerUsageError(f"consumer examples root does not exist: {root}")
    example_dirs = sorted(
        path.parent
        for path in root.rglob(DECLARATION_MEMBER)
        if not any(part in _SKIPPED_SOURCE_DIRS or part.startswith(".") for part in path.relative_to(root).parts)
    )
    if not example_dirs:
        raise ConsumerUsageError(f"no {DECLARATION_MEMBER} found under {root}")
    reports = [validate_consumer(example_dir, **options) for example_dir in example_dirs]
    exit_code = max(report["exit_code"] for report in reports)
    return {
        "schema": REPORT_SCHEMA,
        "command": "validate-consumer",
        "target": str(root),
        "all": True,
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "reports": reports,
        "summary": {
            "consumers": len(reports),
            "passed": sum(1 for report in reports if report["exit_code"] == 0),
            "failed": sum(1 for report in reports if report["exit_code"] == 1),
            "environment": sum(1 for report in reports if report["exit_code"] == 2),
        },
    }


def format_report(report: Mapping[str, Any]) -> str:
    """Actionable human-readable rendering of one report."""
    lines = [f"{report['command']}: {report['target']}"]
    for check in report.get("checks", []):
        marker = {"passed": "ok", "failed": "FAIL", "skipped": "-", "unavailable": "?"}[check["status"]]
        suffix = " (required)" if check.get("required") and check["status"] != STATUS_PASSED else ""
        lines.append(f"  [{marker}] {check['name']}{suffix}")
        for error in check["errors"]:
            lines.append(f"        {error}")
        for note in check["notes"]:
            lines.append(f"        note: {note}")
    exit_code = report["exit_code"]
    verdict = {0: "all required checks passed", 1: "contract failure", 2: "environment or command problem"}[exit_code]
    lines.append(f"exit {exit_code}: {verdict}")
    return "\n".join(lines)
