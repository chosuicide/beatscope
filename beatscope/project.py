"""Project management, content hashing, configuration, and disk caching."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator

from .schema import ANALYZER_VERSION, SCHEMA_VERSION, normalize_rhythm, validate_rhythm_v4
from .visual_recipe_schema import validate_visual_recipe, validate_visual_timeline

RECIPE_FILENAME = "visual-recipe.json"
TIMELINE_FILENAME = "visual-timeline.json"

# Bounded wait for the artifact regeneration lock.  Regeneration is
# deterministic, so an expired wait degrades to harmless concurrent writes
# of identical bytes rather than an error.
_ARTIFACT_LOCK_ATTEMPTS = 100
_ARTIFACT_LOCK_DELAY_SECONDS = 0.01
_ATOMIC_REPLACE_ATTEMPTS = 10
_ATOMIC_REPLACE_DELAY_SECONDS = 0.01


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes through a sibling temporary file and ``os.replace``."""
    descriptor, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.{os.getpid()}.",
        suffix=".tmp",
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        for attempt in range(_ATOMIC_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                # Windows may briefly deny a replace when another thread or
                # process has just replaced the same destination.  Each
                # writer owns a unique temporary file, so a bounded retry is
                # safe and preserves the final atomic hand-off.
                if attempt + 1 == _ATOMIC_REPLACE_ATTEMPTS:
                    raise
                time.sleep(_ATOMIC_REPLACE_DELAY_SECONDS)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def write_visual_artifacts(
    directory: Path,
    rhythm: dict[str, Any],
    recipe: dict[str, Any],
    timeline: dict[str, Any],
) -> None:
    """Validate and atomically persist visual artifacts (recipe first).

    Nothing is written unless both artifacts validate, so present-but-invalid
    artifacts can never replace existing valid ones (plan sections 7/8).
    """
    from .visual_recipe import canonical_visual_bytes, require_valid_visual_artifacts

    require_valid_visual_artifacts(rhythm, recipe, timeline)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(directory / RECIPE_FILENAME, canonical_visual_bytes(recipe))
    _atomic_write_bytes(directory / TIMELINE_FILENAME, canonical_visual_bytes(timeline))


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

        # 5. visual artifacts (v0.8): compile from the already-validated
        # rhythm.  Never re-runs audio analysis; fails loudly on compiler
        # errors before any artifact file is touched.
        self.ensure_visual_artifacts(rhythm_data)

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

    @contextlib.contextmanager
    def _artifact_lock(self, p_dir: Path) -> Iterator[None]:
        """Best-effort exclusive lock so concurrent readers regenerate once."""
        lock_path = p_dir / ".visual-artifacts.lock"
        acquired = False
        for _ in range(_ARTIFACT_LOCK_ATTEMPTS):
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(descriptor)
                acquired = True
                break
            except FileExistsError:
                time.sleep(_ARTIFACT_LOCK_DELAY_SECONDS)
        try:
            yield
        finally:
            if acquired:
                with contextlib.suppress(OSError):
                    lock_path.unlink()

    def _current_visual_artifacts(
        self, p_dir: Path, rhythm_data: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Return the stored artifacts when they still match the rhythm.

        Identity comes from the stored artifact fingerprint (project id,
        canonical Rhythm digest, schema/version, motif bank, compiler) plus
        a full re-validation against the rhythm.  File modification times
        are never consulted.
        """
        from .visual_recipe import visual_artifact_fingerprint

        recipe_file = p_dir / RECIPE_FILENAME
        timeline_file = p_dir / TIMELINE_FILENAME
        if not (recipe_file.is_file() and timeline_file.is_file()):
            return None
        try:
            recipe = json.loads(recipe_file.read_text(encoding="utf-8"))
            timeline = json.loads(timeline_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(recipe, dict) or not isinstance(timeline, dict):
            return None
        diagnostics = recipe.get("diagnostics")
        expected = visual_artifact_fingerprint(rhythm_data)
        if not isinstance(diagnostics, dict) or diagnostics.get("artifact_fingerprint") != expected:
            return None
        if validate_visual_recipe(recipe) or validate_visual_timeline(timeline, rhythm_data, recipe):
            return None
        return recipe, timeline

    def ensure_visual_artifacts(
        self, rhythm_data: dict[str, Any], *, force: bool = False
    ) -> dict[str, Any]:
        """Compile and persist visual artifacts for a rhythm (plan section 8).

        Regenerates only when artifacts are missing or their fingerprint/
        version no longer matches, unless ``force`` is set.  Compilation and
        validation happen in memory first; invalid artifacts never replace
        existing ones.  Audio is never re-analyzed and ``project_id`` never
        changes.
        """
        from .visual_recipe import compile_visual_artifacts

        errors = validate_rhythm_v4(rhythm_data)
        if errors:
            raise ValueError(
                "Cannot compile visual artifacts for an invalid Rhythm Project v4: "
                + "; ".join(errors)
            )

        p_dir = self.get_project_dir(str(rhythm_data.get("project_id", ""))[:12])
        if not force:
            current = self._current_visual_artifacts(p_dir, rhythm_data)
            if current is not None:
                return {
                    "recipe": current[0],
                    "timeline": current[1],
                    "regenerated": False,
                    "project_dir": p_dir,
                }
        recipe, timeline = compile_visual_artifacts(rhythm_data)
        with self._artifact_lock(p_dir):
            write_visual_artifacts(p_dir, rhythm_data, recipe, timeline)
        return {
            "recipe": recipe,
            "timeline": timeline,
            "regenerated": True,
            "project_dir": p_dir,
        }

    def get_project_visual_artifacts(
        self, project_id: str, *, force: bool = False
    ) -> dict[str, Any] | None:
        """Load a project rhythm and its visual artifacts, regenerating lazily.

        This is the project-load path that upgrades v0.7 caches on first
        read (plan section 8).
        """
        rhythm = self.get_project_rhythm(project_id)
        if rhythm is None:
            return None
        artifacts = self.ensure_visual_artifacts(rhythm, force=force)
        return {
            "rhythm": rhythm,
            "recipe": artifacts["recipe"],
            "timeline": artifacts["timeline"],
            "regenerated": artifacts["regenerated"],
        }

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
