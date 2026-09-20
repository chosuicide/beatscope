"""The enhanced backend: what it keeps from the product, and what it takes from the model.

Two of these run anywhere. The parity check needs the optional model package and
its weights, so it skips where they are absent - which is why the wiring is tested
with a stub instead: the interesting contract is that the model supplies the beats
and nothing else changes.
"""
from __future__ import annotations

import numpy as np
import pytest

from beatscope.backends.base import never_cancelled, noop_progress
from beatscope.backends.beat_this_model import (
    BeatThisModelBackend,
    BeatThisModelUnavailable,
    _beat_rows,
    _tempo_from_beats,
    model_beats_and_downbeats,
)
from beatscope.backends.lightweight import LightweightBackend
from beatscope.models import AnalysisConfig


def _stub_evidence():
    return type(
        "Evidence",
        (),
        {
            "duration": 30.0,
            "sample_rate": 44100,
            "channels": 2,
            "tempo_bpm": 120.0,
            "grid_origin": 0.0,
            "bars": 15,
            "beats": [{"time": 0.0, "beat": 1, "bar": 1, "downbeat": True, "sequence_gap": False}],
            "onsets": [{"id": 1, "raw_time": 0.5, "strength": 0.9, "bands": {}, "accent": True, "confidence": 0.9}],
            "energy": {"fps": 100, "bands": {}},
            "tempo_score": 0.5,
            "tempo_segments": [],
            "audio": None,
            "warnings": [],
            "diagnostics": {"existing": 1},
            "provenance": {"beats": {"method": "lightweight"}, "onsets": {"method": "multiband-flux-v1"}},
        },
    )()


class _StubInner:
    """The product's own analysis, with the pieces the adapter must not touch."""

    name = "stub"
    version = "1"

    def analyze(self, audio_path, config, progress, cancelled):
        return _stub_evidence()


def test_the_model_supplies_the_beats_and_the_product_keeps_the_rest(monkeypatch, tmp_path):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF")
    beats = np.array([0.5, 1.0, 1.5, 2.0, 2.5])
    downbeats = np.array([0.5, 2.5])
    monkeypatch.setattr(
        "beatscope.backends.beat_this_model.model_beats_and_downbeats",
        lambda path, model, device: (beats, downbeats, np.full(1500, 0.75)),
    )

    backend = BeatThisModelBackend(_StubInner(), model="final0", device="cpu")
    evidence = backend.analyze(audio, AnalysisConfig.from_dict({}), noop_progress, never_cancelled)

    assert [row["time"] for row in evidence.beats] == [0.5, 1.0, 1.5, 2.0, 2.5]
    assert evidence.provenance["beats"] == {"method": "beat-this-model:final0"}
    # The onset work is the product's and must survive untouched.
    assert evidence.onsets == _stub_evidence().onsets
    assert evidence.provenance["onsets"] == {"method": "multiband-flux-v1"}
    assert evidence.diagnostics["existing"] == 1
    model_report = evidence.diagnostics["model"]
    assert model_report["frames"] == 1500
    assert model_report["frame_rate"] == pytest.approx(50.0)
    assert model_report["beats"] == 5 and model_report["downbeats"] == 2
    assert "not a calibrated probability" in model_report["support_note"]


def test_a_missing_model_package_says_so_instead_of_switching_algorithms(monkeypatch, tmp_path):
    """The plan forbids silently analysing with something else under this name."""
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setattr(
        "beatscope.backends.beat_this_model.model_beats_and_downbeats",
        lambda path, model, device: (_ for _ in ()).throw(BeatThisModelUnavailable("no Beat This here")),
    )
    backend = BeatThisModelBackend(_StubInner())
    with pytest.raises(BeatThisModelUnavailable):
        backend.analyze(audio, AnalysisConfig.from_dict({}), noop_progress, never_cancelled)


def test_beat_rows_keep_the_products_numbering_and_the_models_times():
    rows = _beat_rows(np.array([0.5, 1.0, 1.5]), np.array([0.5]))
    assert [row["time"] for row in rows] == [0.5, 1.0, 1.5]
    assert [row["downbeat"] for row in rows] == [True, False, False]
    assert [row["beat"] for row in rows] == [1, 2, 3]
    assert [row["bar"] for row in rows] == [1, 1, 1]


def test_tempo_comes_from_the_models_own_beats():
    assert _tempo_from_beats(np.array([0.0, 0.5, 1.0, 1.5])) == 120.0
    assert _tempo_from_beats(np.array([0.0])) == 0.0
    assert _tempo_from_beats(np.array([])) == 0.0


def test_the_enhanced_route_is_registered_and_never_the_default():
    from beatscope.models import BACKENDS
    from beatscope.pipeline import resolve_backend

    assert "enhanced" in BACKENDS
    assert AnalysisConfig.from_dict({}).backend == "lightweight"
    assert isinstance(resolve_backend(AnalysisConfig.from_dict({"backend": "enhanced"})), BeatThisModelBackend)


def test_the_adapter_agrees_with_the_official_pipeline():
    """Phase 3's acceptance. Skips where the optional model is not installed."""
    pytest.importorskip("beat_this", reason="needs the public-benchmark extra")
    audio = next(
        iter(sorted((_repo_root() / "build/public-benchmark/audio").rglob("*.wav"))),
        None,
    )
    if audio is None:
        pytest.skip("local Ballroom corpus is not unpacked")

    from beat_this.inference import Audio2Beats
    from beat_this.preprocessing import load_audio

    signal, sample_rate = load_audio(str(audio))
    expected_beats, expected_downbeats = Audio2Beats(checkpoint_path="final0", device="cpu")(signal, sample_rate)
    beats, downbeats, _ = model_beats_and_downbeats(audio, "final0", "cpu")

    assert list(map(float, beats)) == list(map(float, expected_beats))
    assert list(map(float, downbeats)) == list(map(float, expected_downbeats))


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[1]


def test_the_lightweight_inner_backend_is_the_default_wrapper():
    """The adapter wraps the product's analyzer rather than replacing it."""
    backend = BeatThisModelBackend(LightweightBackend())
    assert isinstance(backend.inner, LightweightBackend)
    assert backend.name == "enhanced"
    assert backend.version == "beat-this-model:final0"
