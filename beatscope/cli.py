"""Command Line Interface for BeatScope."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

from .benchmark import run_benchmark
from .models import AnalysisConfig
from .pipeline import analyze_track
from .server import serve
from .separation import run_demucs
from .rhythm import save_rhythm, write_rhythm_midi
from .exports import generate_rhythm_midi, generate_rhythm_csv
from .schema import load_rhythm_project


def warn_deprecated(command: str, replacement: str) -> None:
    print(
        f"beatscope {command} is deprecated.\nUse: {replacement}",
        file=sys.stderr,
    )


def print_project_summary(result: dict, output: Path, midi_path: Path) -> None:
    print(json.dumps({
        "output": str(output),
        "midi": str(midi_path),
        "project_id": result["project_id"],
        "backend": result["analysis"].get("backend") or result["analysis"].get("pipeline"),
        "bpm": result["tempo"]["global_bpm"],
        "origin": result["grid"]["origin"],
        "bars": result["grid"]["bars"],
        "onsets": len(result["onsets"]),
        "overview": len(result.get("patterns", {}).get("bars") or result.get("overview") or []),
    }, ensure_ascii=False))


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
    analyze = sub.add_parser("analyze", help="analyze an audio file into a rhythm project")
    analyze.add_argument("audio", type=Path)
    analyze.add_argument("-o", "--output", type=Path, help="output rhythm JSON (default: <audio>.rhythm.json)")
    analyze.add_argument("--backend", choices=("lightweight", "beat-this", "demucs"), default="lightweight")
    analyze.add_argument("--beats", type=Path, help="Beat This beat file (required for --backend beat-this)")
    analyze.add_argument("--drums", type=Path, help="drums stem to analyze instead of the full mix (beat-this)")
    analyze.add_argument("--subdivision", type=int, choices=(16, 32), default=16)

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

    # analyze-separated (deprecated)
    high = sub.add_parser(
        "analyze-separated",
        help="deprecated: use 'analyze --backend demucs'",
    )
    high.add_argument("original", type=Path)
    high.add_argument("--drums", type=Path, required=True)
    high.add_argument("--bass", type=Path, required=True)
    high.add_argument("--output", type=Path, required=True)
    high.add_argument("--model", default="htdemucs")

    # rhythm (deprecated)
    rhythm = sub.add_parser(
        "rhythm",
        help="deprecated: use 'analyze --backend beat-this'",
    )
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

    # benchmark
    bench = sub.add_parser("benchmark", help="run the accuracy benchmark against synthetic ground truth")
    bench.add_argument("--output-dir", type=Path, default=Path("build") / "benchmark")
    bench.add_argument("--fixtures-dir", type=Path, help="reuse a fixture directory instead of generating one")
    bench.add_argument(
        "--baseline",
        type=Path,
        help="accepted baseline JSON to compare against (default: tests/fixtures/benchmark-baseline.json)",
    )
    bench.add_argument(
        "--accept-baseline",
        action="store_true",
        help="explicitly re-record the baseline after reviewing the metric diff; refuses while any absolute gate fails",
    )

    # benchmark-structure (v0.7): whole-song arrangement metrics
    bench_struct = sub.add_parser(
        "benchmark-structure",
        help="run the whole-song structure benchmark against synthetic arrangements",
    )
    bench_struct.add_argument("--output-dir", type=Path, default=Path("build") / "structure-benchmark")
    bench_struct.add_argument("--fixtures-dir", type=Path, help="reuse a fixture directory instead of generating one")

    # doctor
    sub.add_parser("doctor", help="check system dependencies and configuration")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor()

    if args.command == "analyze":
        config = AnalysisConfig(backend=args.backend, subdivision=args.subdivision)
        result = analyze_track(args.audio, config, beat_file=args.beats, drums_path=args.drums)
        output = args.output or args.audio.with_suffix(".rhythm.json")
        save_rhythm(result, output)
        midi_path = output.with_suffix(".mid")
        write_rhythm_midi(result, midi_path)
        print_project_summary(result, output, midi_path)
        return 0

    if args.command == "separate":
        print(json.dumps(run_demucs(args.audio, args.output_dir, args.model, args.device), ensure_ascii=False))
        return 0

    if args.command == "analyze-separated":
        warn_deprecated("analyze-separated", "beatscope analyze --backend demucs")
        config = AnalysisConfig(backend="demucs")
        result = analyze_track(args.original, config)
        save_rhythm(result, args.output)
        midi_path = args.output.with_suffix(".mid")
        write_rhythm_midi(result, midi_path)
        print_project_summary(result, args.output, midi_path)
        return 0

    if args.command == "rhythm":
        warn_deprecated(
            "rhythm",
            "beatscope analyze --backend beat-this --beats <file> --drums <stem>",
        )
        config = AnalysisConfig(backend="beat-this", subdivision=args.subdivision)
        result = analyze_track(args.original, config, beat_file=args.beat_this, drums_path=args.drums)
        save_rhythm(result, args.output)
        midi_path = args.output.with_suffix(".rhythm.mid")
        write_rhythm_midi(result, midi_path)
        print_project_summary(result, args.output, midi_path)
        return 0

    if args.command == "benchmark":
        results = run_benchmark(
            args.output_dir, args.fixtures_dir, args.baseline,
            accept_baseline=args.accept_baseline,
        )
        print(f"Benchmark written to {results['output_dir']}")
        baseline = results.get("baseline") or {}
        if args.accept_baseline:
            if baseline.get("accepted"):
                print(f"Baseline accepted ({baseline.get('analyzer_version')}):")
                for entry in baseline.get("diff", []):
                    old_f1, new_f1 = entry["beat_f1"]
                    old_mae, new_mae = entry["beat_mae_ms"]
                    print(
                        f"  {entry['name']}: beat F1 {old_f1} -> {new_f1},"
                        f" MAE {old_mae} -> {new_mae} ms"
                    )
                return 0
            print(f"Baseline NOT accepted: {baseline.get('reason')}")
            print(f"Gates failed: {', '.join(baseline.get('gates_failed', []))}")
            return 1
        failed = results["gates"]["failed"]
        print(f"Gates failed: {', '.join(failed) if failed else 'none'}")
        return 1 if failed else 0

    if args.command == "benchmark-structure":
        from .structure_benchmark import run_structure_benchmark

        results = run_structure_benchmark(args.output_dir, args.fixtures_dir)
        print(f"Structure benchmark written to {results['output_dir']}")
        failed = results["gates"]["failed"]
        print(f"Gates failed: {', '.join(failed) if failed else 'none'}")
        return 1 if failed else 0

    if args.command == "export":
        data = load_rhythm_project(args.project)
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
