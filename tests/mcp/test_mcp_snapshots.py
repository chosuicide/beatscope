"""Snapshot pinning of the MCP protocol surface (plan section 22).

Snapshots live in ``tests/mcp/snapshots/`` and only change when someone runs
``python tests/record_mcp_snapshots.py`` explicitly. A failing comparison here
means the tool/resource contract changed and must be a conscious decision.
"""
import json
from pathlib import Path

import pytest
from mcp import Client

from mcp_support import PROJECT_A, build_snapshot_server, capture_snapshots
from snapshot_utils import diff_snapshots

pytestmark = pytest.mark.anyio

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


def _load(name: str) -> dict:
    return json.loads((SNAPSHOT_DIR / f"{name}.json").read_text(encoding="utf-8"))


async def test_snapshots_pin_tools_resources_and_project_response(tmp_path: Path):
    captured = await capture_snapshots(tmp_path)
    problems = []
    for name, actual in captured.items():
        diffs = diff_snapshots(_load(name), actual)
        problems += [f"{name}: {diff}" for diff in diffs]
    assert not problems, "MCP surface changed; run tests/record_mcp_snapshots.py if intended:\n" + "\n".join(problems)


async def test_captured_surface_leaks_no_private_paths(tmp_path: Path):
    captured = await capture_snapshots(tmp_path)
    text = json.dumps(captured, ensure_ascii=False)
    # The analyze tool's input schema legitimately names an audio_path
    # *parameter*; what must never appear is a private local path value.
    assert "X:/private" not in text
    assert "audio.wav" not in text
    assert str(tmp_path) not in text


async def test_snapshot_server_reports_expected_identity(tmp_path: Path):
    server = build_snapshot_server(tmp_path)
    async with Client(server, raise_exceptions=True) as client:
        assert client.server_info.name == "beatscope_mcp"
        result = await client.read_resource("beatscope://schema/v4")
    assert json.loads(result.contents[0].text)["schema_version"].startswith("4.")
    assert PROJECT_A  # referenced by the snapshots
