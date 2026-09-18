import json
import shutil
from copy import deepcopy

import pytest

from beatscope.project import (
    ProjectManager,
    compute_cache_key,
    content_hash,
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


def _sample_rhythm(project_id: str, sha: str, display_name: str = "song.wav") -> dict:
    """The smallest rhythm document save_project accepts."""
    return {
        "schema_version": "4.0",
        "project_id": project_id,
        "source": {"display_name": display_name, "duration": 10.0, "sample_rate": 44100, "channels": 2, "sha256": sha},
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


def _saved_project(tmp_path, name: str = "song.wav"):
    """Save one project and return (manager, project_id, project_dir)."""
    pm = ProjectManager(cache_root=tmp_path / "cache")
    audio = tmp_path / name
    audio.write_bytes(b"RIFF dummy wav data")
    sha = content_hash(audio)
    project_id = sha[:12]
    p_dir = pm.save_project(project_id, audio, _sample_rhythm(project_id, sha, name), {"subdivision": 16}, compute_cache_key(sha, {"subdivision": 16}))
    return pm, project_id, p_dir


def test_project_audio_path_is_relative_and_survives_a_moved_cache(tmp_path):
    """The stored audio path is relative, so relocating the cache keeps working."""
    pm, project_id, p_dir = _saved_project(tmp_path)

    meta = json.loads((p_dir / "project.json").read_text(encoding="utf-8"))
    assert meta["audio_path"] == "source.audio", "an absolute path would not survive a move"
    assert pm.get_project_audio_path(project_id) == p_dir / "source.audio"

    moved_root = tmp_path / "elsewhere"
    shutil.move(str(tmp_path / "cache"), str(moved_root))

    moved = ProjectManager(cache_root=moved_root)
    found = moved.get_project_audio_path(project_id)
    assert found is not None and found.is_file()
    assert found == moved_root / "projects" / project_id / "source.audio"


def test_project_audio_path_reads_legacy_absolute_paths(tmp_path):
    """A project written before the change keeps working, and degrades safely."""
    pm, project_id, p_dir = _saved_project(tmp_path)
    meta_file = p_dir / "project.json"
    elsewhere = tmp_path / "original-location.wav"
    elsewhere.write_bytes(b"RIFF the original upload")

    # A stored absolute path that still resolves is honoured.
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    meta["audio_path"] = str(elsewhere)
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    assert pm.get_project_audio_path(project_id) == elsewhere

    # One that no longer resolves falls back to the copy beside the project.
    meta["audio_path"] = str(tmp_path / "gone" / "original-location.wav")
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    assert pm.get_project_audio_path(project_id) == p_dir / "source.audio"


def test_project_without_audio_anywhere_resolves_to_none(tmp_path):
    pm, project_id, p_dir = _saved_project(tmp_path)
    (p_dir / "source.audio").unlink()
    meta_file = p_dir / "project.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    meta["audio_path"] = "missing.audio"
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    assert pm.get_project_audio_path(project_id) is None
