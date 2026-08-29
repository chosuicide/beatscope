"""Data structures for the unified analysis pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

BACKENDS = ("lightweight", "beat-this", "demucs")
SEPARATION_MODES = ("off", "auto", "on")


@dataclass(frozen=True)
class AnalysisConfig:
    """Immutable analysis configuration; serializes stably for cache keys."""

    backend: str = "lightweight"
    subdivision: int = 16
    separation: str = "off"
    sample_rate: int = 44100
    hop_length: int = 256
    n_fft: int = 2048

    def validate(self) -> None:
        if self.backend not in BACKENDS:
            raise ValueError(f"unsupported backend: {self.backend}")
        if self.subdivision not in (16, 32):
            raise ValueError("subdivision must be 16 or 32")
        if self.separation not in SEPARATION_MODES:
            raise ValueError(f"unsupported separation mode: {self.separation}")
        if self.sample_rate <= 0 or self.hop_length <= 0 or self.n_fft <= 0:
            raise ValueError("sample_rate, hop_length and n_fft must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AnalysisConfig":
        known = {name: value for name, value in (data or {}).items() if name in cls.__dataclass_fields__}
        return cls(**known)
