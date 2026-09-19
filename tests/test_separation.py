"""The Demucs child process: it must not be able to hang the analysis queue.

run_demucs spawns `python -m demucs.separate`, which is slow by nature and can
hang. The queue has a single worker, so a child that never returns would block
every later job; these tests drive wait_for_process with a real child instead of
demucs, so they run in a second and need no model.
"""
import subprocess
import sys
import time

import pytest

from beatscope.backends.base import AnalysisCancelled
from beatscope.separation import SeparationTimeout, wait_for_process

# A child that sleeps far longer than any test should take.
SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]


def _spawn():
    return subprocess.Popen(SLEEPER, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _assert_dead(process, timeout=10.0):
    """A killed child is reaped, so poll() stops returning None."""
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert process.poll() is not None, "the child survived the abort"


def test_cancellation_kills_the_child_and_reports_analysis_cancelled():
    process = _spawn()
    started = time.monotonic()
    with pytest.raises(AnalysisCancelled):
        wait_for_process(process, cancelled=lambda: True, timeout_seconds=60)
    assert time.monotonic() - started < 10, "cancellation should not wait for the deadline"
    _assert_dead(process)


def test_a_cancel_callback_that_stays_false_lets_the_child_finish():
    process = subprocess.Popen(
        [sys.executable, "-c", "print('stems ready')"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout, _ = wait_for_process(process, cancelled=lambda: False, timeout_seconds=60)
    assert "stems ready" in stdout


def test_the_deadline_kills_the_child_and_says_how_to_raise_it():
    process = _spawn()
    started = time.monotonic()
    with pytest.raises(SeparationTimeout) as excinfo:
        wait_for_process(process, cancelled=None, timeout_seconds=1.0)
    assert time.monotonic() - started < 10
    assert "BEATSCOPE_DEMUCS_TIMEOUT_SECONDS" in str(excinfo.value)
    _assert_dead(process)


def test_a_finished_child_reports_its_output():
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout, stderr = wait_for_process(process, cancelled=None, timeout_seconds=60)
    assert stdout.strip() == "out"
    assert stderr.strip() == "err"
