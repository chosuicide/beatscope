"""Tool surface tests over an in-process MCP client (plan sections 12-13, 23)."""
import json
from pathlib import Path

import pytest
from mcp import Client

from mcp_support import PRIVATE_AUDIO, PROJECT_A, build_snapshot_server

pytestmark = pytest.mark.anyio

TOOL_NAMES = {
    "beatscope_list_projects",
    "beatscope_get_project",
    "beatscope_get_visual_state",
    "beatscope_get_events",
}


@pytest.fixture
def server(tmp_path: Path):
    return build_snapshot_server(tmp_path)


async def test_tool_surface_is_prefixed_and_readonly(server):
    async with Client(server, raise_exceptions=True) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOL_NAMES
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False
        assert tool.annotations.title
        assert tool.description
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert schema["properties"], tool.name


async def test_list_projects_returns_envelope(server):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("beatscope_list_projects", {})
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["ok"] is True
    assert payload["total"] == 1
    project = payload["projects"][0]
    assert project["project_id"] == PROJECT_A
    assert PRIVATE_AUDIO not in result.content[0].text


async def test_get_project_summary_and_timing(server):
    async with Client(server, raise_exceptions=True) as client:
        summary = json.loads(
            (await client.call_tool("beatscope_get_project", {"project_id": PROJECT_A})).content[0].text
        )
        timing = json.loads(
            (
                await client.call_tool(
                    "beatscope_get_project", {"project_id": PROJECT_A, "detail": "timing"}
                )
            ).content[0].text
        )
    assert summary["detail"] == "summary"
    assert summary["data"]["beats"] == 8
    assert "energy" not in summary["data"]
    assert timing["data"]["timing"]["tempo"]["global_bpm"] == 120.0
    assert "energy" not in timing["data"]


async def test_invalid_arguments_map_to_actionable_errors(server):
    async with Client(server, raise_exceptions=False) as client:
        bad_limit = await client.call_tool("beatscope_list_projects", {"limit": 0})
        bad_detail = await client.call_tool(
            "beatscope_get_project", {"project_id": PROJECT_A, "detail": "everything"}
        )
        bad_id = await client.call_tool("beatscope_get_project", {"project_id": "xyz"})
    for result in (bad_limit, bad_detail, bad_id):
        assert result.is_error is True
    assert "limit" in bad_limit.content[0].text
    assert "detail" in bad_detail.content[0].text
    assert "project_id" in bad_id.content[0].text


async def test_missing_project_error_carries_guidance(server):
    async with Client(server, raise_exceptions=False) as client:
        result = await client.call_tool("beatscope_get_project", {"project_id": "0e1f2a3b4c5d"})
    assert result.is_error is True
    text = result.content[0].text
    assert "does not exist" in text
    assert "beatscope_list_projects" in text  # actionable next step


async def test_full_detail_truncates_against_small_budget(tmp_path: Path):
    from beatscope.mcp.server import create_server
    from mcp_support import McpEnv

    env = McpEnv(tmp_path / "cache", tmp_path)
    env.seed()
    tiny_server = create_server(env.settings(max_response_chars=1000))
    async with Client(tiny_server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "beatscope_get_project", {"project_id": PROJECT_A, "detail": "full"}
        )
    payload = json.loads(result.content[0].text)
    assert payload["truncated"] is True
    assert payload["data"] is None
    assert payload["resource"] == f"beatscope://projects/{PROJECT_A}/rhythm"
    assert payload["note"]
