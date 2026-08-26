import json
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
    project_id = cache_key[:12]

    rhythm_sample = {
        "schema_version": "3.0",
        "project_id": project_id,
        "source": {"display_name": "song.wav", "duration": 10.0, "sample_rate": 44100, "channels": 2, "sha256": sha},
        "analysis": {"pipeline": "test", "analyzer_version": "0.3.0", "created_at": "2026-08-25T00:00:00Z", "warnings": [], "separation_used": False},
        "tempo": {"global_bpm": 120.0, "confidence": 0.9, "variable_tempo": False},
        "grid": {"time_signature": [4, 4], "origin": 0.0, "default_subdivision": 16, "bars": 5},
        "beats": [],
        "onsets": [],
        "energy": {"fps": 100, "start": 0.0, "bands": {"all": [], "low": [], "mid": [], "high": []}},
        "overview": [],
        "exports": {},
    }

    # Save
    p_dir = pm.save_project(project_id, audio, rhythm_sample, cfg, cache_key)
    assert (p_dir / "rhythm.json").is_file()
    assert (p_dir / "project.json").is_file()
    assert (p_dir / "adjustments.json").is_file()

    # Retrieve
    loaded = pm.get_project_rhythm(project_id)
    assert loaded["schema_version"] == "3.0"
    assert loaded["project_id"] == project_id

    # Cache lookup
    cached = pm.find_cached_rhythm(cache_key)
    assert cached is not None
    assert cached["project_id"] == project_id

    # Adjustments
    pm.save_adjustments(project_id, {"bpm": 122.5, "origin": 0.12})
    adj = json.loads((p_dir / "adjustments.json").read_text(encoding="utf-8"))
    assert adj["bpm"] == 122.5
