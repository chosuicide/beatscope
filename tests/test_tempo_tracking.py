"""Unit tests for tempo tracking (plan sections 10-15).

The synthetic novelty curves use sample_rate=25600 with hop 256, i.e. exactly
100 frames per second, so beat periods land on whole frames and the expected
autocorrelation ties are exact rather than float-noise-dependent.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from beatscope.tempo_tracking import (
    MAX_BPM,
    MIN_BPM,
    SEGMENT_MERGE_LOG2,
    TempoCandidate,
    TempoPath,
    align_beats_to_onsets,
    build_local_tempo_candidates,
    build_tempo_segments_from_beats,
    dynamic_programming_beats,
    huber,
    interpolate_period_guide,
    number_beats,
    repair_beat_continuity,
    segment_tempo_curve,
    select_tempo_path,
    track_tempo_and_beats,
)

SAMPLE_RATE = 25600
HOP = 256
FPS = SAMPLE_RATE / HOP  # exactly 100.0


def impulse_novelty(beats: list[float], duration_s: float, gains: list[float] | None = None) -> np.ndarray:
    """Novelty as unit impulses at beat frames (optionally per-beat gains)."""
    n = int(round(duration_s * FPS))
    x = np.zeros(n, dtype=np.float64)
    for k, t in enumerate(beats):
        frame = int(round(t * FPS))
        if 0 <= frame < n:
            x[frame] = 1.0 if gains is None else gains[k % len(gains)]
    return x


def regular_beats(bpm: float, duration_s: float) -> list[float]:
    step = 60.0 / bpm
    return [k * step for k in range(int(duration_s / step))]


def middle_window_candidates(windows, index=None):
    return windows[index if index is not None else len(windows) // 2]


def test_huber_shapes():
    assert huber(0.0) == 0.0
    assert huber(0.5) == pytest.approx(0.125)  # quadratic region
    assert huber(-0.5) == pytest.approx(0.125)
    assert huber(2.0) == pytest.approx(1.5)  # linear region: 1*(2-0.5)
    assert huber(1.0) == pytest.approx(0.5)  # boundary shared by both branches


def test_top_candidate_is_the_true_tempo():
    novelty = impulse_novelty(regular_beats(120.0, 12.0), 12.0)
    windows = build_local_tempo_candidates(novelty, SAMPLE_RATE, HOP, global_prior_bpm=120.0)
    # Every multiple-of-period lag correlates at ~1.0 for a perfect impulse
    # train; per-window ranking may wobble between 120 and 60 by float noise,
    # but the Viterbi tie tolerance plus the prior-distance rule must settle
    # on the true tempo globally.
    for window in windows:
        top = [c for c in window if abs(c.bpm - 120.0) < 0.1]
        assert top and top[0].emission_score == pytest.approx(1.0, abs=1e-9)
    path = select_tempo_path(windows, global_prior_bpm=120.0)
    assert np.all(path.bpms == 120.0)


def test_window_contains_true_tempo_candidate():
    novelty = impulse_novelty(regular_beats(140.0, 12.0), 12.0)
    windows = build_local_tempo_candidates(novelty, SAMPLE_RATE, HOP, global_prior_bpm=120.0)
    candidates = middle_window_candidates(windows)
    near_140 = [c for c in candidates if abs(c.bpm - 140.0) <= 3.0]
    assert near_140, f"no ~140 BPM candidate among {[round(c.bpm, 2) for c in candidates]}"
    assert all(MIN_BPM <= c.bpm <= MAX_BPM for c in candidates)


def test_octave_trap_yields_stable_octave_candidates():
    beats = regular_beats(120.0, 12.0)
    halves = sorted(beats + [t + 0.25 for t in beats])
    gains = [1.0 if any(abs(t - b) < 1e-9 for b in beats) else 0.55 for t in halves]
    novelty = impulse_novelty(halves, 12.0, gains=gains)
    first = build_local_tempo_candidates(novelty, SAMPLE_RATE, HOP, global_prior_bpm=120.0)
    second = build_local_tempo_candidates(novelty, SAMPLE_RATE, HOP, global_prior_bpm=120.0)

    candidates = middle_window_candidates(first)
    bpms = [round(c.bpm, 6) for c in candidates]
    assert any(abs(b - 120.0) < 1.0 for b in bpms), bpms
    assert any(abs(b - 60.0) < 1.0 for b in bpms), bpms
    # 240 sits outside the legal candidate range; the octave family still
    # appears through the 0.5x variant, and ordering is fully determined.
    assert first == second


def test_silent_novelty_produces_zero_score_fallbacks():
    novelty = np.zeros(6000, dtype=np.float64)
    windows = build_local_tempo_candidates(novelty, SAMPLE_RATE, HOP, global_prior_bpm=None)
    assert len(windows) > 0
    for window in windows:
        assert len(window) == 1
        assert window[0].bpm == 120.0
        assert window[0].emission_score == 0.0
        assert window[0].origin == "fallback"
    path = select_tempo_path(windows, global_prior_bpm=120.0)
    assert np.all(np.isfinite(path.bpms)) and np.all(path.bpms == 120.0)
    assert np.all(np.isfinite(interpolate_period_guide(path, len(novelty), FPS)))


def test_candidate_building_is_deterministic():
    novelty = impulse_novelty(regular_beats(120.0, 10.0), 10.0)
    first = build_local_tempo_candidates(novelty, SAMPLE_RATE, HOP, global_prior_bpm=120.0)
    second = build_local_tempo_candidates(novelty, SAMPLE_RATE, HOP, global_prior_bpm=120.0)
    assert first == second


def _hand_window(index: int, entries: list[tuple[float, float]]) -> list[TempoCandidate]:
    return [
        TempoCandidate(index * 50, bpm, FPS * 60.0 / bpm, score, "peak")
        for bpm, score in entries
    ]


def test_path_follows_a_real_tempo_step():
    windows = (
        [_hand_window(i, [(120.0, 0.9), (60.0, 0.55)]) for i in range(8)]
        + [_hand_window(8 + i, [(140.0, 0.9), (70.0, 0.55)]) for i in range(8)]
    )
    path = select_tempo_path(windows, global_prior_bpm=120.0)
    assert list(path.bpms[:8]) == [120.0] * 8
    assert list(path.bpms[8:]) == [140.0] * 8
    # The change evidence must be recorded for the segmentation stage.
    assert path.change_scores[8] > 0.0


def test_path_never_octave_flips_mid_song():
    # Half the song prefers 120, the other half prefers 60 by emission. An
    # octave switch between adjacent anchors is hard-forbidden, so the path
    # must commit to one family for the whole song instead of flipping.
    windows = (
        [_hand_window(i, [(120.0, 0.9), (60.0, 0.8)]) for i in range(8)]
        + [_hand_window(8 + i, [(60.0, 0.9), (120.0, 0.05)]) for i in range(8)]
    )
    path = select_tempo_path(windows, global_prior_bpm=120.0)
    ratios = np.abs(np.diff(np.log2(path.bpms)))
    assert np.all(ratios < 0.5), f"octave flip in path: {path.bpms}"
    assert len(set(path.bpms.tolist())) == 1


def test_equal_costs_break_ties_toward_smaller_bpm():
    # 60 and 240 sit symmetrically around the 120 prior (|log2| == 1.0 both,
    # exactly), so every cost key ties and rule 4 (smaller BPM) decides.
    windows = [_hand_window(0, [(240.0, 0.8), (60.0, 0.8)])]
    path = select_tempo_path(windows, global_prior_bpm=120.0)
    assert path.bpms[0] == 60.0


def test_path_selection_is_deterministic():
    windows = (
        [_hand_window(i, [(120.0, 0.9), (60.0, 0.55)]) for i in range(4)]
        + [_hand_window(4 + i, [(126.0, 0.7), (63.0, 0.75)]) for i in range(4)]
    )
    first = select_tempo_path(windows, global_prior_bpm=120.0)
    second = select_tempo_path(windows, global_prior_bpm=120.0)
    assert np.array_equal(first.bpms, second.bpms)
    assert np.array_equal(first.change_scores, second.change_scores)


def test_interpolate_period_guide_log_space():
    path = TempoPath(
        anchor_frames=np.array([0, 100], dtype=np.int64),
        bpms=np.array([120.0, 60.0]),
        emission_scores=np.array([1.0, 1.0]),
        change_scores=np.zeros(2),
    )
    curve = interpolate_period_guide(path, 201, FPS)
    assert len(curve) == 201
    assert curve[0] == pytest.approx(FPS * 60.0 / 120.0)
    assert curve[200] == pytest.approx(FPS * 60.0 / 60.0)
    # Frame 50 is halfway between the anchors; log-space interpolation means
    # the tempo there is the geometric mean (84.85 BPM), not 90.
    midpoint = FPS * 60.0 / math.sqrt(120.0 * 60.0)
    assert curve[50] == pytest.approx(midpoint, rel=1e-9)
    assert curve[100] == pytest.approx(FPS * 60.0 / 60.0, rel=1e-9)


def test_interpolate_period_guide_single_anchor_and_empty():
    path = TempoPath(
        anchor_frames=np.array([0], dtype=np.int64),
        bpms=np.array([95.0]),
        emission_scores=np.array([0.5]),
        change_scores=np.zeros(1),
    )
    curve = interpolate_period_guide(path, 50, FPS)
    assert np.all(curve == FPS * 60.0 / 95.0)
    assert interpolate_period_guide(path, 0, FPS).size == 0


# ---------------------------------------------------------------------------
# Commit 3: beat DP, alignment, repair, numbering, segmentation, orchestrator
# ---------------------------------------------------------------------------

def variable_grid_times(bpm_at, duration_s: float) -> list[float]:
    """Same deterministic recurrence as the fixture generator (plan 12.3)."""
    beats: list[float] = []
    time = 0.0
    while time < duration_s - 1e-9:
        beats.append(time)
        time += 60.0 / bpm_at(time)
    return beats


def guide_from_bpm_fn(bpm_at, n: int) -> np.ndarray:
    return FPS * 60.0 / bpm_at(np.arange(n, dtype=np.float64) / FPS)


def _step_bpm(cut: float, before: float, after: float):
    return lambda t: np.where(np.asarray(t) < cut, before, after)


def test_beat_dp_recovers_constant_grid():
    beats = regular_beats(120.0, 12.0)
    novelty = impulse_novelty(beats, 12.0)
    curve = np.full(len(novelty), FPS * 60.0 / 120.0)
    frames, diag = dynamic_programming_beats(novelty, curve)
    assert diag["tracked"] is True
    expected = np.array([int(round(t * FPS)) for t in beats], dtype=np.int64)
    np.testing.assert_array_equal(frames, expected)


def test_beat_dp_follows_step_guide():
    bpm_at = _step_bpm(8.0, 120.0, 140.0)
    beats = variable_grid_times(bpm_at, 16.0)
    novelty = impulse_novelty(beats, 16.0)
    curve = guide_from_bpm_fn(bpm_at, len(novelty))
    frames, diag = dynamic_programming_beats(novelty, curve)
    assert diag["tracked"] is True
    expected = np.array([int(round(t * FPS)) for t in beats], dtype=np.int64)
    assert len(frames) == len(expected)
    assert int(np.max(np.abs(frames - expected))) <= 1


def test_beat_dp_rejects_silence():
    frames, diag = dynamic_programming_beats(np.zeros(1200), np.full(1200, 50.0))
    assert frames.size == 0
    assert diag["tracked"] is False
    assert diag["untracked_reason"] == "insufficient-novelty-support"


def test_beat_dp_never_emits_unsupported_frames():
    # A constant noise floor under the impulse train: median subtraction maps
    # the floor to zero support, so head/tail noise frames must be trimmed.
    beats = regular_beats(120.0, 12.0)
    novelty = impulse_novelty(beats, 12.0) + 0.05
    curve = np.full(len(novelty), FPS * 60.0 / 120.0)
    frames, diag = dynamic_programming_beats(novelty, curve)
    expected = np.array([int(round(t * FPS)) for t in beats], dtype=np.int64)
    np.testing.assert_array_equal(frames, expected)
    assert diag["beat_chain_length"] == len(expected)


def test_beat_dp_anchors_subdivision_phase_on_first_onset():
    # 16th-note pulse train at 100 BPM: every 4th pulse is a beat, and all
    # pulses have equal amplitude, so every 4-pulse phase is equally
    # supported. The first-onset anchor must settle the phase on pulse #0.
    pulses = [k * 0.15 for k in range(int(8.0 / 0.15))]
    novelty = impulse_novelty(pulses, 8.0)
    curve = np.full(len(novelty), FPS * 60.0 / 100.0)
    frames, diag = dynamic_programming_beats(novelty, curve)
    expected = np.array([int(round(k * 0.6 * FPS)) for k in range(14)], dtype=np.int64)
    np.testing.assert_array_equal(frames, expected)
    assert diag["tracked"] is True


def test_beat_dp_rejects_offbeat_first_onset():
    # A loud pickup half a period before beat 1 must not drag the chain off
    # phase: chaining through it costs far more tightness than the one-beat
    # anchor bonus is worth.
    beats = regular_beats(120.0, 12.0)
    novelty = impulse_novelty(beats, 12.0)
    pickup = int(round(0.25 * FPS))
    novelty[pickup] = 2.0
    curve = np.full(len(novelty), FPS * 60.0 / 120.0)
    frames, diag = dynamic_programming_beats(novelty, curve)
    expected = np.array([int(round(t * FPS)) for t in beats], dtype=np.int64)
    np.testing.assert_array_equal(frames, expected)
    assert pickup not in set(frames.tolist())


def test_align_snaps_toward_local_peak():
    novelty = np.zeros(1200)
    novelty[503] = 0.9
    curve = np.full(1200, 50.0)
    aligned, snapped = align_beats_to_onsets(
        np.array([500, 550, 600], dtype=np.int64), novelty, curve, FPS
    )
    assert list(aligned) == [503, 550, 600]
    assert snapped == 1


def test_align_refuses_snap_that_breaks_neighbor_intervals():
    novelty = np.zeros(1200)
    novelty[503] = 0.9
    curve = np.full(1200, 50.0)
    # Snapping 500 -> 503 would squeeze the right interval to 0.34 periods.
    aligned, snapped = align_beats_to_onsets(
        np.array([500, 520], dtype=np.int64), novelty, curve, FPS
    )
    assert list(aligned) == [500, 520]
    assert snapped == 0


def test_repair_removes_duplicate_keeping_stronger_beat():
    novelty = np.zeros(1200)
    novelty[500] = 0.3
    novelty[510] = 1.0
    novelty[560] = 1.0
    curve = np.full(1200, 50.0)
    frames, diag = repair_beat_continuity(
        np.array([500, 510, 560], dtype=np.int64), curve, novelty, fps=FPS
    )
    assert list(frames) == [510, 560]
    assert diag["duplicates_removed"] == 1
    assert diag["beats_inserted"] == 0


def test_repair_duplicate_tie_keeps_better_phase():
    novelty = np.zeros(1200)
    for frame in (450, 500, 510, 560):
        novelty[frame] = 1.0
    curve = np.full(1200, 50.0)
    frames, diag = repair_beat_continuity(
        np.array([450, 500, 510, 560], dtype=np.int64), curve, novelty, fps=FPS
    )
    assert list(frames) == [450, 500, 560]
    assert diag["duplicates_removed"] == 1


def test_repair_inserts_single_missing_beat():
    novelty = np.zeros(1200)
    novelty[500] = 1.0
    novelty[545] = 0.8
    novelty[590] = 1.0
    curve = np.full(1200, 45.0)  # gap of 90 frames sits inside 1.65x..2.35x
    frames, diag = repair_beat_continuity(
        np.array([500, 590], dtype=np.int64), curve, novelty, fps=FPS
    )
    assert list(frames) == [500, 545, 590]
    assert diag["beats_inserted"] == 1
    assert diag["unrepairable_gaps"] == 0


def test_repair_counts_unrepairable_gap():
    novelty = np.zeros(1200)
    novelty[500] = 1.0
    novelty[700] = 1.0
    curve = np.full(1200, 45.0)  # gap of 200 frames is beyond 2.35x
    frames, diag = repair_beat_continuity(
        np.array([500, 700], dtype=np.int64), curve, novelty, fps=FPS
    )
    assert list(frames) == [500, 700]
    assert diag["beats_inserted"] == 0
    assert diag["unrepairable_gaps"] == 1


def test_number_beats_assigns_bars_after_repair():
    numbered = number_beats([0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
    assert numbered[0] == {
        "time": 0.0, "beat": 1, "bar": 1, "downbeat": True, "sequence_gap": False,
    }
    assert numbered[3]["beat"] == 4 and numbered[3]["bar"] == 1
    assert numbered[4]["bar"] == 2 and numbered[4]["beat"] == 1
    assert numbered[4]["downbeat"] is True
    assert numbered[5]["beat"] == 2 and numbered[5]["downbeat"] is False


def test_segment_tempo_curve_constant_is_one_segment():
    bpms = np.full(20, 120.0)
    times = np.arange(20) * 0.5 + 0.25
    pieces = segment_tempo_curve(times, bpms, None, 12.0)
    assert len(pieces) == 1
    assert pieces[0][0] == 0 and pieces[0][1] == 20
    assert pieces[0][2] == pytest.approx(120.0)


def test_segment_tempo_curve_splits_at_supported_change():
    bpms = np.concatenate([np.full(16, 120.0), np.full(16, 140.0)])
    change = np.zeros(32)
    change[16] = 1.0
    times = np.arange(32) * 0.5 + 0.25
    pieces = segment_tempo_curve(times, bpms, change, 17.0)
    assert len(pieces) == 2
    assert pieces[0][0] == 0 and pieces[0][1] == 16
    assert pieces[0][2] == pytest.approx(120.0)
    assert pieces[1][0] == 16 and pieces[1][1] == 32
    assert pieces[1][2] == pytest.approx(140.0)


def test_segment_tempo_curve_ignores_unsupported_blip():
    bpms = np.full(20, 120.0)
    bpms[10] = 140.0
    times = np.arange(20) * 0.5 + 0.25
    pieces = segment_tempo_curve(times, bpms, None, 12.0)
    assert len(pieces) == 1


def test_build_tempo_segments_layout_on_step_beats():
    bpm_at = _step_bpm(8.0, 120.0, 140.0)
    beats = variable_grid_times(bpm_at, 16.0)
    segments = build_tempo_segments_from_beats(beats, 16.0, method="beat-marker-intervals")
    assert len(segments) == 2
    first, second = segments
    assert first["start"] == 0.0
    assert second["end"] == 16.0
    assert first["end"] == second["start"]  # contiguous, no gap or overlap
    assert first["end"] == pytest.approx(8.0, abs=0.5)
    assert first["bpm"] == pytest.approx(120.0, abs=1.5)
    assert second["bpm"] == pytest.approx(140.0, abs=2.0)
    assert all(s["method"] == "beat-marker-intervals" for s in segments)
    assert all(s["score"] is None for s in segments)


def test_build_tempo_segments_score_uses_emission_support():
    beats = regular_beats(120.0, 8.0)
    emissions = np.linspace(0.2, 1.0, len(beats) - 1)
    segments = build_tempo_segments_from_beats(
        beats, 8.0, method="m", interval_emissions=emissions
    )
    assert len(segments) == 1
    assert segments[0]["score"] == pytest.approx(float(np.mean(emissions)), abs=1e-3)
    assert 0.0 <= segments[0]["score"] <= 1.0


def test_build_tempo_segments_merges_near_identical_neighbors():
    bpm_at = _step_bpm(8.0, 120.0, 120.5)  # log2 ratio ~0.006, far below 0.02
    beats = variable_grid_times(bpm_at, 16.0)
    segments = build_tempo_segments_from_beats(beats, 16.0, method="m")
    assert len(segments) == 1
    assert segments[0]["bpm"] == pytest.approx(120.25, abs=0.5)


def test_build_tempo_segments_drift_keeps_merge_invariant():
    # 100 -> 140 BPM linear drift over 24 s, like the fixture.
    bpm_at = lambda t: 100.0 + 40.0 * t / 24.0
    beats = variable_grid_times(bpm_at, 24.0)
    segments = build_tempo_segments_from_beats(beats, 24.0, method="m")
    assert len(segments) >= 2
    for left, right in zip(segments, segments[1:]):
        assert left["end"] == right["start"]
        # The re-merge pass must leave no near-identical neighbors behind.
        assert abs(math.log2(right["bpm"] / left["bpm"])) >= SEGMENT_MERGE_LOG2 - 1e-9


def test_track_silence_falls_back_to_prior_without_fake_beats():
    res = track_tempo_and_beats(np.zeros(6000), SAMPLE_RATE, HOP, global_prior_bpm=None)
    assert res.beat_times == ()
    assert res.global_bpm == 120.0
    assert res.tempo_segments == ()
    assert res.path_score is None
    assert res.diagnostics["tracked"] is False


def test_track_constant_tempo_end_to_end():
    beats = regular_beats(120.0, 24.0)
    novelty = impulse_novelty(beats, 24.0)
    res = track_tempo_and_beats(
        novelty, SAMPLE_RATE, HOP, global_prior_bpm=None, duration=24.0
    )
    assert len(res.beat_times) == len(beats)
    for got, want in zip(res.beat_times, beats):
        assert got == pytest.approx(want, abs=0.01)
    assert res.global_bpm == pytest.approx(120.0, abs=0.5)
    assert len(res.tempo_segments) == 1
    segment = res.tempo_segments[0]
    assert segment["start"] == 0.0 and segment["end"] == 24.0
    assert segment["bpm"] == pytest.approx(120.0, abs=0.5)
    assert segment["method"] == "local-autocorrelation-viterbi+beat-dp"
    assert res.diagnostics["tracked"] is True
    assert res.diagnostics["tempo_path_octave_switches"] == 0
    assert res.path_score is not None and res.path_score > 0.5


def test_track_step_tempo_end_to_end():
    bpm_at = _step_bpm(8.0, 120.0, 140.0)
    truth = variable_grid_times(bpm_at, 24.0)
    novelty = impulse_novelty(truth, 24.0)
    res = track_tempo_and_beats(
        novelty, SAMPLE_RATE, HOP, global_prior_bpm=None, duration=24.0
    )
    assert abs(len(res.beat_times) - len(truth)) <= 2
    assert 125.0 <= res.global_bpm <= 135.0
    assert len(res.tempo_segments) == 2
    first, second = res.tempo_segments
    assert first["end"] == second["start"]
    assert first["bpm"] == pytest.approx(120.0, abs=1.5)
    assert second["bpm"] == pytest.approx(140.0, abs=2.0)


def test_track_resists_octave_trap():
    beats = regular_beats(120.0, 24.0)
    halves = sorted(beats + [t + 0.25 for t in beats])
    main = set(beats)
    gains = [1.0 if any(abs(t - b) < 1e-9 for b in main) else 0.55 for t in halves]
    novelty = impulse_novelty(halves, 24.0, gains=gains)
    res = track_tempo_and_beats(
        novelty, SAMPLE_RATE, HOP, global_prior_bpm=None, duration=24.0
    )
    assert res.diagnostics["tempo_path_octave_switches"] == 0
    assert res.global_bpm == pytest.approx(120.0, abs=3.0)
    assert abs(len(res.beat_times) - len(beats)) <= 2


def test_track_is_deterministic():
    bpm_at = _step_bpm(8.0, 120.0, 140.0)
    novelty = impulse_novelty(variable_grid_times(bpm_at, 16.0), 16.0)
    first = track_tempo_and_beats(novelty, SAMPLE_RATE, HOP, global_prior_bpm=None)
    second = track_tempo_and_beats(novelty, SAMPLE_RATE, HOP, global_prior_bpm=None)
    assert first == second


def test_track_matches_truth_on_real_fixed_120_fixture(fixed_120_audio, synth_audio):
    from beatscope.audio_io import load_analysis_audio
    from beatscope.features import compute_multiband_novelty

    y, sr, duration, _channels, _warnings = load_analysis_audio(fixed_120_audio)
    _times, novelty = compute_multiband_novelty(y, sr=sr, hop=256)
    truth = synth_audio["fixed-120"]["truth"]
    res = track_tempo_and_beats(
        novelty["all"], sr, 256, global_prior_bpm=None, duration=duration
    )

    tolerance = 0.070
    hits = sum(
        1
        for beat in res.beat_times
        if any(abs(beat - ref) <= tolerance for ref in truth["beats"])
    )
    precision = hits / len(res.beat_times) if res.beat_times else 0.0
    recall = hits / len(truth["beats"])
    f1 = 2 * precision * recall / (precision + recall) if hits else 0.0
    assert f1 >= 0.9, f"beat F1 {f1:.3f} (precision {precision:.3f}, recall {recall:.3f})"
    assert res.global_bpm == pytest.approx(120.0, abs=2.0)
    assert len(res.tempo_segments) == 1
    assert res.tempo_segments[0]["bpm"] == pytest.approx(120.0, abs=2.0)
