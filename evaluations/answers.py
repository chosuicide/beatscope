"""The ten read-only evaluation questions with their answer derivations.

Shared by ``build_fixture.py`` (computes and writes the XML) and the
validating test (recomputes independently and compares against the XML),
so each answer has exactly one derivation. Every question is read-only,
deterministic, and answerable from the committed fixture cache alone.
"""
from __future__ import annotations

import json
from pathlib import Path

from beatscope.mcp.models import EventsInput, VisualStateInput

EVAL_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = EVAL_DIR / "fixtures-manifest.json"


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def project_ids() -> dict[str, str]:
    """fixture short name -> committed project id."""
    return {entry["name"]: entry["project_id"] for entry in load_manifest()["projects"]}


def fixture_cache_root() -> Path:
    return EVAL_DIR / load_manifest()["fixture_cache"]


async def build_service():
    """BeatScopeService over the committed fixture cache with a live runtime."""
    from beatscope.mcp.paths import PathPolicy
    from beatscope.mcp.runtime_bridge import RuntimeBridge
    from beatscope.mcp.service import BeatScopeService
    from beatscope.project import ProjectManager

    bridge = RuntimeBridge()
    await bridge.start()
    projects = ProjectManager(fixture_cache_root())
    service = BeatScopeService(projects, PathPolicy([fixture_cache_root().parent]), runtime=bridge)
    return service, bridge


def _fmt(value: float) -> str:
    return f"{round(float(value), 4):g}"


def _rhythm_path(service, project_id: str) -> Path:
    return service.projects.projects_dir / project_id[:12] / "rhythm.json"


# ----------------------------------------------------------------- questions


async def _q1_position(service, bridge) -> str:
    ids = project_ids()
    state = await service.get_visual_state(
        VisualStateInput(project_id=ids["fixed-120"], time=2.5)
    )
    return f"bar {state['bar']}, beat {state['beat']}"


async def _q2_onset_count_compare(service, bridge) -> str:
    ids = project_ids()
    counts = {}
    for name in ("offgrid", "tempo-change"):
        page = await service.get_events(
            EventsInput(project_id=ids[name], start=0.0, end=10.0, include={"onsets"}, limit=1)
        )
        counts[name] = page["total"]
    winner = max(counts, key=lambda name: counts[name])
    return f"{ids[winner]} ({counts[winner]} vs {counts['offgrid' if winner != 'offgrid' else 'tempo-change']})"


async def _q3_nearest_accent(service, bridge) -> str:
    ids = project_ids()
    rhythm = service.load_validated_rhythm(ids["fixed-120"])
    accents = (rhythm.get("cues") or {}).get("accent") or []
    best = min(accents, key=lambda cue: abs(float(cue["time"]) - 3.0))
    return f"{_fmt(best['time'])} s"


async def _q4_lowest_strongest_onset(service, bridge) -> str:
    ids = project_ids()
    page = await service.get_events(
        EventsInput(project_id=ids["fixed-120"], start=1.0, end=3.0, include={"onsets"}, limit=500)
    )
    onsets = [event for event in page["events"] if event["kind"] == "onset"]
    best = max(onsets, key=lambda o: (o["bands"]["low"], -float(o["time"])))
    return f"{_fmt(best['time'])} s"


async def _q5_grid_affinity(service, bridge) -> str:
    ids = project_ids()
    rhythm = service.load_validated_rhythm(ids["offgrid"])
    target = min((o["time"] for o in rhythm["onsets"]), key=lambda t: abs(float(t) - 2.5))
    path = _rhythm_path(service, ids["offgrid"])
    from beatscope.mcp.runtime_bridge import file_fingerprint

    offsets = {}
    for subdivision in (16, 32):
        result = await bridge.call(
            "quantize", project=ids["offgrid"], path=str(path),
            fingerprint=file_fingerprint(path), time=float(target), subdivision=subdivision,
        )
        offsets[subdivision] = abs(result["offsetMs"])
    return "1/32" if offsets[32] < offsets[16] - 1e-6 else "1/16"


async def _q6_pattern_group_first_bar(service, bridge) -> str:
    ids = project_ids()
    rhythm = service.load_validated_rhythm(ids["tempo-change"])
    bars = (rhythm.get("patterns") or {}).get("bars") or []
    groups = []
    for entry in bars:
        group = entry.get("group")
        if group and group not in groups:
            groups.append(group)
    target_group = groups[-1]  # the last distinct group: its first appearance is non-trivial
    first_bar = next(int(e["bar"]) for e in bars if e.get("group") == target_group)
    return f"bar {first_bar}"


