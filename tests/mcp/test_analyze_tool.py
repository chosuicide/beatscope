"""beatscope_analyze_audio: cache integration, validation, progress, cancellation.

Plan section 12 + section 27 Commit 5 acceptance: first analysis and cache
hit both work through MCP, and multiple configurations coexist without
overwriting each other.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest
from mcp import Client

import beatscope.mcp.service as service_module
from beatscope.mcp.errors import AnalysisCancelledError, AnalysisFailed
from beatscope.mcp.models import AnalyzeAudioInput
from beatscope.pipeline import AnalysisCancelled as PipelineCancelled
from mcp_support import create_server_for_settings

pytestmark = pytest.mark.anyio


def _audio_roots(env, *paths) -> tuple[Path, ...]:
    return (env.tmp_path, *(Path(p).parent for p in paths))


def _expected_project_id(audio: str) -> str:
    return hashlib.sha256(Path(audio).read_bytes()).hexdigest()[:12]


async def _analyze(client, **kwargs) -> dict:
    result = await client.call_tool("beatscope_analyze_audio", kwargs)
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


async def test_analyze_then_cache_hit_via_mcp(mcp_env, fixed_120_audio):
    settings = mcp_env.settings(allowed_roots=_audio_roots(mcp_env, fixed_120_audio))
    async with Client(create_server_for_settings(settings), raise_exceptions=True) as client:
        first = await _analyze(client, audio_path=str(fixed_120_audio))
        assert first["ok"] is True
        assert first["cache_hit"] is False
        assert first["project_id"] == _expected_project_id(str(fixed_120_audio))
        assert first["source"]["display_name"] == "fixed-120.wav"
        assert 115 <= first["tempo"]["global_bpm"] <= 125
        assert first["grid"]["bars"] >= 1
        assert first["grid"]["subdivision"] == 16
        assert first["counts"]["beats"] > 0
        assert first["counts"]["onsets"] > 0
        assert first["analysis"]["backend"] == "lightweight"
        assert first["analysis"]["separation_used"] is False
        assert isinstance(first["warnings"], list)

        second = await _analyze(client, audio_path=str(fixed_120_audio))
        assert second["cache_hit"] is True
        assert second["project_id"] == first["project_id"]

        # The fresh project is immediately visible to the read-only surface.
        listed = await client.call_tool("beatscope_list_projects", {})
        payload = json.loads(listed.content[0].text)
        assert first["project_id"] in {p["project_id"] for p in payload["projects"]}


async def test_subdivision_variants_coexist(mcp_env, fixed_120_audio):
    # Large budget: the analyzed rhythm's energy arrays exceed the default,
    # and this test reads the full JSON to check which variant is active.
    settings = mcp_env.settings(
        max_response_chars=500000, allowed_roots=_audio_roots(mcp_env, fixed_120_audio)
    )
    async with Client(create_server_for_settings(settings), raise_exceptions=True) as client:
        p16 = await _analyze(client, audio_path=str(fixed_120_audio), subdivision=16)
        p32 = await _analyze(client, audio_path=str(fixed_120_audio), subdivision=32)

        # Same audio content, different analysis configuration: both cached.
        assert p32["project_id"] == p16["project_id"]
        assert p32["cache_hit"] is False
        assert p32["grid"]["subdivision"] == 32

        async def root_subdivision() -> int:
            project = await client.call_tool(
                "beatscope_get_project",
                {"project_id": p16["project_id"], "detail": "full"},
            )
            data = json.loads(project.content[0].text)["data"]
            return data["grid"]["default_subdivision"]

        assert await root_subdivision() == 32  # last analyzed variant is active

        again16 = await _analyze(client, audio_path=str(fixed_120_audio), subdivision=16)
        assert again16["cache_hit"] is True
        assert again16["grid"]["subdivision"] == 16
        assert await root_subdivision() == 16  # re-hit re-activated the 16 variant


async def test_beat_this_requires_beat_file(mcp_env, fixed_120_audio):
    settings = mcp_env.settings(allowed_roots=_audio_roots(mcp_env, fixed_120_audio))
    async with Client(create_server_for_settings(settings), raise_exceptions=False) as client:
        result = await client.call_tool(
            "beatscope_analyze_audio",
            {"audio_path": str(fixed_120_audio), "backend": "beat-this"},
        )
        assert result.is_error
        assert "beat_file" in result.content[0].text


async def test_beat_this_with_beat_file(mcp_env, fixed_120_audio, beat_file):
    settings = mcp_env.settings(allowed_roots=_audio_roots(mcp_env, fixed_120_audio, beat_file))
    async with Client(create_server_for_settings(settings), raise_exceptions=True) as client:
        result = await _analyze(
            client,
            audio_path=str(fixed_120_audio),
            backend="beat-this",
            beat_file=str(beat_file),
        )
        assert result["cache_hit"] is False
        assert result["analysis"]["backend"] == "beat-this"
        assert result["counts"]["beats"] > 0


async def test_changed_beat_file_does_not_reuse_stale_cache(
    mcp_env, fixed_120_audio, beat_file
):
    alternate = mcp_env.tmp_path / "alternate.beats"
    lines = beat_file.read_text(encoding="utf-8").splitlines()
    timestamp, beat_number = lines[1].split(maxsplit=1)
    lines[1] = f"{float(timestamp) + 0.01:.6f} {beat_number}"
    alternate.write_text("\n".join(lines) + "\n", encoding="utf-8")
    settings = mcp_env.settings(
        allowed_roots=_audio_roots(mcp_env, fixed_120_audio, beat_file, alternate)
    )
    async with Client(create_server_for_settings(settings), raise_exceptions=True) as client:
        first = await _analyze(
            client,
            audio_path=str(fixed_120_audio),
            backend="beat-this",
            beat_file=str(beat_file),
        )
        repeated = await _analyze(
            client,
            audio_path=str(fixed_120_audio),
            backend="beat-this",
            beat_file=str(beat_file),
        )
        changed = await _analyze(
            client,
            audio_path=str(fixed_120_audio),
            backend="beat-this",
            beat_file=str(alternate),
        )

    assert first["cache_hit"] is False
    assert repeated["cache_hit"] is True
    assert changed["cache_hit"] is False


def test_drums_path_requires_beat_this_backend():
    with pytest.raises(ValueError, match="drums_path is only valid"):
        AnalyzeAudioInput(audio_path="song.wav", drums_path="drums.wav")


async def test_path_outside_allowed_roots_is_rejected(mcp_env, fixed_120_audio):
    # Deliberately do NOT include the fixture directory in the roots.
    settings = mcp_env.settings(allowed_roots=(mcp_env.tmp_path,))
    async with Client(create_server_for_settings(settings), raise_exceptions=False) as client:
        result = await client.call_tool(
            "beatscope_analyze_audio", {"audio_path": str(fixed_120_audio)}
        )
        assert result.is_error
        assert "allowed roots" in result.content[0].text


async def test_progress_reports_and_completes(mcp_env, fixed_120_audio):
    service = mcp_env.service(allowed_roots=_audio_roots(mcp_env, fixed_120_audio))
    events: list[tuple[float, str | None]] = []

    async def sink(value: float, message: str | None = None) -> None:
        events.append((float(value), message))

    request = AnalyzeAudioInput(audio_path=str(fixed_120_audio))
    result = await service.analyze_audio(request, progress=sink)
    assert result["cache_hit"] is False
    assert events, "no progress events reached the sink"
    values = [value for value, _ in events]
    assert values == sorted(values), "progress went backwards"
    assert events[-1] == (1.0, "Analysis complete")

    # Second run is a cache hit and reports exactly one final event.
    events.clear()
    await service.analyze_audio(request, progress=sink)
    assert events == [(1.0, "Loaded from cache")]


async def test_task_cancellation_writes_nothing(mcp_env, monkeypatch):
    audio = mcp_env.tmp_path / "long-stem.wav"
    audio.write_bytes(b"RIFF-fake-bytes")
    project_id = hashlib.sha256(audio.read_bytes()).hexdigest()[:12]

    entered = threading.Event()
    saw_cancel: list[bool] = []

    def slow_analyze(audio_path, cfg, **kwargs):
        entered.set()
        cancelled = kwargs["cancelled"]
        for _ in range(200):
            if cancelled():
                saw_cancel.append(True)
                raise PipelineCancelled()
            time.sleep(0.01)
        raise AssertionError("fake analysis was never cancelled")

    monkeypatch.setattr(service_module, "analyze_track", slow_analyze)
    service = mcp_env.service()
    task = asyncio.create_task(service.analyze_audio(AnalyzeAudioInput(audio_path=str(audio))))

    for _ in range(100):
        if entered.is_set():
            break
        await asyncio.sleep(0.01)
    assert entered.is_set(), "worker thread never started"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.05)  # the abandoned thread observes the event on its own
    assert saw_cancel, "cancellation event never reached the worker thread"
    assert not (mcp_env.cache_root / "projects" / project_id / "rhythm.json").exists()


async def test_pipeline_cancel_maps_to_analysis_cancelled(mcp_env, monkeypatch):
    audio = mcp_env.tmp_path / "cancelled.wav"
    audio.write_bytes(b"RIFF-fake-bytes")

    def instant_cancel(*args, **kwargs):
        raise PipelineCancelled()

    monkeypatch.setattr(service_module, "analyze_track", instant_cancel)
    service = mcp_env.service()
    with pytest.raises(AnalysisCancelledError, match="nothing was written"):
        await service.analyze_audio(AnalyzeAudioInput(audio_path=str(audio)))

    project_dir = mcp_env.cache_root / "projects" / _expected_project_id(str(audio))
    assert not (project_dir / "rhythm.json").exists()


async def test_pipeline_failure_maps_to_analysis_failed(mcp_env, monkeypatch):
    audio = mcp_env.tmp_path / "broken.wav"
    audio.write_bytes(b"RIFF-fake-bytes")

    def boom(*args, **kwargs):
        raise ValueError("corrupt waveform")

    monkeypatch.setattr(service_module, "analyze_track", boom)
    service = mcp_env.service()
    with pytest.raises(AnalysisFailed, match="corrupt waveform"):
        await service.analyze_audio(AnalyzeAudioInput(audio_path=str(audio)))
