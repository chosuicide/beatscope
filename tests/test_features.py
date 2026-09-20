import numpy as np
import pytest

from beatscope.features import (
    compute_multiband_novelty,
    extract_onsets,
    normalize_band_signal,
)


def test_normalization_extremes_under_two_percent():
    np.random.seed(42)
    raw = np.random.lognormal(mean=0.0, sigma=1.0, size=5000)
    norm = normalize_band_signal(raw)
    assert norm.min() >= 0.0
    assert norm.max() <= 1.0
    extremes_pct = (norm >= 0.99).mean() * 100
    assert extremes_pct < 2.0


def test_sustained_sine_novelty():
    sr = 44100
    t = np.arange(sr * 2) / sr
    y = 0.5 * np.sin(2 * np.pi * 100 * t).astype(np.float32)
    times, novelty = compute_multiband_novelty(y, sr=sr, hop=256)
    assert len(times) > 0
    steady = novelty["all"][20:]
    assert steady.mean() < 0.2


def test_extract_onsets_clicks():
    sr = 44100
    duration = 2.0
    y = np.zeros(int(sr * duration), dtype=np.float32)
    for onset_sec in (0.2, 0.6, 1.0, 1.4):
        idx = int(onset_sec * sr)
        y[idx : idx + 200] = np.hanning(200)

    times, novelty = compute_multiband_novelty(y, sr=sr, hop=256)
    onsets = extract_onsets(times, novelty, sr=sr, hop=256, bpm=150.0)
    assert len(onsets) >= 4
    extracted_times = [o["raw_time"] for o in onsets]
    for expected in (0.2, 0.6, 1.0, 1.4):
        assert any(abs(t - expected) < 0.05 for t in extracted_times)


# --- onset v2: the mechanisms the accuracy plan asks for, on synthetic signals --
#
# These test the mechanism, not the accuracy. Whether v2 finds more real onsets
# in real music is exactly what the onset evaluation has to answer, and it cannot
# be answered without annotations. What is checked here is that the information
# the plan says is being lost is no longer lost, and that the fixes do not buy it
# by double-counting.


from beatscope.features import (  # noqa: E402
    NOISE_FLOOR_PER_BIN,
    attack_start,
    band_flux,
    compute_raw_band_novelty,
    local_background_threshold,
    resolve_close_candidates,
)

SR = 44100
HOP = 256


def _frames(seconds: float) -> int:
    return int(round(seconds * SR / HOP))


def test_in_band_cancellation_survives_only_in_v2():
    """One band, two bins trading energy: the band average stands still.

    This is the plan's minimal reproduction, on the spectrum directly: a signal
    cannot be built to cancel exactly, because leakage from one tone lands in the
    other's bins, but the statistic can be fed the matrix it is defined on.
    """
    magnitudes = np.array([[10.0, 0.0], [0.0, 10.0]])  # bins x frames

    assert band_flux(magnitudes, version=1)[1] == 0.0, "the average cancels the change"
    assert band_flux(magnitudes, version=2)[1] > 0.0, "per-bin flux keeps it"


def test_two_hits_thirty_five_ms_apart_are_one_event_in_v1_and_two_in_v2():
    gap_frames = 6  # 6 * 256 / 44100 = 34.83 ms
    values = np.zeros(40, dtype=np.float64)
    values[10] = 0.9
    values[10 + gap_frames] = 0.6

    from beatscope.features import detect_transient_peaks

    assert list(detect_transient_peaks(values, 8, 0.10)) == [10], "the shipping spacing drops one"
    assert list(resolve_close_candidates(values, np.array([10, 10 + gap_frames]), min_distance_samples=8)) == [
        10,
        10 + gap_frames,
    ]


def test_a_ripple_on_one_attack_is_not_counted_twice():
    """Keeping dense candidates must not turn one hit into two."""
    values = np.zeros(40, dtype=np.float64)
    values[10] = 0.9
    values[16] = 0.8
    values[11:16] = 0.7  # shallow valley: the same attack still ringing

    kept = resolve_close_candidates(values, np.array([10, 16]), min_distance_samples=8)
    assert list(kept) == [10]


