import csv
import io
import json
import struct
import zipfile
from pathlib import Path

from beatscope.cli import main, run_doctor
from beatscope.consumer_validation import validate_handoff
from beatscope.exports import generate_codex_export, generate_rhythm_csv, generate_rhythm_midi


def test_generate_rhythm_midi_and_csv():
    rhythm_sample = {
        "tempo": {"global_bpm": 120.0},
        "grid": {"origin": 0.0},
        "beats": [
            {"time": 0.0, "beat": 1, "bar": 1, "downbeat": True, "sequence_gap": False},
            {"time": 0.5, "beat": 2, "bar": 1, "downbeat": False, "sequence_gap": False},
        ],
        "onsets": [
            {
                "id": 1,
                "raw_time": 0.0,
                "strength": 0.85,
                "bands": {"all": 0.85, "low": 0.7, "mid": 0.2, "high": 0.1},
                "accent": True,
            },
            {
                "id": 2,
                "raw_time": 0.5,
                "strength": 0.65,
                "bands": {"all": 0.65, "low": 0.1, "mid": 0.5, "high": 0.2},
                "accent": False,
            },
        ],
    }

    # MIDI
    midi_bytes = generate_rhythm_midi(rhythm_sample, subdivision=16)
    assert midi_bytes[:4] == b"MThd"
    assert struct.unpack(">H", midi_bytes[10:12])[0] == 2  # Meta track + Rhythm Reference track

    # CSV
    csv_text = generate_rhythm_csv(rhythm_sample, subdivision=16)
    lines = csv_text.strip().splitlines()
    assert len(lines) == 3
    assert "raw_time,quantized_time,offset_ms,bar,beat,step,strength,low,mid,high,accent" in lines[0]


def test_doctor_runs():
    exit_code = run_doctor()
    assert exit_code == 0


def test_doctor_reports_demucs_from_what_is_installed(monkeypatch, capsys):
    """The Demucs line must follow the probe, whatever the machine has.

    It used to print "[PASS] Demucs: installed" inside a try block that probed
    nothing, so the except branch was unreachable and the command lied to
    exactly the people who run it. Both directions are stubbed rather than
    relying on this machine: demucs is an optional extra and CI installs the
    dev set, so asserting what the local environment happens to have is how a
    test passes here and fails there.
    """
    import importlib.util

    from beatscope.cli import run_doctor

    real_find_spec = importlib.util.find_spec

    def find_spec_returning(result):
        def probe(name, *args, **kwargs):
            return result if name == "demucs" else real_find_spec(name, *args, **kwargs)
        return probe

    monkeypatch.setattr(importlib.util, "find_spec", find_spec_returning(None))
    run_doctor()
    assert "[INFO] Demucs: not installed" in capsys.readouterr().out

    # The doctor only asks whether a spec exists, so any object stands in.
    monkeypatch.setattr(importlib.util, "find_spec", find_spec_returning(object()))
    run_doctor()
    assert "[PASS] Demucs: installed" in capsys.readouterr().out


def test_cli_export(tmp_path):
    json_path = tmp_path / "rhythm.json"
    midi_path = tmp_path / "export.mid"
    csv_path = tmp_path / "export.csv"

    # v3-shaped document: the CLI export path must migrate it to v4 on read.
    rhythm_sample = {
        "schema_version": "3.0",
        "source": {"display_name": "clip.wav", "duration": 2.0, "sample_rate": 44100, "channels": 2, "sha256": "ab" * 32},
        "analysis": {"pipeline": "test", "analyzer_version": "0.3.0", "warnings": [], "separation_used": False},
        "tempo": {"global_bpm": 120.0, "confidence": 0.9, "variable_tempo": False},
        "grid": {"time_signature": [4, 4], "origin": 0.0, "default_subdivision": 16, "bars": 1},
        "beats": [{"time": 0.0, "beat": 1, "bar": 1, "downbeat": True, "confidence": 0.9, "sequence_gap": False}],
        "onsets": [{"id": 1, "raw_time": 0.0, "strength": 0.8, "bands": {"all": 0.8, "low": 0.5, "mid": 0.2, "high": 0.1}, "accent": True, "confidence": 0.8}],
        "energy": {"fps": 100, "start": 0.0, "bands": {"all": [], "low": [], "mid": [], "high": []}},
        "overview": [],
        "exports": {},
    }
    json_path.write_text(json.dumps(rhythm_sample), encoding="utf-8")

    code = main(["export", str(json_path), "--midi", str(midi_path), "--csv", str(csv_path)])
    assert code == 0
    assert midi_path.is_file()
    assert csv_path.is_file()


