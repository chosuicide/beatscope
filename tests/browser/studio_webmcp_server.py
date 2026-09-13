"""Serve the built studio over one seeded synthetic project.

    python tests/browser/studio_webmcp_server.py [--port 0]

Prints one JSON line with the chosen port and the project id, then serves
until killed. The project is the repository's frozen ABA rhythm fixture plus a
silent synthetic WAV, so the browser proof never needs commercial audio and
never runs the analyzer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROJECT_ID = "0a1b2c3d4e5f"
FIXTURE = REPO / "tests" / "fixtures" / "structure" / "aba.rhythm.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="beatscope-studio-webmcp-"))
    os.chdir(work)  # the server's ProjectManager is cwd-relative by design
    project = work / ".beatscope-cache" / "projects" / PROJECT_ID
    project.mkdir(parents=True)

    rhythm = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rhythm["project_id"] = PROJECT_ID
    (project / "rhythm.json").write_text(json.dumps(rhythm, ensure_ascii=False), encoding="utf-8")

    audio = project / "source.audio"
    with wave.open(str(audio), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * int(8000 * float(rhythm["source"]["duration"])))
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

    sys.path.insert(0, str(REPO))
    from beatscope.server import Handler  # noqa: E402  (born after the cwd change)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(json.dumps({"port": server.server_address[1], "project_id": PROJECT_ID}), flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
