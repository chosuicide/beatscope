"""Async bridge to the Node runtime worker (plan section 19.4).

The MCP server itself owns stdio, so the worker is a separate subprocess
with its own pipes. One request id per call, one reader task dispatching
responses to pending futures, a 5 s default timeout, pending futures fail
when the worker crashes, and each call restarts a dead worker at most once.
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
from pathlib import Path
from typing import Any

from .errors import RuntimeUnavailable

WORKER_PATH = Path(__file__).resolve().parent / "runtime_worker.mjs"
DEFAULT_TIMEOUT = 5.0
_SHUTDOWN_GRACE = 2.0


def file_fingerprint(path: Path) -> str:
    """Cheap change detector so the worker reloads an activated variant."""
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _sanitize(value: Any) -> Any:
    """JSON transport rule (plan section 15): non-finite numbers become null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


class _WorkerBroken(RuntimeUnavailable):
    """Transport-level failure: the worker died or stopped accepting writes."""


class RuntimeBridge:
    def __init__(
        self,
        node_command: str = "node",
        worker_path: Path | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.node_command = node_command
        self.worker_path = Path(worker_path) if worker_path else WORKER_PATH
        self.timeout = timeout
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 1
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        await self._ensure_started()

    async def _ensure_started(self) -> None:
        if self.running:
            return
        async with self._start_lock:
            if self.running:
                return
            self._fail_pending(RuntimeUnavailable("BeatScope runtime worker exited."))
            try:
                self._process = await asyncio.create_subprocess_exec(
                    self.node_command,
                    str(self.worker_path),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except (OSError, ValueError) as exc:
                self._process = None
                raise RuntimeUnavailable(
                    f"Cannot start the BeatScope runtime worker ({self.node_command} "
                    f"{self.worker_path.name}): {exc}. Install Node.js or point "
                    "BEATSCOPE_MCP_NODE at the node binary."
                ) from None
            self._reader_task = asyncio.create_task(self._read_loop())
            self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:  # pragma: no cover - guarded by caller
            return
        async for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                print(f"beatscope-mcp runtime: unparsable worker line: {line!r}", file=sys.stderr)
                continue
            future = self._pending.pop(message.get("id"), None)
            if future is None or future.done():
                continue
            if message.get("ok"):
                future.set_result(message.get("result"))
            else:
                future.set_exception(
                    RuntimeUnavailable(f"BeatScope runtime worker error: {message.get('error')}")
                )
        # EOF: the worker process is gone; everything still pending fails.
        self._fail_pending(
            _WorkerBroken("BeatScope runtime worker exited unexpectedly.")
        )

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:  # pragma: no cover - guarded by caller
            return
        async for raw in process.stderr:
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                print(f"beatscope-mcp runtime: {line}", file=sys.stderr)

    def _fail_pending(self, error: RuntimeUnavailable) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def call(self, op: str, timeout: float | None = None, **params: Any) -> Any:
        """Send one request and await its response (auto-restart at most once)."""
        try:
            return await self._transact(op, timeout, **params)
        except _WorkerBroken:
            # The worker died between calls (returncode may lag behind EOF, so
            # force-reap and start fresh); one restart per call (plan 19.4).
            await self._terminate()
            return await self._transact(op, timeout, **params)

    async def _transact(self, op: str, timeout: float | None, **params: Any) -> Any:
        await self._ensure_started()
        process = self._process
        if process is None or process.stdin is None:  # pragma: no cover - _ensure_started sets it
            raise _WorkerBroken("BeatScope runtime worker is not running.")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        payload = json.dumps({"id": request_id, "op": op, **params}, allow_nan=False) + "\n"
        try:
            async with self._write_lock:
                process.stdin.write(payload.encode("utf-8"))
                await process.stdin.drain()
        except (OSError, RuntimeError, ConnectionError, AttributeError) as exc:
            # AttributeError: a proactor transport torn down mid-write exposes
            # the same "worker is gone" condition with a different type.
            self._pending.pop(request_id, None)
            raise _WorkerBroken(
                f"BeatScope runtime worker rejected '{op}': {exc}"
            ) from None
        budget = self.timeout if timeout is None else timeout
        try:
            result = await asyncio.wait_for(future, budget)
        except asyncio.TimeoutError:
            if self._pending.pop(request_id, None) is not None:
                await self._terminate()  # wedged worker: next call starts fresh
            raise RuntimeUnavailable(
                f"BeatScope runtime worker did not answer '{op}' within {budget:g} s."
            ) from None
        return _sanitize(result)

    async def _terminate(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), _SHUTDOWN_GRACE)
        except (OSError, asyncio.TimeoutError):
            try:
                process.kill()
            except OSError:  # pragma: no cover - already gone
                pass

    async def close(self) -> None:
        """Ask the worker to exit, then fall back to terminate (plan 19.4)."""
        process = self._process
        if process is not None and process.returncode is None and process.stdin is not None:
            try:
                process.stdin.write(b'{"id":0,"op":"shutdown"}\n')
                await process.stdin.drain()
                await asyncio.wait_for(process.wait(), _SHUTDOWN_GRACE)
            except (OSError, RuntimeError, asyncio.TimeoutError):
                await self._terminate()
        self._fail_pending(RuntimeUnavailable("BeatScope runtime worker is shut down."))
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutdown best effort
                    pass
        self._reader_task = None
        self._stderr_task = None
        self._process = None
