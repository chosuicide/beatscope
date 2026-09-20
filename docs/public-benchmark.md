# Public beat benchmark

BeatScope's synthetic fixtures answer “did this commit regress?” They do not
answer “how accurate is this analyzer on recorded music?” This benchmark is a
separate, non-blocking evaluation against third-party human annotations.

## Dataset

The first corpus is the 698-excerpt **Ballroom Rhythm Dataset**:

- audio archive: the original ISMIR 2004 tempo-contest download, MD5
  2872a3e52070bc342a4510a95e2fa0b8;
- beat and bar annotations: CPJKU/BallroomAnnotations at commit
  1db08914a8ae15edb01f104046e30bad88effe67;
- annotation format: one measured time and metrical position per row;
- license reported by mirdata: CC BY-NC-SA 4.0.

Audio and annotations belong under ignored build storage and are never included
in the repository, wheel, handoff package, Studio or release.

SMC was considered first because it stresses difficult rhythms. It is not the
first shipped corpus because the official Beat This release states that its
original audio is not publicly available. The runner accepts arbitrary matching
WAV and annotation roots, so an authorized local SMC copy can be evaluated
later without changing the metric code.

## Reproduce

Install the optional evaluators:

    python -m pip install ".[public-benchmark]"

Download the [official audio archive](https://mtg.upf.edu/ismir2004/contest/tempoContest/data1.tar.gz)
and the [revision-pinned annotation archive](https://github.com/CPJKU/BallroomAnnotations/archive/1db08914a8ae15edb01f104046e30bad88effe67.zip),
verify the audio MD5 above, and unpack both under ignored build storage. Then run
a quick genre-balanced sample (replace the two roots with the extracted paths):

    python scripts/benchmark_public.py \
      --audio-root build/public-benchmark/audio/BallroomData \
      --annotation-root build/public-benchmark/annotations/BallroomAnnotations-1db08914a8ae15edb01f104046e30bad88effe67 \
      --limit 32 \
      --workers 4

Omit --limit for all 698 tracks. Use
`--systems beatscope librosa beat-this` to include the official Beat This final0
model; the first use downloads its published model weights (point `TORCH_HOME` at
an existing cache to reuse them instead of downloading again).
Use --device cuda only when the local PyTorch installation reports CUDA.

`--dbn` switches Beat This to its DBN post-processing, which is what the official
`Audio2Beats` pipeline uses and which scores higher than the raw frame peaks.
Without it the model runs without DBN, which is the configuration every recorded
measurement in `evaluations/public-beat/` was made with. DBN needs `madmom`,
which is not installed by the `public-benchmark` extra; until it is, the two
configurations are not comparable and the choice must be stated wherever a
number is quoted.

The command caches each prediction by an identity covering the system id, the
protocol version (metric library, five-second trimming, annotation revision) and
the estimator's configuration, so an interrupted full run resumes without
recomputing finished tracks - while a run under another configuration recomputes
rather than reusing numbers that were measured differently. It writes canonical
results.json and a compact results.md. It uses mir_eval.beat.evaluate with
five-second trimming, including F-measure, Cemgil, CMLc, CMLt, AMLc and AMLt.

Downbeat F-measure is scored for every track whose annotation has downbeats, so a
system that predicts none scores zero there instead of leaving the denominator;
the report states how many tracks the mean covers. Failures remain visible per
track instead of being silently removed, and each system's counts block records
how many tracks were selected, evaluated, failed, and scorable for downbeats.

## Interpretation

This is a corpus measurement, not a release gate and not a claim about every
genre. Ballroom is rhythmically regular and Beat This was trained with Ballroom
data, so a direct comparison is descriptive rather than a fair unseen-test
leaderboard. A future unseen or authorized difficult-rhythm corpus must be
reported separately, never blended into this score.

## First recorded measurement

The repository includes a deterministic 32-track development snapshot: exactly
four excerpts from each of Ballroom's eight genres, selected by the documented
content-independent hash order. All three systems evaluated the same tracks and
reported zero failures.

| System | Beat F-measure | CMLt | AMLt | Downbeat F-measure |
| --- | ---: | ---: | ---: | ---: |
| BeatScope lightweight 0.7.0 | **0.677** | **0.469** | **0.782** | 0.390 |
| librosa default 1.0.0 | 0.644 | 0.434 | 0.766 | — |
| Beat This 1.1.0 final0 (CUDA) | 0.991 | 0.986 | 0.986 | **0.982** |

The canonical per-track report is
[`evaluations/public-beat/ballroom-32-v1.json`](../evaluations/public-beat/ballroom-32-v1.json)
(SHA-256 `796a15bd4b170f2b56dd8a20deeb56f5fad72231cb9199e6bd4bbd07c733a6e2`).
This is deliberately labelled a development snapshot, not the final 698-track
result. It already establishes two useful facts: BeatScope's beat tracking is
competitive with the conventional librosa baseline on this sample, while its
downbeat phase estimation is a clear weakness; Beat This is not a fair unseen
comparison here because its published training data includes Ballroom.

Sources: [mirdata Ballroom loader](https://mirdata.readthedocs.io/en/stable/_modules/mirdata/datasets/ballroom.html),
[Ballroom annotations](https://github.com/CPJKU/BallroomAnnotations),
[Beat This](https://github.com/CPJKU/beat_this), and
[mir_eval beat metrics](https://github.com/mir-evaluation/mir_eval/blob/main/mir_eval/beat.py).

## Recorded measurement: a genre-balanced half (349 of 698)

349 excerpts (a deterministic, genre-balanced half of Ballroom) were evaluated
with all three systems, zero failures. This supersedes the 32-track sample as
the published measurement; that sample stays as the quick development snapshot.

| System | Beat F-measure | CMLt | AMLt | Downbeat F-measure |
| --- | ---: | ---: | ---: | ---: |
| BeatScope lightweight 0.7.0 | **0.701** | 0.472 | 0.765 | 0.410 |
| librosa default 1.0.0 | 0.699 | **0.494** | 0.761 | — |
| Beat This 1.1.0 final0 (CUDA) | 0.991 | 0.987 | 0.987 | 0.988 |

Canonical per-track report:
[`evaluations/public-beat/ballroom-349-v1.json`](../evaluations/public-beat/ballroom-349-v1.json)
(SHA-256 `e048db449892a23e3b4640727757ce5139ff5401f7aa5cc86d7918f6292a6ad9`).

What these numbers do and do not say:

- it is a **half of the corpus**, not the full 698-track result, and it is
  labelled that way everywhere;
- BeatScope's beat tracking is **level with librosa** (0.701 vs 0.699) while its
  continuity measures sit slightly below it (CMLt 0.472 vs 0.494), and its
  **downbeat phase estimation remains a clear weakness** at 0.410 - the honest
  reading is that downbeats are not yet a strength of this analyzer;
- Beat This scores near the ceiling because **Ballroom is part of its published
  training data**: it is an upper-bound reference, not a fair unseen opponent,
  and it must not be presented as a leaderboard win;
- these are corpus measurements, not a release gate and not a claim about every
  genre. Reproduce with the same command plus `--limit 349`, or omit `--limit`
  for all 698.
