"""Small, deterministic risk hints. These are not calibrated confidence scores."""
from __future__ import annotations

import math
from typing import Any


def timing_quality(rhythm: dict[str, Any]) -> dict[str, Any]:
    tempo = rhythm.get("tempo") or {}
    global_bpm = tempo.get("global_bpm") or tempo.get("bpm")
    regions = []
    for segment in tempo.get("segments") or []:
        bpm, score = segment.get("bpm"), segment.get("score")
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (bpm, global_bpm)):
            continue
        ratio = bpm / global_bpm
        # Low algorithmic support AND a substantial departure. Genuine tempo
        # changes remain intact; this only asks the consumer to cross-check.
        if isinstance(score, (int, float)) and math.isfinite(score) and score < .25 and abs(math.log2(ratio)) > .2:
            alias = min((.5, 2/3, 1.5, 2), key=lambda x: abs(math.log2(ratio/x)))
            regions.append({
                "interval": [segment.get("start"), segment.get("end")],
                "bpm": bpm, "support_score": score,
                "ratio_to_global": round(ratio, 4),
                "subdivision_alias_candidate": alias if abs(math.log2(ratio/alias)) < .12 else None,
            })
    onsets = rhythm.get("onsets") or []
    saturated = sum(isinstance(o.get("strength"), (int, float)) and o["strength"] >= .999 for o in onsets)
    diagnostics = (rhythm.get("analysis") or {}).get("diagnostics") or {}
    meter_source = diagnostics.get("meter_source")
    if not isinstance(meter_source, str) or len(meter_source) > 80:
        meter_source = "unspecified"
    revision = diagnostics.get("timing_revision")
    unverified_revision = isinstance(revision, dict) and revision.get("status") == "unverified"
    result = {
        "status": "needs-crosscheck" if regions or unverified_revision else "not-perceptually-verified",
        "suspect_tempo_regions": regions,
        "onset_strength_ceiling": {"count": saturated, "total": len(onsets)},
        "meter_source": meter_source,
        "support_semantics": "algorithmic score, not a calibrated probability",
        "limits": "Risk hints do not validate beats, meter, section meaning or audio-visual quality. Preserve originals; record any alternate grid with its method and verification status.",
    }
    if unverified_revision:
        result["timing_revision_status"] = "unverified"
    return result
