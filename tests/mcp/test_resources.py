"""Resource surface tests over an in-process MCP client (plan section 18)."""
import json
from pathlib import Path

import pytest
from mcp import Client

from mcp_support import PRIVATE_AUDIO, PROJECT_A, build_snapshot_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def server(tmp_path: Path):
    return build_snapshot_server(tmp_path)


async def test_manifest_resource_is_summary_without_private_paths(server):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.read_resource(f"beatscope://projects/{PROJECT_A}/manifest")
    assert result.contents[0].mime_type == "application/json"
    text = result.contents[0].text
    data = json.loads(text)
    assert data["project_id"] == PROJECT_A
    assert data["display_name"] == "characterization.wav"
    assert data["bpm"] == 120.0
    assert PRIVATE_AUDIO not in text
    assert "energy" not in data


async def test_rhythm_resource_returns_complete_project(server):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.read_resource(f"beatscope://projects/{PROJECT_A}/rhythm")
    data = json.loads(result.contents[0].text)
    assert data["schema_version"] == "4.0"
    assert len(data["beats"]) == 8
    assert "energy" in data  # the resource is the complete schema v4 JSON


async def test_missing_project_resource_is_an_error_with_guidance(server):
    async with Client(server, raise_exceptions=False) as client:
        with pytest.raises(Exception, match="does not exist"):
            await client.read_resource("beatscope://projects/deadbeefdead/manifest")


async def test_resource_with_malformed_project_id_is_an_error(server):
    async with Client(server, raise_exceptions=False) as client:
        with pytest.raises(Exception, match="project_id"):
            await client.read_resource("beatscope://projects/NOT-A-ID/manifest")


async def test_template_resources_are_listed(server):
    async with Client(server, raise_exceptions=True) as client:
        templates = (await client.list_resource_templates()).resource_templates
    uris = sorted(str(t.uri_template) for t in templates)
    assert uris == [
        "beatscope://projects/{project_id}/manifest",
        "beatscope://projects/{project_id}/rhythm",
    ]
