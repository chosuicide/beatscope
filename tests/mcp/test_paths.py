"""PathPolicy security tests (plan sections 9 and 23.1)."""
import os
from pathlib import Path

import pytest

from beatscope.mcp.errors import PathNotAllowed
from beatscope.mcp.paths import AUDIO_SUFFIXES, PathPolicy


@pytest.fixture()
def policy(tmp_path: Path) -> PathPolicy:
    root = tmp_path / "music"
    root.mkdir()
    return PathPolicy([root])


@pytest.fixture()
def audio_file(tmp_path: Path) -> Path:
    root = tmp_path / "music"
    target = root / "song.wav"
    target.write_bytes(b"RIFF")
    return target


def test_resolves_valid_audio_inside_root(policy: PathPolicy, audio_file: Path) -> None:
    resolved = policy.resolve_audio(str(audio_file))
    assert resolved.is_absolute()
    assert resolved.name == "song.wav"


def test_resolves_relative_path_against_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "music"
    root.mkdir()
    (root / "song.flac").write_bytes(b"fLaC")
    policy = PathPolicy([root])
    monkeypatch.chdir(root)
    resolved = policy.resolve_audio("song.flac")
    assert resolved == (root / "song.flac").resolve()


def test_rejects_dotdot_escape(policy: PathPolicy, tmp_path: Path) -> None:
    secret = tmp_path / "secret.wav"
    secret.write_bytes(b"RIFF")
    with pytest.raises(PathNotAllowed, match="allowed roots"):
        policy.resolve_audio(os.path.join(str(tmp_path / "music"), os.pardir, "secret.wav"))


def test_rejects_directory(policy: PathPolicy, audio_file: Path) -> None:
    with pytest.raises(PathNotAllowed, match="not a regular file"):
        policy.resolve_audio(str(audio_file.parent))


def test_rejects_wrong_extension(policy: PathPolicy, tmp_path: Path) -> None:
    (policy.allowed_roots[0] / "notes.txt").write_text("hi")
    with pytest.raises(PathNotAllowed, match="extensions"):
        policy.resolve_audio(str(policy.allowed_roots[0] / "notes.txt"))


def test_rejects_missing_file(policy: PathPolicy) -> None:
    with pytest.raises(PathNotAllowed, match="does not exist"):
        policy.resolve_audio(str(policy.allowed_roots[0] / "ghost.wav"))


def test_rejects_empty_and_nul(policy: PathPolicy) -> None:
    with pytest.raises(PathNotAllowed):
        policy.resolve_audio("")
    with pytest.raises(PathNotAllowed):
        policy.resolve_audio("song\x00.wav")


def test_rejects_oversized_input(policy: PathPolicy, monkeypatch: pytest.MonkeyPatch) -> None:
    from beatscope.mcp import paths as paths_mod

    monkeypatch.setattr(paths_mod, "MAX_INPUT_BYTES", 4)
    big = policy.allowed_roots[0] / "big.wav"
    big.write_bytes(b"RIFFxxxx")
    with pytest.raises(PathNotAllowed, match="limit"):
        policy.resolve_audio(str(big))


def test_beat_file_requires_beats_suffix(policy: PathPolicy) -> None:
    wrong = policy.allowed_roots[0] / "beats.txt"
    wrong.write_text("120.0 0.5")
    with pytest.raises(PathNotAllowed, match="extensions"):
        policy.resolve_beat_file(str(wrong))


def test_export_target_rules(policy: PathPolicy, tmp_path: Path) -> None:
    root = policy.allowed_roots[0]
    ok = policy.resolve_export_target(str(root / "out.zip"))
    assert ok == (root / "out.zip").resolve()

    with pytest.raises(PathNotAllowed, match=r"\.zip"):
        policy.resolve_export_target(str(root / "out.tar"))

    with pytest.raises(PathNotAllowed, match="parent directory does not exist"):
        policy.resolve_export_target(str(root / "missing-dir" / "out.zip"))

    outside = tmp_path / "outside.zip"
    with pytest.raises(PathNotAllowed, match="allowed roots"):
        policy.resolve_export_target(str(outside))

    target_dir = root / "adir.zip"
    target_dir.mkdir()
    with pytest.raises(PathNotAllowed, match="existing directory"):
        policy.resolve_export_target(str(target_dir))


def test_symlink_escape_rejected(policy: PathPolicy, tmp_path: Path) -> None:
    secret = tmp_path / "secret.wav"
    secret.write_bytes(b"RIFF")
    link = policy.allowed_roots[0] / "innocent.wav"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks requires privileges on this platform")
        return
    with pytest.raises(PathNotAllowed, match="allowed roots"):
        policy.resolve_audio(str(link))


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from beatscope.mcp.paths import MCPSettings

    monkeypatch.setenv("BEATSCOPE_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("BEATSCOPE_ALLOWED_ROOTS", os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")]))
    monkeypatch.setenv("BEATSCOPE_MCP_NODE", "node20")
    monkeypatch.setenv("BEATSCOPE_MCP_MAX_RESPONSE_CHARS", "5000")
    monkeypatch.setenv("BEATSCOPE_MCP_LOG_LEVEL", "debug")
    settings = MCPSettings.from_env()
    assert settings.cache_root == tmp_path / "cache"
    assert len(settings.allowed_roots) == 2
    assert settings.node_command == "node20"
    assert settings.max_response_chars == 5000
    assert settings.log_level == "DEBUG"

    monkeypatch.delenv("BEATSCOPE_ALLOWED_ROOTS")
    fallback = MCPSettings.from_env()
    assert fallback.allowed_roots  # cwd fallback keeps the server usable
    assert set(AUDIO_SUFFIXES) == {".wav", ".flac", ".mp3", ".ogg", ".m4a"}
