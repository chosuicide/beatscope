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
    CASE_PROBE_GATES,
    GATE_POLICY,
    PERF_PROBE_GATES,
    RECORDED_ONLY_GATES,
    TRANSITION_SAMPLE_COUNT,
    checkpoint_mismatches,
    collect_visual_checkpoints,
    evaluate_visual_case,
    identity_report,
    load_visual_checkpoints,
    load_visual_fixtures,
    motion_report,
    run_visual_benchmark,
    scene_tiling_report,
    transition_report,
    transition_sample_times,
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
    assert visual_benchmark.REDUCED_IMPUSE_SCALE_MAX == 0.15
    assert visual_benchmark.SCENE_QUERY_P95_MS == 0.10
    assert visual_benchmark.DIRECTOR_QUERY_P95_MS == 0.35
    assert visual_benchmark.RENDERER_CPU_P95_MS == 2.0
    assert visual_benchmark.FRAME_BUDGET_P95_MS == 18.0
    assert visual_benchmark.MAX_DRAW_CALLS == 1
    assert visual_benchmark.DIRECTOR_ALLOCATION_SMOKE_BYTES == 262_144
    assert visual_benchmark.PERF_FIXTURE_NAME == "visual-dense"
    assert visual_benchmark.PERF_SCENE_QUERIES == 3000
    assert visual_benchmark.PERF_DIRECTOR_QUERIES == 2000
    assert visual_benchmark.PERF_ALLOCATION_QUERIES == 8000
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


def test_every_blocking_gate_is_enforced(tmp_path):
    assert visual_benchmark.ENFORCED_GATES == BLOCKING_GATES
    results = run_visual_benchmark(tmp_path / "report", cases=[])
    assert results["gates"]["pending"] == []
    assert results["gates"]["unavailable"] == []
    assert results["gates"]["failed"] == []


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


# ------------------------------------------------- identity: palette gate


def test_family_palette_gate_flags_invalid_slot():
    case = _compiled_case()
    case["recipe"]["families"]["A"]["palette_slot"] = 9
    result = evaluate_visual_case(case["name"], case["rhythm"], case["recipe"], case["timeline"])
    assert "family-palette-equality" in result["gates_failed"]
    assert result["metrics"]["identity"]["palette_violations"]


def test_family_palette_gate_flags_unknown_family_reference():
    case = _compiled_case()
    case["timeline"]["scenes"][0]["family"] = "ZZ"
    result = evaluate_visual_case(case["name"], case["rhythm"], case["recipe"], case["timeline"])
    assert "family-palette-equality" in result["gates_failed"]


# ----------------------------------------------- motion sampling (18.4)


def _smoothstep(value: float) -> float:
    clamped = min(1.0, max(0.0, value))
    return clamped * clamped * (3.0 - 2.0 * clamped)


FROM_BASE = {"spread": 0.3, "twist": 0.16, "flow": 0.24, "orbit": 0.52, "void": 0.22, "contrast": 0.66}
TO_BASE = {"spread": 0.42, "twist": 0.1, "flow": 0.3, "orbit": 0.4, "void": 0.3, "contrast": 0.5}
BOUNDARY, LEAD, SETTLE, STRENGTH, PALETTE_CAP = 8.0, 0.5, 0.75, 0.8, 0.42


def _synthetic_timeline():
    return {
        "duration": 16.0,
        "scenes": [
            {"id": "scene-001", "family": "A", "start_time": 0.0, "end_time": 8.0, "variant_delta": {}},
            {"id": "scene-002", "family": "B", "start_time": 8.0, "end_time": 16.0, "variant_delta": {}},
        ],
        "transitions": [
            {
                "id": "t1",
                "boundary_bar": 9,
                "time": BOUNDARY,
                "lead_seconds": LEAD,
                "settle_seconds": SETTLE,
                "strength": STRENGTH,
                "treatment": "phase-turn",
                "driver": "harmony",
            }
        ],
    }


def _synthetic_recipe():
    return {
        "families": {
            "A": {"composition": dict(FROM_BASE)},
            "B": {"composition": dict(TO_BASE)},
        },
        "tokens": {"motion": {"max_palette_mix": PALETTE_CAP}},
    }


