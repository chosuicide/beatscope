# BeatScope timing handoff: consumer-fixture

You are reading the measured timing facts for one audio file: 30.000 s,
15 bars, 60 beats, 370 transients, 3 structural segments.
This package describes the music. It carries no style, no scene, no assets and
no task: the visual is a decision you make with the user.

## Read this package cheaply

- Do **not** read `rhythm-map.json` or `response-relevance-data.js` in full:
  they are megabytes of numbers. Query them with a program and print only the
  window you need; one short script beats a full read.
- Ask the runtime for a window, not for the song:
  `getResponseEvents(start, end, budget)` returns just the candidates in that
  span, at their measured times.
- Cut on measured times: cuts, markers and edits come from `raw_time`, never
  from a quantised grid. `BEATSCOPE.md` says which file carries which.
- The other documents are reference, not a reading order. Consult them when a
  question comes up:

  | File | Authoritative for |
  | --- | --- |
  | `beatscope-package.json` | entry module, capabilities, function names, per-member sha256 |
  | `BEATSCOPE.md` | the clock contract, what the fields mean, the invariants |
  | `SKILL.md`, `references/schema.md` | how to consume the API, exact field semantics |
  | `rhythm.mid`, `rhythm.csv` | the same facts for a DAW or a spreadsheet (quantised: `BEATSCOPE.md`) |
  | `README.md` | the inventory, what is deliberately absent, what is authoritative |

## Work with the user

Ask about intent, material and taste. Never ask about technicalities: nobody
outside this package knows what an event budget is, and choosing it is your job.

1. What are we making: a new visual, their own version of something they have
   seen, a tool, or an edit of footage they already have?
2. What material exists (footage, images, logo, typeface, palette) and what may
   you generate?
3. Where will it play, in what shape: aspect ratio, frame rate, resolution,
   whole song or one section?
4. Two or three references they like, and anything they never want to see.
5. Derive the response budget yourself from those answers: a calm montage and a
   fast cut want different densities. To agree on pacing, talk in their terms
   ("a cut about every two seconds", "only the big hits") - never ask anyone to
   pick a number of onsets or compare budgets.
6. Show your plan before building: which facts drive what, how dense it will be
   and what stays still. Then deliver the consumer, a two-line note on what
   drives what, and how to re-render it.

## Start here

1. Verify the package before writing code: `node consumer-probe.js .`
2. Query facts, never audio: `getVisualState(time)` for one instant;
   `getResponseEvents(start, end, budget)` for the candidates in a window.
3. Sample media time: `audio.currentTime` once per frame, or `frame / fps`
   offline. Never accumulate time. The full contract is in `BEATSCOPE.md`.

## Self-check before you finish

    node consumer-probe.js .

Timing parity must be exact: the same time must resolve to the same facts.

## Package honesty

`beatscope-package.json` describes what exists, not aspirations. Trust it over
any other description: if it does not declare a function or a file, do not use
it. `README.md` lists what is deliberately absent.
