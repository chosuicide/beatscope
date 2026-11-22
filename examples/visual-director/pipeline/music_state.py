"""BeatScope-driven dual-clock state machine (no hardcoded frame counts).

Consumes ``beatscope-frame-timeline-1`` JSON produced by ``bake-timeline.mjs``
and evaluates deterministic, seek-safe visual directives per frame.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FrameDirective:
    frame: int
    time: float
    stage_id: str
    phase_name: str  # steady_daylight | probing_intrusion | xerox_climax | cold_return | stepped_iris_close
    # 3D scene camera & intrusion controls (seek-safe)
    cam_jitter_x: float
    cam_jitter_y: float
    intrusion_visible: bool
    intrusion_seed: int
    intrusion_scale: float
    # OpenCV physical pixel FX controls
    cutout_active: bool
    cutout_dilate_px: int
    pixel_sort_active: bool
    pixel_sort_y_frac: tuple[float, float]
    pixel_sort_depth_range: tuple[int, int]
    xerox_steps: int
    xerox_threshold: int
    xerox_crop_seed: int
    burn_level: float
    iris_step: int  # -1 = open, 0..3 = 4-step hard iris close
    # Musical provenance for diagnostics
    cue_hit_ids: tuple[str, ...]
    bands_all: float
    beat_phase: float


def load_timeline(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "beatscope-frame-timeline-1":
        raise ValueError(f"Expected beatscope-frame-timeline-1, got {data.get('schema')!r}")
    if not isinstance(data.get("frames"), list) or not data["frames"]:
        raise ValueError("Timeline has no frames")
    return data


def _recent_cue_age_frames(
    frames: list[dict[str, Any]],
    frame_idx: int,
    max_lookback: int,
    min_strength: float,
) -> tuple[int | None, dict[str, Any] | None]:
    """Deterministically inspect the nearest recent prominent cue without mutable state."""
    lo = max(0, frame_idx - max_lookback)
    for idx in range(frame_idx, lo - 1, -1):
        hits = frames[idx].get("cueHits") or []
        best = None
        for hit in hits:
            if hit.get("manual") or float(hit.get("strength", 0.0)) >= min_strength:
                if best is None or float(hit.get("strength", 0.0)) > float(best.get("strength", 0.0)):
                    best = hit
        if best is not None:
            return frame_idx - idx, best
    return None, None


def evaluate_frame_directive(timeline: dict[str, Any], frame_idx: int) -> FrameDirective:
    """Pure, seek-safe mapping from BeatScope timeline facts to dual-clock visual directives."""
    frames: list[dict[str, Any]] = timeline["frames"]
    window = timeline["window"]
    fps = float(window["fps"])
    total_frames = len(frames)
    clamped = max(0, min(total_frames - 1, int(frame_idx)))
    row = frames[clamped]

    t = float(row["time"])
    win_start = float(window["start"])
    win_dur = max(1e-6, float(window["duration"]))
    progress = max(0.0, min(1.0, (t - win_start) / win_dur))

    stage_id = str(row.get("stageId") or "start")
    stage_index = int(row.get("stageIndex") or 0)
    stages = timeline.get("stages") or []
    stage_count = max(1, len(stages))

    bands = row.get("bands") or {}
    low = float(bands.get("low") or 0.0)
    mid = float(bands.get("mid") or 0.0)
    high = float(bands.get("high") or 0.0)
    band_all = float(bands.get("all") or 0.0)
    beat_phase = float(row.get("beatPhase") or 0.0)
    cue_hits = tuple(str(h["id"]) for h in (row.get("cueHits") or []))

    # Optional BeatScope score.json override (e.g. score setup.phase or values.burn)
    score = row.get("score") or {}
    score_setup = score.get("setup") or {}
    score_values = score.get("values") or {}

    # Stepped clock (6fps) for non-smooth experimental cadence
    step_div = max(1, round(fps / 6.0))
    step_tick = clamped // step_div

    # Deterministic 1-2px handheld breathe (never unseeded random)
    cam_jitter_x = round(math.sin(clamped * 0.43 + 0.7) * 0.0045 + math.sin(clamped * 1.17) * 0.0018, 6)
    cam_jitter_y = round(math.cos(clamped * 0.37 + 1.3) * 0.0038 + math.cos(clamped * 0.91) * 0.0015, 6)

    # Determine arc phase from BeatScope stages + musical window progress
    # Closing iris occupies the last ~0.5s (4 discrete steps, at least 4 frames)
    iris_frames = min(max(4, int(round(fps * 0.5))), max(4, total_frames // 5))
    cold_return_frames = min(max(4, int(round(fps * 0.5))), max(4, total_frames // 6))
    frames_left = total_frames - 1 - clamped

    if isinstance(score_setup.get("phase"), str):
        phase_name = str(score_setup["phase"])
    elif frames_left < iris_frames and total_frames >= 12:
        phase_name = "stepped_iris_close"
    elif frames_left < iris_frames + cold_return_frames and total_frames >= 16:
        phase_name = "cold_return"
    elif stage_count >= 3:
        # Multi-stage songs: stage 0 steady, middle stages probe -> climax
        if stage_index == 0 and progress < 0.28:
            phase_name = "steady_daylight"
        elif stage_index == 1 or progress < 0.52:
            phase_name = "probing_intrusion"
        else:
            phase_name = "xerox_climax"
    else:
        if progress < 0.25:
            phase_name = "steady_daylight"
        elif progress < 0.52:
            phase_name = "probing_intrusion"
        else:
            phase_name = "xerox_climax"

    # Check recent BeatScope resolved cues (prime-frame burst window: 5 frames)
    cue_age, cue_hit = _recent_cue_age_frames(frames, clamped, max_lookback=4, min_strength=0.45)
    strong_cue_burst = cue_age is not None and cue_age < 5

    # Default restrained daylight state
    intrusion_visible = False
    intrusion_seed = step_tick
    intrusion_scale = 1.0
    cutout_active = False
    pixel_sort_active = False
    pixel_sort_y_frac = (0.34, 0.72)
    pixel_sort_depth_range = (14000, 44000)
    xerox_steps = 0
    xerox_threshold = 138
    xerox_crop_seed = step_tick
    burn_level = 0.0
    iris_step = -1

    if phase_name == "steady_daylight":
        # Deliberate restraint: hold stark noon reality. Only manual user cues may nudge a 1-frame hairline probe.
        if cue_hit is not None and cue_hit.get("manual") and cue_age == 0:
            intrusion_visible = True
            cutout_active = True
            intrusion_scale = 0.75
    elif phase_name == "probing_intrusion":
        # Dual-clock tension: intrusion cracks open on resolved cues (3-5 prime frames)
        if strong_cue_burst or (band_all >= 0.62 and (step_tick % 3 == 0)):
            intrusion_visible = True
            cutout_active = True
            intrusion_scale = 0.85 + 0.35 * min(1.0, low + (float(cue_hit["strength"]) if cue_hit else 0.4))
            # Depth-constrained pixel sort kicks in when mid/high novelty rises
            if mid >= 0.25 or high >= 0.25 or strong_cue_burst:
                pixel_sort_active = True
                band_center = 0.35 + 0.30 * ((step_tick * 37) % 10) / 10.0
                half_h = 0.14 + 0.10 * min(1.0, high + mid * 0.5)
                pixel_sort_y_frac = (max(0.08, band_center - half_h), min(0.92, band_center + half_h))
        burn_level = 0.12 * min(1.0, band_all) if strong_cue_burst else 0.0
    elif phase_name == "xerox_climax":
        # Full darkroom xerox array + Bayer 4x4 collapse synchronized to beatPhase & bands
        intrusion_visible = True
        cutout_active = True
        intrusion_scale = 1.05 + 0.35 * min(1.0, low + band_all * 0.5)
        pixel_sort_active = True
        band_shift = 0.18 * math.sin(beat_phase * math.tau)
        pixel_sort_y_frac = (max(0.10, 0.24 + band_shift * 0.5), min(0.90, 0.76 + band_shift * 0.5))
        # Stepped xerox array count rises with bands.all & cues (4..9 steps)
        xerox_steps = int(min(9, max(4, round(4 + 4.0 * band_all + (2 if strong_cue_burst else 0)))))
        xerox_threshold = int(max(105, min(168, round(152 - 36 * high - (12 if strong_cue_burst else 0)))))
        burn_level = min(0.92, max(0.32, 0.36 + 0.46 * band_all + (0.14 if strong_cue_burst else 0.0)))
    elif phase_name == "cold_return":
        # Hard cut back to calm, unbothered noon reality — zero intrusion, zero burn
        intrusion_visible = False
        cutout_active = False
        pixel_sort_active = False
        xerox_steps = 0
        burn_level = 0.0
    elif phase_name == "stepped_iris_close":
        # 4 discrete hard steps closing to absolute void, placed BEFORE unified_media_pass
        into_iris = max(0, iris_frames - 1 - frames_left)
        iris_step = min(3, int((into_iris * 4) // max(1, iris_frames)))
        burn_level = 0.18 if iris_step < 3 else 0.0

    # Respect optional numeric score.json track overrides if authored
    if isinstance(score_values.get("darkroom.burn"), (int, float)):
        burn_level = max(0.0, min(1.0, float(score_values["darkroom.burn"])))

    return FrameDirective(
        frame=clamped,
        time=t,
        stage_id=stage_id,
        phase_name=phase_name,
        cam_jitter_x=cam_jitter_x,
        cam_jitter_y=cam_jitter_y,
        intrusion_visible=intrusion_visible,
        intrusion_seed=intrusion_seed,
        intrusion_scale=round(intrusion_scale, 4),
        cutout_active=cutout_active,
        cutout_dilate_px=2,
        pixel_sort_active=pixel_sort_active,
        pixel_sort_y_frac=(round(pixel_sort_y_frac[0], 4), round(pixel_sort_y_frac[1], 4)),
        pixel_sort_depth_range=pixel_sort_depth_range,
        xerox_steps=xerox_steps,
        xerox_threshold=xerox_threshold,
        xerox_crop_seed=xerox_crop_seed,
        burn_level=round(burn_level, 4),
        iris_step=iris_step,
        cue_hit_ids=cue_hits,
        bands_all=round(band_all, 4),
        beat_phase=round(beat_phase, 4),
    )


def causal_attack_release_envelope(
    values: list[float],
    attack_tau: float = 0.02,
    release_tau: float = 0.18,
    fps: float = 60.0,
) -> list[float]:
    """Anti-jitter causal attack-release smoother for raw per-frame BeatScope band novelty.

    Never wire raw per-frame `bands.low/mid/high` directly into 3D mesh vertices, scale, or
    camera transforms; pass the series through this causal envelope first so hits punch fast
    and decay smoothly without 15-30Hz tremor.
    """
    if not values:
        return []
    dt = 1.0 / max(1.0, float(fps))
    a_att = 1.0 - math.exp(-dt / max(1e-4, float(attack_tau)))
    a_rel = 1.0 - math.exp(-dt / max(1e-4, float(release_tau)))
    out: list[float] = []
    cur = float(values[0])
    for v in values:
        x = float(v)
        coeff = a_att if x >= cur else a_rel
        cur = cur + coeff * (x - cur)
        out.append(round(cur, 6))
    return out


def build_directive_schedule(timeline: dict[str, Any], frame_indices: list[int] | None = None) -> list[dict[str, Any]]:
    indices = frame_indices if frame_indices is not None else list(range(len(timeline["frames"])))
    return [asdict(evaluate_frame_directive(timeline, i)) for i in indices]
