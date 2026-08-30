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


def test_migrate_v3_to_v4_validates():
    from beatscope.schema import migrate_v3_to_v4, validate_rhythm_v4

    v4 = migrate_v3_to_v4(sample_v3_dict(), project_id="a1b2c3d4e5f6")
    errors = validate_rhythm_v4(v4)
    assert errors == []
    assert v4["schema_version"] == "4.0"
    assert v4["project_id"] == "a1b2c3d4e5f6"
    assert v4["meter"] == {"numerator": 4, "denominator": 4}
    assert v4["grid"].get("time_signature") is None
    assert v4["tempo"]["segments"][0]["method"] == "migrated-global-bpm"
    assert v4["tempo"]["segments"][0]["score"] is None
    assert v4["analysis"]["backend"] == "legacy"
    assert v4["analysis"]["diagnostics"]["migrated_from"] == "beat-this+demucs-drums+multiband-novelty"
    assert v4["analysis"]["diagnostics"]["legacy_tempo_score"] == 0.95
    assert v4["analysis"]["diagnostics"]["variable_tempo"] is False
    assert v4["analysis"]["provenance"]["beats"]["method"] == "unknown"


def test_migrate_v3_drops_confidence_and_moves_accent():
    import json

    from beatscope.schema import migrate_v3_to_v4

    v4 = migrate_v3_to_v4(sample_v3_dict(), project_id="a1b2c3d4e5f6")
    serialized = json.dumps(v4)
    for forbidden in ("kick", "snare", "hihat", "bass_808", "confidence"):
        assert f'"{forbidden}"' not in serialized
    assert v4["beats"][0]["beat_in_bar"] == 1 and v4["beats"][0]["downbeat"] is True
    assert v4["beats"][0]["index"] == 0
    assert v4["beats"][1]["beat_in_bar"] == 2 and v4["beats"][1]["downbeat"] is False
    assert v4["onsets"][0]["time"] == 0.0
    assert "accent" not in v4["onsets"][0]
    assert v4["cues"]["accent"] == [{"time": 0.0, "onset": 1}]


def test_migrate_v3_merges_pregrid_beats():
    from beatscope.schema import migrate_v3_to_v4, validate_rhythm_v4

    data = sample_v3_dict()
    data["beats"].insert(0, {"time": -0.5, "beat": 0, "bar": 0, "downbeat": False, "confidence": 0.9, "sequence_gap": False})
    v4 = migrate_v3_to_v4(data, project_id="a1b2c3d4e5f6")
    assert validate_rhythm_v4(v4) == []
    assert v4["beats"][0]["bar"] == 1 and v4["beats"][0]["beat_in_bar"] == 1
    assert v4["analysis"]["diagnostics"]["pregrid_beats_merged"] == 1


def test_migrate_v3_overview_becomes_patterns():
    from beatscope.schema import migrate_v3_to_v4

    data = sample_v3_dict()
    data["overview"] = [{"bar": 1, "label": "A", "group": "A", "mean_strength": 0.5, "similarity_previous": 0.0, "vector": []}]
    v4 = migrate_v3_to_v4(data, project_id="a1b2c3d4e5f6")
    assert v4["patterns"]["method"] == "migrated-from-v3-overview"
    assert v4["patterns"]["bars"][0]["label"] == "A"
    assert "overview" not in v4


def test_normalize_rhythm_passthrough_and_rejection():
    import pytest

    from beatscope.schema import UnsupportedSchemaVersion, normalize_rhythm, validate_rhythm_v4

    from beatscope.schema import migrate_v3_to_v4

    v4 = migrate_v3_to_v4(sample_v3_dict(), project_id="a1b2c3d4e5f6")
    assert normalize_rhythm(v4) is v4  # v4 passthrough, no copy
    assert validate_rhythm_v4(normalize_rhythm(sample_v3_dict())) == []
    with pytest.raises(UnsupportedSchemaVersion):
        normalize_rhythm({"schema_version": "9.9"})
    with pytest.raises(UnsupportedSchemaVersion):
        normalize_rhythm("not a dict")


def test_migrate_v2_chain_reaches_v4():
    from beatscope.schema import normalize_rhythm, validate_rhythm_v4

    v2_data = {
        "version": "2.0",
        "source": {"file": "night_owl.wav", "sample_rate": 44100, "duration": 10.0},
        "tempo": {"bpm": 130.0},
        "grid": {"time_signature": "4/4", "origin": 0.5, "subdivision": 16, "bars": 5},
        "beats": [{"time": 0.5, "beat": 1, "bar": 1, "sequence_gap": False}],
        "onsets": [{"raw_time": 0.501, "strength": 0.85, "bands": {"all": 0.85, "low": 0.7, "mid": 0.1, "high": 0.05}, "accent": True, "confidence": 0.85}],
        "energy": {"frames": [{"time": 0.0, "all": 0.0, "low": 0.0, "mid": 0.0, "high": 0.0}]},
        "overview": [],
        "analysis": {"method": "beat-this-grid"},
    }
    v4 = normalize_rhythm(v2_data, project_id="a1b2c3d4e5f6")
    assert v4["schema_version"] == "4.0"
    assert validate_rhythm_v4(v4) == []
    assert v4["cues"]["accent"][0]["onset"] == 1
    assert v4["analysis"]["diagnostics"]["migrated_from"] == "beat-this-grid"