def test_codex_export_contains_portable_skill():
    rhythm_sample = {
        "source": {"display_name": "demo.wav", "duration": 2.0, "sample_rate": 44100},
        "tempo": {"global_bpm": 120.0},
        "grid": {"origin": 0.0, "bars": 1, "default_subdivision": 16},
        "beats": [{"time": 0.0, "beat": 1, "bar": 1}],
        "onsets": [],
        "energy": {"bands": {"all": [], "low": [], "mid": [], "high": []}},
    }
    payload = generate_codex_export(rhythm_sample)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert {"SKILL.md", "references/schema.md", "rhythm-map.json", "visual-state.js", "BEATSCOPE.md"} <= names
        assert "name: beatscope-visualizer" in archive.read("SKILL.md").decode("utf-8")


# --- variable-tempo MIDI tempo map (plan sections 19.2 / 19.4 / 22.6) -------

def _parse_midi(data: bytes) -> dict:
    """Minimal SMF reader: returns per-track [(tick, kind, a, b)] event lists."""
    assert data[:4] == b"MThd"
    header_len = struct.unpack(">I", data[4:8])[0]
    n_tracks = struct.unpack(">H", data[10:12])[0]
    division = struct.unpack(">H", data[12:14])[0]
    pos = 8 + header_len
    tracks = []
    for _ in range(n_tracks):
        assert data[pos:pos + 4] == b"MTrk"
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 8 + length
        events = []
        tick = 0
        i = 0
        while i < len(chunk):
            delta = 0
            while True:
                byte = chunk[i]
                i += 1
                delta = (delta << 7) | (byte & 0x7F)
                if not byte & 0x80:
                    break
            tick += delta
            status = chunk[i]
            i += 1
            if status == 0xFF:
                meta_type = chunk[i]
                i += 1
                payload_len = chunk[i]
                i += 1
                events.append((tick, "meta", meta_type, chunk[i:i + payload_len]))
                i += payload_len
            else:
                events.append((tick, "note", status, chunk[i], chunk[i + 1]))
                i += 2
        tracks.append(events)
    return {"division": division, "tracks": tracks}


def _note_on_ticks(parsed: dict) -> list[int]:
    ticks = []
    for track in parsed["tracks"]:
        for event in track:
            if (
                len(event) == 5
                and event[1] == "note"
                and (event[2] & 0xF0) == 0x90
                and event[4] > 0
            ):
                ticks.append(event[0])
    return sorted(ticks)


def _tempo_events(parsed: dict) -> list[tuple[int, int]]:
    """(tick, microseconds_per_quarter) for every FF 51 meta event."""
    found = []
    for track in parsed["tracks"]:
        for event in track:
            if len(event) == 4 and event[1] == "meta" and event[2] == 0x51:
                found.append((event[0], int.from_bytes(event[3], "big")))
    return found


def _variable_rhythm(origin: float = 0.0, segments: list | None = None) -> dict:
    """Tempo-map rhythm: onsets quantize exactly onto the stored beats."""
    if segments is None:
        segments = [
            {"start": 0.0, "end": 8.0, "bpm": 120.0, "method": "test", "score": None},
            {"start": 8.0, "end": 16.0, "bpm": 140.0, "method": "test", "score": None},
        ]
    return {
        "tempo": {
            "global_bpm": 129.9,
            "segments": segments,
        },
        "grid": {"origin": origin},
        "beats": [{"time": t, "bar": 1, "beat": 1} for t in (0.0, 4.0, 8.0, 12.0, 16.0)],
        "onsets": [
            {"id": i, "raw_time": t, "strength": 0.8, "bands": {"all": 0.8, "low": 0, "mid": 0, "high": 0}}
            for i, t in enumerate((2.0, 8.0, 10.0), 1)
        ],
    }


