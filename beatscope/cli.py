"""Command Line Interface for BeatScope."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

from .analysis import analyze_audio, save_beatmap
from .server import serve
from .midi import write_midi_exports
from .high_quality import analyze_separated, save_analysis
from .separation import run_demucs
from .rhythm import analyze_rhythm, save_rhythm, write_rhythm_midi
from .exports import generate_rhythm_midi, generate_rhythm_csv


def run_doctor() -> int:
    """Check environment dependencies and system readiness."""
    print("=" * 60)
    print(" BeatScope Environment & Dependency Diagnostic (Doctor)")
    print("=" * 60)

    # 1. Python
    py_ver = sys.version.split()[0]
    if sys.version_info >= (3, 10):
        print(f" [PASS] Python version: {py_ver} (>= 3.10)")
    else:
        print(f" [FAIL] Python version: {py_ver} (requires >= 3.10)")

    # 2. Soundfile
    try:
        import soundfile as sf
        print(f" [PASS] soundfile: installed (libsndfile {sf.__libsndfile_version__})")
    except Exception as exc:
        print(f" [WARN] soundfile: not available ({exc})")

    # 3. FFmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        print(f" [PASS] ffmpeg: {ffmpeg_path}")
    else:
        print(" [WARN] ffmpeg: not found in PATH (needed for MP3/M4A if libsndfile lacks decoder)")

    # 4. Librosa
    try:
        import librosa
        print(f" [PASS] librosa: {librosa.__version__}")
    except Exception:
        print(" [WARN] librosa: not installed (required for high-quality / Demucs pipelines)")

    # 5. PyTorch & CUDA
    try:
        import torch
        cuda_avail = torch.cuda.is_available()
        device_name = torch.cuda.get_device_name(0) if cuda_avail else "CPU only"
        if cuda_avail:
            print(f" [PASS] PyTorch {torch.__version__} with CUDA: {device_name}")
        else:
            print(f" [INFO] PyTorch {torch.__version__} (CUDA not available, CPU mode)")
    except Exception:
        print(" [INFO] PyTorch: not installed (optional, needed for GPU Demucs)")

    # 6. Demucs
    try:
        import demucs
        print(f" [PASS] Demucs: installed")
    except Exception:
        print(" [INFO] Demucs: not installed (optional, needed for automated stem separation)")

    # 7. Cache Directory & Free Disk Space
    cache_path = Path(".beatscope-cache")
    try:
        cache_path.mkdir(parents=True, exist_ok=True)
        test_file = cache_path / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        print(f" [PASS] Cache directory: {cache_path.resolve()} (writable)")
    except Exception as exc:
        print(f" [FAIL] Cache directory write check failed: {exc}")

    try:
        total, used, free = shutil.disk_usage(cache_path.resolve())
        free_gb = round(free / (1024 ** 3), 2)
        if free_gb >= 1.0:
            print(f" [PASS] Free disk space: {free_gb} GB")
        else:
            print(f" [WARN] Free disk space low: {free_gb} GB")
    except Exception:
        pass

    print("=" * 60)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="beatscope", description="Create an editable rhythm map locally")
    sub = parser.add_subparsers(dest="command", required=True)

    # analyze
    analyze = sub.add_parser("analyze", help="analyze an audio file")
    analyze.add_argument("audio", type=Path)
    analyze.add_argument("-o", "--output", type=Path)
    analyze.add_argument("--midi-dir", type=Path)

    # serve
    run = sub.add_parser("serve", help="start the local web UI")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8765)
    run.add_argument("--project", type=Path)

    # separate
    separate = sub.add_parser("separate", help="run optional GPU Demucs separation")
    separate.add_argument("audio", type=Path)
    separate.add_argument("--output-dir", type=Path, default=Path(".beatscope-cache/night-owl/stems"))
    separate.add_argument("--model", default="htdemucs")
    separate.add_argument("--device", default="cuda")

    # analyze-separated
    high = sub.add_parser("analyze-separated", help="analyze Demucs drums/bass stems")
    high.add_argument("original", type=Path)
    high.add_argument("--drums", type=Path, required=True)
    high.add_argument("--bass", type=Path, required=True)
    high.add_argument("--output", type=Path, required=True)
    high.add_argument("--model", default="htdemucs")

    # rhythm
    rhythm = sub.add_parser("rhythm", help="build a fact-based rhythm map from Beat This and a drums stem")
    rhythm.add_argument("original", type=Path)
    rhythm.add_argument("--drums", type=Path, required=True)
    rhythm.add_argument("--beat-this", type=Path, required=True)
    rhythm.add_argument("--output", type=Path, required=True)
    rhythm.add_argument("--subdivision", type=int, choices=(16, 32), default=16)

    # export
    export = sub.add_parser("export", help="export rhythm reference MIDI or CSV from rhythm.json")
    export.add_argument("project", type=Path, help="Path to rhythm.json")
    export.add_argument("--midi", type=Path, help="Output MIDI file path")
    export.add_argument("--csv", type=Path, help="Output CSV file path")
    export.add_argument("--subdivision", type=int, choices=(16, 32), default=16)

    # doctor
    sub.add_parser("doctor", help="check system dependencies and configuration")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor()

    if args.command == "analyze":
        result = analyze_audio(args.audio)
        output = args.output or args.audio.with_suffix(".beatmap.json")
        save_beatmap(result, output)
        midi_dir = args.midi_dir or output.parent
        midi = write_midi_exports(result, midi_dir, output.stem.replace(".beatmap", ""))
        print(json.dumps({
            "output": str(output),
            "duration": result["source"]["duration"],
            "bpm": result["tempo"]["bpm"],
            "events": {k: len(v) for k, v in result["events"].items()},
            "bass_notes": len(result.get("bass_notes", [])),
            "midi": midi,
        }, ensure_ascii=False))
        return 0

    if args.command == "separate":
        print(json.dumps(run_demucs(args.audio, args.output_dir, args.model, args.device), ensure_ascii=False))
        return 0

    if args.command == "analyze-separated":
        result = analyze_separated(args.original, args.drums, args.bass, args.model)
        save_analysis(result, args.output)
        midi = write_midi_exports(result, args.output.parent, args.output.stem.replace(".beatmap", ""))
        print(json.dumps({
            "output": str(args.output),
            "bpm": result["tempo"]["bpm"],
            "origin": result["grid"]["origin"],
            "bars": result["grid"]["bars"],
            "events": {k: len(v) for k, v in result["events"].items()},
            "bass_notes": len(result["bass_notes"]),
            "midi": midi,
        }, ensure_ascii=False))
        return 0

    if args.command == "rhythm":
        result = analyze_rhythm(args.original, args.drums, args.beat_this, args.subdivision)
        save_rhythm(result, args.output)
        midi_path = args.output.with_suffix(".rhythm.mid")
        write_rhythm_midi(result, midi_path)
        bpm_val = result["tempo"].get("global_bpm", result["tempo"].get("bpm"))
        print(json.dumps({
            "output": str(args.output),
            "midi": str(midi_path),
            "bpm": bpm_val,
            "origin": result["grid"]["origin"],
            "bars": result["grid"]["bars"],
            "onsets": len(result["onsets"]),
            "overview": len(result["overview"]),
        }, ensure_ascii=False))
        return 0

    if args.command == "export":
        data = json.loads(args.project.read_text(encoding="utf-8"))
        subdiv = args.subdivision
        exported: dict[str, str] = {}
        if args.midi:
            midi_bytes = generate_rhythm_midi(data, subdivision=subdiv)
            args.midi.write_bytes(midi_bytes)
            exported["midi"] = str(args.midi)
        if args.csv:
            csv_str = generate_rhythm_csv(data, subdivision=subdiv)
            args.csv.write_text(csv_str, encoding="utf-8")
            exported["csv"] = str(args.csv)
        print(json.dumps({"exported": exported}, ensure_ascii=False))
        return 0

    serve(args.host, args.port, args.project)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