def test_the_local_threshold_sees_a_weak_event_a_global_percentile_misses():
    """A loud passage must not raise the bar for a quiet one."""
    values = np.zeros(400, dtype=np.float64)
    values[50:150] = 0.9  # loud passage
    values[300] = 0.25  # a real but weak event, far from it

    thresholds = local_background_threshold(values)
    global_threshold = max(0.10, float(np.percentile(values, 75)))

    assert values[300] < global_threshold, "the whole-track threshold hides it"
    assert values[300] >= thresholds[300], "the local threshold does not"


def test_v2_records_where_the_attack_started_next_to_the_peak():
    rising = np.zeros(30, dtype=np.float64)
    rising[8:15] = np.linspace(0.15, 0.9, 7)  # a slow attack, peak at frame 14
    start = attack_start(rising, 14, floor=0.10)
    assert start < 14, "a slow attack must walk back"
    assert rising[start] > 0.10 and rising[start - 1] <= 0.10, "and stop at the floor"


def test_silence_yields_nothing_and_a_steady_tone_is_not_a_fact_sheet():
    """Silence is the contract. A steady tone is only a description.

    v1 reports an event every frame or so on a tone, because its whole-track
    percentile sits inside the numerical ripple of a signal with no events in it
    - the same mechanism that hides weak events in a quiet passage of real music.
    v2's local threshold does not fix that by construction: a uniform ripple has
    no peaks, but a median-plus-spread threshold still passes the tail of any
    distribution. What it must not do is invent events in silence, and the noise
    gate is what keeps inaudible signals from arriving at all.
    """
    for version in (1, 2):
        silence = np.zeros(SR, dtype=np.float32)
        times, novelty = compute_multiband_novelty(silence, SR, HOP, version=version)
        raw = compute_raw_band_novelty(silence, SR, HOP, version=version)[1]
        assert extract_onsets(times, novelty, SR, HOP, version=version, raw_novelty=raw) == [], "silence"

    time_axis = np.arange(SR) / SR
    tone = (0.3 * np.sin(2 * np.pi * 220 * time_axis)).astype(np.float32)
    v1 = extract_onsets(*compute_multiband_novelty(tone, SR, HOP, version=1), SR, HOP, version=1)
    v2 = _extract_v2(tone)
    assert len(v1) > 5, "v1 on a steady tone, for the record"
    assert len(v2) > 0, "v2 does not claim to be silent on a tone either"


def test_an_unknown_version_is_refused_rather_than_defaulted():
    time_axis = np.arange(SR) / SR
    signal = (0.3 * np.sin(2 * np.pi * 220 * time_axis)).astype(np.float32)
    for call in (
        lambda: compute_multiband_novelty(signal, SR, HOP, version=3),
        lambda: extract_onsets(np.zeros(3), {"all": np.zeros(3), "low": np.zeros(3), "mid": np.zeros(3), "high": np.zeros(3)}, SR, HOP, version=3),
        # v2 without the raw flux cannot gate, and must say so rather than
        # silently extracting from whatever the normalized signal looks like.
        lambda: extract_onsets(np.zeros(3), {"all": np.zeros(3), "low": np.zeros(3), "mid": np.zeros(3), "high": np.zeros(3)}, SR, HOP, version=2),
    ):
        with pytest.raises(ValueError):
            call()


def _extract_v2(signal: np.ndarray, sr: int = SR, hop: int = HOP) -> list[dict]:
    """Call v2 the way a caller has to: raw flux for the gate, normalized for the rest."""
    times, novelty = compute_multiband_novelty(signal, sr, hop, version=2)
    raw = compute_raw_band_novelty(signal, sr, hop, version=2)[1]
    return extract_onsets(times, novelty, sr, hop, version=2, raw_novelty=raw)


