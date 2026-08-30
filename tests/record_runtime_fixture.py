"""Record tests/fixtures/runtime/variable-tempo-project.json from a fixed v0.6 analysis.

The runtime characterization must come from one real analyzer run, pinned to
disk. Re-run after an intentional analyzer change and review the diff:

    python tests/record_runtime_fixture.py

Unstable fields (``analysis.created_at``) are removed; float values are
rounded to 4 decimals so the file stays machine-stable. Energy arrays are
kept in full because the runtime reads them frame by frame.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from fixtures.generate_audio import generate_all  # noqa: E402

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "runtime" / "variable-tempo-project.json"


def _round_floats(obj: Any, digits: int = 4) -> Any:
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return round(obj, digits)
    if isinstance(obj, dict):
        return {key: _round_floats(value, digits) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(value, digits) for value in obj]
    return obj


def main() -> int:
    from beatscope.pipeline import analyze_track

    with tempfile.TemporaryDirectory(prefix="beatscope-runtime-fixture-") as tmp:
        synth = generate_all(Path(tmp))
        project = analyze_track(synth["tempo-change"]["audio"])

    project.pop("created_at", None)
    analysis = project.get("analysis")
    if isinstance(analysis, dict):
        analysis.pop("created_at", None)
        analysis.pop("warnings", None)

    FIXTURE_PATH.write_text(
        json.dumps(_round_floats(project), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    segments = project["tempo"]["segments"]
    print(f"recorded {FIXTURE_PATH.relative_to(Path(__file__).parent.parent)}: "
          f"{len(project['beats'])} beats, {len(segments)} segments "
          f"({', '.join(str(s['bpm']) for s in segments)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
