# Architecture in one page

Five things live here. Four of them ship; the fifth measures the first.

| Piece | Where | What it does |
| --- | --- | --- |
| Analyzer | `beatscope/` (Python) | Audio -> Rhythm IR: beats, transients with band energies, tempo segments, bars, cues, structure families and boundaries. |
| Beathi studio | `web-src/` -> `beatscope/web/app` | The only page: upload a song, get a deterministic film. Its build output is **not tracked**: run `npm run build --prefix web-src` before packaging or serving a checkout. |
| Movie engine | `beatscope/web/mv-*.mjs`, `mv-visual.js` | The same `makePlan` function the preview, the renderer and the WebMCP explanation call. |
| Handoff package | `beatscope/exports.py` | Timing facts + deterministic runtime + probe + agent guidance, as a byte-stable zip. No visual layer, no task statement. |
| Benchmarks | `evaluations/`, `docs/public-benchmark.md` | Measurements, not release gates. |

Two entries read the same model: the stdio MCP server (`beatscope/mcp/`) for
local automation, and the in-browser WebMCP Studio Director
(`web-src/src/webmcp/`, contract in `docs/webmcp-studio.md`) for an agent
working in the visible studio.

## Kept on purpose, with no UI

- `beatscope/web/composition-runtime.mjs` and the composition model under
  `web-src/src/composition|direction|motion` — the "*Export for Agent*" artwork
  path and its tests still use them (`beatscope/composition_export.py`).
- `tests/reflected-response-study.mjs` — a research study with its own test,
  kept as a record; nothing in the product calls it, so it lives with the test
  rather than in the package.
- `docs/design/movie-studio.md` — the frozen contract of the studio's UI.

## Research code, outside the package

`research/` holds corpus construction and labelling (`chart_labels.py`). It
imports from `beatscope`, never the other way around, and it is not packaged:
the wheel installs the product, and the scripts that need these modules insert
the repo root on `sys.path` themselves.

## Authority, so nobody has to guess

- Response ranking: the promoted model is `beatscope/data/response-ranker-v3.json`.
  Later generations and their training/evaluation scripts under `scripts/` are
  research history, not the shipping path. `response_relevance` is an ordering
  value — never a probability or a confidence.
- Repo docs describe the product; the package's own documents (AGENT.md,
  BEATSCOPE.md, SKILL.md, references/schema.md) are the authority for anyone
  consuming an exported package, and contract tests keep the two in step.
- Historical implementation plans are local only: `/*_IMPLEMENTATION_PLAN.md`
  is ignored, and they now live under `plans/`.
