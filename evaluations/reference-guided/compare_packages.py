"""Verify baseline/current handoffs refer to the same song and exact beat/onset times."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def facts(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        rhythm = json.loads(archive.read("rhythm-map.json"))
        return {
            "source_sha256": rhythm["source"]["sha256"],
            "beats": [(beat.get("id"), beat.get("time")) for beat in rhythm.get("beats", [])],
            "onsets": [(onset.get("id"), onset.get("time", onset.get("raw_time"))) for onset in rhythm.get("onsets", [])],
            "agent_doc_sha256": hashlib.sha256(archive.read("AGENT.md")).hexdigest(),
            "members": len(archive.namelist()),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    args = parser.parse_args()
    old, new = facts(args.baseline), facts(args.current)
    report = {
        "same_audio": old["source_sha256"] == new["source_sha256"],
        "same_beats": old["beats"] == new["beats"],
        "same_onsets": old["onsets"] == new["onsets"],
        "distinct_agent_instructions": old["agent_doc_sha256"] != new["agent_doc_sha256"],
        "baseline_members": old["members"],
        "current_members": new["members"],
    }
    print(json.dumps(report, indent=2))
    return 0 if all(report[key] for key in ("same_audio", "same_beats", "same_onsets", "distinct_agent_instructions")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
