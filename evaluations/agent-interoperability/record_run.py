"""Run recorder for the frozen cross-Agent interoperability task.

Records `beatscope-agent-run-1` metadata files into ``runs/`` after an
operator has reviewed a generated consumer for secrets and licenses
(plan section 13.2). The recorder is deliberately strict:

- records are validated structurally against ``schema.json`` without a
  jsonschema dependency;
- ``task_sha256`` and ``package_sha256`` are recomputed here and must
  match the frozen ``TASK.md`` and the shared fixture lock;
- any key outside the schema's closed set is rejected, so private
  prompts, credentials, chain of thought, account IDs, and billing
  data cannot enter Git through a record;
- obvious credential-shaped strings are rejected even inside free-text
  fields;
- human interventions must be documented as repairs;
- existing records are never overwritten: evaluation evidence is
  append-only, and removals stay visible in Git history.

Usage:

    python evaluations/agent-interoperability/record_run.py \
        --record candidate.json --confirm-review

Exit codes: 0 written, 1 invalid record, 2 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date as date_type
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
RUNS_DIR = EVAL_DIR / "runs"
SCHEMA_PATH = EVAL_DIR / "schema.json"
TASK_PATH = EVAL_DIR / "TASK.md"
FIXTURE_LOCK_PATH = EVAL_DIR.parents[1] / "examples" / "shared" / "fixture-lock.json"

RUN_SCHEMA = "beatscope-agent-run-1"
INDEX_SCHEMA = "beatscope-agent-run-index-1"

ALLOWED_KEYS = frozenset(
    {
        "schema",
        "agent",
        "model_family",
        "date",
        "task_sha256",
        "package_sha256",
        "framework",
        "attempts",
        "human_interventions",
        "validator",
        "human_repairs",
        "artistic_note",
    }
)
REQUIRED_KEYS = frozenset(
    {
        "schema",
        "agent",
        "model_family",
        "date",
        "task_sha256",
        "package_sha256",
        "framework",
        "attempts",
        "human_interventions",
        "validator",
    }
)
VALIDATOR_KEYS = frozenset({"required", "passed", "failed", "unavailable"})

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Cheap credential-shaped strings; the operator review is the real
# gate, this only stops obvious accidents inside free-text fields.
SECRET_PATTERNS = (
    "sk-",
    "ghp_",
    "gho_",
    "github_pat_",
    "AKIA",
    "xoxb-",
    "BEGIN PRIVATE KEY",
    "api_key=",
    "apikey=",
    "password=",
    "Bearer ",
)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def structural_errors(record: object) -> list[str]:
    """Validate one run record against the frozen schema's contract."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record:must-be-object"]

    if record.get("schema") != RUN_SCHEMA:
        errors.append("schema:must-be " + RUN_SCHEMA)

    unknown = sorted(set(record) - ALLOWED_KEYS)
    if unknown:
        # Closed key set: this is what keeps private material out.
        errors.append("record:forbidden-keys " + ",".join(unknown))
    missing = sorted(REQUIRED_KEYS - set(record))
    if missing:
        errors.append("record:missing-keys " + ",".join(missing))
    if errors:
        return errors

    for field in ("agent", "model_family", "framework"):
        value = record[field]
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}:non-empty-string-required")
    if not DATE_PATTERN.match(str(record["date"])) or not _date_is_real(record["date"]):
        errors.append("date:must-be-YYYY-MM-DD")
    for field in ("task_sha256", "package_sha256"):
        if not isinstance(record[field], str) or not SHA256_PATTERN.match(record[field]):
            errors.append(f"{field}:must-be-lowercase-sha256")
    if not _is_int(record["attempts"]) or record["attempts"] < 1:
        errors.append("attempts:positive-integer-required")
    if not _is_int(record["human_interventions"]) or record["human_interventions"] < 0:
        errors.append("human_interventions:non-negative-integer-required")

    validator = record["validator"]
    if not isinstance(validator, dict) or set(validator) != VALIDATOR_KEYS:
        errors.append("validator:must-have-exactly " + ",".join(sorted(VALIDATOR_KEYS)))
    else:
        for key, value in validator.items():
            if not _is_int(value) or value < 0:
                errors.append(f"validator.{key}:non-negative-integer-required")

    repairs = record.get("human_repairs")
    if repairs is not None:
        if not isinstance(repairs, list) or not all(isinstance(item, str) for item in repairs):
            errors.append("human_repairs:must-be-list-of-strings")
    if record["human_interventions"] > 0 and (
        not isinstance(repairs, list) or not repairs
    ):
        # Plan section 13.4: any human repair is documented.
        errors.append("human_repairs:required-when-human-interventions-positive")

    note = record.get("artistic_note")
    if note is not None and not isinstance(note, str):
        errors.append("artistic_note:must-be-string")
    return errors


