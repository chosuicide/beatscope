# Frozen interoperability task (v0.9 plan section 13.1)

This file is the byte-stable task given to every Coding Agent run. Run
records pin `task_sha256` of these exact bytes, so any edit here
invalidates every recorded run and must ship with a new evaluation
generation. The only permitted variation between runs is the
`<TARGET_FRAMEWORK>` placeholder; all other instructions stay
byte-identical.

## Task

```text
Build an original audio-reactive visual using the supplied BeatScope package.
Use the package's frame API as the only musical timing source. Support play,
pause, seek, replay, and reduced motion. Do not copy the BeatScope player.
Run the supplied validation command and report any unsupported requirement.
```

## Placeholder

`<TARGET_FRAMEWORK>` is replaced by exactly one framework name per run
(for example `canvas`, `three.js`, or `remotion`). No other word in the
task may change between runs.

## Supplied inputs

- one BeatScope handoff package (the shared frozen fixture, or an
  export of equivalent version) with its `checkpoints.json`;
- the package's own `AGENT.md` routing document;
- the validation command: `python -m beatscope.cli validate-consumer
  <example-dir>` (plus `--browser` or `--offline` when the consumer
  declares the matching capability).

## Recording a run

After the run finishes, an operator reviews the generated source for
secrets and licenses, then records metadata only:

```bash
python evaluations/agent-interoperability/record_run.py \
    --record run.json --confirm-review
```

Private prompts, credentials, hidden chain of thought, account IDs,
and vendor billing data must never enter the record. See
`runs/README.md` for the full procedure and the honest publication
threshold.
