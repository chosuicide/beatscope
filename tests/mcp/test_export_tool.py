"""beatscope_export_package: ZIP handoff, overwrite rules, atomic write, wheel data.

Plan section 17 + section 27 Commit 6 acceptance: the export contains the
runtime, visual-state, SKILL, and schema reference; the destination gets a
complete ZIP via atomic replace; the wheel ships the packaged data files.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from mcp import Client

from mcp_support import PROJECT_A, create_server_for_settings

pytestmark = pytest.mark.anyio

REQUIRED_PACKAGE_FILES = {
    "rhythm-map.json",
    "beatscope-runtime.js",
    "visual-state.js",
    "BEATSCOPE.md",
    "SKILL.md",
    "references/schema.md",
    "README.md",
}


def _server(mcp_env):
    return create_server_for_settings(mcp_env.settings())


async def _export(client, **kwargs):
    return await client.call_tool("beatscope_export_package", kwargs)


async def test_export_roundtrip_via_mcp(mcp_env, tmp_path: Path):
    destination = tmp_path / "handoff" / "package.zip"
    destination.parent.mkdir()
    async with Client(_server(mcp_env), raise_exceptions=True) as client:
        result = await _export(
            client, project_id=PROJECT_A, destination=str(destination)
        )
    assert not result.is_error, result.content[0].text
    payload = json.loads(result.content[0].text)

    names = {entry["name"] for entry in payload["files"]}
    assert REQUIRED_PACKAGE_FILES <= names
    assert payload["ok"] is True
    assert payload["project_id"] == PROJECT_A
    assert payload["overwritten"] is False

    # The reported metadata matches the file that actually landed on disk.
    assert destination.is_file()
    data = destination.read_bytes()
    assert payload["size_bytes"] == len(data)
    assert payload["sha256"] == hashlib.sha256(data).hexdigest()
    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == names
        rhythm_map = json.loads(archive.read("rhythm-map.json"))
        assert rhythm_map["bpm"]  # agent-facing map is complete
        assert "getVisualState" in archive.read("visual-state.js").decode("utf-8")


async def test_export_requires_overwrite_for_existing_destination(mcp_env, tmp_path: Path):
    destination = tmp_path / "package.zip"
    async with Client(_server(mcp_env), raise_exceptions=False) as client:
        first = await _export(client, project_id=PROJECT_A, destination=str(destination))
        assert not first.is_error

        blocked = await _export(client, project_id=PROJECT_A, destination=str(destination))
        assert blocked.is_error
        assert "overwrite" in blocked.content[0].text

        replaced = await _export(
            client, project_id=PROJECT_A, destination=str(destination), overwrite=True
        )
    assert not replaced.is_error, replaced.content[0].text
    payload = json.loads(replaced.content[0].text)
    assert payload["overwritten"] is True


async def test_export_rejects_non_zip_destination(mcp_env, tmp_path: Path):
    async with Client(_server(mcp_env), raise_exceptions=False) as client:
        result = await _export(
            client, project_id=PROJECT_A, destination=str(tmp_path / "package.txt")
        )
    assert result.is_error
    assert ".zip" in result.content[0].text


async def test_export_destination_outside_roots_is_rejected(mcp_env, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside-roots")
    async with Client(_server(mcp_env), raise_exceptions=False) as client:
        result = await _export(
            client, project_id=PROJECT_A, destination=str(outside / "package.zip")
        )
    assert result.is_error
    assert "allowed roots" in result.content[0].text


async def test_export_missing_project_is_actionable(mcp_env, tmp_path: Path):
    async with Client(_server(mcp_env), raise_exceptions=False) as client:
        result = await _export(
            client, project_id="0e1f2a3b4c5d", destination=str(tmp_path / "package.zip")
        )
    assert result.is_error
    assert "does not exist" in result.content[0].text


async def test_export_leaves_no_temp_files_even_on_failure(mcp_env, tmp_path: Path, monkeypatch):
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    destination = out_dir / "package.zip"

    # Success path: only the final ZIP remains (atomic replace, no leftovers).
    async with Client(_server(mcp_env), raise_exceptions=True) as client:
        await _export(client, project_id=PROJECT_A, destination=str(destination))
    assert {p.name for p in out_dir.iterdir()} == {"package.zip"}

    # Failure path: a crashed payload leaves neither destination nor temp file.
    import beatscope.mcp.service as service_module

    def boom(rhythm, **kwargs):
        raise RuntimeError("zip worker exploded")

    monkeypatch.setattr(service_module, "generate_codex_export", boom)
    async with Client(_server(mcp_env), raise_exceptions=False) as client:
        failed = await _export(client, project_id=PROJECT_A, destination=str(destination))
    assert failed.is_error
    assert {p.name for p in out_dir.iterdir()} == {"package.zip"}


def test_wheel_ships_mcp_package_data(tmp_path: Path):
    """The published wheel must contain every file the server reads at runtime."""
    repo_root = Path(__file__).resolve().parents[2]
    dist = tmp_path / "dist"
    dist.mkdir()
    subprocess.run(
            [sys.executable, "-m", "pip", "wheel", str(repo_root), "--no-deps", "--no-build-isolation",
         "-w", str(dist)],
        check=True, capture_output=True, timeout=240,
    )
    (wheel,) = dist.glob("beatscope-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    required = {
        "beatscope/mcp/runtime_worker.mjs",
        "beatscope/mcp/data/schema_v4.json",
        "beatscope/runtime/runtime.js",
        "beatscope/agent_skill/SKILL.md",
        "beatscope/agent_skill/references/schema.md",
    }
    assert required <= names, sorted(required - names)
