"""Demucs backend: optional stem separation that delegates the actual analysis.

Separation only changes where the evidence comes from; it never changes the
output schema.
"""
from __future__ import annotations

from pathlib import Path

from ..backends.base import (
    AnalysisCancelled,
    AnalysisEvidence,
    AnalyzerBackend,
    CancelCallback,
    ProgressCallback,
    check_cancelled,
)
from ..backends.lightweight import LightweightBackend
from ..messages import msg
from ..models import AnalysisConfig

DEFAULT_STEMS_DIR = Path(".beatscope-cache") / "stems"


class DemucsBackend:
    """Separate stems with Demucs, then hand the drums stem to an inner backend."""

    name = "demucs"
    version = "1.0"

    def __init__(
        self,
        inner: AnalyzerBackend | None = None,
        model: str = "htdemucs",
        device: str = "cuda",
        stems_dir: Path = DEFAULT_STEMS_DIR,
    ):
        self.inner = inner if inner is not None else LightweightBackend()
        self.model = model
        self.device = device
        self.stems_dir = Path(stems_dir)

    def analyze(
        self,
        audio_path: Path,
        config: AnalysisConfig,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> AnalysisEvidence:
        check_cancelled(cancelled)
        progress("separate", 0.30, msg("stage.separate"))
        from ..separation import run_demucs

        # The separation runs for minutes; hand it the cancel callback so a
        # cancel request interrupts it instead of waiting for the next stage.
        stems = run_demucs(audio_path, self.stems_dir, self.model, self.device, cancelled=cancelled)
        drums = stems.get("drums")
        if not drums or not Path(drums).is_file():
            raise RuntimeError("Demucs separation did not produce a drums stem")

        evidence = self.inner.analyze(Path(drums), config, progress, cancelled)
        evidence.diagnostics["separated"] = True
        evidence.diagnostics["separation_model"] = self.model
        return evidence


__all__ = ["AnalyzerBackend", "AnalysisEvidence", "AnalysisCancelled", "ProgressCallback", "CancelCallback", "check_cancelled"]
