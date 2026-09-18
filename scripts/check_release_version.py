"""Fail closed unless a stable release tag matches every shipped version source.

Uses only the Python 3.10+ standard library; no package installation is needed.
Document/schema versions and historical examples are intentionally independent.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"


def _python_constant(path: Path, name: str) -> str:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"{path}: missing literal {name}")


def read_versions(root: Path) -> dict[str, str]:
    # The project uses a static, single-line TOML version. Reject missing/dynamic
    # metadata rather than importing the package or needing tomllib on Python 3.10.
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    project = re.search(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", pyproject)
    matches = re.findall(r'^version\s*=\s*[\"\']([^\"\']+)[\"\']\s*$', project[1] if project else "", re.M)
    if len(matches) != 1:
        raise ValueError("pyproject.toml: expected one static [project].version")
    versions = {
        "pyproject.toml": matches[0],
        "beatscope/__init__.py": _python_constant(root / "beatscope/__init__.py", "__version__"),
        "beatscope/exports.py": _python_constant(root / "beatscope/exports.py", "PACKAGE_VERSION"),
    }
    for name in ("package.json", "web-src/package.json"):
        versions[name] = json.loads((root / name).read_text(encoding="utf-8"))["version"]
    lock = json.loads((root / "web-src/package-lock.json").read_text(encoding="utf-8"))
    versions["web-src/package-lock.json:version"] = lock["version"]
    versions["web-src/package-lock.json:packages[''].version"] = lock["packages"][""]["version"]
    title = (root / "packaging/PORTABLE-README.txt").read_text(encoding="utf-8").splitlines()[0]
    prefix = "BEATHI STUDIO / BEATSCOPE v"
    if not title.startswith(prefix):
        raise ValueError("packaging/PORTABLE-README.txt: missing version title")
    versions["packaging/PORTABLE-README.txt"] = title[len(prefix):]
    return versions


def validate_release_version(root: Path, tag: str) -> list[str]:
    if not re.fullmatch("v" + RELEASE_VERSION, tag):
        return [f"Invalid release tag {tag!r}: expected vMAJOR.MINOR.PATCH (stable release)"]
    try:
        versions = read_versions(root)
    except (OSError, ValueError, KeyError, TypeError, IndexError, SyntaxError) as exc:
        return [f"Cannot read release versions: {exc}"]
    expected = tag[1:]
    return [
        f"{source}: {version!r} does not match tag {tag!r} (expected {expected!r})"
        for source, version in versions.items() if version != expected
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Git tag, e.g. v0.12.1")
    args = parser.parse_args()
    errors = validate_release_version(ROOT, args.tag)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Release versions match {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