async def _q7_global_bpm(service, bridge) -> str:
    ids = project_ids()
    bpms = []
    for name in ("fixed-120", "tempo-change"):
        rhythm = service.load_validated_rhythm(ids[name])
        bpm = (rhythm.get("tempo") or {}).get("global_bpm")
        bpms.append(_fmt(bpm))
    return f"{bpms[0]} BPM and {bpms[1]} BPM"


async def _q8_only_downbeat(service, bridge) -> str:
    ids = project_ids()
    rhythm = service.load_validated_rhythm(ids["fixed-120"])
    downbeats = [
        float(b["time"])
        for b in rhythm["beats"]
        if b.get("downbeat") and 0.0 < float(b["time"]) <= 2.0
    ]
    assert len(downbeats) == 1, downbeats
    return f"{_fmt(downbeats[0])} s"


async def _q9_dominant_band(service, bridge) -> str:
    ids = project_ids()
    state = await service.get_visual_state(
        VisualStateInput(project_id=ids["tempo-change"], time=4.0)
    )
    bands = {name: state[name] for name in ("low", "mid", "high")}
    return max(bands, key=lambda name: bands[name])


async def _q10_beat_provenance(service, bridge) -> str:
    ids = project_ids()
    rhythm = service.load_validated_rhythm(ids["offgrid"])
    return str(rhythm["analysis"]["provenance"]["beats"]["method"])


def questions() -> list[dict[str, str]]:
    """Ordered evaluation questions bound to their answer computation."""
    ids = project_ids()
    return [
        {
            "id": "visual-position-at-2.5s",
            "question": (
                f"For project {ids['fixed-120']}, use beatscope_get_visual_state at time 2.5 "
                "seconds: which bar and beat is that?"
            ),
            "compute": _q1_position,
        },
        {
            "id": "onset-count-compare-0-10s",
            "question": (
                f"Count the onsets in the interval (0, 10] seconds for project {ids['offgrid']} "
                f"and project {ids['tempo-change']} with beatscope_get_events. Which project id "
                "has more onsets there?"
            ),
            "compute": _q2_onset_count_compare,
        },
        {
            "id": "accent-nearest-3s",
            "question": (
                f"In project {ids['fixed-120']}, which accent cue time is closest to 3.0 seconds?"
            ),
            "compute": _q3_nearest_accent,
        },
        {
            "id": "strongest-low-onset-1-3s",
            "question": (
                f"Among the onsets in (1.0, 3.0] seconds of project {ids['fixed-120']} "
                "(beatscope_get_events), which onset has the highest low-band energy? "
                "Break ties by the earliest time and answer with that onset's time."
            ),
            "compute": _q4_lowest_strongest_onset,
        },
        {
            "id": "grid-affinity-offgrid-onset",
            "question": (
                f"In project {ids['offgrid']}, take the onset closest to 2.5 seconds and "
                "quantize it against both the 1/16 and the 1/32 grid. Which subdivision does "
                "it sit closer to? Answer '1/16' or '1/32'."
            ),
            "compute": _q5_grid_affinity,
        },
        {
            "id": "pattern-group-first-bar",
            "question": (
                f"In project {ids['tempo-change']}, in which bar does the last distinct pattern "
                "group (patterns.bars[].group) appear for the first time?"
            ),
            "compute": _q6_pattern_group_first_bar,
        },
        {
            "id": "global-bpm-compare",
            "question": (
                f"Which global BPM does project {ids['fixed-120']} report, and which does "
                f"project {ids['tempo-change']} report, in that order?"
            ),
            "compute": _q7_global_bpm,
        },
        {
            "id": "only-downbeat-0-2s",
            "question": (
                f"What is the only downbeat time in the interval (0.0, 2.0] seconds of "
                f"project {ids['fixed-120']}?"
            ),
            "compute": _q8_only_downbeat,
        },
        {
            "id": "dominant-band-at-4s",
            "question": (
                f"At time 4.0 seconds in project {ids['tempo-change']}, which frequency band "
                "has the highest energy: low, mid, or high?"
            ),
            "compute": _q9_dominant_band,
        },
        {
            "id": "beat-provenance-method",
            "question": (
                f"According to its provenance, which analysis method produced the beats of "
                f"project {ids['offgrid']}?"
            ),
            "compute": _q10_beat_provenance,
        },
    ]
