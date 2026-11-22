"""Chunked Producer-Consumer BeatScope + Blender + OpenCV rendering orchestrator.

Features:
1. Pre-render AST/regex anti-cheapness gate (profile-configurable).
2. Mandatory 4-frame BeatScope landmark probe mode (--probe -> probe_grid.png + probe_grid_gray.png).
3. Chunk-level Blender Producer (max_workers=1 to prevent GPU OOM) + OpenCV ProcessPoolExecutor Consumer.
4. Direct handoff to BeatScope's render.mjs (--frames-dir) and verify.mjs.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .anti_cheapness_lint import enforce_lint
from .music_state import FrameDirective, build_directive_schedule, evaluate_frame_directive, load_timeline
from .opencv_fx import apply_music_fx

PIPELINE_DIR = Path(__file__).resolve().parent


def find_blender(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_file() else None
    env = os.environ.get("BLENDER_PATH")
    if env and Path(env).is_file():
        return Path(env)
    found = shutil.which("blender")
    if found:
        return Path(found)
    for root in (Path(r"C:\Program Files\Blender Foundation"), Path(r"D:\Program Files\Blender Foundation")):
        if root.is_dir():
            candidates = sorted(root.glob("Blender*/blender.exe"), reverse=True)
            if candidates:
                return candidates[0]
    return None


def _render_synthetic_passes(
    schedule: list[dict[str, Any]],
    passes_dir: Path,
    width: int,
    height: int,
) -> None:
    """Fast deterministic 3-channel synthetic daylight courtyard fallback (for CI/no-Blender dry runs)."""
    passes_dir.mkdir(parents=True, exist_ok=True)
    yy, xx = np.mgrid[0:height, 0:width]
    nx = xx.astype(np.float32) / max(1, width - 1)
    ny = yy.astype(np.float32) / max(1, height - 1)

    for entry in schedule:
        idx = int(entry["frame"])
        jx = float(entry["cam_jitter_x"]) * 60.0
        jy = float(entry["cam_jitter_y"]) * 60.0
        sx = np.clip(nx + jx / width, 0.0, 1.0)
        sy = np.clip(ny + jy / height, 0.0, 1.0)

        # Sunlit tiled wall + concrete floor + harsh diagonal noon louver shadows
        wall = sy < 0.72
        tile_u = (sx * 16.0) % 1.0
        tile_v = (sy * 11.0) % 1.0
        mortar = (tile_u < 0.04) | (tile_v < 0.04)
        shadow_stripe = ((sx * 5.0 + sy * 2.2) % 1.0) < 0.24

        b = np.where(wall, 198, 178).astype(np.float32)
        g = np.where(wall, 212, 190).astype(np.float32)
        r = np.where(wall, 222, 198).astype(np.float32)
        b = np.where(wall & mortar, 92, b)
        g = np.where(wall & mortar, 96, g)
        r = np.where(wall & mortar, 100, r)
        factor = np.where(shadow_stripe, 0.42, 1.08)
        beauty = np.stack([b * factor, g * factor, r * factor], axis=-1)

        # Linear 16-bit depth map: wall ~32000, floor ramps 20000..36000, foreground rail ~9000
        depth = np.where(wall, 32000 + (sx - 0.5) * 4000, 18000 + (1.0 - sy) * 26000)

        # Foreground steel handrail occluder (close depth, protects foreground in depth pixel sort)
        post_l = (np.abs(sx - 0.22) < 0.015) & (sy > 0.36)
        post_r = (np.abs(sx - 0.78) < 0.015) & (sy > 0.36)
        rail_top = (np.abs(sy - (0.42 + 0.04 * sx)) < 0.012) & (sx > 0.16) & (sx < 0.84)
        fg_rail = post_l | post_r | rail_top
        beauty[fg_rail] = np.array([150, 155, 162], dtype=np.float32)
        depth[fg_rail] = 9000

        # Irregular jagged intrusion crack mask behind foreground rail
        mask = np.zeros((height, width), dtype=np.uint8)
        if entry.get("intrusion_visible"):
            seed = int(entry.get("intrusion_seed", 0))
            scale = float(entry.get("intrusion_scale", 1.0))
            cx = int(width * (0.46 + 0.16 * np.sin((seed + 1) * 1.9)))
            cy = int(height * 0.58)
            poly = np.array(
                [
                    [cx - int(18 * scale), cy + int(110 * scale)],
                    [cx + int(34 * scale), cy + int(95 * scale)],
                    [cx + int(12 * scale), cy - int(20 * scale)],
                    [cx + int(52 * scale), cy - int(145 * scale)],
                    [cx + int(6 * scale), cy - int(220 * scale)],
                    [cx - int(24 * scale), cy - int(65 * scale)],
                    [cx - int(42 * scale), cy + int(35 * scale)],
                ],
                dtype=np.int32,
            )
            cv2.fillPoly(mask, [poly], 255)
            mask[fg_rail] = 0
            beauty[mask > 127] = np.array([6, 6, 6], dtype=np.float32)

        beauty_u8 = np.clip(beauty, 0, 255).astype(np.uint8)
        depth_u16 = np.clip(depth, 0, 65535).astype(np.uint16)
        cv2.imwrite(str(passes_dir / f"beauty_{idx:06d}.png"), beauty_u8)
        cv2.imwrite(str(passes_dir / f"depth_{idx:06d}.png"), depth_u16)
        cv2.imwrite(str(passes_dir / f"mask_{idx:06d}.png"), mask)


def _render_blender_chunk(
    blender_exe: Path,
    schedule_chunk: list[dict[str, Any]],
    passes_dir: Path,
    work_dir: Path,
    chunk_id: int,
    width: int,
    height: int,
    samples: int,
) -> None:
    schedule_file = work_dir / f"schedule_chunk_{chunk_id:04d}.json"
    schedule_file.write_text(json.dumps(schedule_chunk, indent=2), encoding="utf-8")
    scene_script = PIPELINE_DIR / "blender_scene.py"
    cmd = [
        str(blender_exe),
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(scene_script),
        "--",
        "--schedule",
        str(schedule_file),
        "--out-dir",
        str(passes_dir),
        "--width",
        str(width),
        "--height",
        str(height),
        "--samples",
        str(samples),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(
            f"Blender chunk {chunk_id} failed (exit {proc.returncode}):\n"
            f"{proc.stderr[-1500:]}\n{proc.stdout[-800:]}"
        )


def _postprocess_frame_worker(payload: tuple[dict[str, Any], str, str, int]) -> str:
    directive_dict, passes_dir_str, frames_dir_str, fps = payload
    idx = int(directive_dict["frame"])
    passes_dir = Path(passes_dir_str)
    frames_dir = Path(frames_dir_str)

    beauty = cv2.imread(str(passes_dir / f"beauty_{idx:06d}.png"), cv2.IMREAD_COLOR)
    depth16 = cv2.imread(str(passes_dir / f"depth_{idx:06d}.png"), cv2.IMREAD_UNCHANGED)
    mask8 = cv2.imread(str(passes_dir / f"mask_{idx:06d}.png"), cv2.IMREAD_GRAYSCALE)
    if beauty is None or depth16 is None or mask8 is None:
        raise FileNotFoundError(f"Missing 3-channel pass PNGs for frame {idx} in {passes_dir}")

    directive = FrameDirective(
        **{
            **directive_dict,
            "pixel_sort_y_frac": tuple(directive_dict["pixel_sort_y_frac"]),
            "pixel_sort_depth_range": tuple(directive_dict["pixel_sort_depth_range"]),
            "cue_hit_ids": tuple(directive_dict["cue_hit_ids"]),
        }
    )
    final_bgr = apply_music_fx(beauty, depth16, mask8, directive, video_fps=fps)
    out_file = frames_dir / f"frame-{idx:06d}.png"
    cv2.imwrite(str(out_file), final_bgr)
    return str(out_file)


def _build_probe_grid(
    frames_dir: Path,
    timeline_path: Path,
    probe_indices: list[int],
    probe_labels: list[str] | None,
    out_grid: Path,
    out_gray: Path,
    reference_tools: Path | None,
    cols: int | None = None,
) -> dict[str, Any]:
    count = len(probe_indices)
    grid_cols = cols if cols is not None else (2 if count <= 4 else (3 if count <= 9 else 4))
    if reference_tools is not None and reference_tools.is_file():
        cmd = [
            "node",
            str(reference_tools),
            "probe-grid",
            "--frames-dir",
            str(frames_dir),
            "--frame-pattern",
            "frame-%06d.png",
            "--timeline",
            str(timeline_path),
            "--frames",
            ",".join(str(i) for i in probe_indices),
            "--cols",
            str(grid_cols),
            "--out",
            str(out_grid),
            "--grayscale-out",
            str(out_gray),
        ]
        if probe_labels:
            cmd += ["--labels", ",".join(probe_labels)]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError(f"reference-tools probe-grid failed: {proc.stderr or proc.stdout}")
        return json.loads(proc.stdout)

    # Pure OpenCV fallback (zero putText calls — stays 100% clean under strict-darkroom lint!)
    tiles = []
    for idx in probe_indices:
        img = cv2.imread(str(frames_dir / f"frame-{idx:06d}.png"), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"Missing probe frame {idx}")
        tiles.append(cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA))
    grid_rows = (count + grid_cols - 1) // grid_cols
    while len(tiles) < grid_cols * grid_rows:
        tiles.append(np.zeros((360, 640, 3), dtype=np.uint8))
    rows_img = [np.hstack(tiles[r * grid_cols : (r + 1) * grid_cols]) for r in range(grid_rows)]
    grid = np.vstack(rows_img)
    cv2.imwrite(str(out_grid), grid)
    gray = cv2.cvtColor(grid, cv2.COLOR_BGR2GRAY)
    cv2.imwrite(str(out_gray), gray)
    return {
        "schema": "beatscope-probe-grid-1",
        "out": str(out_grid),
        "grayscale_out": str(out_gray),
        "grid": {"cols": grid_cols, "rows": grid_rows, "count": count},
        "frames": [{"frame": i} for i in probe_indices],
        "aesthetic_verdict": "not_automatically_determined",
    }


def _find_reference_tools(package_dir: Path | None, explicit: Path | None) -> Path | None:
    if explicit is not None and explicit.is_file():
        return explicit
    if package_dir is not None and (package_dir / "reference-tools.mjs").is_file():
        return package_dir / "reference-tools.mjs"
    env_repo = os.environ.get("BEATSCOPE_REPO")
    if env_repo:
        candidate = Path(env_repo) / "beatscope" / "agent_skill" / "reference-tools.mjs"
        if candidate.is_file():
            return candidate
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "beatscope" / "agent_skill" / "reference-tools.mjs"
        if candidate.is_file():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BeatScope x Visual Director Blender + OpenCV pipeline.")
    parser.add_argument("--timeline", type=Path, required=True, help="Path to beatscope-frame-timeline-1 JSON")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output directory for passes, frames and probes")
    parser.add_argument("--package", type=Path, default=None, help="Unpacked BeatScope timing package directory")
    parser.add_argument("--reference-tools", type=Path, default=None, help="Optional path to BeatScope reference-tools.mjs")
    parser.add_argument("--backend", choices=("blender", "synthetic"), default="blender")
    parser.add_argument("--blender", type=Path, default=None, help="Path to blender executable")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--samples", type=int, default=16, help="Blender EEVEE samples")
    parser.add_argument("--chunk-size", type=int, default=16, help="Frames per Blender chunk")
    parser.add_argument("--workers", type=int, default=max(1, min(6, (os.cpu_count() or 2) - 1)))
    parser.add_argument("--lint-profile", default="universal-baseline", choices=("universal-baseline", "strict-darkroom", "editorial-kinetic", "off"))
    parser.add_argument("--lint-rules", type=Path, default=None)
    parser.add_argument("--probe", action="store_true", help="Render ONLY landmark probe frames (2..16) and build probe_grid.png")
    parser.add_argument("--frames", type=str, default=None, help="Optional comma-separated 2..16 frame indices for --probe")
    parser.add_argument("--cols", type=int, default=None, help="Optional probe grid columns (1..6)")
    parser.add_argument("--probe-tag", type=str, default="", help="Optional suffix (e.g. v2) so probe grids never clobber prior versions")
    parser.add_argument("--start-frame", type=int, default=0, help="First frame index for full/surgical render")
    parser.add_argument("--end-frame", type=int, default=None, help="Last inclusive frame index for full/surgical render")
    parser.add_argument("--reuse-unchanged", action="store_true", help="Pass --reuse-unchanged to BeatScope render.mjs for surgical re-mux")
    parser.add_argument("--mux-mp4", type=Path, default=None, help="Optional MP4 path to mux via BeatScope render.mjs --frames-dir")
    parser.add_argument("--audio", type=Path, default=None, help="Original song audio for BeatScope render.mjs")
    parser.add_argument("--score", type=Path, default=None, help="Optional BeatScope score.json for verify.mjs")
    args = parser.parse_args(argv)

    # 1. Mandatory pre-render anti-cheapness static code gate
    enforce_lint([PIPELINE_DIR], profile=args.lint_profile, custom_rules_path=args.lint_rules)

    timeline = load_timeline(args.timeline)
    window = timeline["window"]
    fps = int(round(float(window["fps"])))
    total_frames = int(window["frameCount"])

    blender_exe: Path | None = None
    if args.backend == "blender":
        blender_exe = find_blender(args.blender)
        if blender_exe is None:
            raise RuntimeError("Blender executable not found; install Blender or pass --blender / --backend synthetic")

    out_dir = args.out_dir.resolve()
    passes_dir = out_dir / "passes"
    work_dir = out_dir / "work"
    passes_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    if args.probe:
        frames_dir = out_dir / "probe_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        if args.frames:
            probe_indices = [int(v.strip()) for v in args.frames.split(",")]
            probe_labels = None
        else:
            picked = timeline.get("probeFrames", [])[:16]
            probe_indices = [int(p["frame"]) for p in picked]
            probe_labels = [str(p.get("role", f"slot {i + 1}")) for i, p in enumerate(picked)]
        if len(probe_indices) < 2 or len(probe_indices) > 16:
            raise ValueError(f"Probe mode requires 2..16 frames, got {probe_indices}")

        schedule = build_directive_schedule(timeline, probe_indices)
        (work_dir / "probe_schedule.json").write_text(json.dumps(schedule, indent=2), encoding="utf-8")

        if args.backend == "blender":
            assert blender_exe is not None
            _render_blender_chunk(blender_exe, schedule, passes_dir, work_dir, 0, args.width, args.height, args.samples)
        else:
            _render_synthetic_passes(schedule, passes_dir, args.width, args.height)

        for entry in schedule:
            _postprocess_frame_worker((entry, str(passes_dir), str(frames_dir), fps))

        suffix = f"_{args.probe_tag}" if args.probe_tag else ""
        grid_path = out_dir / f"probe_grid{suffix}.png"
        gray_path = out_dir / f"probe_grid{suffix}_gray.png"
        for existing in (grid_path, gray_path):
            if existing.exists():
                existing.unlink()
        ref_tools = _find_reference_tools(args.package, args.reference_tools)
        probe_report = _build_probe_grid(frames_dir, args.timeline.resolve(), probe_indices, probe_labels, grid_path, gray_path, ref_tools, cols=args.cols)
        summary = {
            "mode": "probe",
            "backend": args.backend,
            "lint_profile": args.lint_profile,
            "probe_indices": probe_indices,
            "directives": schedule,
            "probe_grid": probe_report,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    # 2. Full or Surgical Range Chunked Producer-Consumer render
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    start_f = max(0, int(args.start_frame))
    end_f = total_frames - 1 if args.end_frame is None else min(total_frames - 1, int(args.end_frame))
    target_indices = list(range(start_f, end_f + 1))
    full_schedule = build_directive_schedule(timeline, target_indices)
    (work_dir / "full_schedule.json").write_text(json.dumps(full_schedule, indent=2), encoding="utf-8")

    chunks = [
        full_schedule[i : i + args.chunk_size]
        for i in range(0, len(full_schedule), args.chunk_size)
    ]

    rendered_files: list[str] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        pending_futures: list[concurrent.futures.Future[str]] = []
        for chunk_id, chunk in enumerate(chunks):
            if args.backend == "blender":
                assert blender_exe is not None
                _render_blender_chunk(blender_exe, chunk, passes_dir, work_dir, chunk_id, args.width, args.height, args.samples)
            else:
                _render_synthetic_passes(chunk, passes_dir, args.width, args.height)

            for entry in chunk:
                pending_futures.append(
                    pool.submit(_postprocess_frame_worker, (entry, str(passes_dir), str(frames_dir), fps))
                )
        for fut in pending_futures:
            rendered_files.append(fut.result())

    result: dict[str, Any] = {
        "mode": "full",
        "backend": args.backend,
        "lint_profile": args.lint_profile,
        "frameCount": len(rendered_files),
        "chunks": len(chunks),
        "frames_dir": str(frames_dir),
    }

    # 3. Optional BeatScope render.mjs (--frames-dir) mux + verify.mjs sync inspection
    if args.mux_mp4 is not None:
        if args.package is None or args.audio is None:
            raise ValueError("--mux-mp4 requires both --package and --audio")
        render_mjs = args.package.resolve() / "render.mjs"
        render_cmd = [
            "node",
            str(render_mjs),
            "--frames-dir",
            str(frames_dir),
            "--frame-pattern",
            "frame-%06d.png",
            "--frame-start",
            "0",
            "--audio",
            str(args.audio.resolve()),
            "--out",
            str(args.mux_mp4.resolve()),
            "--start",
            str(window["start"]),
            "--seconds",
            str(window["duration"]),
            "--fps",
            str(fps),
            "--width",
            str(args.width),
            "--height",
            str(args.height),
        ]
        if args.reuse_unchanged:
            render_cmd.append("--reuse-unchanged")
        proc = subprocess.run(render_cmd, cwd=args.package.resolve(), capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError(f"BeatScope render.mjs failed:\n{proc.stderr or proc.stdout}")
        result["render_report"] = json.loads(proc.stdout)

        if args.score is not None:
            verify_mjs = args.package.resolve() / "verify.mjs"
            sync_out = Path(str(args.mux_mp4.resolve()) + ".sync.json")
            verify_cmd = [
                "node",
                str(verify_mjs),
                "--score",
                str(args.score.resolve()),
                "--video",
                str(args.mux_mp4.resolve()),
                "--out",
                str(sync_out),
            ]
            vproc = subprocess.run(verify_cmd, cwd=args.package.resolve(), capture_output=True, text=True, encoding="utf-8")
            if vproc.returncode not in (0, 1):
                raise RuntimeError(f"BeatScope verify.mjs failed:\n{vproc.stderr or vproc.stdout}")
            result["verify_report"] = json.loads(vproc.stdout)
            result["verify_exit_code"] = vproc.returncode

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
