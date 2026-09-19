"""Demo media belongs in release assets, not in the repository.

The clone is large because every demo update added its media to git, and git
keeps it forever: dropping a file in a later commit does not shrink the clone.
This gate stops the bleeding - it fails when a *new* file above the budget is
committed, and the fix is to attach it to a release and link it, which is how
the product tour film is published already.

The two files listed below are the media that predate the gate. They stay: the
point is to stop growth, not to rewrite history.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Tracked files allowed above the budget, with the reason they are exempt.
ALLOWED_OVERSIZED = {
    "docs/demo/beathi-studio.gif": "the studio walkthrough the README embeds",
    "docs/demo/agent-to-film.webp": "the agent-to-film loop the README embeds",
}
BUDGET_BYTES = 1024 * 1024


def oversized_tracked_files(entries: list[tuple[str, int]]) -> dict[str, int]:
    """The tracked files over budget, excluding the ones grandfathered above."""
    return {
        name: size
        for name, size in entries
        if size > BUDGET_BYTES and name not in ALLOWED_OVERSIZED
    }


def tracked_file_sizes() -> list[tuple[str, int]]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\0")
    sizes = []
    for name in listed:
        path = ROOT / name
        if name and path.is_file():
            sizes.append((name, path.stat().st_size))
    return sizes


def test_no_new_tracked_file_exceeds_the_media_budget():
    try:
        entries = tracked_file_sizes()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - no git around
        pytest.skip("needs a git checkout to know what is tracked")

    offenders = oversized_tracked_files(entries)
    assert not offenders, (
        "these files are over the "
        f"{BUDGET_BYTES // 1024 // 1024} MB budget and are not grandfathered: "
        + ", ".join(f"{name} ({size / 1048576:.1f} MB)" for name, size in sorted(offenders.items()))
        + ". Attach the media to a release and link it instead of committing it; "
        "if it must be tracked, add it to ALLOWED_OVERSIZED with a reason."
    )


def test_the_budget_actually_rejects_something():
    """A gate that cannot fail is not a gate."""
    entries = [("docs/demo/beathi-studio.gif", 6 * 1024 * 1024), ("docs/demo/new-demo.gif", 3 * 1024 * 1024)]
    assert oversized_tracked_files(entries) == {"docs/demo/new-demo.gif": 3 * 1024 * 1024}
