"""Project management, content hashing, configuration, and disk caching."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .schema import ANALYZER_VERSION, SCHEMA_VERSION, normalize_rhythm, validate_rhythm_v4


def content_hash(path: str | Path) -> str:
    """Calculate streaming SHA-256 hash of a file."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found for hashing: {path}")
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(obj: Any) -> str:
    """Produce deterministic canonical JSON string."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_cache_key(
    audio_sha256: str,
    analysis_config: dict[str, Any],
    schema_ver: str = SCHEMA_VERSION,
    analyzer_ver: str = ANALYZER_VERSION,
) -> str:
    """Compute deterministic cache key based on file hash, schema version, and config."""
    payload = (
        audio_sha256
        + ":"
        + schema_ver
        + ":"
        + analyzer_ver
        + ":"
        + canonical_json(analysis_config)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ProjectManager:
    """Manages project workspaces and cached analysis artifacts on disk."""

    def __init__(self, cache_root: str | Path = ".beatscope-cache"):
        self.cache_root = Path(cache_root).resolve()
        self.projects_dir = self.cache_root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def get_project_dir(self, project_id: str) -> Path:
        p_dir = self.projects_dir / project_id[:12]
        p_dir.mkdir(parents=True, exist_ok=True)
        return p_dir

    def find_cached_rhythm(self, sha256: str, cache_key: str) -> dict[str, Any] | None:
        """Find cached rhythm.json for this content hash whose config cache_key matches."""
        p_dir = self.projects_dir / sha256[:12]
        rhythm_file = p_dir / "rhythm.json"
        config_file = p_dir / "analysis-config.json"
        if rhythm_file.is_file() and config_file.is_file():
            try:
                cfg = json.loads(config_file.read_text(encoding="utf-8"))
                if cfg.get("cache_key") == cache_key:
                    rhythm_data = json.loads(rhythm_file.read_text(encoding="utf-8"))
                    if not validate_rhythm_v4(rhythm_data):
                        return rhythm_data
            except Exception:
                pass
        return None

    def save_project(
        self,
        project_id: str,
        audio_path: Path,
        rhythm_data: dict[str, Any],
        config: dict[str, Any],
        cache_key: str,
    ) -> Path:
        """Save project metadata, config, rhythm JSON, and subdirectories."""
        p_dir = self.get_project_dir(project_id)
        (p_dir / "stems").mkdir(exist_ok=True)
        (p_dir / "exports").mkdir(exist_ok=True)
        (p_dir / "logs").mkdir(exist_ok=True)

        # 1. project.json (contains private local path)
        project_meta = {
            "project_id": project_id[:12],
            "audio_path": str(audio_path.resolve()),
            "display_name": audio_path.name,
            "created_at": rhythm_data.get("analysis", {}).get("created_at"),
            "cache_key": cache_key,
        }
        (p_dir / "project.json").write_text(json.dumps(project_meta, indent=2, ensure_ascii=False), encoding="utf-8")

        # 2. analysis-config.json
        cfg_with_key = {**config, "cache_key": cache_key}
        (p_dir / "analysis-config.json").write_text(json.dumps(cfg_with_key, indent=2, ensure_ascii=False), encoding="utf-8")

        # 3. rhythm.json
        (p_dir / "rhythm.json").write_text(json.dumps(rhythm_data, indent=2, ensure_ascii=False), encoding="utf-8")

        # 4. adjustments.json (initialize if not present)
        adj_file = p_dir / "adjustments.json"
        if not adj_file.is_file():
            adj_file.write_text(json.dumps({"bpm": None, "origin": None}, indent=2), encoding="utf-8")

        return p_dir

    def get_project_rhythm(self, project_id: str) -> dict[str, Any] | None:
        p_dir = self.get_project_dir(project_id)
        rhythm_file = p_dir / "rhythm.json"
        if rhythm_file.is_file():
            # Read-time migration (plan section 24): stored v3 projects are
            # served as v4; the file on disk is left untouched.
            return normalize_rhythm(json.loads(rhythm_file.read_text(encoding="utf-8")))
        return None

    def get_project_audio_path(self, project_id: str) -> Path | None:
        p_dir = self.get_project_dir(project_id)
        meta_file = p_dir / "project.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                p = Path(meta.get("audio_path", ""))
                if p.is_file():
                    return p
            except Exception:
                pass
        return None

    def save_adjustments(self, project_id: str, adjustments: dict[str, Any]) -> None:
        p_dir = self.get_project_dir(project_id)
        (p_dir / "adjustments.json").write_text(json.dumps(adjustments, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_projects(self) -> list[dict[str, Any]]:
        """List recently analyzed projects."""
        results = []
        for p_dir in self.projects_dir.iterdir():
            if p_dir.is_dir():
                meta_file = p_dir / "project.json"
                if meta_file.is_file():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        results.append(meta)
                    except Exception:
                        pass
        return results
