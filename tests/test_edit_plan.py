import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from beatscope.edit_plan import (
    default_edit_plan,
    edit_plan_bytes,
    edit_plan_request,
    load_edit_plan,
    validate_edit_plan,
)
from beatscope.exports import generate_codex_export
from beatscope.mv_jobs import MovieJobs

FIXTURE = Path(__file__).parent / "fixtures/runtime/structure-project.json"
PROJECT = "0a1b2c3d4e5f"


def manager(tmp_path):
    rhythm = json.loads(FIXTURE.read_text())
    project = tmp_path / PROJECT
    project.mkdir()
    audio = project / "source.audio"
    audio.write_bytes(b"test")
    return SimpleNamespace(cache_root=tmp_path, get_project_dir=lambda _: project,
                           get_project_rhythm=lambda _: rhythm, get_project_audio_path=lambda _: audio)


def test_saved_overrides_survive_restart_and_export_without_changing_facts(tmp_path):
    projects = manager(tmp_path)
    rhythm = projects.get_project_rhythm(PROJECT)
    before = copy.deepcopy(rhythm)
    status, headers, payload = edit_plan_request(projects, PROJECT)
    assert status == 200 and not (projects.get_project_dir(PROJECT) / "edit-plan.json").exists()
    plan = json.loads(payload)
    plan["boundaries"] = [{"id": "stage:custom", "time": 1.125}]
    plan["cues"] = [{"id": "o:0", "deleted": True}, {"id": "o:1", "time": 2.345}, {"id": "u:custom", "time": 2.399}]
    assert edit_plan_request(projects, PROJECT, edit_plan_bytes(plan))[0] == 428
    status, updated, _ = edit_plan_request(projects, PROJECT, edit_plan_bytes(plan), headers["ETag"])
    assert status == 200
    assert edit_plan_request(projects, PROJECT, payload, headers["ETag"])[0] == 409
    assert load_edit_plan(projects, PROJECT) == plan
    assert rhythm == before
    with zipfile.ZipFile(io.BytesIO(generate_codex_export(rhythm, edit_plan=load_edit_plan(projects, PROJECT)))) as archive:
        assert json.loads(archive.read("edit-plan.json")) == plan
        assert json.loads(archive.read("rhythm-map.json"))["onsets"] == before["onsets"]
        manifest = json.loads(archive.read("beatscope-package.json"))
        assert manifest["capabilities"]["edit_plan"] is True
        assert manifest["integrity"]["members"]["edit-plan.json"] == updated["ETag"].strip('"')


@pytest.mark.parametrize("change", [
    lambda p: p.update(source_sha256="wrong"),
    lambda p: p.update(boundaries=[{"id": "a", "time": 3}, {"id": "b", "time": 2}]),
    lambda p: p.update(cues=[{"id": "o:999999", "time": 1}]),
    lambda p: p.update(cues=[{"id": "u:a", "time": float("nan")}]),
    lambda p: p.update(cues=[{"id": "u:a", "time": True}]),
    lambda p: p.update(cues=[{"id": "u:a", "time": 1}, {"id": "u:a", "time": 2}]),
])
def test_invalid_edits_are_rejected(change):
    rhythm = json.loads(FIXTURE.read_text())
    plan = default_edit_plan(rhythm)
    change(plan)
    with pytest.raises(ValueError):
        validate_edit_plan(plan, rhythm)


def test_render_submission_freezes_plan_and_does_not_reuse_stale_job(tmp_path, monkeypatch):
    projects = manager(tmp_path)
    recorded = []
    monkeypatch.setattr("beatscope.mv_jobs.renderer_tools", lambda: {"available": True})
    monkeypatch.setattr("beatscope.mv_jobs.threading.Thread", lambda **kwargs: SimpleNamespace(start=lambda: recorded.append(kwargs)))
    jobs = MovieJobs(projects)
    job = jobs.submit(PROJECT, seed=1)
    snapshot = recorded[0]["args"][-1]
    assert job["edit_plan_digest"] == hashlib.sha256(edit_plan_bytes(snapshot)).hexdigest()
    plan = copy.deepcopy(snapshot)
    plan["cues"] = [{"id": "u:new", "time": .25}]
    status, headers, _ = edit_plan_request(projects, PROJECT)
    assert status == 200
    edit_plan_request(projects, PROJECT, edit_plan_bytes(plan), headers["ETag"])
    assert snapshot["cues"] == []
    with pytest.raises(RuntimeError):
        jobs.submit(PROJECT, seed=1)
