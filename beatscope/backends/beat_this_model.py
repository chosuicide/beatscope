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

import bisect
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


def _beat_rows(
    times: np.ndarray,
    downbeats: np.ndarray,
    *,
    max_numerator: int = 16,
    tolerance: float = 1e-3,
) -> tuple[list[dict[str, Any]], int, str]:
    """Number the model's beats, publishing the model's own downbeats.

    Returns ``(rows, numerator, downbeat_source)``. The schema allows a numerator
    of 1..16, requires a downbeat exactly where beat_in_bar is 1, and says nothing
    about where a track starts - so the numbering bends to the model rather than
    the other way round:

    - the numerator is the longest bar, which keeps every beat_in_bar in range
      even when the model heard bars of different lengths;
    - a track that begins mid-bar is numbered as the end of the bar before it, so
      its first downbeat still lands on beat_in_bar 1;
    - only a model with no downbeats at all, or a bar longer than the schema can
      express, falls back to the product's 4-cycle - and then the source says so.
    """
    downbeat_set = set()
    for index, time in enumerate(times):
        if any(abs(float(time) - float(value)) <= tolerance for value in downbeats):
            downbeat_set.add(index)
    boundaries = sorted(downbeat_set)

    bar_lengths = [
        later - earlier for earlier, later in zip(boundaries, boundaries[1:], strict=False)
    ]
    if boundaries and boundaries[-1] != len(times) - 1:
        # The final bar runs from its downbeat to the last beat inclusive, so its
        # length is len(times) - boundaries[-1]. Subtracting one more - which this
        # did - made a single-downbeat track declare a numerator one short of the
        # positions it then generated, and the schema rejects that.
        bar_lengths.append(len(times) - boundaries[-1])
    if not boundaries:
        bar_lengths = []
    if boundaries and boundaries[0] > 0:
        bar_lengths.append(boundaries[0])  # the leading partial bar, counted back

    numerator = max(bar_lengths, default=0)
    if boundaries and max_numerator >= numerator >= 1:
        starts_on_downbeat = boundaries[0] == 0
        rows = []
        for index, time in enumerate(times):
            before = bisect.bisect_right(boundaries, index) - 1
            if before < 0:
                # Ahead of the first downbeat: the tail of the preceding bar.
                bar = 1
                position = numerator - (boundaries[0] - index) + 1
            else:
                bar = before + 1 + (0 if starts_on_downbeat else 1)
                position = index - boundaries[before] + 1
            rows.append(
                {
                    "time": round(float(time), 6),
                    "beat": position,
                    "bar": bar,
                    "downbeat": index in downbeat_set,
                    "sequence_gap": False,
                }
            )
        return rows, numerator, "measured-from-model-downbeats"

    rows = [
        {
            "time": round(float(time), 6),
            "beat": index % 4 + 1,
            "bar": index // 4 + 1,
            "downbeat": index % 4 == 0,
            "sequence_gap": False,
        }
        for index, time in enumerate(times)
    ]
    return rows, 4, "assumed-4-4-not-measured"


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

        rows, numerator, downbeat_source = _beat_rows(beats, downbeats)
        evidence.beats = rows
        evidence.tempo_bpm = _tempo_from_beats(beats)
        # Every beat-derived fact comes from the model, so the project cannot say
        # one tempo globally and another in its segments, or cover three bars of
        # beats while declaring five. Empty segments make the pipeline build one
        # segment from this tempo; the origin is the first model beat; the bar
        # count is the one the numbering produced.
        evidence.tempo_segments = []
        evidence.grid_origin = float(beats[0]) if len(beats) else 0.0
        evidence.bars = max((row["bar"] for row in rows), default=0)
        # No score exists for a tempo read off the beats, and a score is not what
        # says whether something was measured - so the backend says it directly.
        evidence.tempo_score = None
        # The model is the only source of beat judgement here; saying so keeps the
        # two contributions separable, which is the whole point of the phase.
        evidence.provenance = {
            **evidence.provenance,
            "beats": {"method": f"beat-this-model:{self.model}"},
        }
        # No beats means no measured tempo, whatever the reason; the lightweight
        # path uses the same rule. A project that says "measured" with a global
        # tempo of zero is a contradiction a consumer would have to guess about.
        evidence.diagnostics["tempo_fallback"] = len(beats) < 2
        evidence.diagnostics["meter_numerator"] = numerator
        evidence.diagnostics["meter_source"] = downbeat_source
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
            "downbeat_times": [round(float(value), 6) for value in downbeats],
        }
        # The structure analysis is computed by the pipeline from the waveform,
        # against the *lightweight* bar grid - so its bar indices do not describe
        # this project's bars. On one ARTBeaT track that produced a project the
        # schema rejects ("segments[0] must start at bar 1"), which is how a
        # warning-only version of this failed. Withholding the waveform makes the
        # pipeline skip that analysis and say so, which is the plan's rule for
        # bar-dependent work whose grid is not the one it was computed against.
        evidence.audio = None
        evidence.diagnostics["structure_unavailable"] = "computed against the lightweight bar grid"
        evidence.warnings = [
            *evidence.warnings,
            "beats come from the enhanced model, not the lightweight tracker",
            "structure analysis is unavailable here: it is computed against the lightweight bar grid",
        ]
        return evidence


__all__ = [
    "BeatThisModelBackend",
    "BeatThisModelUnavailable",
    "MODEL_NAME",
    "model_beats_and_downbeats",
]
