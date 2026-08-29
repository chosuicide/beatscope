"""Shared support for MCP tests and the snapshot recorder.

Deliberately *not* named conftest: pytest imports the repo's other conftest.py
files as module "conftest", so helpers must live in a uniquely named module.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from beatscope.mcp.paths import MCPSettings, PathPolicy
from beatscope.mcp.service import BeatScopeService
from beatscope.project import ProjectManager

TESTS_DIR = Path(__file__).resolve().parents[1]
FIXTURE_RHYTHM = TESTS_DIR / "fixtures" / "runtime" / "characterization-project.json"

PROJECT_A = "0a1b2c3d4e5f"  # characterization.wav, 2026-08-29
PROJECT_B = "0b2c3d4e5f60"  # second-demo.wav, 2026-08-30 (newer)
PRIVATE_AUDIO = "X:/private/audio.wav"


def seed_project(
    cache_root: Path,
    *,
    project_id: str,
    display_name: str,
    created_at: str,
    mutate: Callable[[dict], None] | None = None,
) -> None:
    """Write one deterministic project (rhythm.json + project.json) into the cache."""
    rhythm = json.loads(FIXTURE_RHYTHM.read_text(encoding="utf-8"))
    rhythm["project_id"] = project_id
    rhythm["source"]["display_name"] = display_name
    rhythm["analysis"]["created_at"] = created_at
    if mutate is not None:
        mutate(rhythm)
    p_dir = cache_root / "projects" / project_id[:12]
    p_dir.mkdir(parents=True, exist_ok=True)
    (p_dir / "rhythm.json").write_text(json.dumps(rhythm, ensure_ascii=False), encoding="utf-8")
    meta = {
        "project_id": project_id[:12],
        "audio_path": PRIVATE_AUDIO,
        "display_name": display_name,
        "created_at": created_at,
        "cache_key": "test-cache-key",
    }
    (p_dir / "project.json").write_text(json.dumps(meta), encoding="utf-8")


class McpEnv:
    """Temp cache plus the service/policy/settings built on it."""

    def __init__(self, cache_root: Path, tmp_path: Path) -> None:
        self.cache_root = cache_root
        self.tmp_path = tmp_path
        self.projects = ProjectManager(cache_root)
        self.paths = PathPolicy([tmp_path])

    def seed(
        self,
        project_id: str = PROJECT_A,
        display_name: str = "characterization.wav",
        created_at: str = "2026-08-29T00:00:00Z",
        mutate: Callable[[dict], None] | None = None,
    ) -> None:
        seed_project(
            self.cache_root,
            project_id=project_id,
            display_name=display_name,
            created_at=created_at,
            mutate=mutate,
        )

    def service(self, max_response_chars: int = 25000, allowed_roots=None) -> BeatScopeService:
        roots = allowed_roots if allowed_roots is not None else (self.tmp_path,)
        return BeatScopeService(
            self.projects, PathPolicy(roots), runtime=None, max_response_chars=max_response_chars
        )

    def settings(self, max_response_chars: int = 25000, allowed_roots=None) -> MCPSettings:
        return MCPSettings(
            cache_root=self.cache_root,
            allowed_roots=(allowed_roots if allowed_roots is not None else (self.tmp_path,)),
            node_command="node",
            max_response_chars=max_response_chars,
            log_level="WARNING",
        )


def build_snapshot_server(tmp_root: Path):
    """A server over a deterministic single-project cache: fixed ids, no timestamps."""
    cache_root = tmp_root / "cache"
    seed_project(
        cache_root,
        project_id=PROJECT_A,
        display_name="characterization.wav",
        created_at="2026-08-29T00:00:00Z",
    )
    return create_server_for_settings(
        MCPSettings(
            cache_root=cache_root,
            allowed_roots=(tmp_root,),
            node_command="node",
            max_response_chars=25000,
            log_level="WARNING",
        )
    )


def create_server_for_settings(settings: MCPSettings):
    # Imported here so unit tests that only need the service layer do not
    # pay for the MCP SDK import at module load.
    from beatscope.mcp.server import create_server

    return create_server(settings)


def _strip_private(model: Any) -> dict[str, Any]:
    data = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    data.pop("_meta", None)  # server-private metadata must not pin snapshots
    return data


async def capture_snapshots(tmp_root: Path) -> dict[str, Any]:
    """Capture the pinned MCP surface: tools, resources, one project response.

    Everything here is deterministic: fixed fixture project, fixed ids, no
    timestamps or machine paths in any captured payload.
    """
    from mcp import Client

    server = build_snapshot_server(tmp_root)
    async with Client(server, raise_exceptions=True) as client:
        tools = sorted(
            (_strip_private(t) for t in (await client.list_tools()).tools),
            key=lambda t: t["name"],
        )
        static = sorted(
            (_strip_private(r) for r in (await client.list_resources()).resources),
            key=lambda r: str(r["uri"]),
        )
        templates = sorted(
            (_strip_private(t) for t in (await client.list_resource_templates()).resource_templates),
            key=lambda t: str(t["uriTemplate"]),
        )
        summary = json.loads(
            (await client.call_tool("beatscope_get_project", {"project_id": PROJECT_A})).content[0].text
        )
    return {
        "tools": tools,
        "resources": {"static": static, "templates": templates},
        "project-summary": summary,
    }
