"""Optional Demucs launcher; keeps model and generated stems in a chosen cache."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path

def run_demucs(audio: str | Path, output_dir: str | Path, model: str = "htdemucs", device: str = "cuda") -> dict[str, str]:
    source = Path(audio).resolve(); target = Path(output_dir).resolve(); target.mkdir(parents=True, exist_ok=True)
    if device == "cuda":
        try:
            import torch
            if not torch.cuda.is_available(): raise RuntimeError("CUDA 不可用；GPU pipeline 不会偷偷回退 CPU")
        except ImportError as exc: raise RuntimeError("需要安装 CUDA Torch 才能运行 GPU Demucs") from exc
    started = time.perf_counter(); env = os.environ.copy(); env.setdefault("TORCH_HOME", str(target.parent / "torch")); env.setdefault("XDG_CACHE_HOME", str(target.parent / "xdg"))
    command = [sys.executable, "-m", "demucs.separate", "-n", model, "-d", device, "--out", str(target), str(source)]
    completed = subprocess.run(command, env=env, text=True, capture_output=True)
    log = target.parent / "separation.log"; log.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    if completed.returncode: raise RuntimeError(f"Demucs 分离失败（{completed.returncode}），详见 {log}: {completed.stderr[-1000:]}")
    stem_dir = target / model / source.stem
    metadata = {"model": model, "device": device, "source": str(source), "duration_seconds": round(time.perf_counter() - started, 3), "stems_dir": str(stem_dir), "cache_dir": str(target.parent / "xdg"), "command": " ".join(command)}
    (target.parent / "separation.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"drums": str(stem_dir / "drums.wav"), "bass": str(stem_dir / "bass.wav"), "other": str(stem_dir / "other.wav"), "vocals": str(stem_dir / "vocals.wav")}
