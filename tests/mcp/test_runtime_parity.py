"""Runtime parity: MCP visual state must equal direct runtime.js output.

Direct Node import of runtime.js (what the web player runs) is compared
against beatscope_get_visual_state over the MCP bridge at fixed times
(plan section 23.3). JSON transport rules (Infinity -> null) are applied on
both sides, so everything else must match exactly.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client

from mcp_support import PROJECT_A, build_snapshot_server

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not available"),
]

PARITY_SCRIPT = Path(__file__).resolve().parent / "parity_direct.mjs"

# Before first beat (t=0 with a beat at 0.0), exact beat, between beats,
# 10 ms after an onset, past the decay window, after the last beat (3.5).
PARITY_TIMES = ["0.0", "0.5", "1.25", "0.01", "0.3", "4.2"]


def _direct_states(fixture: Path, times: list[str]) -> list[dict]:
    completed = subprocess.run(
        ["node", str(PARITY_SCRIPT), str(fixture), *times],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


async def test_visual_state_matches_direct_runtime(tmp_path: Path):
    server = build_snapshot_server(tmp_path)
    fixture = tmp_path / "cache" / "projects" / PROJECT_A / "rhythm.json"
    expected = _direct_states(fixture, PARITY_TIMES)

    async with Client(server, raise_exceptions=True) as client:
        actual = []
        for time_text in PARITY_TIMES:  # sequential calls: covers seek-back too
            result = await client.call_tool(
                "beatscope_get_visual_state", {"project_id": PROJECT_A, "time": float(time_text)}
            )
            payload = json.loads(result.content[0].text)
            assert payload.pop("ok") is True
            assert payload.pop("project_id") == PROJECT_A
            actual.append(payload)

    assert actual == expected


async def test_seek_back_matches_direct_runtime(tmp_path: Path):
    server = build_snapshot_server(tmp_path)
    fixture = tmp_path / "cache" / "projects" / PROJECT_A / "rhythm.json"
    late, early = _direct_states(fixture, ["3.0", "0.5"])

    async with Client(server, raise_exceptions=True) as client:
        late_mcp = json.loads(
            (
                await client.call_tool(
                    "beatscope_get_visual_state", {"project_id": PROJECT_A, "time": 3.0}
                )
            ).content[0].text
        )
        early_mcp = json.loads(
            (
                await client.call_tool(
                    "beatscope_get_visual_state", {"project_id": PROJECT_A, "time": 0.5}
                )
            ).content[0].text
        )
    assert early_mcp == {**early, "ok": True, "project_id": PROJECT_A}
    assert late_mcp == {**late, "ok": True, "project_id": PROJECT_A}


def test_parity_script_covers_all_plan_time_classes():
    assert len(PARITY_TIMES) >= 6
    assert "0.01" in PARITY_TIMES  # 10 ms after an onset
    assert "4.2" in PARITY_TIMES   # after the last stored beat
