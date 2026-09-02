"""Regenerate the normalized conformance reports for the reference consumers.

These reports are the checked-in evidence that CI replays (plan section
13: "CI must replay checked-in outputs but must not call remote
Agents"). Normalization removes the only machine-dependent value in the
report — the OS-specific path separator in ``target`` — and refuses to
write anything that re-introduces machine-specific content.

Each interactive consumer is validated with ``--browser`` semantics and
the offline consumer with ``--offline`` semantics, so every declared
capability layer carries a definitive status. CI installs the pinned
browser tooling, so all three reference consumers must report ``passed``.

Usage:

    python evaluations/agent-interoperability/record_reports.py
    python evaluations/agent-interoperability/record_reports.py --out build/consumer-evidence

Exit codes: 0 written, 1 generation or leakage failure, 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from beatscope.consumer_validation import validate_consumer, validate_handoff  # noqa: E402

REPORTS_DIR = EVAL_DIR / "reports"
SHARED_DIR = REPO_ROOT / "examples" / "shared"
CONSUMERS = (
    ("canvas-particles", True, False),
    ("threejs-geometry", True, False),
    ("remotion-composition", False, True),
)

FORBIDDEN_REPORT_TEXT = ("E:", "D:", "C:", "\\", "/home/", "/Users/", "AppData", "Temp")


def normalize_report(report: dict, target: str) -> dict:
    normalized = dict(report)
    normalized["target"] = target
    return normalized


def assert_portable(document: object, name: str) -> None:
    text = json.dumps(document, ensure_ascii=False)
    for marker in FORBIDDEN_REPORT_TEXT:
        if marker in text:
            raise SystemExit(f"error: report {name} is not portable: contains {marker!r}")


def write_json(path: Path, document: object) -> None:
    assert_portable(document, path.name)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def collect_reports() -> list[tuple[str, dict]]:
    checkpoints = SHARED_DIR / "checkpoints.json"
    reports: list[tuple[str, dict]] = []

    handoff = validate_handoff(SHARED_DIR / "fixture.beatscope", checkpoints=checkpoints)
    handoff = normalize_report(handoff, "examples/shared/fixture.beatscope")
    reports.append(("handoff-fixture.json", handoff))

    for name, browser, offline in CONSUMERS:
        report = validate_consumer(
            REPO_ROOT / "examples" / name,
            browser=browser,
            offline=offline,
            checkpoints=checkpoints,
        )
        reports.append((f"{name}.json", normalize_report(report, f"examples/{name}")))
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate normalized consumer conformance reports.")
    parser.add_argument("--out", default=None, help="write to this directory instead of evaluations/.../reports")
    args = parser.parse_args(argv)

    out_dir = Path(args.out) if args.out else REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, report in collect_reports():
        write_json(out_dir / name, report)
        print(f"report: {out_dir / name} (exit {report['exit_code']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
