"""RuntimeBridge unit tests (plan section 23.1).

Uses the real Node worker when node is available; stub worker scripts cover
timeout, crash-restart, and shutdown paths. All tests skip when Node.js is
missing so the suite stays portable.
"""
import asyncio
import json
import shutil
import sys
from pathlib import Path

import pytest

from mcp_support import FIXTURE_RHYTHM, PROJECT_A

from beatscope.mcp.errors import RuntimeUnavailable
from beatscope.mcp.runtime_bridge import WORKER_PATH, RuntimeBridge, file_fingerprint

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not available"),
]


@pytest.fixture
async def bridge():
    bridge = RuntimeBridge()
    await bridge.start()
    yield bridge
    await bridge.close()


def _write_worker(tmp_path: Path, body: str) -> Path:
    worker = tmp_path / "stub_worker.mjs"
    worker.write_text(body, encoding="utf-8")
    return worker


async def test_ping_roundtrip(bridge):
    result = await bridge.call("ping")
    assert result["pong"] is True
    assert result["node"].startswith("v")


async def test_at_returns_runtime_state(bridge, tmp_path):
    path = tmp_path / "rhythm.json"
    path.write_text(FIXTURE_RHYTHM.read_text(encoding="utf-8"), encoding="utf-8")
    state = await bridge.call(
        "at", project=PROJECT_A, path=str(path), fingerprint=file_fingerprint(path), time=1.25
    )
    assert state["bar"] == 1
    assert state["beat"] == 3
    assert state["onset"]["age"] == pytest.approx(0.25)


async def test_at_null_age_before_first_onset_becomes_null(bridge, tmp_path):
    path = tmp_path / "rhythm.json"
    path.write_text(FIXTURE_RHYTHM.read_text(encoding="utf-8"), encoding="utf-8")
    state = await bridge.call(
        "at", project=PROJECT_A, path=str(path), fingerprint=file_fingerprint(path), time=-0.5
    )
    assert state["onset"]["item"] is None
    assert state["onset"]["age"] is None  # Infinity -> null JSON transport rule
    assert state["onset"]["value"] == 0


async def test_fingerprint_change_reloads_track(bridge, tmp_path):
    path = tmp_path / "rhythm.json"
    rhythm = json.loads(FIXTURE_RHYTHM.read_text(encoding="utf-8"))
    path.write_text(json.dumps(rhythm), encoding="utf-8")
    request = dict(project=PROJECT_A, path=str(path), fingerprint=file_fingerprint(path))
    before = await bridge.call("at", time=1.25, **request)

    # Change a stored fact (energy band), not just derived values: post-grid
    # position math is driven by stored beats, so bpm alone would not move it.
    rhythm["energy"]["bands"]["all"] = [0.0] * len(rhythm["energy"]["bands"]["all"])
    path.write_text(json.dumps(rhythm), encoding="utf-8")
    request["fingerprint"] = file_fingerprint(path)
    after = await bridge.call("at", time=1.25, **request)

    assert before["all"] != after["all"]  # worker reloaded the changed file


async def test_timeout_fails_and_terminates_worker(tmp_path):
    worker = _write_worker(
        tmp_path,
        "process.stdin.resume();\nsetInterval(() => {}, 1000);\n",
    )
    bridge = RuntimeBridge(worker_path=worker, timeout=0.3)
    await bridge.start()
    try:
        with pytest.raises(RuntimeUnavailable, match="did not answer"):
            await bridge.call("ping")
        await asyncio.sleep(0.1)
        assert bridge._process.returncode is not None  # wedged worker was killed
    finally:
        await bridge.close()


async def test_worker_crash_fails_pending_then_restarts_once(tmp_path):
    worker = _write_worker(
        tmp_path,
        "process.stdin.resume();\n"
        "let buffer = '';\n"
        "process.stdin.on('data', (chunk) => {\n"
        "  buffer += chunk;\n"
        "  let index;\n"
        "  while ((index = buffer.indexOf('\\n')) >= 0) {\n"
        "    const line = buffer.slice(0, index); buffer = buffer.slice(index + 1);\n"
        "    if (!line.trim()) continue;\n"
        "    const request = JSON.parse(line);\n"
        "    if (request.op === 'boom') { process.exit(1); }\n"
        "    process.stdout.write(JSON.stringify({ id: request.id, ok: true, result: { pong: true } }) + '\\n');\n"
        "  }\n"
        "});\n",
    )
    bridge = RuntimeBridge(worker_path=worker)
    await bridge.start()
    try:
        with pytest.raises(RuntimeUnavailable):
            await bridge.call("boom")
        result = await bridge.call("ping")  # next call restarts the worker once
        assert result["pong"] is True
    finally:
        await bridge.close()


async def test_worker_error_response_becomes_runtime_unavailable(bridge, tmp_path):
    with pytest.raises(RuntimeUnavailable, match="unknown op"):
        await bridge.call("nonsense_op")


async def test_close_shuts_worker_down(bridge):
    await bridge.close()
    assert bridge._process is None
    assert bridge.running is False


async def test_missing_node_binary_is_actionable(tmp_path):
    bridge = RuntimeBridge(node_command=str(tmp_path / "definitely-not-node"))
    with pytest.raises(RuntimeUnavailable, match="BEATSCOPE_MCP_NODE"):
        await bridge.start()


async def test_worker_path_matches_packaged_layout():
    assert WORKER_PATH.name == "runtime_worker.mjs"
    assert WORKER_PATH.parent.name == "mcp"
