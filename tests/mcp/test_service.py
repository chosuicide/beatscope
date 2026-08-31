"""Unit tests for the protocol-independent service layer (plan section 20)."""
import json

import pytest

from beatscope.mcp.errors import ProjectNotFound
from beatscope.mcp.models import EventsInput, GetProjectInput, ListProjectsInput
from mcp_support import PRIVATE_AUDIO, PROJECT_A, PROJECT_B


def _json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)


def test_list_projects_envelope_and_summary(mcp_env):
    result = mcp_env.service().list_projects(ListProjectsInput())

    assert set(result) == {
        "ok", "summary", "total", "count", "offset", "has_more", "next_offset", "projects",
    }
    assert result["ok"] is True
    assert result["total"] == 1
    assert result["count"] == 1
    assert result["has_more"] is False
    assert result["next_offset"] is None
    project = result["projects"][0]
    assert project["project_id"] == PROJECT_A
    assert project["display_name"] == "characterization.wav"
    assert project["bpm"] == 120.0
    assert project["bars"] == 2
    assert project["duration"] == 8.0
    assert project["backend"] == "lightweight"
    assert project["beats"] == 8
    assert project["onsets"] == 8
    assert project["cues"] == 1
    assert "120 BPM" in result["summary"]


def test_list_projects_never_leaks_private_paths(mcp_env):
    result = mcp_env.service().list_projects(ListProjectsInput())
    text = _json(result)
    assert PRIVATE_AUDIO not in text
    assert str(mcp_env.tmp_path) not in text
    assert "audio_path" not in text


def test_list_projects_sorts_newest_first(mcp_env):
    mcp_env.seed(PROJECT_B, "second-demo.wav", "2026-08-30T00:00:00Z")
    result = mcp_env.service().list_projects(ListProjectsInput())
    assert [p["project_id"] for p in result["projects"]] == [PROJECT_B, PROJECT_A]


def test_list_projects_backend_filter(mcp_env):
    mcp_env.seed(
        PROJECT_B,
        "second-demo.wav",
        "2026-08-30T00:00:00Z",
        mutate=lambda rhythm: rhythm["analysis"].update(backend="beat-this"),
    )
    service = mcp_env.service()
    beat_this = service.list_projects(ListProjectsInput(backend="beat-this"))
    assert [p["project_id"] for p in beat_this["projects"]] == [PROJECT_B]
    lightweight = service.list_projects(ListProjectsInput(backend="lightweight"))
    assert [p["project_id"] for p in lightweight["projects"]] == [PROJECT_A]


def test_list_projects_query_filter(mcp_env):
    mcp_env.seed(PROJECT_B, "second-demo.wav", "2026-08-30T00:00:00Z")
    service = mcp_env.service()
    by_name = service.list_projects(ListProjectsInput(query="second"))
    assert [p["project_id"] for p in by_name["projects"]] == [PROJECT_B]
    by_id = service.list_projects(ListProjectsInput(query=PROJECT_A[:8]))
    assert [p["project_id"] for p in by_id["projects"]] == [PROJECT_A]
    none = service.list_projects(ListProjectsInput(query="zzz-no-match"))
    assert none["total"] == 0
    assert none["projects"] == []
    assert "0 project(s)" in none["summary"]


def test_list_projects_pagination(mcp_env):
    mcp_env.seed(PROJECT_B, "second-demo.wav", "2026-08-30T00:00:00Z")
    mcp_env.seed("0c3d4e5f6071", "third-demo.wav", "2026-08-28T00:00:00Z")
    service = mcp_env.service()
    page1 = service.list_projects(ListProjectsInput(limit=2, offset=0))
    assert (page1["total"], page1["count"]) == (3, 2)
    assert page1["has_more"] is True
    assert page1["next_offset"] == 2
    page2 = service.list_projects(ListProjectsInput(limit=2, offset=2))
    assert (page2["count"], page2["has_more"], page2["next_offset"]) == (1, False, None)
    beyond = service.list_projects(ListProjectsInput(limit=2, offset=99))
    assert (beyond["count"], beyond["has_more"], beyond["next_offset"]) == (0, False, None)


def test_list_projects_skips_broken_cache_entries(mcp_env, capsys):
    service = mcp_env.service()
    # Missing rhythm.json
    (mcp_env.cache_root / "projects" / PROJECT_A / "rhythm.json").unlink()
    assert service.list_projects(ListProjectsInput())["total"] == 0
    # Unreadable rhythm.json
    mcp_env.seed()
    (mcp_env.cache_root / "projects" / PROJECT_A / "rhythm.json").write_text("{broken", encoding="utf-8")
    assert service.list_projects(ListProjectsInput())["total"] == 0
    stderr = capsys.readouterr().err
    assert "beatscope-mcp: skipping" in stderr


def test_get_project_summary_detail(mcp_env):
    result = mcp_env.service().get_project(GetProjectInput(project_id=PROJECT_A))
    assert result["ok"] is True
    assert result["project_id"] == PROJECT_A
    assert result["detail"] == "summary"
    assert result["truncated"] is False
    assert result["resource"] is None
    assert result["note"] is None
    assert result["data"]["onsets"] == 8
    assert "energy" not in result["data"]


