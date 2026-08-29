"""stdio subprocess smoke test: the server must start, serve, and exit.

Runs the server as a real child process over stdio with a hard timeout, so a
server that never shuts down fails the test instead of hanging CI.
"""
import json
import sys

import anyio
import pytest

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from beatscope.mcp.server import SERVER_NAME

TOTAL_TIMEOUT = 10.0


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=["-m", "beatscope.mcp.server"])


@pytest.mark.anyio
async def test_stdio_smoke() -> None:
    with anyio.fail_after(TOTAL_TIMEOUT):
        async with Client(_server_params(), raise_exceptions=True) as client:
            assert client.server_info.name == SERVER_NAME
            tool_names = {t.name for t in (await client.list_tools()).tools}
            assert tool_names == {
                "beatscope_list_projects",
                "beatscope_get_project",
                "beatscope_get_visual_state",
                "beatscope_get_events",
                "beatscope_analyze_audio",
                "beatscope_export_package",
            }
            result = await client.read_resource("beatscope://schema/v4")
            assert json.loads(result.contents[0].text)["schema_version"].startswith("4.")
    # Leaving the async with block closes stdin; the child must exit on its own.
