"""Runtime parity: MCP visual state must equal direct runtime.js output.

Direct Node import of runtime.js (what the web player runs) is compared
against beatscope_get_visual_state over the MCP bridge at fixed times
(plan section 23.3). JSON transport rules (Infinity -> null) are applied on
both sides, so everything else must match exactly.
"""
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client

from beatscope.mcp.paths import MCPSettings
from beatscope.project import ProjectManager
from mcp_support import (
    PRIVATE_AUDIO,
    PROJECT_A,
    build_snapshot_server,
    create_server_for_settings,
)

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


def _direct_scene_states(
    fixture: Path, recipe: Path, timeline: Path, times: list[str]
) -> list[dict]:
    completed = subprocess.run(
        ["node", str(PARITY_SCRIPT), str(fixture), "--scene", str(recipe), str(timeline), *times],
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
            payload.pop("visual", None)  # additive v0.8 block; pinned in the scene test below
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
    # The additive visual block rides on both responses; the block itself is
    # pinned against the scene director in the scene parity test below.
    early_mcp.pop("visual")
    late_mcp.pop("visual")
    assert early_mcp == {**early, "ok": True, "project_id": PROJECT_A}
    assert late_mcp == {**late, "ok": True, "project_id": PROJECT_A}


def test_parity_script_covers_all_plan_time_classes():
    assert len(PARITY_TIMES) >= 6
    assert "0.01" in PARITY_TIMES  # 10 ms after an onset
    assert "4.2" in PARITY_TIMES   # after the last stored beat


# --- scene parity: the additive visual block vs scene-director.js (plan 18.1)

async def test_scene_state_matches_direct_runtime(tmp_path: Path):
    server = build_snapshot_server(tmp_path)
    project_dir = tmp_path / "cache" / "projects" / PROJECT_A
    fixture = project_dir / "rhythm.json"
    # Compile and persist the artifacts up front so the direct side and the
    # MCP worker read the same recipe/timeline documents (and fingerprints).
    rhythm = json.loads(fixture.read_text(encoding="utf-8"))
    rhythm["project_id"] = PROJECT_A
    ProjectManager(tmp_path / "cache").ensure_visual_artifacts(rhythm)
    recipe = project_dir / "visual-recipe.json"
    timeline = project_dir / "visual-timeline.json"
    expected = _direct_scene_states(fixture, recipe, timeline, PARITY_TIMES)

    async with Client(server, raise_exceptions=True) as client:
        for time_text, direct in zip(PARITY_TIMES, expected):
            result = await client.call_tool(
                "beatscope_get_visual_state", {"project_id": PROJECT_A, "time": float(time_text)}
            )
            payload = json.loads(result.content[0].text)
            assert payload.pop("ok") is True
            assert payload.pop("project_id") == PROJECT_A
            visual = payload.pop("visual")
            assert payload == direct["at"]
            assert visual == {
                "scene": direct["scene"]["scene"],
                "transition": direct["scene"]["transition"],
                "composition": direct["scene"]["composition"],
            }
            # Structure-level facts the scene contract pins everywhere.
            assert visual["scene"]["family"] == "LEGACY"
            assert visual["transition"]["stage"] in {"idle", "approach", "cross", "settle"}


# --- variable-tempo parity across the tempo seam (plan section 18.3) --------

VARIABLE_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "runtime" / "variable-tempo-project.json"
PROJECT_VARIABLE = "0c3d4e5f6071"  # variable-tempo.wav (pinned v0.6 analysis)

# Mid segment 1, seam -1 ms, seam, seam + 1 ms, midpoint of two unequal beats,
# past the last stored beat: every side of the change point is covered.
VARIABLE_TIMES = ["3.9968", "7.9925", "7.9935", "7.9945", "8.2082", "16.2"]


def _seed_variable_project(cache_root: Path) -> None:
    rhythm = json.loads(VARIABLE_FIXTURE.read_text(encoding="utf-8"))
    rhythm["project_id"] = PROJECT_VARIABLE
    rhythm.setdefault("analysis", {})["created_at"] = "2026-08-30T00:00:00Z"
    project_dir = cache_root / "projects" / PROJECT_VARIABLE
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "rhythm.json").write_text(json.dumps(rhythm, ensure_ascii=False), encoding="utf-8")
    meta = {
        "project_id": PROJECT_VARIABLE,
        "audio_path": PRIVATE_AUDIO,
        "display_name": "variable-tempo.wav",
        "created_at": "2026-08-30T00:00:00Z",
        "cache_key": "variable-cache-key",
    }
    (project_dir / "project.json").write_text(json.dumps(meta), encoding="utf-8")


async def test_variable_tempo_visual_state_matches_direct_runtime(tmp_path: Path):
    cache_root = tmp_path / "cache"
    _seed_variable_project(cache_root)
    fixture = cache_root / "projects" / PROJECT_VARIABLE / "rhythm.json"
    expected = _direct_states(fixture, VARIABLE_TIMES)

    settings = MCPSettings(
        cache_root=cache_root,
        allowed_roots=(tmp_path,),
        node_command="node",
        max_response_chars=25000,
        log_level="WARNING",
    )
    async with Client(create_server_for_settings(settings), raise_exceptions=True) as client:
        actual = []
        for time_text in VARIABLE_TIMES:
            result = await client.call_tool(
                "beatscope_get_visual_state",
                {"project_id": PROJECT_VARIABLE, "time": float(time_text)},
            )
            payload = json.loads(result.content[0].text)
            assert payload.pop("ok") is True
            assert payload.pop("project_id") == PROJECT_VARIABLE
            payload.pop("visual", None)  # additive block; omitted past the last scene
            actual.append(payload)

    assert actual == expected


async def test_runtime_bridge_matches_direct_runtime_across_seam(tmp_path: Path):
    from beatscope.mcp.runtime_bridge import RuntimeBridge, file_fingerprint

    fixture = tmp_path / "variable.rhythm.json"
    fixture.write_text(VARIABLE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    direct = _direct_states(fixture, VARIABLE_TIMES)
    expected = dict(zip(VARIABLE_TIMES, direct))

    bridge = RuntimeBridge()
    await bridge.start()
    try:
        states = await asyncio.gather(*(
            bridge.call(
                "at",
                project=PROJECT_VARIABLE,
                path=str(fixture),
                fingerprint=file_fingerprint(fixture),
                time=float(time_text),
            )
            for time_text in VARIABLE_TIMES
        ))
    finally:
        await bridge.close()

    assert dict(zip(VARIABLE_TIMES, states)) == expected


def test_variable_parity_times_cover_the_change_point():
    rhythm = json.loads(VARIABLE_FIXTURE.read_text(encoding="utf-8"))
    boundary = rhythm["tempo"]["segments"][1]["start"]
    before = boundary - 0.001
    after = boundary + 0.001
    assert str(boundary) in VARIABLE_TIMES
    assert str(before) in VARIABLE_TIMES
    assert str(after) in VARIABLE_TIMES
