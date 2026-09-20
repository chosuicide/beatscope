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
from .beat_this_model import MODEL_NAME, BeatThisModelBackend, BeatThisModelUnavailable
from .demucs import DemucsBackend
from .lightweight import LightweightBackend

__all__ = [
    "AnalysisCancelled",
    "AnalysisEvidence",
    "AnalyzerBackend",
    "BeatThisBackend",
    "MODEL_NAME",
    "BeatThisModelBackend",
    "BeatThisModelUnavailable",
    "DemucsBackend",
    "LightweightBackend",
    "check_cancelled",
    "never_cancelled",
    "noop_progress",
]
