"""Mechanism test only: synthetic media here are not real Agent evaluation runs."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from beatscope.exports import generate_codex_export

ROOT = Path(__file__).resolve().parents[1]
RECORDER = ROOT / "evaluations" / "reference-guided" / "record_run.py"
HELPER = ROOT / "beatscope" / "agent_skill" / "reference-tools.mjs"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module():
    spec = importlib.util.spec_from_file_location("reference_run_recorder", RECORDER)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_frozen_reference_cases_are_distinct_and_publish_no_local_paths():
    here = ROOT / "evaluations" / "reference-guided"
    text = (here / "cases.json").read_text(encoding="utf-8")
    cases = json.loads(text)
    assert cases["generation"] == 1
    assert {case["id"] for case in cases["cases"]} == {"editorial-image", "voxel-state"}
    assert len({case["reference"]["sha256"] for case in cases["cases"]}) == 2
    assert all(len(case["reference"]["sha256"]) == 64 for case in cases["cases"])
    assert "E:\\" not in text and "C:\\" not in text and "D:\\" not in text
    task = (here / "TASK.md").read_text(encoding="utf-8")
    assert "10-second" in task and "The attached video is a visual reference" in task
    assert "portrait holds" not in task and "central geometric" not in task


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("node"), reason="FFmpeg and Node are needed")
def test_run_recorder_requires_real_files_and_writes_path_free_append_only_summary(tmp_path: Path):
    reference = tmp_path / "reference.mp4"
    preview = tmp_path / "preview.mp4"
    for target, color, length in ((reference, "red", 2), (preview, "blue", 10)):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=24:d={length}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)],
            check=True, timeout=30,
        )
    audio = tmp_path / "target.wav"
    audio.write_bytes(b"synthetic test audio bytes; not playable")
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"synthetic media asset")
    source = tmp_path / "source.js"
    source.write_text("export const frame = (time) => time;\n", encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text('{"motion":"steady"}\n', encoding="utf-8")
    task = tmp_path / "TASK.md"
    task.write_text("Synthetic mechanism test only.\n", encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({
        "target_audio": {"sha256": digest(audio)},
        "cases": [{"id": "test-case", "reference": {"sha256": digest(reference)}, "assets": [{"id": "asset", "sha256": digest(asset)}]}],
    }), encoding="utf-8")
    rhythm = {
        "project_id": "aabbccddeeff", "schema_version": "4.0",
        "source": {"display_name": "target.wav", "duration": 10, "sha256": digest(audio), "sample_rate": 22050, "channels": 1},
        "tempo": {"global_bpm": 120}, "grid": {"origin": 0, "bars": 5, "default_subdivision": 16},
        "beats": [{"id": n, "time": n * 0.5, "bar": n // 4 + 1, "beat_in_bar": n % 4 + 1} for n in range(20)],
        "onsets": [{"id": 1, "time": 0.5, "strength": 0.8, "bands": {"all": 0.8, "low": 0.5, "mid": 0.2, "high": 0.1}, "accent": True}],
        "energy": {"bands": {"all": [], "low": [], "mid": [], "high": []}},
    }
    package = tmp_path / "timing.zip"
    package.write_bytes(generate_codex_export(rhythm, include_response_relevance=False))
    with zipfile.ZipFile(io.BytesIO(package.read_bytes())) as archive:
        assert json.loads(archive.read("rhythm-map.json"))["source"]["sha256"] == digest(audio)
        timing = tmp_path / "timing.json"
        timing.write_bytes(archive.read("rhythm-map.json"))
    plan.write_text(json.dumps({
        "schema": "beatscope-film-plan-1", "duration": 10, "work_interval": [0, 10], "render_interval": [0, 10],
        "concept": {"subject": "field", "development": "sustained field"},
        "timing_source": {"path": "timing.json", "sha256": digest(timing)},
        "sections": [{"id": "a", "interval": [0, 10], "purpose": "sustain", "continuity": "same color"}],
        "shots": [{"id": "hold", "section_id": "a", "interval": [0, 10], "subject": "field", "purpose": "hold", "composition": "full frame", "material": "test asset", "motion": "none", "entry": {"reason": "opening", "carries": "initial field", "changes": "none"}}],
        "actions": [],
    }), encoding="utf-8")
    sample = tmp_path / "sample.jpg"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0", "-i", str(reference), "-frames:v", "1", str(sample)], check=True, timeout=30)
    review_path = tmp_path / "creative-review.json"
    review = {
        "schema": "beatscope-creative-review-2", "reference_mode": "reference-led",
        "user_request": {"task": "test", "supplied_choices": [], "authorized_assumptions": []},
        "inputs": [
            {"id": "ref", "path": str(reference), "sha256": digest(reference), "roles": ["reference"]},
            {"id": "asset", "path": str(asset), "sha256": digest(asset), "roles": ["usable_asset"]},
        ],
        "observations": [{"id": "o", "reference_id": "ref", "interval": [0, 1], "method": "ordered-frames", "detail": "static red field", "evidence_paths": ["sample.jpg"]}],
        "requirements": [{"id": "r", "observation_ids": ["o"], "instruction": "hold a field", "priority": "critical", "success_criterion": "no cut"}],
        "feature_inventory": [
            {"kind": "persistent-anchor", "status": "observed", "observation_ids": ["o"], "requirement_ids": ["r"]},
            {"kind": "state-sequence", "status": "not_applicable", "reason": "single field"},
            {"kind": "within-state-evolution", "status": "not_applicable", "reason": "held field"},
        ],
        "asset_bindings": [{"requirement_id": "r", "asset_ids": ["asset"], "code_location": "source.js"}],
        "preview": {"path": "preview.mp4", "sha256": digest(preview), "source_path": "source.js", "source_sha256": digest(source), "plan_path": "plan.json", "plan_sha256": digest(plan), "renderer": "ffmpeg"},
        "comparisons": [{"reference_id": "ref", "reference_interval": [0, 1], "preview_interval": [0, 1], "path": "comparison.mp4", "preview_sha256": digest(preview)}],
        "reviews": [{"requirement_id": "r", "status": "matched", "paired_evidence": "comparison.mp4", "result": "mechanism test declaration only"}],
        "sequence_reviews": [{"interval": [0, 10], "method": "ordered-frames", "evidence_path": "preview.mp4", "evidence_sha256": digest(preview), "preview_sha256": digest(preview), "plan_sha256": digest(plan), "checks": {"continuity": "matched", "pacing": "matched", "motion": "matched", "timing": "matched"}, "result": "mechanism test declaration only"}],
        "review": {"level": "self", "user_accepted": False},
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")
    compared = subprocess.run(["node", str(HELPER), "compare", "--record", str(review_path), "--out", "comparison.mp4"], capture_output=True, text=True, timeout=30)
    assert compared.returncode == 0, compared.stderr
    review["comparisons"][0]["sha256"] = digest(tmp_path / "comparison.mp4")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    input_record = {
        "schema": "beatscope-reference-agent-run-1", "case_id": "test-case", "variant": "new", "run_id": "test-1",
        "client": "unit-test", "model": "synthetic", "model_version": "0", "tool_access": "local-test",
        "rerender_command": "ffmpeg synthetic", "interventions": [], "review_level": "self",
        "task_sha256": digest(task), "inputs": {"audio": str(audio), "reference": str(reference), "asset": str(asset)},
        "package_path": str(package), "preview_path": str(preview), "source_path": str(source), "creative_review_path": str(review_path),
    }
    record_path = tmp_path / "run.json"
    record_path.write_text(json.dumps(input_record), encoding="utf-8")
    recorder = module()
    runs = tmp_path / "runs"
    with pytest.raises(ValueError, match="confirm-review"):
        recorder.run_record(record_path, False, runs, cases, task)
    summary = recorder.run_record(record_path, True, runs, cases, task)["summary"]
    assert summary["preview_sha256"] == digest(preview)
    assert str(tmp_path) not in json.dumps(summary)
    with pytest.raises(ValueError, match="append-only"):
        recorder.run_record(record_path, True, runs, cases, task)
    incomplete_record = dict(input_record)
    incomplete_record.update(variant="baseline", run_id="test-2", review_level="none")
    incomplete_record.pop("creative_review_path")
    record_path.write_text(json.dumps(incomplete_record), encoding="utf-8")
    with pytest.raises(ValueError, match="missing review level"):
        recorder.run_record(record_path, True, runs, cases, task)
    incomplete = recorder.run_record(record_path, True, runs, cases, task, allow_incomplete=True)["summary"]
    assert incomplete["evidence_status"] == "incomplete"
    assert incomplete["incomplete_reason"] == "missing_review_record"
    assert incomplete["reference_fidelity"] == "not_verified"
    assert incomplete["comparison_sha256"] == []
    assert incomplete["timing_sha256"] == summary["timing_sha256"]