def test_get_project_timing_detail(mcp_env):
    result = mcp_env.service().get_project(GetProjectInput(project_id=PROJECT_A, detail="timing"))
    timing = result["data"]["timing"]
    assert len(timing["beats"]) == 8
    assert timing["tempo"]["global_bpm"] == 120.0
    assert timing["grid"]["bars"] == 2
    assert "energy" not in timing
    assert "energy" not in result["data"]


def test_get_project_full_detail(mcp_env):
    result = mcp_env.service().get_project(GetProjectInput(project_id=PROJECT_A, detail="full"))
    assert result["truncated"] is False
    assert result["data"]["schema_version"] == "4.0"
    assert len(result["data"]["onsets"]) == 8
    assert "energy" in result["data"]  # full detail is the complete project


def test_get_project_full_truncates_to_resource(mcp_env):
    service = mcp_env.service(max_response_chars=1000)
    result = service.get_project(GetProjectInput(project_id=PROJECT_A, detail="full"))
    assert result["truncated"] is True
    assert result["data"] is None
    assert result["resource"] == f"beatscope://projects/{PROJECT_A}/rhythm"
    assert "resource" in result["note"]
    assert "beatscope_get_events" in result["note"]


def test_get_project_missing(mcp_env):
    with pytest.raises(ProjectNotFound, match="does not exist"):
        mcp_env.service().get_project(GetProjectInput(project_id="0e1f2a3b4c5d"))


def test_get_project_rejects_unsupported_stored_schema(mcp_env):
    rhythm_file = mcp_env.cache_root / "projects" / PROJECT_A / "rhythm.json"
    rhythm_file.write_text(json.dumps({"schema_version": "9.9"}), encoding="utf-8")
    with pytest.raises(ProjectNotFound, match="cannot be read"):
        mcp_env.service().get_project(GetProjectInput(project_id=PROJECT_A))


def test_get_project_rejects_invalid_stored_project(mcp_env):
    rhythm_file = mcp_env.cache_root / "projects" / PROJECT_A / "rhythm.json"
    rhythm_file.write_text(json.dumps({"schema_version": "4.0", "source": {}}), encoding="utf-8")
    with pytest.raises(ProjectNotFound, match="schema v4 validation"):
        mcp_env.service().get_project(GetProjectInput(project_id=PROJECT_A))


# ------------------------------------------------ v0.7 structure in summaries

def _structure_mutate(rhythm: dict) -> None:
    """Inject a legal v0.7 whole-song structure into the 8 s fixture."""
    rhythm["patterns"]["method"] = "bar-multiview-ssm-v2"
    rhythm["patterns"]["segments"] = [
        {
            "id": "segment-001", "index": 0, "start_bar": 1, "end_bar": 1,
            "start_time": 0.0, "end_time": 4.0, "family": "A", "variant": 0,
            "display_label": "A", "bar_count": 1,
        },
        {
            "id": "segment-002", "index": 1, "start_bar": 2, "end_bar": 2,
            "start_time": 4.0, "end_time": 8.0, "family": "B", "variant": 0,
            "display_label": "B", "bar_count": 1,
        },
    ]
    rhythm["patterns"]["boundaries"] = [
        {"bar": 2, "time": 4.0, "novelty": 0.78, "drivers": {"harmony": 0.83}},
    ]


def test_project_summary_includes_neutral_structure(mcp_env):
    mcp_env.seed(mutate=_structure_mutate)
    result = mcp_env.service().get_project(GetProjectInput(project_id=PROJECT_A, detail="summary"))
    structure = result["data"]["structure"]
    assert structure == {
        "segment_count": 2,
        "families": ["A", "B"],
        "form": "A-B",
        "method": "bar-multiview-ssm-v2",
    }


def test_project_summary_omits_structure_without_segments(mcp_env):
    result = mcp_env.service().get_project(GetProjectInput(project_id=PROJECT_A, detail="summary"))
    assert "structure" not in result["data"]


@pytest.mark.anyio
async def test_get_events_segments_overlap_window_and_leak_no_matrices(mcp_env):
    mcp_env.seed(mutate=_structure_mutate)
    service = mcp_env.service()
    # (start, end] window vs span facts: a segment overlaps when its
    # [start_time, end_time) intersects the window.
    result = await service.get_events(EventsInput(
        project_id=PROJECT_A, start=5.0, end=6.0,
        include={"segments", "boundaries"},
    ))
    kinds = {event["kind"] for event in result["events"]}
    assert kinds == {"segment"}  # no boundary inside (5, 6]
    segment = result["events"][0]
    assert segment == {
        "kind": "segment", "time": 4.0, "end": 8.0,
        "family": "B", "label": "B", "index": 1,
    }

    wide = await service.get_events(EventsInput(
        project_id=PROJECT_A, start=0.0, end=8.0,
        include={"segments", "boundaries"},
    ))
    assert [event["kind"] for event in wide["events"]] == ["segment", "boundary", "segment"]
    boundary = wide["events"][1]
    assert boundary["time"] == 4.0 and boundary["bar"] == 2
    assert boundary["novelty"] == 0.78 and boundary["drivers"] == {"harmony": 0.83}
    # No feature vectors anywhere in the response.
    assert "vector" not in json.dumps(wide)
