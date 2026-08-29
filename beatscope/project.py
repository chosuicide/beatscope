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

    @staticmethod
    def _variant_dir(project_dir: Path, cache_key: str) -> Path:
        """Return a traversal-safe directory for one analysis configuration."""
        variant_id = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        return project_dir / "variants" / variant_id

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")

    def _activate_variant(
        self,
        project_dir: Path,
        rhythm_data: dict[str, Any],
        config_data: dict[str, Any],
    ) -> None:
        """Expose a cached variant through the stable project API paths."""
        self._write_json(project_dir / "rhythm.json", rhythm_data)
        self._write_json(project_dir / "analysis-config.json", config_data)
        meta_file = project_dir / "project.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta["cache_key"] = config_data.get("cache_key")
                meta["created_at"] = rhythm_data.get("analysis", {}).get("created_at")
                self._write_json(meta_file, meta)
            except (OSError, ValueError, TypeError):
                pass

    def find_cached_rhythm(self, sha256: str, cache_key: str) -> dict[str, Any] | None:
        """Find and activate the cached variant for an audio/config pair.

        The root project files remain the stable web/API location.  Variant
        files allow multiple backends and analysis settings for the same audio
        hash to coexist; a cache hit promotes the requested variant to root.
        """
        p_dir = self.projects_dir / sha256[:12]
        variant_dir = self._variant_dir(p_dir, cache_key)
        candidates = [
            (variant_dir / "rhythm.json", variant_dir / "analysis-config.json", True),
            (p_dir / "rhythm.json", p_dir / "analysis-config.json", False),
        ]
        for rhythm_file, config_file, is_variant in candidates:
            if not rhythm_file.is_file() or not config_file.is_file():
                continue
            try:
                cfg = json.loads(config_file.read_text(encoding="utf-8"))
                if cfg.get("cache_key") == cache_key:
                    rhythm_data = json.loads(rhythm_file.read_text(encoding="utf-8"))
                    if not validate_rhythm_v4(rhythm_data):
                        if is_variant:
                            self._activate_variant(p_dir, rhythm_data, cfg)
                        else:
                            variant_dir.mkdir(parents=True, exist_ok=True)
                            self._write_json(variant_dir / "rhythm.json", rhythm_data)
                            self._write_json(variant_dir / "analysis-config.json", cfg)
                        return rhythm_data
            except (OSError, ValueError, TypeError):
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
        """Validate and save the active project plus its config-specific variant."""
        errors = validate_rhythm_v4(rhythm_data)
        if errors:
            raise ValueError("Cannot save invalid Rhythm Project v4: " + "; ".join(errors))

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
        self._write_json(p_dir / "project.json", project_meta)

        # 2. analysis-config.json
        cfg_with_key = {**config, "cache_key": cache_key}
        self._write_json(p_dir / "analysis-config.json", cfg_with_key)

        # 3. rhythm.json
        self._write_json(p_dir / "rhythm.json", rhythm_data)

        # Keep every analysis configuration for this audio hash.  The root
        # files above are the currently active variant used by the web API.
        variant_dir = self._variant_dir(p_dir, cache_key)
        variant_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(variant_dir / "analysis-config.json", cfg_with_key)
        self._write_json(variant_dir / "rhythm.json", rhythm_data)

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
