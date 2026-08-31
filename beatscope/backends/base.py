"""AnalyzerBackend protocol and the AnalysisEvidence contract.

Backends produce intermediate evidence; they never decide the final schema,
project id, exports, or visual cues. ``pipeline.build_rhythm_project`` is the
only place where evidence becomes a RhythmProject.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np

ProgressCallback = Callable[[str, float, str], None]
CancelCallback = Callable[[], bool]


class AnalysisCancelled(RuntimeError):
    """Raised inside the pipeline when the caller requests cancellation."""


@dataclass
class AnalysisEvidence:
    """Intermediate analysis facts produced by one backend run."""

    duration: float
    sample_rate: int
    channels: int
    tempo_bpm: float
    grid_origin: float
    bars: int
    beats: list[dict[str, Any]]
    onsets: list[dict[str, Any]]
    energy: dict[str, Any]
    tempo_score: float | None = None
    # Piecewise-constant tempo segments covering [0, duration]; empty when the
    # backend has no variable-tempo evidence (the pipeline then falls back to
    # a single global-tempo segment, plan section 16.2).
    tempo_segments: list[dict[str, Any]] = field(default_factory=list)
    # Decoded mono waveform at ``sample_rate`` that the backend already holds;
    # the pipeline reuses it for whole-song structure analysis instead of
    # decoding a second time. None when the backend cannot supply it (the
    # pipeline then keeps the legacy bar-group patterns).
    audio: np.ndarray | None = None
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)


class AnalyzerBackend(Protocol):
    name: str
    version: str

    def analyze(
        self,
        audio_path: Path,
        config: "AnalysisConfig",  # noqa: F821 - imported lazily to avoid cycles
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> AnalysisEvidence:
        ...


def noop_progress(stage: str, value: float, message: str) -> None:
    return None


def never_cancelled() -> bool:
    return False


def check_cancelled(cancelled: CancelCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise AnalysisCancelled("analysis cancelled by caller")
