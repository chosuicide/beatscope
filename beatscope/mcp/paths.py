"""Path whitelist policy for untrusted MCP inputs (plan section 9).

Model-supplied paths are untrusted even though the server runs locally: the
policy fixes the validation order and turns every rejection into an
actionable ``PathNotAllowed`` instead of leaking raw OS errors.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .errors import PathNotAllowed

AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".ogg", ".m4a"}
BEAT_SUFFIXES = {".beats"}
EXPORT_SUFFIXES = {".zip"}

ROOTS_ENV = "BEATSCOPE_ALLOWED_ROOTS"
CACHE_ROOT_ENV = "BEATSCOPE_CACHE_ROOT"
NODE_ENV = "BEATSCOPE_MCP_NODE"
MAX_RESPONSE_CHARS_ENV = "BEATSCOPE_MCP_MAX_RESPONSE_CHARS"
LOG_LEVEL_ENV = "BEATSCOPE_MCP_LOG_LEVEL"

# The web upload path enforces the same ceiling; MCP inputs must not become a
# loophole around it.
try:
    from ..web_api import MAX_UPLOAD_BYTES as MAX_INPUT_BYTES
except ImportError:  # pragma: no cover - web_api only fails if exports/jobs break
    MAX_INPUT_BYTES = 500 * 1024 * 1024

_ROOT_HELP = (
    "Path is outside BeatScope's allowed roots. Add its parent directory to "
    "BEATSCOPE_ALLOWED_ROOTS and restart the MCP server, or copy the file into "
    "an already allowed directory."
)


def _parse_roots(raw: str) -> tuple[Path, ...]:
    roots = []
    for part in raw.split(os.pathsep):
        candidate = part.strip()
        if candidate:
            roots.append(Path(candidate).expanduser().resolve())
    return tuple(roots)


@dataclass(frozen=True)
class MCPSettings:
    """Environment-driven server settings (plan section 8.2)."""

    cache_root: Path
    allowed_roots: tuple[Path, ...]
    node_command: str
    max_response_chars: int
    log_level: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "MCPSettings":
        environment = os.environ if env is None else env
        raw_roots = environment.get(ROOTS_ENV, "") or os.getcwd()
        try:
            max_chars = int(environment.get(MAX_RESPONSE_CHARS_ENV, "25000"))
        except ValueError:
            max_chars = 25000
        return cls(
            cache_root=Path(environment.get(CACHE_ROOT_ENV, ".beatscope-cache")).expanduser(),
            allowed_roots=_parse_roots(raw_roots) or (Path.cwd().resolve(),),
            node_command=environment.get(NODE_ENV, "node"),
            max_response_chars=max(1000, max_chars),
            log_level=environment.get(LOG_LEVEL_ENV, "WARNING").upper(),
        )


def is_allowed(path: Path, roots: Iterable[Path]) -> bool:
    """Containment without string-prefix tricks."""
    return any(path == root or path.is_relative_to(root) for root in roots)


class PathPolicy:
    """Resolve and authorize model-supplied paths against allowed roots."""

    def __init__(self, allowed_roots: Iterable[Path]) -> None:
        roots = tuple(Path(root).expanduser().resolve() for root in allowed_roots)
        if not roots:
            raise ValueError("PathPolicy requires at least one allowed root")
        self.allowed_roots = roots

    def resolve_input(self, raw: str, suffixes: set[str], kind: str) -> Path:
        if not raw or "\x00" in raw:
            raise PathNotAllowed(f"{kind} path is empty or contains a NUL character.")
        path = Path(raw).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            raise PathNotAllowed(
                f"{kind} file does not exist: {raw}. Provide an existing local file."
            ) from None
        if not resolved.is_file():
            raise PathNotAllowed(f"{kind} path is not a regular file: {resolved}")
        if not is_allowed(resolved, self.allowed_roots):
            raise PathNotAllowed(_ROOT_HELP)
        if resolved.suffix.lower() not in suffixes:
            allowed = ", ".join(sorted(suffixes))
            raise PathNotAllowed(
                f"{kind} file must have one of these extensions: {allowed}. Got: {resolved.suffix or '(none)'}"
            )
        try:
            size = resolved.stat().st_size
        except OSError as exc:  # pragma: no cover - stat on a just-checked file
            raise PathNotAllowed(f"{kind} file cannot be read: {exc}") from None
        if size > MAX_INPUT_BYTES:
            limit_mb = MAX_INPUT_BYTES // (1024 * 1024)
            raise PathNotAllowed(f"{kind} file exceeds BeatScope's {limit_mb} MB limit: {resolved}")
        return resolved

    def resolve_audio(self, raw: str) -> Path:
        return self.resolve_input(raw, AUDIO_SUFFIXES, "Audio")

    def resolve_beat_file(self, raw: str) -> Path:
        return self.resolve_input(raw, BEAT_SUFFIXES, "Beat file")

    def resolve_export_target(self, raw: str) -> Path:
        if not raw or "\x00" in raw:
            raise PathNotAllowed("Destination path is empty or contains a NUL character.")
        if Path(raw).suffix.lower() != ".zip":
            raise PathNotAllowed(f"Destination must end with .zip: {raw}")
        target = Path(raw).expanduser()
        parent = target.parent
        try:
            resolved_parent = parent.resolve(strict=True)
        except (OSError, RuntimeError):
            raise PathNotAllowed(
                f"Destination parent directory does not exist: {parent}. Create it first."
            ) from None
        if not resolved_parent.is_dir():
            raise PathNotAllowed(f"Destination parent is not a directory: {resolved_parent}")
        if not is_allowed(resolved_parent, self.allowed_roots):
            raise PathNotAllowed(_ROOT_HELP)
        if not os.access(resolved_parent, os.W_OK):
            raise PathNotAllowed(f"Destination parent directory is not writable: {resolved_parent}")
        if target.is_dir():
            raise PathNotAllowed(f"Destination is an existing directory: {target}")
        return resolved_parent / target.name
