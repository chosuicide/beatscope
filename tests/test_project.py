import json
from copy import deepcopy
import pytest
from beatscope.project import (
    content_hash,
    compute_cache_key,
    ProjectManager,
)


def test_content_hash_streaming(tmp_path):
    p = tmp_path / "test.bin"
    p.write_bytes(b"hello beatscope content hashing" * 100)
    h1 = content_hash(p)
    assert len(h1) == 64
    # modify content
    p.write_bytes(b"modified beatscope content hashing" * 100)
    h2 = content_hash(p)
    assert h1 != h2


def test_cache_key_deterministic():
    k1 = compute_cache_key("abc123", {"subdivision": 16, "separation": "auto"})
    k2 = compute_cache_key("abc123", {"separation": "auto", "subdivision": 16})
    assert k1 == k2
    k3 = compute_cache_key("abc123", {"subdivision": 32, "separation": "auto"})
    assert k1 != k3


def test_project_manager_lifecycle(tmp_path):
    pm = ProjectManager(cache_root=tmp_path / "cache")
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF dummy wav data")
    
    sha = content_hash(audio)
    cfg = {"subdivision": 16}
    cache_key = compute_cache_key(sha, cfg)
    project_id = sha[:12]

    rhythm_sample = {
        "schema_version": "4.0",
        "project_id": project_id,
        "source": {"display_name": "song.wav", "duration": 10.0, "sample_rate": 44100, "channels": 2, "sha256": sha},
        "analysis": {
            "backend": "test",
            "pipeline_version": "0.4.0",
            "created_at": "2026-08-25T00:00:00Z",
            "warnings": [],
            "separation_used": False,
            "provenance": {"beats": {"method": "test-beats"}, "onsets": {"method": "test-onsets"}},
        },
        "tempo": {"global_bpm": 120.0, "segments": [{"start": 0.0, "end": 10.0, "bpm": 120.0, "method": "test", "score": None}]},
        "meter": {"numerator": 4, "denominator": 4},
        "grid": {"origin": 0.0, "default_subdivision": 16, "bars": 5},
        "beats": [],
        "onsets": [],
        "energy": {"fps": 100, "start": 0.0, "bands": {"all": [], "low": [], "mid": [], "high": []}},
        "patterns": {"method": "bar-rhythm-cosine-v1", "bars": []},
        "cues": {"accent": [], "impact": [], "scale": [], "flow": [], "flash": [], "bloom": []},
        "exports": {},
    }

    # Save
    p_dir = pm.save_project(project_id, audio, rhythm_sample, cfg, cache_key)
    assert (p_dir / "rhythm.json").is_file()
    assert (p_dir / "project.json").is_file()
    assert (p_dir / "adjustments.json").is_file()

    # Retrieve
    loaded = pm.get_project_rhythm(project_id)
    assert loaded["schema_version"] == "4.0"
    assert loaded["project_id"] == project_id

    # Cache lookup (content-addressed: same sha, different config -> miss)
    cached = pm.find_cached_rhythm(sha, cache_key)
    assert cached is not None
    assert cached["project_id"] == project_id
    assert pm.find_cached_rhythm(sha, "stale-key") is None
    assert pm.find_cached_rhythm("0" * 64, cache_key) is None

    # Adjustments
    pm.save_adjustments(project_id, {"bpm": 122.5, "origin": 0.12})
    adj = json.loads((p_dir / "adjustments.json").read_text(encoding="utf-8"))
    assert adj["bpm"] == 122.5


def test_project_manager_rejects_invalid_v4_before_writing(tmp_path):
    pm = ProjectManager(cache_root=tmp_path / "cache")
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"audio")
    sha = content_hash(audio)
    invalid = {
        "schema_version": "4.0",
        "project_id": sha[:12],
    }

    with pytest.raises(ValueError, match="invalid Rhythm Project v4"):
        pm.save_project(sha[:12], audio, invalid, {}, compute_cache_key(sha, {}))

    assert not (pm.projects_dir / sha[:12]).exists()


def test_project_manager_preserves_and_activates_config_variants(tmp_path):
    pm = ProjectManager(cache_root=tmp_path / "cache")
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF variant cache")
    sha = content_hash(audio)
    project_id = sha[:12]

    base = {
        "schema_version": "4.0",
        "project_id": project_id,
        "source": {"display_name": "song.wav", "duration": 1.0, "sample_rate": 44100, "channels": 1, "sha256": sha},
        "analysis": {
            "backend": "test",
            "pipeline_version": "0.4.0",
            "created_at": "2026-08-29T00:00:00Z",
            "warnings": [],
            "separation_used": False,
            "provenance": {"beats": {"method": "test"}, "onsets": {"method": "test"}},
        },
        "tempo": {"global_bpm": 120.0, "segments": [{"start": 0.0, "end": 1.0, "bpm": 120.0, "method": "test", "score": None}]},
        "meter": {"numerator": 4, "denominator": 4},
        "grid": {"origin": 0.0, "default_subdivision": 16, "bars": 1},
        "beats": [],
        "onsets": [],
        "energy": {"fps": 100, "start": 0.0, "bands": {"all": [], "low": [], "mid": [], "high": []}},
        "patterns": {"method": "bar-rhythm-cosine-v1", "bars": []},
        "cues": {"accent": [], "impact": [], "scale": [], "flow": [], "flash": [], "bloom": []},
        "exports": {},
    }
    cfg16 = {"subdivision": 16}
    cfg32 = {"subdivision": 32}
    key16 = compute_cache_key(sha, cfg16)
    key32 = compute_cache_key(sha, cfg32)
    rhythm16 = deepcopy(base)
    rhythm16["analysis"]["warnings"] = ["variant-16"]
    rhythm32 = deepcopy(base)
    rhythm32["analysis"]["warnings"] = ["variant-32"]
    rhythm32["grid"]["default_subdivision"] = 32

    p_dir = pm.save_project(project_id, audio, rhythm16, cfg16, key16)
    pm.save_project(project_id, audio, rhythm32, cfg32, key32)

    assert len(list((p_dir / "variants").iterdir())) == 2
    assert pm.get_project_rhythm(project_id)["analysis"]["warnings"] == ["variant-32"]

    cached16 = pm.find_cached_rhythm(sha, key16)
    assert cached16["analysis"]["warnings"] == ["variant-16"]
    assert pm.get_project_rhythm(project_id)["analysis"]["warnings"] == ["variant-16"]

    cached32 = pm.find_cached_rhythm(sha, key32)
    assert cached32["analysis"]["warnings"] == ["variant-32"]
    assert pm.get_project_rhythm(project_id)["analysis"]["warnings"] == ["variant-32"]
