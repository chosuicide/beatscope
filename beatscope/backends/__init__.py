"""Backend implementations for the unified analysis pipeline."""
from __future__ import annotations

from .base import (
    AnalysisCancelled,
    AnalysisEvidence,
    AnalyzerBackend,
    check_cancelled,
    never_cancelled,
    noop_progress,
)
from .beat_this import BeatThisBackend
from .demucs import DemucsBackend
from .lightweight import LightweightBackend

__all__ = [
    "AnalysisCancelled",
    "AnalysisEvidence",
    "AnalyzerBackend",
    "BeatThisBackend",
    "DemucsBackend",
    "LightweightBackend",
    "check_cancelled",
    "never_cancelled",
    "noop_progress",
]
