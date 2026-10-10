"""Keep the repository skill aligned with the copy shipped in BeatScope exports.

The example under ``examples/shared/fixture.beatscope`` is intentionally excluded:
it is a frozen consumer fixture, not a source copy.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "beatscope" / "agent_skill"
TARGET = ROOT / "skills" / "beatscope-visualizer"
FILES = tuple(Path(name) for name in (
    "SKILL.md", "references/schema.md", "references/directing.md", "references/picture-tools.md",
    "references/handoff-rules.md", "references/complete-example.md",
    "references/rendering.md", "references/common-failures.md",
))
# Keep the relative score/clip links in directing.md valid in both skill copies.
FILES += tuple(Path(f"examples/directing/{name}.{suffix}")
               for name in ("accent", "transition", "transition-late", "buildup", "dense", "pause", "return")
               for suffix in ("json", "mp4"))


def drifted_files() -> list[Path]:
    return [
        relative for relative in FILES
        if not (TARGET / relative).is_file() or (SOURCE / relative).read_bytes() != (TARGET / relative).read_bytes()
    ]


def sync() -> None:
    for relative in FILES:
        destination = TARGET / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / relative, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail instead of updating drifted files")
    args = parser.parse_args()
    drift = drifted_files()
    if not drift:
        print("Agent skill copies are synchronized.")
        return 0
    if args.check:
        print("Agent skill copy drift: " + ", ".join(str(path) for path in drift))
        return 1
    sync()
    print("Synchronized: " + ", ".join(str(path) for path in drift))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