def _synthetic_frame(time, *, reduced=False):
    if time == BOUNDARY:
        stage, impulse = "cross", STRENGTH
    elif BOUNDARY < time <= BOUNDARY + SETTLE:
        stage, impulse = "settle", 0.0
    elif BOUNDARY - LEAD <= time < BOUNDARY:
        stage, impulse = "approach", 0.0
    else:
        stage, impulse = "idle", 0.0
    envelope = (
        1.0 if stage == "cross"
        else _smoothstep((time - (BOUNDARY - LEAD)) / LEAD) if stage == "approach"
        else 1.0 - _smoothstep((time - BOUNDARY) / SETTLE) if stage == "settle"
        else 0.0
    )
    motion_scale = 0.2 if reduced else 1.0
    mix = _smoothstep((time - BOUNDARY) / SETTLE) if time > BOUNDARY else 0.0
    composition = {
        key: FROM_BASE[key] + (TO_BASE[key] - FROM_BASE[key]) * mix * (0.2 if reduced and key in ("spread", "twist", "flow") else 1.0)
        for key in FROM_BASE
    }
    composition["paletteMix"] = mix * PALETTE_CAP
    return {
        "time": time,
        "transition": {
            "stage": stage,
            "impulse": impulse * (0.15 if reduced else 1.0),
            "strength": STRENGTH,
            "channels": {
                "phaseTurn": envelope * motion_scale,
                "radialPart": 0.0,
                "aperture": 0.0,
                "flowShear": 0.0,
                "contrastHit": STRENGTH if stage == "cross" else STRENGTH * envelope if stage == "settle" else 0.0,
            },
        },
        "composition": composition,
    }


def _synthetic_samples():
    times = transition_sample_times(_synthetic_timeline())["t1"]
    samples = []
    for time in times:
        beat = {"lobeSplit": 0.1}
        samples.append({
            "transition": "t1",
            "time": time,
            "full": _synthetic_frame(time),
            "reduced": _synthetic_frame(time, reduced=True),
            "beat": beat,
            "sceneSpread": 0.35,
        })
    return samples


def test_transition_sample_times_follow_plan_grid():
    samples = transition_sample_times(_synthetic_timeline())["t1"]
    assert len(samples) == TRANSITION_SAMPLE_COUNT
    assert samples[3] == BOUNDARY
    for offset, expected in (
        (0, BOUNDARY - LEAD - 0.001),
        (1, BOUNDARY - LEAD),
        (2, BOUNDARY - 0.001),
        (4, BOUNDARY + 0.001),
        (5, BOUNDARY + SETTLE / 2),
        (6, BOUNDARY + SETTLE),
        (7, BOUNDARY + SETTLE + 0.001),
    ):
        assert abs(samples[offset] - expected) < 1e-12


def test_motion_report_accepts_conforming_samples():
    report = motion_report(_synthetic_recipe(), _synthetic_timeline(), _synthetic_samples())
    assert report["sample_count"] == TRANSITION_SAMPLE_COUNT
    assert report["past_end_samples"] == 0
    assert report["bounds_violations"] == []
    assert report["continuity_violations"] == []
    assert report["impulse_violations"] == []
    assert report["reduced_motion_violations"] == []
    assert report["settle_exactness_violations"] == []
    assert report["combined_spread_violations"] == []
    assert report["combined_spread_max"] == 0.35


def _sample_at(samples, time):
    return next(sample for sample in samples if abs(sample["time"] - time) < 1e-12)


@pytest.mark.parametrize(
    "mutate, field",
    [
        # a composition channel jumps across the boundary
        (
            lambda samples: _sample_at(samples, BOUNDARY + 0.001)["full"]["composition"].update(spread=0.31),
            "continuity_violations",
        ),
        # the impulse leaks below its sanctioned boundary instant
        (
            lambda samples: _sample_at(samples, BOUNDARY - 0.001)["full"]["transition"].update(impulse=0.4),
            "impulse_violations",
        ),
        # reduced motion closes the whole crossfade distance
        (
            lambda samples: _sample_at(samples, BOUNDARY + SETTLE / 2)["reduced"]["composition"].update(
                spread=_sample_at(samples, BOUNDARY + SETTLE / 2)["full"]["composition"]["spread"]
            ),
            "reduced_motion_violations",
        ),
        # settlement misses the target scene base
        (
            lambda samples: _sample_at(samples, BOUNDARY + SETTLE)["full"]["composition"].update(spread=0.4),
            "settle_exactness_violations",
        ),
        # the combined spread breaks through the cap
        (
            lambda samples: _sample_at(samples, BOUNDARY).update(sceneSpread=0.9),
            "combined_spread_violations",
        ),
    ],
)
def test_motion_report_flags_violations(mutate, field):
    samples = _synthetic_samples()
    mutate(samples)
    report = motion_report(_synthetic_recipe(), _synthetic_timeline(), samples)
    assert report[field], field


