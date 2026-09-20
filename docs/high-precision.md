# High-precision mode

BeatScope's default analyzer finds beats itself, with no model and no download.
`--backend enhanced` replaces that one judgement with the Beat This model's: the
model supplies beats and downbeats, and BeatScope keeps everything else it does -
onsets, energy, tempo, the project and the exports. The two contributions stay
separable, which is the point: a number can be attributed to the model or to the
product, never to "the system" as a whole.

## Install

```powershell
pip install "beatscope[public-benchmark]"
```

That pulls in Beat This. The first analysis downloads the `final0` checkpoint;
point `TORCH_HOME` at an existing cache to reuse weights you already have:

```powershell
$env:TORCH_HOME = 'D:/Tools/BeatScope/models'
```

Nothing else changes. Without the extra, `--backend enhanced` raises and names
what is missing rather than quietly analysing with something else under the same
name.

## Run it

```powershell
beatscope analyze song.wav --backend enhanced --model-device cuda
```

`--model-device` accepts `cpu` or `cuda`; it is passed to the backend through the
environment (`BEATSCOPE_MODEL_DEVICE`), because the device is not part of the
stored project format. The checkpoint is `final0` and is pinned by
`BEATSCOPE_MODEL`, for a run that needs to name its weights.

From Python, the same thing:

```python
from beatscope.models import AnalysisConfig
from beatscope.pipeline import analyze_track

project = analyze_track("song.wav", AnalysisConfig.from_dict({"backend": "enhanced"}))
```

The command line also writes MIDI next to the project, and the handoff package
exports the same way it does for any other backend:

```powershell
beatscope analyze song.wav --backend enhanced -o song.rhythm.json
beatscope validate-handoff song.beatscope.zip
```

## Asking for it over HTTP

The upload route takes the backend as a query parameter, so a client can request
it without a new endpoint:

```
POST /api/jobs/analyze?backend=enhanced   (default: lightweight)
```

An unknown name is refused with a 400 rather than analysed as the default under a
name the caller did not ask for. The device comes from the server's environment
(`BEATSCOPE_MODEL_DEVICE`), because it belongs to the machine serving the request,
not to the request itself:

```powershell
$env:BEATSCOPE_MODEL_DEVICE = 'cuda'
beatscope serve --open
```

The studio has a **Standard / High precision** button in the upload area, and it
sends exactly this parameter. It needs the extra installed on the machine that
serves the page: the portable Windows build deliberately ships without PyTorch, so
high precision there is unavailable rather than silently absent, and the button
says so.

## What the project says about itself

An enhanced project records where its beat facts came from, so a consumer never
has to guess:

| Field | Meaning |
| --- | --- |
| `analysis.provenance.beats.method` | `beat-this-model:final0` |
| `analysis.diagnostics.model` | checkpoint, device, frames, frame rate, beat and downbeat counts, mean beat support |
| `analysis.diagnostics.meter_source` | `measured-from-model-downbeats`, or `assumed-4-4-not-measured` |
| `analysis.diagnostics.tempo_source` | `measured`, or `prior-fallback` when no tempo could be measured |
| `analysis.diagnostics.structure_unavailable` | present: the bar-dependent structure analysis is not computed for this backend |

`model.mean_beat_support` is the sigmoid of the model's frame logits. It is the
model's confidence in its own frames and is not a calibrated probability.

## Two limits worth knowing before you use it

**No structure analysis.** The structure pass is computed against BeatScope's own
bar grid, so its bar indices do not describe a project whose bars come from the
model. Rather than publish indices that contradict the beats, the enhanced backend
skips that analysis and records why. Onsets, energy, tempo and the exports are
unaffected.

**The model's own meter, when the schema can hold it.** A model that hears three
or five beats to the bar is published as such: the numerator is the longest bar,
and a track that begins mid-bar is numbered as the end of the bar before it. When
a bar is longer than the schema's limit of 16 beats, the project falls back to the
product's 4-cycle and `meter_source` says so.

## Measured, with the corpus attached to each number

| Corpus | What it is | Beat F1 | Downbeat F1 |
| --- | --- | --- | --- |
| Ballroom, 349 tracks | **training data for `final0`** | 0.9908 | 0.9875 |
| GTZAN, 999 tracks | held out: `final0` was trained on everything except GTZAN | **0.8909** | **0.7871** |
| ARTBeaT, 25 tracks | full product path, built for tempo changes and syncopation | **0.7604** | not scored (no downbeat annotations) |

Read them in that order. The Ballroom figure is what in-domain looks like and is
not a claim about anything else; GTZAN is the held-out number, and it is a
*model-level* measurement (no decoding, onsets or export in that loop); ARTBeaT is
the only one of the three that exercises the whole product path.

## Known limits

- **Classical and piano material is weaker.** GTZAN's classical tracks score 0.6591
  against 0.9746 for hiphop, and ARTBeaT's piano case 0.6296. The pattern is
  consistent across both corpora and is recorded as a limit, not as a to-do.
- **Tempo changes cost continuity.** On ARTBeaT the beat F1 survives a change
  (0.52-0.92) while CMLt collapses to 0.0000-0.1053 on several tracks: the beats
  found are right, the sequence is not tracked through the change.
- **Syncopation and deception cases can fail outright.** `Deception_102` scores
  0.0000 and `Syncopated_94` 0.2051.
- **The checkpoint's licence is an open question.** The Beat This code is MIT; the
  published *weights* are a separate artefact and their terms have not been
  reviewed for redistribution. Installing them for local analysis is one thing;
  shipping them inside a product is a decision that has not been made.

## What it is not

It is not a claim of beating Beat This. The beats are Beat This's; the adapter was
verified to agree with the official pipeline element by element, including across
the chunk boundaries it uses for long audio. BeatScope's own contribution to
accuracy is zero here, and that is by design: the enhanced backend exists so the
product's own work - onsets, structure, exports, the studio - can be compared
against a strong baseline instead of a weak one.
