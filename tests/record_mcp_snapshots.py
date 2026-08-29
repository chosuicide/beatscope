"""Regenerate the MCP protocol snapshots in tests/mcp/snapshots/ (plan section 22).

Run explicitly; nothing updates snapshots automatically:

    python tests/record_mcp_snapshots.py           # rewrite the snapshot files
    python tests/record_mcp_snapshots.py --check   # diff only, exit 1 on drift

The captured surface is deterministic: a fixed fixture project (no timestamps,
no machine paths) plus the packaged schema resource. Server-private ``_meta``
is stripped and keys are sorted so diffs stay reviewable.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
for candidate in (TESTS_DIR.parent, TESTS_DIR, TESTS_DIR / "mcp"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import mcp_support  # noqa: E402
from snapshot_utils import diff_snapshots  # noqa: E402

SNAPSHOT_DIR = TESTS_DIR / "mcp" / "snapshots"


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    with tempfile.TemporaryDirectory() as tmp:
        captured = asyncio.run(mcp_support.capture_snapshots(Path(tmp)))

    problems: list[str] = []
    for name, actual in sorted(captured.items()):
        path = SNAPSHOT_DIR / f"{name}.json"
        if check_only:
            if not path.is_file():
                problems.append(f"{name}: snapshot missing, run without --check to record it")
                continue
            expected = json.loads(path.read_text(encoding="utf-8"))
            problems += [f"{name}: {diff}" for diff in diff_snapshots(expected, actual)]
            continue
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(actual, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"recorded {path}")

    if problems:
        print("MCP surface drifted from the recorded snapshots:")
        print("\n".join(problems))
        return 1
    print("OK" if check_only else f"recorded {len(captured)} snapshot file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