def test_load_rhythm_project_migrates_without_rewriting(tmp_path):
    import json as json_mod

    from beatscope.schema import load_rhythm_project

    path = tmp_path / "old.rhythm.json"
    path.write_text(json_mod.dumps(sample_v3_dict()), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    project = load_rhythm_project(path)
    assert project["schema_version"] == "4.0"
    assert path.read_text(encoding="utf-8") == before  # read-time migration only
    # invalid project id in the v3 sample is re-derived, not trusted
    assert len(project["project_id"]) == 12


def test_load_rhythm_project_rejects_invalid_v4(tmp_path):
    import json as json_mod

    import pytest

    from beatscope.schema import InvalidRhythmProject, load_rhythm_project

    path = tmp_path / "bad.rhythm.json"
    bad = {"schema_version": "4.0", "tempo": {"confidence": 0.9}}
    path.write_text(json_mod.dumps(bad), encoding="utf-8")
    with pytest.raises(InvalidRhythmProject) as excinfo:
        load_rhythm_project(path)
    assert excinfo.value.errors


# --- schema v4 tempo segments and provenance extensions (plan section 22.3) ---

def _minimal_v4_project(**tempo_overrides):
    from beatscope.schema import SCHEMA_VERSION

    tempo = {
        "global_bpm": 120.0,
        "segments": [{
            "start": 0.0, "end": 12.0, "bpm": 120.0, "method": "test", "score": None,
        }],
    }
    tempo.update(tempo_overrides)
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": "a1b2c3d4e5f6",
        "source": {"display_name": "s.wav", "duration": 12.0, "sample_rate": 44100, "channels": 1, "sha256": "ab" * 32},
        "analysis": {
            "backend": "lightweight",
            "pipeline_version": "0.6.0",
            "created_at": "2026-08-30T00:00:00Z",
            "warnings": [],
            "separation_used": False,
            "provenance": {"beats": {"method": "test"}, "onsets": {"method": "test"}},
        },
        "tempo": tempo,
        "meter": {"numerator": 4, "denominator": 4},
        "grid": {"origin": 0.0, "default_subdivision": 16, "bars": 3},
        "beats": [],
        "onsets": [],
        "energy": {"fps": 100, "start": 0.0, "bands": {"all": [], "low": [], "mid": [], "high": []}},
        "patterns": {"method": "test", "bars": []},
        "cues": {"accent": [], "impact": [], "scale": [], "flow": [], "flash": [], "bloom": []},
        "exports": {},
    }


def test_v4_multi_segment_tempo_is_legal():
    from beatscope.schema import validate_rhythm_v4

    project = _minimal_v4_project(
        segments=[
            {"start": 0.0, "end": 6.0, "bpm": 118.5, "method": "a", "score": 0.5},
            {"start": 6.0, "end": 9.0, "bpm": 140.0, "method": "a", "score": None},
            {"start": 9.0, "end": 12.0, "bpm": 92.25, "method": "a", "score": 0.75},
        ],
    )
    assert validate_rhythm_v4(project) == []


def test_v4_optional_provenance_extensions_are_legal():
    from beatscope.schema import validate_rhythm_v4

    project = _minimal_v4_project()
    project["analysis"]["provenance"]["meter_phase"] = {
        "method": "four-four-cycle-from-first-tracked-beat",
        "backend": "lightweight",
        "inferred": True,
    }
    project["analysis"]["provenance"]["beats"]["tempo_source"] = "local-autocorrelation-viterbi"
    assert validate_rhythm_v4(project) == []


def test_v4_still_rejects_forbidden_confidence_in_segments():
    from beatscope.schema import validate_rhythm_v4

    project = _minimal_v4_project()
    project["tempo"]["segments"][0]["confidence"] = 0.9
    errors = validate_rhythm_v4(project)
    assert any("confidence" in error for error in errors)


def test_v4_rejects_segment_overlap_reverse_and_illegal_bpm():
    from beatscope.schema import validate_rhythm_v4

    overlap = _minimal_v4_project(
        segments=[
            {"start": 0.0, "end": 8.0, "bpm": 120.0, "method": "a", "score": None},
            {"start": 7.0, "end": 12.0, "bpm": 140.0, "method": "a", "score": None},
        ],
    )
    assert any("overlaps" in error for error in validate_rhythm_v4(overlap))

    reverse = _minimal_v4_project(
        segments=[
            {"start": 0.0, "end": 8.0, "bpm": 120.0, "method": "a", "score": None},
            {"start": 9.0, "end": 12.0, "bpm": 140.0, "method": "a", "score": None},
            {"start": 6.0, "end": 12.0, "bpm": 100.0, "method": "a", "score": None},
        ],
    )
    assert any("overlaps" in error for error in validate_rhythm_v4(reverse))

    illegal_bpm = _minimal_v4_project()
    illegal_bpm["tempo"]["segments"][0]["bpm"] = 500.0
    assert any("bpm" in error for error in validate_rhythm_v4(illegal_bpm))
