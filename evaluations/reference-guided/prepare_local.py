"""Build a current local timing package for the frozen reference evaluation.

Usage: python evaluations/reference-guided/prepare_local.py --rhythm build/.../target.rhythm.json --out build/.../current.zip
This does not create a baseline package or imply any Agent run took place.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from beatscope.exports import generate_codex_export

HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rhythm", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    rhythm = json.loads(args.rhythm.read_text(encoding="utf-8"))
    if rhythm.get("source", {}).get("sha256") != cases["target_audio"]["sha256"]:
        parser.error("rhythm source hash differs from the frozen target song")
    if args.out.exists():
        parser.error("output already exists; use a new name and keep prior evidence")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = generate_codex_export(rhythm)
    args.out.write_bytes(payload)
    print(json.dumps({"package": str(args.out), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
