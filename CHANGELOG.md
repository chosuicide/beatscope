# Changelog

BeatScope is versioned by git tag, and each release page carries the notes for
that version. This file records the same history in one place, newest first;
`PACKAGE_VERSION` in `beatscope/exports.py` tracks the handoff package format,
which is versioned separately from the product.

## Unreleased

The audit pass over the 0.12 line. Nothing here changes the timing facts or the
package format.

**Correctness**

- The Demucs child process is bounded and cancellable: it is polled against the
  cancel callback and a deadline, so a hung separation can no longer block the
  single-worker analysis queue forever.
- A composition export for an unknown project answers 404 instead of crashing
  with an uncaught AttributeError, and an upload that is already owned by a
  running job is no longer deleted when the client disconnects early.
- `project.json` stores the audio as a relative name, so a moved or restored
  cache keeps resolving; legacy absolute paths still work.
- The job manager locks its fields, lets completion win over a cancel that
  arrived during the final write, evicts finished jobs, and reports queue
  position.
- `beatscope doctor` actually probes for Demucs instead of always reporting it
  installed.

**Static analysis**

- ruff runs `E/F/W/I/B` (with E501/E701/E702 exempted as documented house
  style), and mypy runs in CI, checked as Linux at 3.12 so the local run is the
  CI run. Both are clean.

**Packaging and docs**

- The synchronous `/api/analyze` route is gone; uploads go through the job
  queue.
- Research code (`research/chart_labels.py`) and the reflected-response study
  left the wheel, and the package-data globs are explicit.
- User-visible strings live in `beatscope/messages.py`, English first with the
  Chinese column beside it.
- The README version statements are checked against `pyproject.toml` in CI.

## 0.12.1 — 2026-09-17

- Corrected the energy timebase, kept films across failed renders, and gated
  releases on the version check.

## 0.12.0 — 2026-09-13

The studio, the timing-only handoff and the WebMCP Studio Director. The full
notes are in `.github/release-notes/v0.12.0.md` and on the release page.

## Earlier

0.10.0, 0.8.1, 0.6.1, 0.6.0 and 0.5.0 predate this file; their release pages
carry the notes.