def test_midi_single_segment_matches_v0_5_ticks():
    from beatscope.midi import TPQ

    single = [{"start": 0.0, "end": 16.0, "bpm": 120.0, "method": "test", "score": None}]
    parsed = _parse_midi(generate_rhythm_midi(_variable_rhythm(origin=0.5, segments=single), subdivision=16))
    # v0.5 formula: (t - origin) * bpm / 60 * TPQ, still exact for one segment.
    assert _note_on_ticks(parsed) == [
        int(round((t - 0.5) * 120.0 / 60.0 * TPQ)) for t in (2.0, 8.0, 10.0)
    ]
    assert _tempo_events(parsed) == [(0, 500_000)]


def test_midi_change_point_tempo_event_and_post_change_integration():
    from beatscope.midi import TPQ

    parsed = _parse_midi(generate_rhythm_midi(_variable_rhythm(), subdivision=16))
    seam_tick = int(round(8.0 * 120.0 / 60.0 * TPQ))
    # The tempo meta event sits exactly at the change point tick.
    assert (seam_tick, int(round(60_000_000 / 140.0))) in _tempo_events(parsed)
    assert (0, 500_000) in _tempo_events(parsed)
    # Post-change events integrate at 140 BPM from the seam.
    assert seam_tick in _note_on_ticks(parsed)
    assert int(seam_tick + 2.0 * 140.0 / 60.0 * TPQ) in _note_on_ticks(parsed)
    # Pre-change event still uses the 120 BPM segment.
    assert int(2.0 * 120.0 / 60.0 * TPQ) in _note_on_ticks(parsed)


def test_midi_event_ticks_are_monotonic_and_roundtrip_parses():
    parsed = _parse_midi(generate_rhythm_midi(_variable_rhythm(), subdivision=16))
    for track in parsed["tracks"]:
        ticks = [tick for tick, *_rest in track]
        assert ticks == sorted(ticks)
    assert len(_tempo_events(parsed)) == 2  # round-trip: both tempo meta events


def test_csv_quantizes_against_adjacent_real_beats():
    rhythm = {
        "tempo": {"global_bpm": 120.0},
        "grid": {"origin": 0.0},
        # Non-uniform beats: a global 120 BPM grid would quantize 0.85 to
        # 0.84375; real adjacent beats (0.5 -> 0.9, 4 parts) give 0.8.
        "beats": [
            {"time": 0.0, "bar": 1, "beat": 1},
            {"time": 0.5, "bar": 1, "beat": 2},
            {"time": 0.9, "bar": 1, "beat": 3},
            {"time": 1.4, "bar": 2, "beat": 1},
        ],
        "onsets": [{"id": 1, "raw_time": 0.85, "strength": 0.5, "bands": {"all": 0.5, "low": 0, "mid": 0, "high": 0}}],
        "cues": {"accent": []},
    }
    rows = list(csv.reader(io.StringIO(generate_rhythm_csv(rhythm, subdivision=16))))
    assert rows[1][1] == "0.8000"  # quantized_time


def test_codex_export_keeps_tempo_segments_and_no_local_paths(tmp_path):
    rhythm = _variable_rhythm()
    rhythm["source"] = {"display_name": "demo.wav", "duration": 16.0, "sample_rate": 44100}
    rhythm["schema_version"] = "4.0"
    payload = generate_codex_export(rhythm)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        rhythm_map = json.loads(archive.read("rhythm-map.json").decode("utf-8"))
        assert rhythm_map["tempo"]["global_bpm"] == 129.9
        assert [s["bpm"] for s in rhythm_map["tempo"]["segments"]] == [120.0, 140.0]
        assert len(rhythm_map["beats"]) == 5
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8", errors="replace")
            assert str(tmp_path) not in text
            assert r"X:\private" not in text
