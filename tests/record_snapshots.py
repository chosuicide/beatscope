"""Regenerate tests/snapshots/legacy/*.json from the current entry points.

Run after an intentional behavior change and review the diff before committing:

    python tests/record_snapshots.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from fixtures.generate_audio import beats_file_content, generate_all  # noqa: E402
from snapshot_utils import canonical_snapshot  # noqa: E402

SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "legacy"
TRUTH_DIR = Path(__file__).parent / "fixtures" / "truth"


def main() -> int:
    from beatscope.jobs import JobManager
    from beatscope.project import ProjectManager
    from beatscope.rhythm import analyze_rhythm

    try:
        import librosa  # noqa: F401
        has_librosa = True
    except ImportError:
        has_librosa = False

    with tempfile.TemporaryDirectory(prefix="beatscope-record-") as tmp:
        audio_dir = Path(tmp) / "audio"
        synth = generate_all(audio_dir)
        fixed_120 = synth["fixed-120"]["audio"]
        silence = synth["silence"]["audio"]

        beat_file = Path(tmp) / "fixed-120.beats"
        beat_file.write_text(beats_file_content(synth["fixed-120"]["truth"]["beats"]), encoding="utf-8")

        TRUTH_DIR.mkdir(parents=True, exist_ok=True)
        (TRUTH_DIR / "ground-truth.json").write_text(
            json.dumps({name: item["truth"] for name, item in synth.items()}, indent=2),
            encoding="utf-8",
        )

        def run_web(audio_path: str, config: dict | None = None) -> dict:
            import shutil
            import time

            # JobManager deletes its input after analysis; feed it a disposable copy.
            upload_dir = Path(tmp) / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            upload = upload_dir / Path(audio_path).name
            shutil.copy2(audio_path, upload)
            manager = ProjectManager(cache_root=Path(tmp) / "cache")
            jobs = JobManager(manager)
            job = jobs.submit_analysis(
                upload, Path(audio_path).name,
                config or {"subdivision": 16, "separation": "auto"},
            )
            deadline = time.time() + 180
            while job.state in ("queued", "running") and time.time() < deadline:
                time.sleep(0.05)
            if job.state != "complete":
                raise RuntimeError(f"web analysis failed: {job.error}")
            rhythm = manager.get_project_rhythm(job.project_id)
            if rhythm is None:
                raise RuntimeError("completed job produced no rhythm.json")
            return rhythm

        entries: dict[str, dict] = {}
        if has_librosa:
            entries["lightweight_web"] = run_web(fixed_120)
            entries["silence_web"] = run_web(silence)
            entries["rhythm_path"] = analyze_rhythm(fixed_120, fixed_120, beat_file)
        else:
            raise SystemExit("librosa is required to record snapshots")

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        for name, project in entries.items():
            target = SNAPSHOT_DIR / f"{name}.json"
            target.write_text(
                json.dumps(canonical_snapshot(project), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"recorded {target.relative_to(Path(__file__).parent)}")

    print(f"done ({len(entries)} snapshots, librosa={'yes' if has_librosa else 'no'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
