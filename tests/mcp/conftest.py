"""Fixtures for MCP tests; the actual helpers live in mcp_support.py."""
from __future__ import annotations

import pytest

from mcp_support import McpEnv


@pytest.fixture
def mcp_env(tmp_path) -> McpEnv:
    env = McpEnv(tmp_path / "cache", tmp_path)
    env.seed()
    return env