# --- timing-only package -----------------------------------------------------
#
# The handoff carries measured facts plus an optional ordering sidecar. The v0.8
# visual layer is deliberately not shipped: the package states no task and
# pre-decides no visual language (see tests/test_consumer_contract.py).

TIMING_ONLY_MANIFEST = {
    "beatscope-package.json", "README.md", "AGENT.md", "rhythm-map.json",
    "rhythm.mid", "rhythm.csv", "response-relevance.json", "response-relevance-data.js",
    "visual-state.js", "beatscope-runtime.js", "worker-example.js", "consumer-probe.js",
    "BEATSCOPE.md", "SKILL.md", "references/schema.md", "LICENSE",
}
VISUAL_MANIFEST_MEMBERS = {
    "visual-recipe.json", "visual-timeline.json", "visual-recipe-data.js",
    "visual-timeline-data.js", "scene-director.js",
}


def _visual_export_rhythm():
    fixture = Path(__file__).parent / "fixtures" / "runtime" / "characterization-project.json"
    rhythm = json.loads(fixture.read_text(encoding="utf-8"))
    rhythm["project_id"] = "0a1b2c3d4e5f"
    rhythm["source"]["display_name"] = "characterization.wav"
    return rhythm


def test_codex_export_carries_timing_facts_only():
    rhythm = _visual_export_rhythm()
    with zipfile.ZipFile(io.BytesIO(generate_codex_export(rhythm))) as archive:
        names = set(archive.namelist())
        assert names == TIMING_ONLY_MANIFEST
        assert not (names & VISUAL_MANIFEST_MEMBERS)
        shim = archive.read("visual-state.js").decode("utf-8")
        assert "export function getVisualState" in shim
        assert "export function getResponseEvents" in shim
        assert "getSceneState" not in shim and "getBeatScopeFrame" not in shim
        response = json.loads(archive.read("response-relevance.json").decode("utf-8"))
        manifest = json.loads(archive.read("beatscope-package.json").decode("utf-8"))
        assert response["schema"] == "beatscope-response-relevance-1"
        assert [row["onset_id"] for row in response["events"]] == [
            onset["id"] for onset in rhythm["onsets"]
        ]
        # Honest capabilities: no scene surface, and the sidecars ride inside.
        assert manifest["capabilities"]["scenes"] is False
        assert "frame" not in manifest["functions"] and "scene" not in manifest["functions"]
        assert manifest["capabilities"]["response_relevance"] is True
        assert manifest["functions"]["response_events"] == "getResponseEvents"
        assert manifest["files"]["response_relevance"] == "response-relevance.json"
        assert manifest["display_name"] == "characterization.wav"
        assert manifest["summary"]["beats"] == len(rhythm["beats"])
        # The data module embeds the same document the JSON member holds.
        module = archive.read("response-relevance-data.js").decode("utf-8")
        assert module.startswith("// Generated by BeatScope")
        tail = module.split("export const RESPONSE_RELEVANCE = ", 1)[1]
        assert json.loads(tail.strip().rstrip(";").strip()) == response


def test_codex_export_package_is_deterministic():
    rhythm = _visual_export_rhythm()
    first = zipfile.ZipFile(io.BytesIO(generate_codex_export(rhythm)))
    second = zipfile.ZipFile(io.BytesIO(generate_codex_export(rhythm)))
    try:
        assert first.namelist() == second.namelist()
        for name in first.namelist():
            assert first.read(name) == second.read(name), name
    finally:
        first.close()
        second.close()


def test_fresh_codex_export_passes_its_executable_trust_boundary(tmp_path):
    """A live export must validate, not only the checked-in no-ranker fixture."""
    package = tmp_path / "fresh.beatscope.zip"
    package.write_bytes(generate_codex_export(_visual_export_rhythm()))

    report = validate_handoff(package)
    checks = {check["name"]: check for check in report["checks"]}

    assert checks["executable-trust"]["status"] == "passed"
    assert checks["node-probe"]["status"] == "passed"
    assert checks["worker-smoke"]["status"] == "passed"


