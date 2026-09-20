"""Beat This model backend: the model's beats, BeatScope's everything else.

The accuracy plan's phase 3. A mature model supplies the general rhythmic
judgement - beats and downbeats - while the product keeps its own onset
extraction, energy and structure work, so the two contributions can be reported
apart.

The adapter does not re-implement the model's post-processing. It calls the same
`Audio2Frames` + `Postprocessor(type="minimal")` pair that the official
`Audio2Beats` uses, with the same official audio loader, so its beat times agree
with that pipeline by construction rather than by hope. DBN is a separate
post-processor that needs madmom and is off by default upstream; this backend
matches the default.

The per-frame logits are kept and reported as *model support*. They are not
calibrated probabilities and are never presented as one.

One thing this deliberately does not do: express the model's own downbeats as the
product's bar/beat numbering. The schema requires a bar and a beat-in-bar for
every beat and the pipeline fixes 4/4, so a model that hears three or five beats
per bar cannot be carried through yet. The beats therefore keep the product's
existing numbering, and the model's downbeat times are recorded in the
diagnostics for the phase 5 work that lifts that restriction.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..messages import msg
from .base import (
    AnalysisEvidence,
    AnalyzerBackend,
    CancelCallback,
    ProgressCallback,
    check_cancelled,
)

MODEL_NAME = "final0"
MODEL_CACHE: dict[tuple[str, str], tuple[Any, Any]] = {}


class BeatThisModelUnavailable(RuntimeError):
    """The optional model package or its weights are not available."""


def _tools(model: str, device: str) -> tuple[Any, Any]:
    """The frame model and the official minimal post-processor, cached per process.

    Loading the checkpoint takes seconds, and the queue runs one worker per
    process, so the pair is built once and reused for every track it analyses.
    """
    key = (model, device)
    if key not in MODEL_CACHE:
        try:
            from beat_this.inference import Audio2Frames
            from beat_this.model.postprocessor import Postprocessor
        except ImportError as exc:  # pragma: no cover - depends on the optional extra
            raise BeatThisModelUnavailable(
                "the enhanced backend needs the public-benchmark extra (Beat This)"
            ) from exc
        MODEL_CACHE[key] = (
            Audio2Frames(checkpoint_path=model, device=device),
            Postprocessor(type="minimal"),
        )
    return MODEL_CACHE[key]


def model_beats_and_downbeats(
    audio_path: str | Path, model: str = MODEL_NAME, device: str = "cpu"
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Beat and downbeat times from the official model, plus its beat support.

    Returns ``(beats, downbeats, beat_support)`` where the times are seconds and
    the support is the sigmoid of the per-frame beat logits - the model's
    confidence in its own frames, which is what the plan asks to be reported as
    support rather than as a probability.
    """
    try:
        from beat_this.preprocessing import load_audio
    except ImportError as exc:  # pragma: no cover - depends on the optional extra
        raise BeatThisModelUnavailable("the enhanced backend needs the public-benchmark extra") from exc

    frames, postprocess = _tools(model, device)
    # The official loader, so the signal handed to the model is the one the
    # official pipeline would have handed it.
    signal, sample_rate = load_audio(str(audio_path))
    beat_logits, downbeat_logits = frames(signal, sample_rate)
    beats, downbeats = postprocess(beat_logits, downbeat_logits)
    # On CUDA the logits arrive as a GPU tensor, which numpy cannot read; the
    # support curve is small and belongs on the host anyway.
    if hasattr(beat_logits, "detach"):
        beat_logits = beat_logits.detach().cpu()
    logits = np.asarray(beat_logits, dtype=np.float64)
    support = 1.0 / (1.0 + np.exp(-logits))
    return np.asarray(beats, dtype=float), np.asarray(downbeats, dtype=float), support


def _beat_rows(times: np.ndarray, downbeats: np.ndarray, numerator: int = 4) -> list[dict[str, Any]]:
    """Product-shaped beat rows for the model's times.

    Numbering stays the product's 4-cycle for now; see the module docstring for
    why the model's own downbeats are not used for bar/beat yet. They are kept in
    the diagnostics instead of being dropped.
    """
    rows: list[dict[str, Any]] = []
    for index, time in enumerate(times):
        rows.append(
            {
                "time": round(float(time), 6),
                "beat": index % numerator + 1,
                "bar": index // numerator + 1,
                "downbeat": index % numerator == 0,
                "sequence_gap": False,
            }
        )
    return rows


def _tempo_from_beats(times: np.ndarray) -> float:
    """Median beat interval as a tempo, or 0.0 when there is nothing to measure."""
    if len(times) < 2:
        return 0.0
    intervals = np.diff(np.asarray(times, dtype=float))
    intervals = intervals[intervals > 0]
    if len(intervals) == 0:
        return 0.0
    median = float(np.median(intervals))
    return round(60.0 / median, 3) if median > 0 else 0.0


class BeatThisModelBackend:
    """The official model's beats over the lightweight analysis of everything else."""

    name = "enhanced"

    def __init__(
        self,
        inner: AnalyzerBackend,
        model: str = MODEL_NAME,
        device: str = "cpu",
    ) -> None:
        self.inner = inner
        self.model = model
        self.device = device
        # The protocol wants a version string; naming the checkpoint keeps two
        # runs under different weights distinguishable in the provenance.
        self.version = f"beat-this-model:{model}"

    def analyze(
        self,
        audio_path: Path,
        config: Any,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> AnalysisEvidence:
        check_cancelled(cancelled)
        progress("model", 0.25, msg("stage.model"))
        beats, downbeats, support = model_beats_and_downbeats(audio_path, self.model, self.device)
        check_cancelled(cancelled)

        # The product's own work, unchanged: onsets, energy, structure.
        evidence = self.inner.analyze(audio_path, config, progress, cancelled)

        evidence.beats = _beat_rows(beats, downbeats)
        evidence.tempo_bpm = _tempo_from_beats(beats)
        evidence.tempo_score = None
        # The model is the only source of beat judgement here; saying so keeps the
        # two contributions separable, which is the whole point of the phase.
        evidence.provenance = {
            **evidence.provenance,
            "beats": {"method": f"beat-this-model:{self.model}"},
        }
        evidence.diagnostics["model"] = {
            "checkpoint": self.model,
            "device": self.device,
            "frames": int(len(support)),
            "frame_rate": (
                round(len(support) / evidence.duration, 4) if evidence.duration else None
            ),
            "beats": int(len(beats)),
            "downbeats": int(len(downbeats)),
            "mean_beat_support": round(float(np.mean(support)), 6) if len(support) else None,
            "support_note": "sigmoid of the model's frame logits; not a calibrated probability",
            "downbeat_times": [round(float(value), 6) for value in downbeats[:64]],
        }
        evidence.warnings = [*evidence.warnings, "beats come from the enhanced model, not the lightweight tracker"]
        return evidence


__all__ = [
    "BeatThisModelBackend",
    "BeatThisModelUnavailable",
    "MODEL_NAME",
    "model_beats_and_downbeats",
]
