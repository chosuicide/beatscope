"""Consumer handoff contract (v0.9 plan sections 4 and 6).

The exported handoff is given to autonomous coding tools, so its routing
document — ``beatscope-package.json`` — is validated as strictly as any
other input. This module owns the manifest rules, the checkpoint and
fixture-lock document rules, and the layout-independent package digest.
It is pure validation: nothing here executes package JavaScript, reads
the network, or touches the filesystem.

Manifest invariants (plan section 4.3):

- paths are relative POSIX paths with no ``..``, drive prefix, URI, or
  leading slash;
- ``entry`` and ``probe`` name members that exist in the archive;
- duration is finite and agrees with ``rhythm-map.json`` within 1e-6 s;
- capabilities describe present files and exported functions, never
  aspirations;
- integrity covers every functional member except the manifest itself;
- no timestamp, machine path, username, host, or audio bytes enter the
  document;
- ``package_version`` describes the handoff package, not the analyzer.

Unknown additive capabilities and manifest fields may be ignored by older
consumers, so validation only rejects values that contradict the declared
shape, never merely unfamiliar names.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping

MANIFEST_SCHEMA = "beatscope-package-1"
CHECKPOINT_SCHEMA = "beatscope-consumer-checkpoints-1"
FIXTURE_LOCK_SCHEMA = "beatscope-consumer-fixture-lock-1"

MANIFEST_MEMBER = "beatscope-package.json"
ENTRY_MEMBER = "visual-state.js"
PROBE_MEMBER = "consumer-probe.js"
WORKER_MEMBER = "worker-example.js"
RHYTHM_MEMBER = "rhythm-map.json"
RECIPE_MEMBER = "visual-recipe.json"
TIMELINE_MEMBER = "visual-timeline.json"

KNOWN_CAPABILITIES = ("timing", "bands", "structure", "scenes", "module_worker")
KNOWN_FUNCTIONS = ("frame", "timing", "scene")
KNOWN_FILES = ("rhythm", "recipe", "timeline")

DURATION_TOLERANCE = 1e-6

_FORBIDDEN_KEYS = frozenset(
    {
        "generated_at",
        "timestamp",
        "created_at",
        "modified_at",
        "hostname",
        "host",
        "username",
        "user",
        "machine",
        "source_path",
        "audio_file",
        "audio_bytes",
    }
)

_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def package_member_digest(members: Mapping[str, bytes]) -> str:
    """Content address over an unpacked package, independent of layout.

    Length-prefixes each name and payload so member boundaries are
    unambiguous, and sorts by POSIX path so ZIP order and directory walks
    agree. The manifest itself is excluded by callers that carry one, so
    the same digest covers v0.8 packages and self-describing v0.9 ones.
    """
    digest = hashlib.sha256()
    for name in sorted(members):
        raw_name = name.encode("utf-8")
        digest.update(len(raw_name).to_bytes(4, "big"))
        digest.update(raw_name)
        digest.update(len(members[name]).to_bytes(8, "big"))
        digest.update(members[name])
    return digest.hexdigest()


def valid_member_path(value: Any) -> bool:
    """Relative POSIX package path, safe to join under any root."""
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    if value.startswith("/") or value.startswith("~"):
        return False
    if "://" in value or re.match(r"^[A-Za-z]:", value):
        return False
    parts = value.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _forbidden_key_violations(value: Any, path: str) -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            if key in _FORBIDDEN_KEYS:
                violations.append(f"forbidden-key:{here}")
            else:
                violations.extend(_forbidden_key_violations(item, here))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            violations.extend(_forbidden_key_violations(item, f"{path}[{index}]"))
    return violations


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def canonical_manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    """Deterministic UTF-8 JSON with LF endings and sorted keys."""
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"


def validate_manifest(
    manifest: Any,
    members: Mapping[str, bytes] | None = None,
) -> list[str]:
    """Return a sorted list of human-readable violations; empty means valid.

    ``members`` maps archive names to their exact uncompressed bytes. When
    it is given, path existence, hash integrity, and full coverage are
    checked; without it only the document shape is validated.
    """
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest:not-an-object"]

    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"schema:expected {MANIFEST_SCHEMA!r}")

    version = manifest.get("package_version")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        errors.append(f"package_version:invalid:{version!r}")

    project_id = manifest.get("project_id")
    if not isinstance(project_id, str) or not project_id or "/" in project_id or "\\" in project_id:
        errors.append(f"project_id:invalid:{project_id!r}")

    duration = manifest.get("duration")
    if not _finite_number(duration):
        errors.append(f"duration:invalid:{duration!r}")
    else:
        if float(duration) < 0:
            errors.append(f"duration:negative:{duration!r}")
        clock = manifest.get("clock")
        if not isinstance(clock, dict):
            errors.append("clock:not-an-object")
        else:
            if clock.get("unit") != "seconds":
                errors.append(f"clock.unit:invalid:{clock.get('unit')!r}")
            if clock.get("semantics") != "media-time":
                errors.append(f"clock.semantics:invalid:{clock.get('semantics')!r}")
            minimum = clock.get("minimum")
            maximum = clock.get("maximum")
            if not _finite_number(minimum) or not _finite_number(maximum):
                errors.append("clock.bounds:invalid")
            else:
                if float(minimum) < 0:
                    errors.append(f"clock.minimum:negative:{minimum!r}")
                if float(maximum) < float(minimum):
                    errors.append("clock.maximum:below-minimum")
                elif abs(float(maximum) - float(duration)) > DURATION_TOLERANCE:
                    errors.append("clock.maximum:duration-mismatch")

    entry = manifest.get("entry")
    if not valid_member_path(entry):
        errors.append(f"entry:invalid-path:{entry!r}")
    probe = manifest.get("probe")
    if not valid_member_path(probe):
        errors.append(f"probe:invalid-path:{probe!r}")

    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, dict):
        errors.append("capabilities:not-an-object")
        capabilities = {}
    for name, flag in capabilities.items():
        if not isinstance(flag, bool):
            errors.append(f"capabilities.{name}:not-boolean")
    for name in KNOWN_CAPABILITIES:
        if name not in capabilities:
            errors.append(f"capabilities.{name}:missing")
    scenes = capabilities.get("scenes") is True

    functions = manifest.get("functions")
    if not isinstance(functions, dict):
        errors.append("functions:not-an-object")
        functions = {}
    for name, value in functions.items():
        if name not in KNOWN_FUNCTIONS:
            errors.append(f"functions.{name}:unknown")
        elif not isinstance(value, str) or not value.strip():
            errors.append(f"functions.{name}:invalid:{value!r}")
    if "timing" not in functions:
        errors.append("functions.timing:missing")
    if scenes:
        for name in ("frame", "scene"):
            if name not in functions:
                errors.append(f"functions.{name}:required-with-scenes")
    else:
        for name in ("frame", "scene"):
            if name in functions:
                errors.append(f"functions.{name}:requires-scenes")

    files = manifest.get("files")
    if not isinstance(files, dict):
        errors.append("files:not-an-object")
        files = {}
    for name, value in files.items():
        if name not in KNOWN_FILES:
            errors.append(f"files.{name}:unknown")
        elif not valid_member_path(value):
            errors.append(f"files.{name}:invalid-path:{value!r}")
    if "rhythm" not in files:
        errors.append("files.rhythm:missing")
    if scenes and ("recipe" not in files or "timeline" not in files):
        errors.append("files.recipe-timeline:required-with-scenes")
    if not scenes and ("recipe" in files or "timeline" in files):
        errors.append("files.recipe-timeline:requires-scenes")
    timing_on = capabilities.get("timing") is True
    if timing_on and "rhythm" not in files:
        errors.append("files.rhythm:required-with-timing")
    if "rhythm" in files and not timing_on:
        errors.append("capabilities.timing:required-with-rhythm-file")

    worker_on = capabilities.get("module_worker") is True
    if members is not None:
        if WORKER_MEMBER in members and not worker_on:
            errors.append(f"capabilities.module_worker:required-with-{WORKER_MEMBER}")
        if worker_on and WORKER_MEMBER not in members:
            errors.append(f"capabilities.module_worker:missing-{WORKER_MEMBER}")
        for label, path in (
            ("entry", entry),
            ("probe", probe),
            *[("files." + name, value) for name, value in files.items() if isinstance(value, str)],
        ):
            if valid_member_path(path) and path not in members:
                errors.append(f"{label}:missing-member:{path}")

    integrity = manifest.get("integrity")
    if not isinstance(integrity, dict):
        errors.append("integrity:not-an-object")
        integrity = {}
    if integrity.get("algorithm") != "sha256":
        errors.append(f"integrity.algorithm:invalid:{integrity.get('algorithm')!r}")
    listed = integrity.get("members")
    if not isinstance(listed, dict):
        errors.append("integrity.members:not-an-object")
        listed = {}
    for name, digest in listed.items():
        if not isinstance(name, str) or not valid_member_path(name):
            errors.append(f"integrity.members:invalid-name:{name!r}")
            continue
        if not is_sha256_hex(digest):
            errors.append(f"integrity:{name}:invalid-digest")
            continue
        if members is not None:
            if name not in members:
                errors.append(f"integrity:{name}:missing-member")
            elif sha256_hex(members[name]) != digest:
                errors.append(f"integrity:{name}:hash-mismatch")
    if members is not None:
        expected = {name for name in members if name != MANIFEST_MEMBER}
        for name in sorted(expected - set(listed)):
            errors.append(f"integrity:{name}:uncovered")

    errors.extend(_forbidden_key_violations(manifest, ""))
    return sorted(set(errors))


def manifest_duration_errors(manifest: Mapping[str, Any], rhythm_map: Mapping[str, Any]) -> list[str]:
    """The manifest duration must agree with the rhythm map within 1e-6 s."""
    errors: list[str] = []
    duration = manifest.get("duration")
    rhythm_duration = rhythm_map.get("duration")
    if not _finite_number(duration) or not _finite_number(rhythm_duration):
        return ["duration:not-comparable"]
    if abs(float(duration) - float(rhythm_duration)) > DURATION_TOLERANCE:
        errors.append(
            f"duration:mismatch:{duration!r} vs rhythm {rhythm_duration!r}"
        )
    return errors


def validate_checkpoints(
    checkpoints: Any,
    members: Mapping[str, bytes] | None = None,
) -> list[str]:
    """Validate a ``beatscope-consumer-checkpoints-1`` document.

    With ``members`` the recorded package digest must match the actual
    member set, so a checkpoint file cannot silently describe another
    package than the one beside it.
    """
    errors: list[str] = []
    if not isinstance(checkpoints, dict):
        return ["checkpoints:not-an-object"]

    if checkpoints.get("schema") != CHECKPOINT_SCHEMA:
        errors.append(f"schema:expected {CHECKPOINT_SCHEMA!r}")

    package_sha = checkpoints.get("package_sha256")
    if not is_sha256_hex(package_sha):
        errors.append(f"package_sha256:invalid:{package_sha!r}")
    elif members is not None and package_sha != package_member_digest(members):
        errors.append("package_sha256:member-mismatch")

    duration = checkpoints.get("duration")
    if not _finite_number(duration) or float(duration) < 0:
        errors.append(f"duration:invalid:{duration!r}")
        duration = None

    times = checkpoints.get("times")
    if not isinstance(times, list) or not times:
        errors.append("times:must-be-non-empty-list")
    else:
        previous: float | None = None
        for index, time in enumerate(times):
            if not _finite_number(time):
                errors.append(f"times[{index}]:invalid:{time!r}")
                continue
            value = float(time)
            if previous is not None and value <= previous:
                errors.append(f"times[{index}]:not-ascending:{value!r}")
            if isinstance(duration, float) and value > duration + DURATION_TOLERANCE:
                errors.append(f"times[{index}]:past-duration:{value!r}")
            previous = value
        if times and _finite_number(times[0]) and float(times[0]) != 0.0:
            errors.append(f"times[0]:not-zero:{times[0]!r}")

    if not is_sha256_hex(checkpoints.get("frames_sha256")):
        errors.append(f"frames_sha256:invalid:{checkpoints.get('frames_sha256')!r}")

    sequence = checkpoints.get("seek_sequence")
    if not isinstance(sequence, list) or not sequence:
        errors.append("seek_sequence:must-be-non-empty-list")
    else:
        for index, time in enumerate(sequence):
            if not _finite_number(time):
                errors.append(f"seek_sequence[{index}]:invalid:{time!r}")
            elif isinstance(duration, float) and not 0.0 <= float(time) <= duration + DURATION_TOLERANCE:
                errors.append(f"seek_sequence[{index}]:out-of-range:{time!r}")

    return sorted(set(errors))


def validate_fixture_lock(lock: Any) -> list[str]:
    """Validate the frozen fixture lock manifest (plan section 9)."""
    errors: list[str] = []
    if not isinstance(lock, dict):
        return ["fixture-lock:not-an-object"]

    if lock.get("schema") != FIXTURE_LOCK_SCHEMA:
        errors.append(f"schema:expected {FIXTURE_LOCK_SCHEMA!r}")

    version = lock.get("generator_version")
    if not isinstance(version, str) or not version:
        errors.append(f"generator_version:invalid:{version!r}")

    duration = lock.get("duration")
    if not _finite_number(duration) or float(duration) < 0:
        errors.append(f"duration:invalid:{duration!r}")

    for field in ("rhythm_sha256", "package_sha256", "checkpoint_sha256"):
        if not is_sha256_hex(lock.get(field)):
            errors.append(f"{field}:invalid:{lock.get(field)!r}")

    return sorted(set(errors))


__all__ = [
    "CHECKPOINT_SCHEMA",
    "ENTRY_MEMBER",
    "FIXTURE_LOCK_SCHEMA",
    "KNOWN_CAPABILITIES",
    "MANIFEST_MEMBER",
    "MANIFEST_SCHEMA",
    "PROBE_MEMBER",
    "RHYTHM_MEMBER",
    "canonical_manifest_bytes",
    "is_sha256_hex",
    "manifest_duration_errors",
    "package_member_digest",
    "sha256_hex",
    "validate_checkpoints",
    "validate_fixture_lock",
    "validate_manifest",
    "valid_member_path",
]
