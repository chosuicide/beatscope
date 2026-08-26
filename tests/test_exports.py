import json
import io
import struct
import zipfile
from beatscope.exports import generate_codex_export, generate_rhythm_midi, generate_rhythm_csv
from beatscope.cli import run_doctor, main


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


def test_cli_export(tmp_path):
    json_path = tmp_path / "rhythm.json"
    midi_path = tmp_path / "export.mid"
    csv_path = tmp_path / "export.csv"

    rhythm_sample = {
        "tempo": {"global_bpm": 120.0},
        "grid": {"origin": 0.0},
        "beats": [{"time": 0.0, "beat": 1, "bar": 1, "downbeat": True, "sequence_gap": False}],
        "onsets": [{"raw_time": 0.0, "strength": 0.8, "bands": {"all": 0.8, "low": 0.5, "mid": 0.2, "high": 0.1}}],
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
