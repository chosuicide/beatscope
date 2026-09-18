"""Serve the built studio over one seeded synthetic project.

    python tests/browser/studio_webmcp_server.py [--port 0]

Prints one JSON line with the chosen port and the project id, then serves
until killed. The project is the repository's frozen ABA rhythm fixture plus a
silent synthetic WAV, so the browser proof never needs commercial audio and
never runs the analyzer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROJECT_ID = "0a1b2c3d4e5f"
FIXTURE = REPO / "tests" / "fixtures" / "structure" / "aba.rhythm.json"
SHORT_RENDER_FIXTURE = REPO / "tests" / "fixtures" / "runtime" / "structure-project.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument(
        "--short-render",
        action="store_true",
        help="serve the eight-second runtime fixture for the real-render smoke",
    )
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="beatscope-studio-webmcp-"))
    os.chdir(work)  # the server's ProjectManager is cwd-relative by design
    project = work / ".beatscope-cache" / "projects" / PROJECT_ID
    project.mkdir(parents=True)

    fixture = SHORT_RENDER_FIXTURE if args.short_render else FIXTURE
    rhythm = json.loads(fixture.read_text(encoding="utf-8"))
    rhythm["project_id"] = PROJECT_ID

    audio = project / "source.audio"
    with wave.open(str(audio), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * int(8000 * float(rhythm["source"]["duration"])))
    # The renderer verifies the audio against the digest recorded in the
    # rhythm, so the synthetic take gets its own honest hash.
    rhythm["source"]["sha256"] = hashlib.sha256(audio.read_bytes()).hexdigest()
    (project / "rhythm.json").write_text(json.dumps(rhythm, ensure_ascii=False), encoding="utf-8")
    (project / "project.json").write_text(
        json.dumps({
            "project_id": PROJECT_ID,
            "audio_path": str(audio),
            "display_name": "aba-fixture.wav",
            "created_at": "2026-09-13T00:00:00Z",
            "cache_key": "studio-webmcp-fixture",
        }),
        encoding="utf-8",
    )

    # The renderer looks for Playwright beside web-src; this harness installs it
    # under tests/browser, so point the server at that copy for --render runs.
    module = REPO / "tests" / "browser" / "node_modules" / "playwright" / "index.mjs"
    if module.is_file():
        os.environ.setdefault("BEATSCOPE_PLAYWRIGHT_MODULE", str(module))

    sys.path.insert(0, str(REPO))
    from beatscope.mv_jobs import renderer_tools  # noqa: E402
    from beatscope.server import BeatScopeServer, ServerContext  # noqa: E402  (born after the cwd change)

    server = BeatScopeServer.with_context(("127.0.0.1", args.port), ServerContext.create())
    print(json.dumps({
        "port": server.server_address[1],
        "project_id": PROJECT_ID,
        "renderer": renderer_tools()["available"],
    }), flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