def _clicks(pairs: list[float], seconds: float = 2.0, ring: float = 0.0) -> np.ndarray:
    """Impulses at the given times, optionally with a ring between them."""
    time_axis = np.arange(int(seconds * SR)) / SR
    signal = np.zeros_like(time_axis, dtype=np.float32)
    for center in pairs:
        start = int(center * SR)
        decay = np.exp(-np.arange(200) / 60)
        signal[start:start + 200] += (0.5 * decay).astype(np.float32)
    if ring:
        gap_start, gap_end = int(pairs[0] * SR) + 200, int(pairs[1] * SR)
        signal[gap_start:gap_end] = ring
    return signal


def test_the_entry_consults_the_valley_across_the_shipping_spacing(monkeypatch):
    """The bug this replaces: the entry passed half the spacing, so a pair 35 ms
    apart cleared the distance check and the valley was never consulted."""
    from beatscope import features as features_module

    seen: dict[str, object] = {}
    real = features_module.resolve_close_candidates

    def recording(values, candidates, **kwargs):
        seen.update(kwargs)
        return real(values, candidates, **kwargs)

    monkeypatch.setattr(features_module, "resolve_close_candidates", recording)
    _extract_v2(_clicks([0.5, 0.5 + 6 * HOP / SR]))

    assert seen.get("valley_neighbourhood") == 8, (
        "the valley must be consulted wherever the shipping picker decides"
    )
    assert seen.get("min_distance_samples") == 4, "while the hard minimum stays half of it"


def test_two_hits_with_a_real_gap_between_them_survive_the_entry():
    gap = 6 * HOP / SR  # 34.83 ms, inside the shipping spacing
    first, second = 0.5, 0.5 + gap
    times = [onset["raw_time"] for onset in _extract_v2(_clicks([first, second]))]
    assert any(abs(t - first) < 0.02 for t in times), f"first hit missing: {times}"
    assert any(abs(t - second) < 0.02 for t in times), f"second hit missing: {times}"


def test_v2_refuses_inaudible_noise_through_the_entry():
    """Normalizing first maps any scale onto 0..1; the gate reads the raw flux."""
    rng = np.random.default_rng(0)
    noise = (1e-9 * rng.standard_normal(3 * SR)).astype(np.float32)
    times, novelty = compute_multiband_novelty(noise, SR, HOP, version=2)
    raw = compute_raw_band_novelty(noise, SR, HOP, version=2)[1]

    assert float(novelty["all"].max()) == pytest.approx(1.0, abs=0.01), (
        "the normalized signal looks full-scale, which is why the floor cannot live there"
    )
    assert float(np.median(raw["all"])) < NOISE_FLOOR_PER_BIN, "and the raw flux is orders below it"
    assert extract_onsets(times, novelty, SR, HOP, version=2, raw_novelty=raw) == []


def test_the_noise_gate_does_not_kill_quiet_music():
    """A quiet recording is not noise: attenuating the audio must not remove events."""
    rng = np.random.default_rng(1)
    seconds = 3.0
    time_axis = np.arange(int(seconds * SR)) / SR
    # Broadband bed with four clear hits on top, at a normal listening level.
    bed = 0.05 * rng.standard_normal(len(time_axis))
    hits = _clicks([0.5, 1.1, 1.7, 2.4], seconds=seconds)
    loud = (bed + hits).astype(np.float32)
    quiet = (loud * 0.01).astype(np.float32)  # -40 dB

    loud_times = [onset["raw_time"] for onset in _extract_v2(loud)]
    quiet_times = [onset["raw_time"] for onset in _extract_v2(quiet)]

    assert len(loud_times) >= 4, f"the hits should be found at full level: {loud_times}"
    for hit in (0.5, 1.1, 1.7, 2.4):
        assert any(abs(t - hit) < 0.03 for t in quiet_times), (
            f"the gate swallowed the hit at {hit}s: {quiet_times}"
        )
    # log1p is not scale-equivariant, so the flux shape does shift with level and
    # the counts need not match exactly. What must not happen is the gate erasing
    # the events, which is what a floor on the wrong scale would do.
    assert abs(len(quiet_times) - len(loud_times)) <= 1, f"{len(loud_times)} -> {len(quiet_times)}"
