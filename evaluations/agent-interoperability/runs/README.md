# Cross-Agent run records

This directory holds `beatscope-agent-run-1` metadata files recorded by
`../record_run.py`, plus the derived `index.json`. Records describe how
Coding Agents performed the frozen task in `../TASK.md` (plan section
13). They carry metadata only: no private prompts, credentials, hidden
chain of thought, account IDs, or vendor billing data.

## Status: pending — the cross-Agent claim is not yet earned

The repository currently contains **zero** recorded Agent runs. The
engineering release therefore claims only what is demonstrated in the
reference consumers: one handoff package driving Canvas, Three.js, and
Remotion through the same deterministic frame contract. The claim
"validated across Coding Agents" stays **pending** until the
publication threshold below is met. No run may be fabricated or
backfilled with invented numbers.

## Recording a run

1. Give the Agent only `TASK.md` (with the framework placeholder
   filled) plus the handoff package and its own `AGENT.md`, from a
   fresh context.
2. When the run finishes, review every generated file for secrets and
   licenses, and note any human repair you performed.
3. Write the metadata record (schema in `../schema.json`) and record
   it:

   ```bash
   python evaluations/agent-interoperability/record_run.py \
       --record candidate.json --confirm-review
   ```

   The recorder recomputes `task_sha256` and `package_sha256`, rejects
   unknown keys and credential-shaped strings, requires repairs to be
   documented when `human_interventions` is positive, and never
   overwrites an existing record.

## Publication threshold (plan section 13.4)

The "validated across Coding Agents" claim is allowed only when:

- at least two distinct Coding Agent products complete the frozen task;
- at least one run was performed from a fresh context with only the
  handoff and the task;
- all required conformance checks pass for the published runs;
- any human repair is documented in the record;
- generated source was reviewed for licenses and secrets;
- failures remain visible in this history instead of being deleted.

## Replay

CI replays the checked-in evidence: every run record must match the
frozen `TASK.md` hash and the shared fixture lock, and the normalized
conformance reports in `../reports/` must regenerate byte-identically.
CI never contacts remote Agents or model APIs.
