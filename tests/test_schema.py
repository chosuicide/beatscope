import pytest
from beatscope.schema import SCHEMA_VERSION, ANALYZER_VERSION, validate_rhythm_v3, migrate_v2_to_v3


def sample_v3_dict():
    return {
        "schema_version": "3.0",
        "project_id": "testproj1234",
        "source": {
            "display_name": "song.wav",
            "duration": 120.0,
            "sample_rate": 44100,
            "channels": 2,
            "sha256": "abcdef",
        },
        "analysis": {
            "pipeline": "beat-this+demucs-drums+multiband-novelty",
            "analyzer_version": "0.3.0",
            "created_at": "2026-08-25T00:00:00Z",
            "warnings": [],
            "separation_used": True,
        },
        "tempo": {
            "global_bpm": 120.0,
            "confidence": 0.95,
            "variable_tempo": False,
        },
        "grid": {
            "time_signature": [4, 4],
            "origin": 0.0,
            "default_subdivision": 16,
            "bars": 60,
        },
        "beats": [
            {
                "time": 0.0,
                "beat": 1,
                "bar": 1,
                "downbeat": True,
                "confidence": 0.95,
                "sequence_gap": False,
            },
            {
                "time": 0.5,
                "beat": 2,
                "bar": 1,
                "downbeat": False,
                "confidence": 0.95,
                "sequence_gap": False,
            },
        ],
        "onsets": [
            {
                "id": 1,
                "raw_time": 0.0,
                "strength": 0.8,
                "bands": {"all": 0.8, "low": 0.5, "mid": 0.2, "high": 0.1},
                "accent": True,
                "confidence": 0.8,
            }
        ],
        "energy": {
            "fps": 100,
            "start": 0.0,
            "bands": {
                "all": [0.1, 0.2],
                "low": [0.05, 0.1],
                "mid": [0.03, 0.05],
                "high": [0.02, 0.05],
            },
        },
        "overview": [],
        "exports": {},
    }


def test_validate_valid_v3():
    data = sample_v3_dict()
    errors = validate_rhythm_v3(data)
    assert errors == []


def test_validate_catches_invalid_version():
    data = sample_v3_dict()
    data["schema_version"] = "2.0"
    errors = validate_rhythm_v3(data)
    assert any("schema_version" in e for e in errors)


def test_validate_catches_missing_fields():
    data = sample_v3_dict()
    del data["source"]
    del data["tempo"]
    errors = validate_rhythm_v3(data)
    assert any("source" in e for e in errors)
    assert any("tempo" in e for e in errors)


def test_migrate_v2_to_v3():
    v2_data = {
        "version": "2.0",
        "source": {
            "file": "night_owl.wav",
            "path": "D:/secret/night_owl.wav",
            "drums_path": "D:/secret/drums.wav",
            "beat_this": "D:/secret/beat_this.beats",
            "sample_rate": 44100,
            "duration": 10.0,
        },
        "tempo": {"bpm": 130.0},
        "grid": {
            "time_signature": "4/4",
            "origin": 0.5,
            "subdivision": 16,
            "bars": 5,
            "step_duration": 0.115385,
        },
        "beats": [
            {"time": 0.5, "beat": 1, "bar": 1, "sequence_gap": False},
            {"time": 0.9615, "beat": 2, "bar": 1, "sequence_gap": False},
        ],
        "onsets": [
            {
                "raw_time": 0.501,
                "quantized_time": 0.5,
                "nearest_step": 0,
                "bar": 1,
                "beat": 1,
                "step_in_bar": 1,
                "offset_ms": 1.0,
                "strength": 0.85,
                "bands": {"all": 0.85, "low": 0.7, "mid": 0.1, "high": 0.05},
                "accent": True,
                "confidence": 0.85,
                "pre_grid": False,
            }
        ],
        "energy": {
            "frames": [
                {"time": 0.0, "all": 0.0, "low": 0.0, "mid": 0.0, "high": 0.0},
                {"time": 0.01, "all": 0.5, "low": 0.4, "mid": 0.1, "high": 0.0},
            ]
        },
        "overview": [
            {"bar": 1, "label": "change", "group": "A", "mean_strength": 0.5, "similarity_previous": 0.0, "vector": []}
        ],
        "analysis": {
            "method": "beat-this-grid+drums-stem-multiband-novelty",
            "labels_are": "rhythm_strength_only",
            "fallback": False,
            "beat_sequence_gaps": 0,
        },
    }

    v3 = migrate_v2_to_v3(v2_data, project_id="p12345678901")
    errors = validate_rhythm_v3(v3)
    assert errors == []

    assert v3["schema_version"] == "3.0"
    assert v3["project_id"] == "p12345678901"
    assert v3["source"]["display_name"] == "night_owl.wav"
    assert "path" not in v3["source"]  # absolute paths omitted
    assert v3["grid"]["time_signature"] == [4, 4]
    assert v3["grid"]["default_subdivision"] == 16
    assert v3["beats"][0]["downbeat"] is True
    assert v3["beats"][1]["downbeat"] is False
    assert v3["onsets"][0]["id"] == 1
    assert "quantized_time" not in v3["onsets"][0]  # derived fields not stored in v3 raw onsets
    assert v3["energy"]["fps"] == 100
    assert len(v3["energy"]["bands"]["all"]) == 2
