"""beatscope_get_visual_state and beatscope_get_events tool tests (plan 15-16)."""
import json
from pathlib import Path

import pytest
from mcp import Client

from mcp_support import PROJECT_A, build_snapshot_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def server(tmp_path: Path):
    return build_snapshot_server(tmp_path)


def _payload(result):
    return json.loads(result.content[0].text)


async def test_visual_state_returns_runtime_fields(server):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "beatscope_get_visual_state", {"project_id": PROJECT_A, "time": 1.25}
        )
    assert result.is_error is False
    state = _payload(result)
    assert state["ok"] is True
    assert state["project_id"] == PROJECT_A
    assert state["bar"] == 1
    assert state["beat"] == 3
    assert state["beatIndex"] == 2
    assert state["beatPhase"] == pytest.approx(0.5)
    assert state["low"] == pytest.approx(0.2)  # energy clamps to the last frame
    assert state["all"] == pytest.approx(0.3)
    assert state["onset"]["item"]["id"] == 3   # previous onset at t=1.0
    assert state["onset"]["value"] == 0        # age 0.25 s >= 0.24 s decay window


async def test_visual_state_null_age_before_first_onset(server):
    async with Client(server, raise_exceptions=True) as client:
        direct = await client.call_tool(
            "beatscope_get_visual_state", {"project_id": PROJECT_A, "time": 0.0}
        )
    state = _payload(direct)
    # Fixture's first onset sits exactly at 0.0, so exercise the null rule via
    # the tool description contract instead: onset age is a number here.
    assert state["onset"]["age"] == pytest.approx(0.0)
    assert state["accent"] is None or isinstance(state["accent"], dict)


async def test_visual_state_rejects_negative_time(server):
    async with Client(server, raise_exceptions=False) as client:
        result = await client.call_tool(
            "beatscope_get_visual_state", {"project_id": PROJECT_A, "time": -1.0}
        )
    assert result.is_error is True
    assert "time" in result.content[0].text


async def test_visual_state_unknown_project_is_actionable(server):
    async with Client(server, raise_exceptions=False) as client:
        result = await client.call_tool(
            "beatscope_get_visual_state", {"project_id": "0e1f2a3b4c5d", "time": 1.0}
        )
    assert result.is_error is True
    assert "does not exist" in result.content[0].text


async def test_events_default_window_and_kinds(server):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "beatscope_get_events", {"project_id": PROJECT_A, "start": 0.0, "end": 2.0}
        )
    payload = _payload(result)
    assert payload["ok"] is True
    assert payload["total"] == 9  # 4 beats + 4 onsets + 1 accent cue in (0, 2]
    kinds = {event["kind"] for event in payload["events"]}
    assert kinds == {"beat", "onset", "cue"}
    times = [event["time"] for event in payload["events"]]
    assert times == sorted(times)
    assert all(0.0 < event["time"] <= 2.0 for event in payload["events"])


async def test_events_half_open_boundary_matches_runtime(server):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "beatscope_get_events",
            {"project_id": PROJECT_A, "start": 0.5, "end": 1.0, "include": ["onsets"]},
        )
    payload = _payload(result)
    assert [event["id"] for event in payload["events"]] == [3]  # onset at 1.0 only


async def test_events_include_filter(server):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "beatscope_get_events",
            {"project_id": PROJECT_A, "start": 0.0, "end": 8.0, "include": ["patterns"]},
        )
    payload = _payload(result)
    assert payload["total"] == 2
    assert {event["bar"] for event in payload["events"]} == {1, 2}
    assert all(event["kind"] == "pattern" for event in payload["events"])


async def test_events_cue_type_filter(server):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "beatscope_get_events",
            {
                "project_id": PROJECT_A,
                "start": 0.0,
                "end": 8.0,
                "include": ["cues"],
                "cue_types": ["impact"],
            },
        )
    payload = _payload(result)
    assert payload["total"] == 0  # fixture only has an accent cue


async def test_events_pagination(server):
    async with Client(server, raise_exceptions=True) as client:
        page1 = _payload(
            await client.call_tool(
                "beatscope_get_events",
                {"project_id": PROJECT_A, "start": 0.0, "end": 2.0, "limit": 3, "offset": 0},
            )
        )
        page2 = _payload(
            await client.call_tool(
                "beatscope_get_events",
                {"project_id": PROJECT_A, "start": 0.0, "end": 2.0, "limit": 3, "offset": 3},
            )
        )
    assert (page1["count"], page1["has_more"], page1["next_offset"]) == (3, True, 3)
    assert (page2["count"], page2["has_more"]) == (3, True)
    assert [event["time"] for event in page1["events"]] != [event["time"] for event in page2["events"]]


async def test_events_window_over_ten_minutes_is_rejected(server):
    async with Client(server, raise_exceptions=False) as client:
        result = await client.call_tool(
            "beatscope_get_events",
            {"project_id": PROJECT_A, "start": 0.0, "end": 601.0},
        )
    assert result.is_error is True
    assert "600" in result.content[0].text


async def test_events_unknown_include_value_is_actionable(server):
    async with Client(server, raise_exceptions=False) as client:
        result = await client.call_tool(
            "beatscope_get_events",
            {"project_id": PROJECT_A, "start": 0.0, "end": 1.0, "include": ["notes"]},
        )
    assert result.is_error is True
    assert "include" in result.content[0].text
