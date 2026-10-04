# Reference-guided Agent evaluation · generation 1

This evaluation asks a different question from the frozen v0.9 interoperability task: does the receiving Agent preserve a reference's distinguishing behavior and use supplied assets while keeping BeatScope's timing? It cannot be answered by unit tests or by this repository author generating a comparison video.

`cases.json` commits only logical IDs and hashes. Actual videos, audio, assets, prompt transcripts and working directories remain local in ignored `build/reference-guided/`. The two selected local references differ in composition and editing behavior. Their presence on the author's machine is not publication permission. The same 30-second local target song and frozen 10-second task are used for both variants of each case.

## Run protocol

1. Check every local input against `cases.json`. Preserve the reference as `reference` only, not usable source footage or soundtrack. Use the supplied asset set identically in a case's baseline and new run.
2. Generate the current package and obtain a baseline package from the pre-change code. Confirm beat and onset IDs/times and target audio hash match across both packages. The new package may include additive documentation and diagnostics. Never use the new `AGENT.md` in the baseline task.
3. Run four fresh receiving-Agent contexts: `editorial-image` × baseline/new and `voxel-state` × baseline/new. Use the same model/settings and comparable time/tool budgets within each pair. Give only `TASK.md` and the case's files, without the rubric or private observations. Save actual source, playable 10-second preview, package and run transcript outside Git.
4. Before seeing outputs, an independent visual reviewer inspects each real reference and records timestamped features. Review paired outputs without variant labels where feasible. Record composition, motion/hold/recovery, material use, editing, requested changes, musical alignment, and user burden separately. An author reviewing their own output is **self-review**, not independent review.
5. Use `reference-tools.mjs inspect/compare/check` for structural evidence. It does not score aesthetics. Retain failed attempts and interventions. Expand one successful bounded case to a complete requested piece via the same renderer and record it separately.
6. Run `record_run.py --record <local-run.json> --confirm-review` only after confirming real media, local hashes, and a review record. If a real attempt produced a playable clip but no complete review record, use `--record-incomplete`; its summary must remain visibly incomplete and cannot substantiate reference fidelity. Both modes publish logical IDs and hashes only. Never commit original media paths or private prompts.

Missing agent execution, output video, review or input authorization means real evaluation is **pending**. Do not invent four runs, relabel old v0.9 runs, or claim that timing-package validation proves visual fidelity. Only a completed paired review can support a bounded improvement claim; it cannot prove arbitrary styles or LLMs are reliable.

## Current state

Four actual 10-second receiving-Agent renders now exist locally, one baseline and one reference-guided output for each case. The first-pair, path-free run summaries are in `runs/`; baseline summaries deliberately say `evidence_status: incomplete` because the old package supplied no structured review, while new-run summaries have structural self-review only. The input manifest's `duo` hash was corrected after the recorder rejected both editorial runs: the original file, both copied assets and their actual SHA-256 agree. No input media or timing was changed.

An independent reviewer inspected both references **before** seeing the outputs, then reviewed anonymously labeled pairs using dense ordered frames. The private reports and media live under ignored `build/reference-guided/`. Both new runs improved some distinguishing traits but lost others. Editorial retained the large early title, quiet cobalt field and colored macro inset, but missed the cobalt passage's multi-crop strip and staged arc/letters. Voxel retained rapid environmental changes and glitch recovery, but simplified the persistent sculpture and its checker-like material. Both comparisons therefore have **mixed / inconclusive** visual results, not a demonstrated no-regression win. The reviewer did not judge musical alignment from silent visual samples. A follow-up workflow repair now forces separate inventory of persistent anchor, state sequence and within-state evolution; repeat comparisons are required before any bounded improvement claim.

## Requirement status (first pair, before repaired reruns)

| ID | Status | Evidence or missing work |
| --- | --- | --- |
| R01 real reference observation | Reviewed | Independent pre-output observations: local `build/reference-guided/independent-reference-observations.md`; sampled frames retained locally. |
| R02 concrete understanding | Partial | New Agents supplied reference observations and briefs; independent review found missed defining subfeatures. Updated guide/checker now requires three-part feature inventory; repaired reruns pending. |
| R03 asset binding | Reviewed | Four playable clips visibly reuse the case assets; complete new-run records include job-local bindings. Fidelity to intended roles remains mixed. |
| R04 working preview | Verified | Four 10-second MP4s under ignored `build/reference-guided/runs-local/`; preview SHA-256 and source SHA-256 in `runs/`. |
| R05 comparison and repair | In progress | Blinded independent pair reviews: local `build/reference-guided/independent-editorial-review.md` and `independent-voxel-review.md`. Both pairs have material tradeoffs; repaired outputs not yet reviewed. |
| R06 correct timing | Partial | `compare_packages.py` confirms the same audio, beat IDs/times and onset IDs/times; all four playable outputs use the same target song, but visual-to-onset alignment was not independently scored. |
| R07 no repeated intake | Recorded | `runs/` records zero user-choice requests; one infrastructure usage-limit resume occurred in each editorial run and is recorded separately as an intervention. |
| R08 facts-only package | Verified | `tests/test_exports.py`, `tests/test_consumer_contract.py`; new source export has `scenes:false`, no media/recipe. |
| R09 reachable handoff | Verified in source | `tests/browser/studio-webmcp-smoke.mjs` covers actual ZIP download, EN/ZH copy, clipboard failure and playback preservation; wheel test covers helper/guide. Not a published release claim. |
| R10 evidence is not taste approval | Verified mechanism | `reference-tools.mjs` returns `aesthetic_verdict:not_automatically_determined`; tests reject stale/missing files and critical mismatch. |
| R11 real controlled use | Partial | Four fresh tasks, first-pair records and playable outputs exist. A repaired comparison and one complete bounded piece are still required. |
| R12 honest completion | Verified reporting | This table separates implementation, mixed real results, independent visual review and unrecorded user acceptance. |

The local cases use `build/reference-guided/target.rhythm.json`; `prepare_local.py` builds the current ZIP and `compare_packages.py` verifies a separately prepared pre-change ZIP. Neither script creates a run record or judges reference fidelity. Original files and absolute paths stay out of the repository.