def test_motion_report_ignores_post_settle_ownership_snap():
    # After the settle window both motion modes sit exactly on the owning
    # scene's base; that structural handoff is not a reduced-motion breach.
    samples = _synthetic_samples()
    report = motion_report(_synthetic_recipe(), _synthetic_timeline(), samples)
    assert not report["reduced_motion_violations"]


def test_motion_report_tolerates_past_end_samples():
    samples = _synthetic_samples()
    samples[-1]["full"] = None
    samples[-1]["reduced"] = None
    report = motion_report(_synthetic_recipe(), _synthetic_timeline(), samples)
    assert report["past_end_samples"] >= 1
    assert report["bounds_violations"] == []


# ---------------------------------------------------------- probe runs


def test_probe_gates_become_unavailable_without_node(tmp_path, monkeypatch):
    monkeypatch.setattr(visual_benchmark.shutil, "which", lambda name: None)
    results = run_visual_benchmark(tmp_path / "report")
    assert results["gates"]["failed"] == []
    assert set(results["gates"]["unavailable"]) == set(CASE_PROBE_GATES) | set(PERF_PROBE_GATES)
    by_name = {case["name"]: case for case in results["cases"]}
    # The compiler still runs, so artifact gates stay enforced everywhere.
    assert by_name["visual-legacy"]["metrics"]["tiling"]["scene_count"] == 1
    assert all("compiler-unavailable" not in case["gates_failed"] for case in results["cases"])


def _node_missing() -> bool:
    import shutil

    return shutil.which("node") is None


@pytest.mark.skipif(_node_missing(), reason="Node.js is not available")
def test_full_visual_benchmark_passes_every_gate(tmp_path):
    results = run_visual_benchmark(tmp_path / "report")
    assert results["gates"]["failed"] == []
    assert results["gates"]["unavailable"] == []
    assert results["gates"]["pending"] == []
    assert results["probes"]["driver"] == "ok"
    assert results["probes"]["parity"] == "checked"
    by_name = {case["name"]: case for case in results["cases"]}
    assert len(by_name) == 13
    # Golden checkpoints replay exactly through the live runtime.
    assert all(case["metrics"].get("checkpoint_mismatches", 0) == 0 for case in results["cases"])
    # Determinism probes all ran and passed.
    for case in results["cases"]:
        determinism = case["metrics"].get("determinism") or {}
        assert determinism.get("order_checked") and determinism.get("seek_checked"), case["name"]
        assert determinism.get("parity_checked"), case["name"]
    # Performance probes on the dense fixture stay inside the budgets.
    performance = by_name["visual-dense"]["metrics"]["performance"]
    assert performance["scene_query_p95_ms"] < visual_benchmark.SCENE_QUERY_P95_MS
    assert performance["director_query_p95_ms"] < visual_benchmark.DIRECTOR_QUERY_P95_MS
    assert performance["allocation_retained_bytes"] <= visual_benchmark.DIRECTOR_ALLOCATION_SMOKE_BYTES
    assert set(performance["draw_call_renders"]) == {visual_benchmark.MAX_DRAW_CALLS}
    # The legacy fixture compiles to its single neutral scene.
    assert by_name["visual-legacy"]["metrics"]["tiling"]["scene_count"] == 1
    markdown = (tmp_path / "report" / "visual-benchmark.md").read_text(encoding="utf-8")
    assert "gates failed: 0" in markdown
    assert "gates unavailable: 0" in markdown


# --------------------------------------------------------- checkpoints


def test_committed_checkpoints_cover_every_fixture():
    document = load_visual_checkpoints()
    assert document["schema"] == "beatscope-visual-checkpoints-1"
    assert document["recipe_version"] == "0.8.0"
    assert set(document["fixtures"]) == set(FROZEN_FIXTURES)
    for name, payload in document["fixtures"].items():
        assert len(payload["times"]) == len(payload["states"]) >= 3, name
        assert payload["times"][0] == 0.0
        assert all(state is not None and state["scene"]["family"] for state in payload["states"]), name


@pytest.mark.skipif(_node_missing(), reason="Node.js is not available")
def test_checkpoint_regeneration_is_byte_identical():
    import json

    document = collect_visual_checkpoints()
    text = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    committed = visual_benchmark.COMMITTED_CHECKPOINT_PATH.read_bytes().decode("utf-8")
    assert text == committed


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
