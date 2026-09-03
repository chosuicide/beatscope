"""Build the static WebMCP Director demo (v0.10 plan section 17.4).

The demo is a fully static copy of the web player plus the frozen demo
fixtures: it never calls the local analysis API, so it can be served by
any static host. The build only copies and verifies files - it never
modifies sources, never touches the network, and never re-encodes audio.

Usage:
    python scripts/build_webmcp_demo.py [--output build/webmcp-demo]

With SOURCE_DATE_EPOCH set, build-info.json is deterministic and two
builds are byte-identical (asserted by tests/test_webmcp_demo.py).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "beatscope" / "web"
RUNTIME_ROOT = REPO_ROOT / "beatscope" / "runtime"
DEMO_ROOT = WEB_ROOT / "demo"

WEB_HTML = ("index.html",)
WEB_CSS = ("style.css",)

FORBIDDEN_PATTERNS = (
    # Absolute paths, user directories, and cache/audio locations must never
    # leak into a public static bundle (plan sections 17.3, 17.4, 20.1). The
    # lookbehind keeps URL schemes like "http://" out of the drive-letter
    # match.
    re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]"),
    re.compile(r"\.beatscope-cache"),
    re.compile(r"/Users/"),
    re.compile(r"source\.audio"),
    re.compile(r"source\.path"),
)

TEXT_SUFFIXES = {".html", ".css", ".js", ".mjs", ".json"}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def package_version() -> str:
    try:
        version_module = {}
        exec((REPO_ROOT / "beatscope" / "__init__.py").read_text(encoding="utf-8"), version_module)
        return str(version_module["__version__"])
    except Exception:
        return "unknown"


def verify_fixture_lock() -> None:
    lock_path = DEMO_ROOT / "fixture-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    for entry in lock["files"].values():
        path = DEMO_ROOT / entry["file"]
        actual = sha256_of(path)
        if actual != entry["sha256"]:
            raise SystemExit(
                f"fixture-lock mismatch for {entry['file']}: lock {entry['sha256']} != actual {actual}"
            )


def copy_web_assets(output: Path) -> None:
    for name in WEB_HTML + WEB_CSS:
        shutil.copyfile(WEB_ROOT / name, output / name)
    for source in sorted(WEB_ROOT.glob("*.js")):
        shutil.copyfile(source, output / source.name)
    webmcp = output / "webmcp"
    webmcp.mkdir(exist_ok=True)
    for source in sorted((WEB_ROOT / "webmcp").glob("*.js")):
        shutil.copyfile(source, webmcp / source.name)
    runtime = output / "runtime"
    runtime.mkdir(exist_ok=True)
    for source in sorted(RUNTIME_ROOT.glob("*.js")):
        shutil.copyfile(source, runtime / source.name)
    demo = output / "demo"
    demo.mkdir(exist_ok=True)
    for source in sorted(DEMO_ROOT.iterdir()):
        if source.is_file():
            shutil.copyfile(source, demo / source.name)


def scan_for_leaks(output: Path) -> None:
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                raise SystemExit(f"static demo must not contain {pattern.pattern!r} (in {path.relative_to(output)})")


def write_build_info(output: Path) -> None:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is not None:
        built_at = dt.datetime.fromtimestamp(int(epoch), tz=dt.timezone.utc)
    else:
        built_at = dt.datetime.now(tz=dt.timezone.utc)
    info = {
        "schema": "beatscope-webmcp-demo-build-info-1",
        "commit": git_commit(),
        "version": package_version(),
        "build_time": built_at.isoformat().replace("+00:00", "Z"),
    }
    (output / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def build(output: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    verify_fixture_lock()
    copy_web_assets(output)
    scan_for_leaks(output)
    write_build_info(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "build" / "webmcp-demo",
        help="build directory (default: build/webmcp-demo)",
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else Path(os.getcwd()) / args.output
    build(output)
    files = sum(1 for path in output.rglob("*") if path.is_file())
    print(f"built {output} ({files} files); serve with: python -m http.server 8770 --directory {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
