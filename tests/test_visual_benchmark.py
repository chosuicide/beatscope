"""Visual benchmark skeleton, frozen gates, and fixture baseline tests.

The committed ``tests/fixtures/visual`` set is the v0.8 acceptance baseline:
these tests pin the frozen gate tables and thresholds, verify every frozen
fixture against its documented purpose, and prove the baseline refuses to
move without explicit ``--accept-baseline`` intent.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from beatscope import visual_benchmark
from beatscope.schema import validate_rhythm_v4
from beatscope.visual_benchmark import (
    BLOCKING_GATES,
    GATE_POLICY,
    RECORDED_ONLY_GATES,
    evaluate_visual_case,
    identity_report,
    load_visual_fixtures,
    run_visual_benchmark,
    scene_tiling_report,
    transition_report,
)
from beatscope.visual_recipe_schema import (
    BREAK_FAMILY,
    DRIVER_ORDER,
    TREATMENT_BY_DRIVER,
    dominant_driver,
    treatment_for_driver,
)
from tests.fixtures.visual import generate_visual

from test_visual_recipe import make_recipe, make_rhythm, make_timeline

FROZEN_FIXTURES = load_visual_fixtures()


# ---------------------------------------------------------- frozen gates


def test_frozen_gate_tables():
    assert GATE_POLICY == {
        "determinism": (
            "recipe-bytes-identical",
            "timeline-bytes-identical",
            "scene-state-order-independent",
            "cross-surface-parity",
            "seek-determinism",
        ),
        "identity": (
            "family-motif-equality",
            "family-palette-equality",
            "variant-motif-stability",
            "variant-property-count",
            "variant-distance-bounds",
            "break-reserved-motif",
        ),
        "timeline": (
            "duration-coverage",
            "scene-tiling",
            "transition-count",
            "transition-time-tolerance",
            "driver-treatment-mapping",
            "finite-values",
            "forbidden-fields",
        ),
        "motion": (
            "composition-continuity",
            "impulse-only-jump",
            "reduced-motion-scale",
            "dense-onset-stage-stability",
            "combined-spread-cap",
            "settle-target-exactness",
        ),
        "performance": (
            "scene-query-p95",
            "director-query-p95",
            "renderer-cpu-p95",
            "frame-budget-p95",
            "draw-call-count",
            "director-allocation",
        ),
    }
    expected_blocking = tuple(
        gate for gates in GATE_POLICY.values() for gate in gates if gate not in RECORDED_ONLY_GATES
    )
    assert BLOCKING_GATES == expected_blocking
    assert set(RECORDED_ONLY_GATES) == {"renderer-cpu-p95", "frame-budget-p95"}


def test_frozen_thresholds():
    assert visual_benchmark.TRANSITION_TIME_TOLERANCE_SECONDS == 1e-3
    assert visual_benchmark.COMPOSITION_CONTINUITY_EPS == 1e-5
    assert visual_benchmark.SETTLE_EXACTNESS == 1e-6
    assert visual_benchmark.REDUCED_MOTION_POSITION_MAX == 0.20
    assert visual_benchmark.SCENE_QUERY_P95_MS == 0.10
    assert visual_benchmark.DIRECTOR_QUERY_P95_MS == 0.35
    assert visual_benchmark.RENDERER_CPU_P95_MS == 2.0
    assert visual_benchmark.FRAME_BUDGET_P95_MS == 18.0
    assert visual_benchmark.MAX_DRAW_CALLS == 1
    assert visual_benchmark.SCENE_STEADY_SPREAD_CAP == 0.32
    assert visual_benchmark.HEAVY_BEAT_ADDITIVE_CAP == 0.28
    assert visual_benchmark.COMBINED_SPREAD_CAP == 0.46
    assert visual_benchmark.SCENE_TWIST_CAP == 0.28
    assert visual_benchmark.TRANSITION_TWIST_CAP == 0.12


def test_dominant_driver_tie_breaking_is_deterministic():
    assert dominant_driver(None) == "neutral"
    assert dominant_driver({}) == "neutral"
    assert dominant_driver({"harmony": 0.0, "rhythm": 0.0, "energy": 0.0, "timbre": 0.0}) == "neutral"
    assert dominant_driver({"harmony": 0.4, "timbre": 0.4}) == "harmony"
    assert dominant_driver({"timbre": 0.4, "energy": 0.4}) == "energy"
    assert dominant_driver({"harmony": 0.2, "rhythm": 0.9}) == "rhythm"


def test_treatment_mapping_is_frozen():
    assert TREATMENT_BY_DRIVER == {
        "harmony": "phase-turn",
        "rhythm": "radial-part",
        "energy": "aperture",
        "timbre": "flow-shear",
        "neutral": "cross-settle",
    }
    for driver in DRIVER_ORDER + ("neutral",):
        assert treatment_for_driver(driver) == TREATMENT_BY_DRIVER[driver]
    assert treatment_for_driver("unknown") == "cross-settle"


# ------------------------------------------------------ case evaluation


def _compiled_case(name="visual-unit", **overrides):
    rhythm = make_rhythm()
    recipe = make_recipe(rhythm)
    timeline = make_timeline(rhythm, recipe)
    for key, value in overrides.items():
        if key == "rhythm":
            rhythm = value
        elif key == "recipe":
            recipe = value
        elif key == "timeline":
            timeline = value
    return {"name": name, "rhythm": rhythm, "recipe": recipe, "timeline": timeline}


def test_clean_case_passes_all_enforced_gates():
    case = _compiled_case()
    result = evaluate_visual_case(case["name"], case["rhythm"], case["recipe"], case["timeline"])
    assert result["gates_failed"] == []
    assert result["metrics"]["tiling"]["scene_count"] == 2
    assert result["metrics"]["transitions"]["driver_treatment_mismatches"] == 0


def test_case_without_compiler_reports_unavailable():
    result = evaluate_visual_case("visual-unit", make_rhythm(), None, None)
    assert result["gates_failed"] == ["compiler-unavailable"]


@pytest.mark.parametrize(
    "artifact, expected_gate",
    [
        ("timeline_gap", "scene-tiling"),
        ("timeline_overlap", "scene-tiling"),
        ("forbidden_field", "forbidden-fields"),
        ("variant_motif", "variant-motif-stability"),
        ("break_motif", "break-reserved-motif"),
        ("variant_distance", "variant-distance-bounds"),
        ("transition_driver", "driver-treatment-mapping"),
        ("invalid_schema", "invalid-artifacts"),
    ],
)
def test_illegal_artifacts_fail_with_named_gates(artifact, expected_gate):
    case = _compiled_case()
    if artifact == "timeline_gap":
        case["timeline"]["scenes"][1]["start_time"] = 8.5
    elif artifact == "timeline_overlap":
        case["timeline"]["scenes"][1]["start_time"] = 7.5
    elif artifact == "forbidden_field":
        case["timeline"]["scenes"][0]["emotion"] = "epic"
    elif artifact == "variant_motif":
        case["timeline"]["scenes"][0].update(variant=1)
        case["timeline"]["scenes"][0]["variant_delta"] = {
            "spread": -0.06, "twist": 0.08, "flow": 0.0, "orbit": 0.0, "void": 0.0, "contrast": 0.0,
        }
        case["timeline"]["scenes"][0].update(motif="open-triad")
    elif artifact == "break_motif":
        case["recipe"]["families"][BREAK_FAMILY] = {
            "motif": "open-triad", "palette_slot": 2,
            "composition": {"spread": 0.1, "twist": 0.1, "flow": 0.1, "orbit": 0.1, "void": 0.1, "contrast": 0.1},
        }
    elif artifact == "variant_distance":
        case["timeline"]["scenes"][1].update(variant=1)
        case["timeline"]["scenes"][1]["variant_delta"] = {
            "spread": -0.16, "twist": 0.16, "flow": 0.0, "orbit": 0.0, "void": 0.0, "contrast": 0.0,
        }
    elif artifact == "transition_driver":
        case["timeline"]["transitions"][0].update(treatment="radial-part")
    elif artifact == "invalid_schema":
        case["recipe"]["schema"] = "beatscope-visual-recipe-0"

    result = evaluate_visual_case(case["name"], case["rhythm"], case["recipe"], case["timeline"])
    assert expected_gate in result["gates_failed"], result


def test_metric_reports_expose_tiling_transitions_identity():
    case = _compiled_case()
    tiling = scene_tiling_report(case["timeline"])
    assert tiling == {
        "scene_count": 2,
        "starts_at_zero": True,
        "ends_at_duration": True,
        "gaps": 0,
        "overlaps": 0,
    }
    transitions = transition_report(case["timeline"], case["rhythm"])
    assert transitions["transition_count"] == 1
    assert transitions["count_mismatch"] is False
    assert transitions["driver_treatment_mismatches"] == 0
    assert transitions["max_time_error_seconds"] == 0.0
    identity = identity_report(case["recipe"], case["timeline"])
    assert identity["variant_property_counts"] == []
    assert identity["break_reserved"] is True


# ------------------------------------------------------------- runner


def test_run_visual_benchmark_with_injected_cases(tmp_path):
    clean = _compiled_case("visual-clean")
    broken = _compiled_case("visual-broken")
    broken["timeline"]["transitions"][0].update(treatment="aperture")
    results = run_visual_benchmark(
        tmp_path / "report",
        cases=[
            evaluate_visual_case(clean["name"], clean["rhythm"], clean["recipe"], clean["timeline"]),
            evaluate_visual_case(broken["name"], broken["rhythm"], broken["recipe"], broken["timeline"]),
        ],
    )
    assert results["schema"] == "beatscope-visual-benchmark-1"
    assert results["gates"]["failed"] == ["driver-treatment-mapping", "invalid-artifacts"]
    assert results["output_dir"] == str(tmp_path / "report")
    payload = json.loads((tmp_path / "report" / "visual-benchmark.json").read_text(encoding="utf-8"))
    assert payload["gates"]["failed"] == ["driver-treatment-mapping", "invalid-artifacts"]
    assert {case["name"] for case in payload["cases"]} == {"visual-clean", "visual-broken"}
    markdown = (tmp_path / "report" / "visual-benchmark.md").read_text(encoding="utf-8")
    assert "visual-clean" in markdown and "driver-treatment-mapping" in markdown


def test_run_visual_benchmark_without_compiler_reports_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(visual_benchmark, "_default_compiler", lambda: (None, None))
    results = run_visual_benchmark(tmp_path / "report")
    assert results["gates"]["failed"] == ["compiler-unavailable"]
    assert {case["name"] for case in results["cases"]} == set(generate_visual.FIXTURE_NAMES)
    assert all(case["gates_failed"] == ["compiler-unavailable"] for case in results["cases"])


def test_pending_gates_cover_unimplemented_probes(tmp_path):
    enforced = set(visual_benchmark.ENFORCED_GATES)
    pending = sorted(gate for gate in BLOCKING_GATES if gate not in enforced)
    results = run_visual_benchmark(tmp_path / "report", cases=[])
    assert results["gates"]["pending"] == pending
    assert "composition-continuity" in pending
    assert "scene-query-p95" in pending
    assert "seek-determinism" in pending


def test_run_visual_benchmark_writes_default_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clean = _compiled_case("visual-clean")
    results = run_visual_benchmark(
        cases=[
            evaluate_visual_case(clean["name"], clean["rhythm"], clean["recipe"], clean["timeline"],
                                 canonical_bytes=generate_visual.canonical_bytes,
                                 recipe_bytes_again=generate_visual.canonical_bytes(clean["recipe"]),
                                 timeline_bytes_again=generate_visual.canonical_bytes(clean["timeline"])),
        ],
    )
    assert results["output_dir"] == str(Path("build") / "visual-benchmark")
    assert (tmp_path / "build" / "visual-benchmark" / "visual-benchmark.json").exists()
    assert results["gates"]["failed"] == []


# ------------------------------------------------------ frozen fixtures


def test_every_frozen_fixture_is_valid_v4():
    for name, rhythm in FROZEN_FIXTURES.items():
        assert validate_rhythm_v4(rhythm) == [], name


def test_frozen_fixture_set_matches_plan():
    assert set(FROZEN_FIXTURES) == set(generate_visual.FIXTURE_NAMES)
    assert len(FROZEN_FIXTURES) == 13


@pytest.mark.parametrize(
    "name, expect",
    [
        ("visual-aba", {"families": ["A", "B", "A"], "variants": [0, 0, 0], "boundaries": 2}),
        ("visual-aba-prime", {"families": ["A", "A", "A"], "variants": [0, 1, 0], "boundaries": 2}),
        ("visual-variable-tempo", {"families": ["A", "A", "A"], "variants": [0, 1, 0], "boundaries": 2}),
        ("visual-break", {"families": ["A", BREAK_FAMILY, "A"], "variants": [0, 0, 0], "boundaries": 2}),
        ("visual-driver-harmony", {"dominant": "harmony"}),
        ("visual-driver-rhythm", {"dominant": "rhythm"}),
        ("visual-driver-energy", {"dominant": "energy"}),
        ("visual-driver-timbre", {"dominant": "timbre"}),
        ("visual-neutral-boundary", {"dominant": "neutral"}),
        ("visual-rondo", {"min_families": 5}),
        ("visual-dense", {"dense_onsets": True}),
        ("visual-legacy", {"legacy": True}),
        ("visual-short", {"bars_under": 4}),
    ],
)
def test_frozen_fixtures_serve_their_documented_purpose(name, expect):
    rhythm = FROZEN_FIXTURES[name]
    segments = (rhythm["patterns"].get("segments") or [])
    boundaries = (rhythm["patterns"].get("boundaries") or [])
    if "families" in expect:
        assert [segment["family"] for segment in segments] == expect["families"]
    if "variants" in expect:
        assert [segment["variant"] for segment in segments] == expect["variants"]
    if "boundaries" in expect:
        assert len(boundaries) == expect["boundaries"]
    if "dominant" in expect:
        assert boundaries, name
        for boundary in boundaries:
            assert dominant_driver(boundary.get("drivers")) == expect["dominant"], name
    if "min_families" in expect:
        assert len({segment["family"] for segment in segments}) >= expect["min_families"]
    if expect.get("dense_onsets"):
        boundary = boundaries[0]
        window = [o for o in rhythm["onsets"] if abs(o["time"] - boundary["time"]) <= 2.0]
        assert len(window) >= 24
    if expect.get("legacy"):
        assert "segments" not in rhythm["patterns"]
        assert "boundaries" not in rhythm["patterns"]
    if "bars_under" in expect:
        assert rhythm["grid"]["bars"] < expect["bars_under"]


def test_variable_tempo_fixture_has_real_beat_intervals():
    beats = FROZEN_FIXTURES["visual-variable-tempo"]["beats"]
    intervals = [round(beats[i + 1]["time"] - beats[i]["time"], 4) for i in range(len(beats) - 1)]
    assert len(set(intervals)) > 1, "the fixture must carry differing beat intervals"


# ------------------------------------------------------ baseline refusal


def test_committed_manifest_matches_rebuilt_baseline():
    rebuilt = generate_visual.build_manifest()
    baseline = json.loads(generate_visual.MANIFEST_PATH.read_bytes().decode("utf-8"))
    assert rebuilt == baseline


def test_baseline_differences_describe_changes():
    baseline = json.loads(generate_visual.MANIFEST_PATH.read_bytes().decode("utf-8"))
    tampered = json.loads(json.dumps(baseline))
    tampered["fixtures"]["visual-aba"]["rhythm_sha256"] = "0" * 64
    differences = generate_visual.baseline_differences(tampered, baseline)
    assert len(differences) == 1
    assert differences[0].startswith("visual-aba.rhythm_sha256:")
    extra = json.loads(json.dumps(baseline))
    extra["fixtures"]["visual-new"] = {"project_id": "x", "rhythm_sha256": "0" * 64}
    assert "fixture added: visual-new" in generate_visual.baseline_differences(extra, baseline)


def test_main_refuses_overwrite_without_acceptance(tmp_path, monkeypatch, capsys):
    baseline = json.loads(generate_visual.MANIFEST_PATH.read_bytes().decode("utf-8"))
    stale = json.loads(json.dumps(baseline))
    stale["fixtures"]["visual-aba"]["rhythm_sha256"] = "0" * 64
    manifest_path = tmp_path / "visual-fixtures.json"
    manifest_path.write_text(json.dumps(stale, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(generate_visual, "MANIFEST_PATH", manifest_path)

    assert generate_visual.main([]) == 2
    assert "refusing to overwrite" in capsys.readouterr().out
    assert generate_visual.main(["--accept-baseline"]) == 0
    accepted = json.loads(manifest_path.read_bytes().decode("utf-8"))
    assert accepted["fixtures"]["visual-aba"] == baseline["fixtures"]["visual-aba"]
    assert generate_visual.main([]) == 0
    assert "baseline unchanged" in capsys.readouterr().out
