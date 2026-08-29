"""In-process MCP contract test for the server identity (plan section 23.2)."""
import json

import pytest

from mcp import Client

from beatscope.mcp.server import SERVER_NAME, create_server

pytestmark = pytest.mark.anyio


async def test_client_connects_and_reads_schema_resource() -> None:
    server = create_server()
    async with Client(server, raise_exceptions=True) as client:
        info = client.server_info
        assert info.name == SERVER_NAME

        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == {
            "beatscope_list_projects",
            "beatscope_get_project",
            "beatscope_get_visual_state",
            "beatscope_get_events",
        }

        resources = (await client.list_resources()).resources
        assert [str(r.uri) for r in resources] == ["beatscope://schema/v4"]

        result = await client.read_resource("beatscope://schema/v4")
        payload = json.loads(result.contents[0].text)
        assert payload["schema_version"].startswith("4.")
