"""Release tags must describe the Python, frontend, and portable artifacts."""
from __future__ import annotations

import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts/check_release_version.py"
checker = runpy.run_path(str(CHECKER))
read_versions = checker["read_versions"]
validate_release_version = checker["validate_release_version"]
SOURCES = (
    "pyproject.toml",
    "beatscope/__init__.py",
    "beatscope/exports.py",
    "package.json",
    "web-src/package.json",
    "web-src/package-lock.json",
    "packaging/PORTABLE-README.txt",
)


@pytest.fixture
def release_tree(tmp_path):
    for source in SOURCES:
        target = tmp_path / source
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, target)
    return tmp_path


def test_repository_versions_match_patch_release():
    assert validate_release_version(ROOT, "v0.12.1") == []
    assert set(read_versions(ROOT).values()) == {"0.12.1"}


@pytest.mark.parametrize("tag", ["v0.12.0", "v0.12.2", "v1.0.0"])
def test_rejects_mismatched_tag(tag):
    errors = validate_release_version(ROOT, tag)
    assert errors and all("does not match tag" in error for error in errors)


@pytest.mark.parametrize("tag", ["", "v", "0.12.1", "v0.12", "v00.12.1", "v0.12.1-rc.1", "v0.12.1\n"])
def test_rejects_malformed_or_nonstable_tag(tag):
    assert "Invalid release tag" in validate_release_version(ROOT, tag)[0]


@pytest.mark.parametrize("source", SOURCES)
def test_rejects_stale_version_source(release_tree, source):
    path = release_tree / source
    path.write_text(path.read_text(encoding="utf-8").replace("0.12.1", "0.12.0"), encoding="utf-8")
    errors = validate_release_version(release_tree, "v0.12.1")
    assert any(source in error and "does not match tag" in error for error in errors)


@pytest.mark.parametrize("location", ["top", "root_package"])
def test_checks_both_lockfile_versions_independently(release_tree, location):
    path = release_tree / "web-src/package-lock.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    target = lock if location == "top" else lock["packages"][""]
    target["version"] = "0.12.0"
    path.write_text(json.dumps(lock), encoding="utf-8")
    errors = validate_release_version(release_tree, "v0.12.1")
    assert len(errors) == 1
    assert "web-src/package-lock.json" in errors[0]


@pytest.mark.parametrize("source", SOURCES)
def test_missing_source_fails_closed(release_tree, source):
    (release_tree / source).unlink()
    assert "Cannot read release versions" in validate_release_version(release_tree, "v0.12.1")[0]


def test_malformed_metadata_fails_closed(release_tree):
    (release_tree / "web-src/package-lock.json").write_text("{}", encoding="utf-8")
    assert "Cannot read release versions" in validate_release_version(release_tree, "v0.12.1")[0]


@pytest.mark.parametrize("tag,code", [("v0.12.1", 0), ("v0.12.0", 1), ("invalid", 1)])
def test_cli_exit_status(tag, code, tmp_path):
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--tag", tag],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == code, result.stderr
    assert ("Release versions match" in result.stdout) if code == 0 else result.stderr


def test_release_builds_depend_on_version_gate():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    for job in ("python-package", "windows-portable"):
        assert f"  {job}:\n    needs: [ci, version]" in workflow
    version_job = workflow.split("  version:\n", 1)[1].split("  ci:\n", 1)[0]
    assert "actions/checkout@" in version_job
    assert 'run: python scripts/check_release_version.py --tag "$RELEASE_TAG"' in version_job
    assert "RELEASE_TAG: ${{ github.ref_name }}" in version_job


def test_readme_version_statements_match_the_project():
    """The badges and the install line state the current version.

    Both READMEs are checked. Release URLs are deliberately not: the product
    tour video was attached to v0.12.0 by hand and no later release carries it,
    so pointing that link at a newer tag would break it. Only the statements
    that must track the current version are asserted.
    """
    version = read_versions(ROOT)["pyproject.toml"]
    for name in ("README.md", "README.zh-CN.md"):
        readme = (ROOT / name).read_text(encoding="utf-8")
        assert f"badge/version-{version}-" in readme, f"{name}: version badge is stale"
        assert f"releases/tag/v{version})" in readme, f"{name}: release link is stale"
        assert f"beatscope-{version}-py3-none-any.whl" in readme, f"{name}: wheel name is stale"
