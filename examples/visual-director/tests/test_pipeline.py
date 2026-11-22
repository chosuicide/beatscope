"""End-to-end tests for BeatScope x Visual Director pipeline."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import struct
import subprocess
import sys
import wave
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_beatscope_repo() -> Path | None:
    env_repo = os.environ.get("BEATSCOPE_REPO")
    if env_repo and (Path(env_repo) / "beatscope").is_dir():
        return Path(env_repo)
    for parent in Path(__file__).resolve().parents:
        if (parent / "beatscope" / "exports.py").is_file():
            return parent
    return None


BEATSCOPE_REPO = _resolve_beatscope_repo()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if BEATSCOPE_REPO is not None and str(BEATSCOPE_REPO) not in sys.path:
    sys.path.insert(0, str(BEATSCOPE_REPO))

from pipeline.anti_cheapness_lint import AntiCheapnessViolation, enforce_lint, scan_file, load_rules
from pipeline.music_state import causal_attack_release_envelope, evaluate_frame_directive, load_timeline
from pipeline.opencv_fx import (
    apply_music_fx,
    composite_alpha_backdrop,
    depth_hard_cutout,
    ordered_halftone_dot_plate,
    radial_whip_zoom_blur,
    unified_media_pass,
)


def test_anti_cheapness_lint_passes_pipeline_and_blocks_banned_apis(tmp_path: Path) -> None:
    enforce_lint([PROJECT_ROOT / "pipeline"], profile="strict-darkroom")

    bad_file = tmp_path / "bad_fx.py"
    bad_file.write_text(
        "import cv2\n"
        "def f(img):\n"
        "    cv2.putText(img, 'ERR 1-07', (10, 20), 0, 1, (255,255,255), 1)\n"
        "    return cv2.GaussianBlur(img, (5, 5), 0)\n",
        encoding="utf-8",
    )
    violations = scan_file(bad_file, load_rules("strict-darkroom"))
    assert len(violations) == 2
    with pytest.raises(AntiCheapnessViolation):
        enforce_lint([bad_file], profile="strict-darkroom")

    # editorial-kinetic allows putText while still blocking GaussianBlur
    ed_violations = scan_file(bad_file, load_rules("editorial-kinetic"))
    assert len(ed_violations) == 1
    assert "GaussianBlur" in ed_violations[0].detail


def test_depth_hard_cutout_eliminates_aa_white_halo() -> None:
    frame = np.full((64, 64, 3), 240, dtype=np.uint8)
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[20:40, 20:40] = 255
    # Simulate 1px bright AA fringe at border
    frame[19, 20:40] = 255
    out = depth_hard_cutout(frame, mask, void_color=(5, 5, 5), dilate_px=2)
    assert np.all(out[18:42, 18:42] == 5)


def test_unified_media_pass_is_seek_deterministic() -> None:
    src = np.full((64, 64, 3), 140, dtype=np.uint8)
    a = unified_media_pass(src, frame_idx=12, burn_level=0.5, grain_fps=6, video_fps=24)
    b = unified_media_pass(src, frame_idx=12, burn_level=0.5, grain_fps=6, video_fps=24)
    assert np.array_equal(a, b)


def test_full_beatscope_to_pipeline_to_mux_loop_synthetic(tmp_path: Path) -> None:
    """Exercise BeatScope export -> bake-timeline.mjs -> run_pipeline(--probe & full) -> render.mjs -> verify.mjs."""
    from beatscope.edit_plan import default_edit_plan
    from beatscope.exports import generate_codex_export

    rhythm = json.loads((BEATSCOPE_REPO / "tests/fixtures/runtime/characterization-project.json").read_text(encoding="utf-8"))
    audio_path = tmp_path / "song.wav"
    sr = 44100
    dur = 8
    with wave.open(str(audio_path), "wb") as wf:
        wf.setparams((1, 2, sr, 0, "NONE", "not compressed"))
        wf.writeframes(b"".join(struct.pack("<h", int(7000 * math.sin(2 * math.pi * 110 * i / sr))) for i in range(dur * sr)))
    rhythm["source"]["sha256"] = hashlib.sha256(audio_path.read_bytes()).hexdigest()

    plan = default_edit_plan(rhythm)
    plan["boundaries"] = [{"id": "s:mid", "time": 1.2}]
    pkg_dir = tmp_path / "timing"
    with zipfile.ZipFile(io.BytesIO(generate_codex_export(rhythm, edit_plan=plan))) as zf:
        zf.extractall(pkg_dir)

    job_dir = tmp_path / "job"
    subprocess.run(["node", str(pkg_dir / "examples/start.mjs"), "--out", str(job_dir), "--seconds", "2"], cwd=pkg_dir, check=True)

    timeline_path = job_dir / "frame-timeline.json"
    subprocess.run(
        [
            "node", str(pkg_dir / "bake-timeline.mjs"),
            "--out", str(timeline_path),
            "--score", str(job_dir / "score.json"),
            "--start", "0", "--seconds", "2", "--fps", "24",
        ],
        cwd=pkg_dir,
        check=True,
    )
    tl = load_timeline(timeline_path)
    d1 = evaluate_frame_directive(tl, 10)
    d2 = evaluate_frame_directive(tl, 10)
    assert d1 == d2

    render_dir = job_dir / "render"
    # 1) --probe gate
    probe_proc = subprocess.run(
        [
            sys.executable, "-m", "pipeline.run_pipeline",
            "--timeline", str(timeline_path),
            "--out-dir", str(render_dir),
            "--package", str(pkg_dir),
            "--backend", "synthetic",
            "--width", "320", "--height", "180",
            "--probe",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    probe_out = json.loads(probe_proc.stdout)
    assert probe_out["mode"] == "probe"
    assert (render_dir / "probe_grid.png").is_file()
    assert (render_dir / "probe_grid_gray.png").is_file()

    # 2) Full chunked render + BeatScope render.mjs + verify.mjs
    mp4_path = job_dir / "preview.mp4"
    full_proc = subprocess.run(
        [
            sys.executable, "-m", "pipeline.run_pipeline",
            "--timeline", str(timeline_path),
            "--out-dir", str(render_dir),
            "--package", str(pkg_dir),
            "--audio", str(audio_path),
            "--score", str(job_dir / "score.json"),
            "--backend", "synthetic",
            "--width", "320", "--height", "180",
            "--chunk-size", "16",
            "--mux-mp4", str(mp4_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    full_out = json.loads(full_proc.stdout)
    assert full_out["frameCount"] == 48
    assert mp4_path.is_file()
    assert full_out["render_report"]["frameCount"] == 48
    assert full_out["verify_report"]["savedStages"] == "matched"
    assert full_out["verify_report"]["audioIdentity"] == "bound by render report"

    # 3) Surgical range re-render + BeatScope --reuse-unchanged (reuses untouched segment!)
    # Modify one frame in the final span (frames 32..47) and re-mux with --reuse-unchanged
    surgical_proc = subprocess.run(
        [
            sys.executable, "-m", "pipeline.run_pipeline",
            "--timeline", str(timeline_path),
            "--out-dir", str(render_dir),
            "--package", str(pkg_dir),
            "--audio", str(audio_path),
            "--backend", "synthetic",
            "--width", "320", "--height", "180",
            "--chunk-size", "16",
            "--start-frame", "32", "--end-frame", "47",
            "--reuse-unchanged",
            "--mux-mp4", str(mp4_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    surgical_out = json.loads(surgical_proc.stdout)
    assert surgical_out["frameCount"] == 16
    assert surgical_out["render_report"]["reusedSegments"] >= 1


def test_v2_envelope_and_hyper_keshiki_operators() -> None:
    # Anti-jitter causal envelope smooths wild 0/1 oscillation while preserving fast attack
    raw = [0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    env = causal_attack_release_envelope(raw, attack_tau=0.01, release_tau=0.25, fps=30.0)
    assert len(env) == len(raw)
    assert env[1] > 0.85  # fast attack
    assert env[2] > 0.70  # smooth release (does not snap straight back to 0!)
    assert env[-1] < env[2]

    # Straight-alpha compositing + light wrap
    bg = np.full((64, 64, 3), (220, 140, 40), dtype=np.uint8)
    fg = np.zeros((64, 64, 4), dtype=np.uint8)
    fg[16:48, 16:48, :3] = (20, 20, 25)
    fg[16:48, 16:48, 3] = 255
    comp = composite_alpha_backdrop(bg, fg, light_wrap=0.10)
    assert comp.shape == (64, 64, 3)
    assert tuple(comp[2, 2]) == (220, 140, 40)
    assert comp[32, 32, 0] < 40

    # Radial whip-zoom blur & ordered halftone print plate
    whipped = radial_whip_zoom_blur(comp, strength=0.6, steps=4)
    assert whipped.shape == comp.shape
    half = ordered_halftone_dot_plate(fg[:, :, :3], fg[:, :, 3], ink_bgr=(255, 66, 22), paper_bgr=(238, 243, 244), cell=6)
    assert half.shape == (64, 64, 3)
    assert tuple(half[2, 2]) == (238, 243, 244)
    assert np.any(np.all(half == np.array([255, 66, 22], dtype=np.uint8), axis=-1))