def test_codex_export_visual_shim_imports_in_node(tmp_path):
    import shutil
    import subprocess

    if shutil.which("node") is None:
        import pytest
        pytest.skip("Node.js is not available")

    rhythm = _visual_export_rhythm()
    with zipfile.ZipFile(io.BytesIO(generate_codex_export(rhythm))) as archive:
        for name in archive.namelist():
            target = tmp_path / name.replace("/", "_")
            target.write_bytes(archive.read(name))
    driver = tmp_path / "driver.mjs"
    driver.write_text("""\
import { getVisualState, getResponseEvents } from './visual-state.js';
const direct = getVisualState(1.0);
const selected = getResponseEvents(0, 2, 2);
console.log(JSON.stringify({
  bar: direct.bar,
  beat: direct.beat,
  rankingAvailable: selected.available,
  selected: selected.events.length,
}));
""", encoding="utf-8")
    completed = subprocess.run(
        ["node", str(driver)], capture_output=True, text=True, timeout=30, check=True,
    )
    payload = json.loads(completed.stdout)
    assert payload == {
        "bar": 1,
        "beat": 3,
        "rankingAvailable": True,
        "selected": 2,
    }


def test_codex_export_visual_state_runs_in_module_worker(tmp_path):
    import shutil
    import subprocess

    if shutil.which("node") is None:
        import pytest
        pytest.skip("Node.js is not available")

    with zipfile.ZipFile(io.BytesIO(generate_codex_export(_visual_export_rhythm()))) as archive:
        for name in archive.namelist():
            (tmp_path / name.replace("/", "_")).write_bytes(archive.read(name))
    probe = tmp_path / "worker-probe.mjs"
    probe.write_text("""\
import { parentPort } from 'node:worker_threads';
globalThis.self = { postMessage: (message) => parentPort.postMessage(message) };
await import('./worker-example.js');
parentPort.on('message', (data) => globalThis.self.onmessage({ data }));
""", encoding="utf-8")
    driver = tmp_path / "worker-driver.mjs"
    driver.write_text("""\
import { Worker } from 'node:worker_threads';
const worker = new Worker(new URL('./worker-probe.mjs', import.meta.url), { type: 'module' });
const message = await new Promise((resolve, reject) => {
  worker.once('message', resolve);
  worker.once('error', reject);
  worker.postMessage({ id: 'probe', time: 1.0 });
});
await worker.terminate();
console.log(JSON.stringify(message));
""", encoding="utf-8")
    completed = subprocess.run(
        ["node", str(driver)], capture_output=True, text=True, timeout=30, check=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["id"] == "probe"
    assert payload["time"] == 1.0
    assert payload["timing"]["bar"] == 1
    # Timing facts only: the worker never carries a scene surface.
    assert "scene" not in payload


def test_codex_export_without_compilable_rhythm_stays_legacy():
    # Minimal v0.7-style maps (no project id) keep the legacy package.
    rhythm_sample = {
        "source": {"display_name": "demo.wav", "duration": 2.0, "sample_rate": 44100},
        "tempo": {"global_bpm": 120.0},
        "grid": {"origin": 0.0, "bars": 1, "default_subdivision": 16},
        "beats": [{"time": 0.0, "beat": 1, "bar": 1}],
        "onsets": [],
        "energy": {"bands": {"all": [], "low": [], "mid": [], "high": []}},
    }
    with zipfile.ZipFile(io.BytesIO(generate_codex_export(rhythm_sample))) as archive:
        names = set(archive.namelist())
        # A minimal rhythm has no rankable events, so the sidecar is absent and
        # the manifest must say so rather than pretend it is there.
        assert names == TIMING_ONLY_MANIFEST - {"response-relevance.json", "response-relevance-data.js"}
        shim = archive.read("visual-state.js").decode("utf-8")
        assert "getSceneState" not in shim
        assert "getBeatScopeFrame" not in shim
