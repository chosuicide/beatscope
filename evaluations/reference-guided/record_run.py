"""Record one *real* reference-guided Agent run without publishing local paths.

Input JSON stays under ignored build/. This writes an append-only, path-free
summary only after checking file hashes, a playable preview, package timing,
and the job-local reference evidence check. It cannot judge visual fidelity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
HELPER = ROOT / "beatscope" / "agent_skill" / "reference-tools.mjs"
SCHEMA = "beatscope-reference-agent-run-1"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def insist(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run_record(
    record_path: Path,
    confirm_review: bool,
    runs_dir: Path = RUNS,
    cases_file: Path = HERE / "cases.json",
    task_file: Path = HERE / "TASK.md",
    allow_incomplete: bool = False,
) -> dict:
    insist(confirm_review, "operator must use --confirm-review after inspecting real outputs")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    cases = json.loads(cases_file.read_text(encoding="utf-8"))
    insist(record.get("schema") == SCHEMA, "invalid run schema")
    case = next((item for item in cases["cases"] if item["id"] == record.get("case_id")), None)
    insist(case is not None, "unknown case")
    variant = record.get("variant")
    insist(variant in {"baseline", "new"}, "invalid variant")
    run_id = record.get("run_id")
    insist(isinstance(run_id, str) and run_id.isascii() and run_id.replace("-", "").isalnum() and len(run_id) <= 64, "invalid run id")
    for key in ("client", "model", "model_version", "tool_access", "rerender_command"):
        insist(isinstance(record.get(key), str) and bool(record[key].strip()), f"missing {key}")
    for key in ("client", "model", "model_version", "tool_access"):
        insist(re.fullmatch(r"[A-Za-z0-9 ._+/-]{1,100}", record[key]) is not None, f"unsafe public metadata: {key}")
    insist(isinstance(record.get("interventions"), list), "interventions must be a list")
    allowed_levels = {"none", "self", "independent", "user"} if allow_incomplete else {"self", "independent", "user"}
    insist(record.get("review_level") in allowed_levels, "missing review level")
    insist(sha(task_file) == record.get("task_sha256"), "task drift")

    expected = {
        "audio": cases["target_audio"]["sha256"],
        "reference": case["reference"]["sha256"],
        **{item["id"]: item["sha256"] for item in case["assets"]},
    }
    locators = record.get("inputs") or {}
    insist(set(locators) == set(expected), "input IDs differ from frozen case")
    for name, wanted in expected.items():
        insist(sha(Path(locators[name])) == wanted, f"input hash mismatch: {name}")

    package_path = Path(record["package_path"])
    with zipfile.ZipFile(package_path) as archive:
        rhythm = json.loads(archive.read("rhythm-map.json"))
        package_manifest = json.loads(archive.read("beatscope-package.json"))
        insist(package_manifest.get("capabilities", {}).get("scenes") is False, "package contains scenes")
        beats = [(beat.get("id"), beat.get("time")) for beat in rhythm.get("beats", [])]
        onsets = [(onset.get("id"), onset.get("time", onset.get("raw_time"))) for onset in rhythm.get("onsets", [])]
        timing_sha = hashlib.sha256(json.dumps([beats, onsets], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    insist(rhythm.get("source", {}).get("sha256") == expected["audio"], "package belongs to another song")
    preview_path = Path(record["preview_path"])
    preview_sha = sha(preview_path)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "format=duration:stream=width,height", "-of", "json", str(preview_path)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    media = json.loads(probe.stdout)
    duration = float(media.get("format", {}).get("duration") or 0)
    insist(8 <= duration <= 12 and media.get("streams"), "preview is not a playable 8-12 second video")
    source_path = Path(record["source_path"])
    source_sha = sha(source_path)
    review = {}
    comparison_hashes = []
    evidence_status = "incomplete"
    incomplete_reason = "missing_review_record"
    if record.get("creative_review_path"):
        review_path = Path(record["creative_review_path"])
        review = json.loads(review_path.read_text(encoding="utf-8"))
        insist(review.get("review", {}).get("level") == record["review_level"], "review-level conflict")
        insist(review.get("preview", {}).get("sha256") == preview_sha, "review points to another preview")
        insist(review.get("preview", {}).get("source_sha256") == source_sha, "review points to another source")
        check = subprocess.run(
            ["node", str(HELPER), "check", "--record", str(review_path), "--stage", "preview"],
            capture_output=True, text=True, timeout=60,
        )
        insist(check.returncode == 0 or allow_incomplete, f"reference evidence incomplete: {check.stdout or check.stderr}")
        if check.returncode == 0:
            evidence_status = "complete"
            incomplete_reason = None
            comparison_hashes = [sha(review_path.parent / pair["path"]) for pair in review["comparisons"]]
        else:
            incomplete_reason = "review_check_failed"
    else:
        insist(allow_incomplete, "reference evidence incomplete: review record missing")
    summary = {
        "schema": SCHEMA,
        "generation": 1,
        "run_id": run_id,
        "case_id": case["id"],
        "variant": variant,
        "client": record["client"],
        "model": record["model"],
        "model_version": record["model_version"],
        "tool_access": record["tool_access"],
        "task_sha256": record["task_sha256"],
        "input_sha256": expected,
        "package_sha256": sha(package_path),
        "timing_sha256": timing_sha,
        "preview_sha256": preview_sha,
        "preview_duration": duration,
        "source_sha256": source_sha,
        "comparison_sha256": comparison_hashes,
        "evidence_status": evidence_status,
        "incomplete_reason": incomplete_reason,
        "review_level": record["review_level"],
        "intervention_count": len(record["interventions"]),
        "reference_fidelity": "review-recorded-not-automatically-verified" if evidence_status == "complete" else "not_verified",
        "user_accepted": bool(review.get("review", {}).get("user_accepted")),
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    target = runs_dir / f"{case['id']}-{variant}-{run_id}.json"
    insist(not target.exists(), "append-only record already exists")
    paired = sorted(runs_dir.glob(f"{case['id']}-{'new' if variant == 'baseline' else 'baseline'}-*.json"))
    for path in paired:
        existing = json.loads(path.read_text(encoding="utf-8"))
        insist(existing["timing_sha256"] == timing_sha, "paired run uses different beats/onsets")
        insist(existing["input_sha256"] == expected, "paired run uses different inputs")
    target.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"recorded": str(target), "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--confirm-review", action="store_true")
    parser.add_argument("--record-incomplete", action="store_true", help="preserve a real failed attempt without claiming review completion")
    args = parser.parse_args()
    try:
        print(json.dumps(run_record(args.record, args.confirm_review, allow_incomplete=args.record_incomplete), indent=2))
        return 0
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print(f"record rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
