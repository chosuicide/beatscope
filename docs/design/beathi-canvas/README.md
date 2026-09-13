# Beathi Canvas — frozen design gate (v0.12)

This directory is the frozen design contract for the Beathi Canvas workspace,
approved by the project owner on 2026-09-07. Round 1 Commit 1 froze it; the
implemented React shell (Commit 2) is accepted against these references.

## Contents

| File | Role |
|---|---|
| `reference-a-first-run.png` | Frame A — first run / demo loaded (frozen target) |
| `reference-b-canvas-overview.png` | Frame B — multi-board canvas overview |
| `reference-c-selected-editing.png` | Frame C — selected board editing |
| `reference-d-prompt-package.png` | Frame D — direction proposal diff |
| `frame-{a,b,c,d}.html`, `beathi.css` | Source of the approved frames (1440×900 fixed canvas) |
| `fonts/` | Geist + Geist Mono variable woff2, SIL OFL 1.1, license included |
| `gen_images.py` | Deterministic generator for the bundled artwork (fixed-seed noise, no `random`) |
| `fog-ridge.png`, `fog-bright.png`, `paper-fiber.png`, `halftone.png` | Generated demo artwork used by the frames |
| `motion-spec.md` | Approved interaction/motion specification |
| `design-tokens.json` | Frozen §2.5 token contract |
| `copy-catalog.md` | Bilingual EN/zh-CN string catalog |
| `layout-rules.md` | Responsive layout, stacking, canvas and motion rules |

## Rules

- The four PNG references are the visual targets. The snapshot harness
  (`tests/canvas/`) compares implemented views against baselines derived from
  these frames at 1440×900 and 1920×1080.
- Token or catalog changes require a new design-gate approval.
- The demo artwork is repository-owned, deterministically generated; no
  third-party or copyrighted media is bundled. Fonts are OFL with license text
  preserved; see the Round 1 Commit 1 message for the full license decisions.
- To regenerate references after edits (edit-approval only, never silently):
  `python gen_images.py && open frame-a.html` and capture at 1440×900.