def _date_is_real(value: object) -> bool:
    try:
        date_type.fromisoformat(str(value))
    except ValueError:
        return False
    return True


def secret_errors(record: dict) -> list[str]:
    """Scan free-text fields for credential-shaped strings."""
    errors: list[str] = []
    texts: list[tuple[str, str]] = []
    note = record.get("artistic_note")
    if isinstance(note, str):
        texts.append(("artistic_note", note))
    repairs = record.get("human_repairs")
    if isinstance(repairs, list):
        texts.extend((f"human_repairs[{index}]", item) for index, item in enumerate(repairs) if isinstance(item, str))
    for field, text in texts:
        for pattern in SECRET_PATTERNS:
            if pattern in text:
                errors.append(f"{field}:credential-shaped-content")
                break
    return errors


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_index() -> dict:
    if not RUNS_DIR.exists():
        return {"schema": INDEX_SCHEMA, "runs": []}
    runs: list[dict] = []
    for path in sorted(RUNS_DIR.glob("*.json")):
        if path.name == "index.json":
            continue
        runs.append(json.loads(path.read_text(encoding="utf-8")))
    runs.sort(key=lambda run: (run["date"], run["agent"], run["framework"]))
    return {"schema": INDEX_SCHEMA, "runs": runs}


def write_json(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record a reviewed cross-Agent run (metadata only).")
    parser.add_argument("--record", required=True, help="candidate run-record JSON file")
    parser.add_argument(
        "--confirm-review",
        action="store_true",
        help="affirm the generated source was reviewed for secrets and licenses",
    )
    args = parser.parse_args(argv)

    if not args.confirm_review:
        print("error: pass --confirm-review after reviewing generated source for secrets and licenses", file=sys.stderr)
        return 2
    candidate_path = Path(args.record)
    if not candidate_path.is_file():
        print(f"error: record file not found: {args.record}", file=sys.stderr)
        return 2

    try:
        record = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read record: {exc}", file=sys.stderr)
        return 2

    errors = structural_errors(record)
    errors.extend(secret_errors(record) if isinstance(record, dict) else [])
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    task_sha256 = sha256_bytes(TASK_PATH.read_bytes())
    lock = json.loads(FIXTURE_LOCK_PATH.read_text(encoding="utf-8"))
    if record["task_sha256"] != task_sha256:
        print(
            f"error: task_sha256 does not match frozen TASK.md ({task_sha256}); the task or record is stale",
            file=sys.stderr,
        )
        return 1
    if record["package_sha256"] != lock["package_sha256"]:
        print(
            f"error: package_sha256 does not match the shared fixture lock ({lock['package_sha256']})",
            file=sys.stderr,
        )
        return 1

    slug_source = f"{record['agent']}-{record['framework']}-{record['date']}".lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug_source).strip("-")
    target = RUNS_DIR / f"{slug}.json"
    if target.exists():
        # Evidence is append-only; overwriting would hide a prior run.
        print(f"error: run record already exists: {target}", file=sys.stderr)
        return 1

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(target, record)
    write_json(RUNS_DIR / "index.json", load_index())
    print(f"recorded: {target}")
    print(f"index:    {RUNS_DIR / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
