# WebMCP Studio Director (v0.12)

In a WebMCP-capable browser, an Agent can inspect the song the user has open,
ask for a bounded set of original response timestamps, explain the current
deterministic cut, audition a passage, start a seeded render, and prepare the
timing package — without receiving the source audio and without a second music
analysis. The Studio itself is a thin adapter: it registers tools over
`document.modelContext` and calls the same functions its own buttons call.

Everything is local. Analysis, the movie render and the tools run on the
user's machine; only the same-origin requests the visible page already makes
are used. No audio is uploaded to a BeatScope service, and no tool accepts a
path, URL, prompt, style or project id: the loaded document is the whole
subject.

## The seven tools

| Tool | Kind | Use it for |
| --- | --- | --- |
| `beatscope_get_studio_state` | read | Call first: the loaded song, playback, seed, render job, and which tools can work now |
| `beatscope_inspect_timing` | read | Beats, onsets, cues, segments and boundaries inside one time or measured-bar window |
| `beatscope_get_response_events` | read | A caller-sized set of existing onsets worth responding to, by the v0.11 ordering |
| `beatscope_explain_movie` | read | Which shot covers a time, where its cut came from, and which world the plan assigned |
| `beatscope_control_playback` | action | Play, pause, seek, audition a range, or restore the pre-audition position |
| `beatscope_render_movie` | action | Start one deterministic render (24-bit seed) or cancel the active one |
| `beatscope_export_timing_package` | action | Start the same timing-package download the Data export button offers |

Prerequisites are reported, never assumed: without a loaded song the tools fail
with `track_required`; without a response-relevance sidecar, raw timing still
works while the ranked and explanation tools fail with
`ranking_unavailable` instead of passing chronological order off as a ranking;
without a local renderer, queries, playback and export still work and rendering
reports `render_unavailable`.

Budgets are part of the contract: at most 180 s or 64 bars per window, 200
events per timing page, 64 events per ranked set, ≤64 bars per audition, seven
shots per explanation, and every serialized result stays under 16,000 UTF-16
code units — pages shrink instead of events being truncated. `response_relevance`
is an ordering value, never a probability or a confidence, and no tool invents
kick/snare/808 names, section names or moods.

## Two entries, one model

| Entry | Best for | State it sees |
| --- | --- | --- |
| WebMCP Studio Director | collaborating with the visible local studio | the song loaded in this page, and page actions |
| stdio [MCP server](mcp.md) | coding tools and local automation outside the page | allowed cached projects and filesystem export |

Both read the same Rhythm IR through the same deterministic runtime; only the
transport, the lifecycle and the reachable state differ.

## Ordinary browsers

Registration is feature-detected. A browser without WebMCP shows no Agent
chip, no warning and no broken control: the studio behaves exactly as it does
today. When WebMCP is present, the page shows a compact `AGENT · 7 TOOLS` state
and one transient strip above the transport for page-changing calls only, with
Restore after an audition. Cancellation disposes the registrations; a render
that was already accepted keeps running and is cancelled from the visible
Cancel button.

## Verify it locally

```powershell
npm run build --prefix web-src
python tests/browser/studio_webmcp_server.py --port 8771
node tests/browser/studio-webmcp-smoke.mjs http://127.0.0.1:8771
```

The smoke test injects a test-only `document.modelContext` (nothing is
polyfilled in the product), drives the real callbacks against the real server,
and prints the measured latencies and result ceiling.

## Not in this surface

No upload tool, no arbitrary project access, no visual recipe or scene
timeline, no Agent-driven editing of the movie, and no published demo: this
version documents a local surface, and nothing is deployed or released with it.
