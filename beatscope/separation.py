"""Optional Demucs launcher; keeps model and generated stems in a chosen cache."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .backends.base import AnalysisCancelled
from .messages import msg

# Separation is slow - minutes of CPU for minutes of audio - so this is a hang
# guard rather than a performance budget: it is the point at which waiting
# longer cannot plausibly end well. Override it with
# BEATSCOPE_DEMUCS_TIMEOUT_SECONDS for an unusually slow machine.
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("BEATSCOPE_DEMUCS_TIMEOUT_SECONDS", 3600))
_POLL_SECONDS = 0.5


class SeparationTimeout(RuntimeError):
    """The Demucs child did not finish inside the deadline."""


def _kill(process: subprocess.Popen) -> None:
    process.kill()
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - the kill already landed
        pass


def wait_for_process(
    process: subprocess.Popen,
    *,
    cancelled: Callable[[], bool] | None,
    timeout_seconds: float,
) -> tuple[str, str]:
    """Wait for a child process, honouring cancellation and a deadline.

    Returns its (stdout, stderr). Raises AnalysisCancelled when ``cancelled()``
    turns true and SeparationTimeout when the deadline passes; the child is
    killed either way. The analysis queue has one worker, so a separation that
    never returns would otherwise block every later job with nothing able to
    interrupt it.
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            stdout, stderr = process.communicate(timeout=_POLL_SECONDS)
            return stdout or "", stderr or ""
        except subprocess.TimeoutExpired:
            if cancelled is not None and cancelled():
                _kill(process)
                raise AnalysisCancelled("Demucs separation cancelled") from None
            if time.monotonic() >= deadline:
                _kill(process)
                raise SeparationTimeout(
                    f"Demucs separation did not finish within {timeout_seconds:.0f}s "
                    "(BEATSCOPE_DEMUCS_TIMEOUT_SECONDS raises the limit)"
                ) from None


def run_demucs(
    audio: str | Path,
    output_dir: str | Path,
    model: str = "htdemucs",
    device: str = "cuda",
    *,
    cancelled: Callable[[], bool] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, str]:
    source = Path(audio).resolve(); target = Path(output_dir).resolve(); target.mkdir(parents=True, exist_ok=True)
    if device == "cuda":
        try:
            import torch
            if not torch.cuda.is_available(): raise RuntimeError(msg("error.cuda-unavailable"))
        except ImportError as exc: raise RuntimeError(msg("error.cuda-torch-missing")) from exc
    started = time.perf_counter(); env = os.environ.copy(); env.setdefault("TORCH_HOME", str(target.parent / "torch")); env.setdefault("XDG_CACHE_HOME", str(target.parent / "xdg"))
    command = [sys.executable, "-m", "demucs.separate", "-n", model, "-d", device, "--out", str(target), str(source)]
    log = target.parent / "separation.log"
    process = subprocess.Popen(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = wait_for_process(process, cancelled=cancelled, timeout_seconds=timeout_seconds)
    except (AnalysisCancelled, SeparationTimeout) as exc:
        # Keep whatever the child managed to say: for a hang, that log is the
        # only evidence of where it stopped.
        log.write_text(f"{exc}\n", encoding="utf-8")
        raise
    log.write_text(stdout + "\n" + stderr, encoding="utf-8")
    if process.returncode: raise RuntimeError(msg("error.demucs-failed", code=process.returncode, log=log, detail=stderr[-1000:]))
    stem_dir = target / model / source.stem
    metadata = {"model": model, "device": device, "source": str(source), "duration_seconds": round(time.perf_counter() - started, 3), "stems_dir": str(stem_dir), "cache_dir": str(target.parent / "xdg"), "command": " ".join(command)}
    (target.parent / "separation.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"drums": str(stem_dir / "drums.wav"), "bass": str(stem_dir / "bass.wav"), "other": str(stem_dir / "other.wav"), "vocals": str(stem_dir / "vocals.wav")}
