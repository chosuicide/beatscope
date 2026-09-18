"""Chart parser, alignment, weak-label, and split tests (v0.11 Round 2).

The fixture charts under ``tests/fixtures/event_ranking/charts`` are tiny
original files: they pin parser and alignment semantics only and must never
back any model-quality claim.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

import beatscope.chart_labels as cl
from beatscope.chart_labels import (
    CHART_CONTRACT,
    CODE_ALIGNMENT_MATCH_RATE_TOO_LOW,
    CODE_MALFORMED_CHART,
    CODE_UNSUPPORTED_CHART_FORMAT,
    CODE_UNSUPPORTED_CHART_MODE,
    CODE_UNSUPPORTED_TIMING_FEATURE,
    MAX_PAIRS_PER_EVENT,
    ChartLabelError,
    align_chart_to_clusters,
    assign_development_splits,
    assign_splits,
    assign_splits_with_holdout,
    audit_partition_leakage,
    audit_split_leakage,
    build_preference_pairs,
    build_weak_labels,
    calibrated_chart,
    chart_alignment_verdict,
    coincident_onset_clusters,
    collapse_simultaneous,
    consumed_artifact_conflicts,
    estimate_song_alignment_offset,
    group_charts_into_songs,
    marker_sequence_hash,
    parse_chart_file,
    parse_osu,
    parse_stepmania_sm,
)
from tests.fixtures.event_evidence.generate_event_evidence import REPO_ROOT as _EE_ROOT

CHARTS_DIR = _EE_ROOT / "tests" / "fixtures" / "event_ranking" / "charts"

# ---------------------------------------------------------------- parser helpers


def load_chart(name: str) -> str:
    return (CHARTS_DIR / name).read_text(encoding="utf-8")


def make_entry(chart: dict, audio_sha: str, duration: float = 30.0) -> dict:
    return {"chart": chart, "audio_sha256": audio_sha, "audio_duration": duration}


# ------------------------------------------------------------- parser correctness


def test_sm_constant_bpm_row_times_are_exact():
    charts = parse_chart_file(CHARTS_DIR / "sm-constant.sm")
    assert len(charts) == 1
    chart = charts[0]
    assert chart["schema"] == CHART_CONTRACT
    assert chart["format"] == "stepmania"
    assert chart["mode"] == "dance-single"
    assert chart["difficulty_name"] == "Easy"
    assert chart["declared_meter"] == 1
    assert chart["markers_seconds"] == [0.0, 2.0]
    assert chart["diagnostics"]["raw_object_count"] == 2
    assert chart["diagnostics"]["normalized_marker_count"] == 2


def test_sm_standard_radar_field_and_multi_chart_ids_are_supported():
    text = (
        "#MUSIC:x.ogg;\n#BPMS:0=120;\n"
        "#NOTES:dance-single:Author:Easy:2:0,0,0,0,0:\n1000\n0000\n;\n"
        "#NOTES:dance-single:Author:Hard:8:0,0,0,0,0:\n1000\n0100\n;\n"
    )
    charts = parse_stepmania_sm(text, "a" * 64, "x.ogg")
    assert [chart["difficulty_name"] for chart in charts] == ["Easy", "Hard"]
    assert [chart["markers_seconds"] for chart in charts] == [[0.0], [0.0, 1.0]]
    assert len({chart["chart_sha256"] for chart in charts}) == 2
    assert all(len(chart["chart_sha256"]) == 64 for chart in charts)


def test_sm_bpm_change_and_stop_boundaries():
    chart = parse_chart_file(CHARTS_DIR / "sm-bpm-stop.sm")[0]
    # Beat 3 (before the change), beat 4 (at the BPM change, unshifted by the
    # stop), and beat 5 (after the stop, shifted by one full second).
    assert chart["markers_seconds"] == [0.5, 3.5, 4.5, 6.0]


def test_stepmania_offset_delay_and_stop_follow_engine_row_order():
    chart = parse_stepmania_sm(
        "#OFFSET:-0.5;\n#BPMS:0=60;\n#DELAYS:1=0.25;\n#STOPS:2=0.5;\n"
        "#NOTES:\n:dance-single:X:1:\n1000\n1000\n1000\n1000\n;\n",
        "a" * 64, "x.ogg")[0]
    # Positive audio time is -OFFSET. Delay happens before its row; stop after its row.
    assert chart["markers_seconds"] == [0.5, 1.75, 2.75, 4.25]


def test_ssc_chart_blocks_do_not_leak_timing():
    charts = parse_chart_file(CHARTS_DIR / "ssc-two-charts.ssc")
    by_name = {chart["difficulty_name"]: chart for chart in charts}
    assert by_name["Beginner"]["markers_seconds"] == [1.0]
    assert by_name["Beginner"]["declared_meter"] == 1
    # Chart two overrides the BPM for its own block only.
    assert by_name["Nightmare"]["markers_seconds"] == [0.0]
    assert by_name["Nightmare"]["declared_meter"] == 12
    assert len({chart["chart_sha256"] for chart in charts}) == 2


def test_ssc_lift_is_a_head_and_sm_lift_is_rejected():
    chart = parse_chart_file(CHARTS_DIR / "ssc-chords.ssc")[0]
    assert chart["markers_seconds"] == [0.0, 3.0]
    assert chart["diagnostics"] == {
        "raw_object_count": 4,
        "normalized_marker_count": 2,
        "ignored_tail_count": 1,
        "ignored_hazard_count": 1,
    }
    with pytest.raises(ChartLabelError) as error:
        parse_chart_file(CHARTS_DIR / "sm-lift.sm")
    assert error.value.code == CODE_UNSUPPORTED_TIMING_FEATURE


def test_chords_collapse_to_one_marker_per_row():
    sm = "#BPMS:0=120.000;\n#NOTES:\n:dance-single:X:1:\n1100\n0000\n;\n"
    chart = parse_stepmania_sm(sm, "a" * 64, "x.ogg")[0]
    assert chart["markers_seconds"] == [0.0]
    assert chart["diagnostics"]["raw_object_count"] == 2
    assert chart["diagnostics"]["normalized_marker_count"] == 1


def test_unsupported_warp_and_time_signature_fail_honestly():
    with pytest.raises(ChartLabelError) as warp_error:
        parse_chart_file(CHARTS_DIR / "sm-warp.sm")
    assert warp_error.value.code == CODE_UNSUPPORTED_TIMING_FEATURE
    with pytest.raises(ChartLabelError) as time_error:
        parse_chart_file(CHARTS_DIR / "sm-timesig.sm")
    assert time_error.value.code == CODE_UNSUPPORTED_TIMING_FEATURE
    with pytest.raises(ChartLabelError) as bpm_error:
        parse_chart_file(CHARTS_DIR / "sm-negative-bpm.sm")
    assert bpm_error.value.code == CODE_UNSUPPORTED_TIMING_FEATURE


def test_malformed_lane_count_and_bad_fields_fail():
    with pytest.raises(ChartLabelError) as lanes:
        parse_chart_file(CHARTS_DIR / "sm-bad-lanes.sm")
    assert lanes.value.code == CODE_MALFORMED_CHART
    with pytest.raises(ChartLabelError) as fields:
        parse_stepmania_sm("#BPMS:0=120;\n#NOTES:\n:Easy:1:\n1000\n;\n", "a" * 64, "x.ogg")
    assert fields.value.code == CODE_MALFORMED_CHART


def test_osu_standard_circles_and_slider_heads_survive():
    chart = parse_chart_file(CHARTS_DIR / "osu-standard.osu")[0]
    assert chart["format"] == "osu"
    assert chart["mode"] == "osu-standard"
    assert chart["audio_reference"] == "std audio.mp3"
    assert chart["markers_seconds"] == [1.0, 2.0]
    assert chart["diagnostics"] == {
        "raw_object_count": 3,
        "normalized_marker_count": 2,
        "ignored_tail_count": 0,
        "ignored_hazard_count": 1,
    }


def test_taiko_includes_circles_but_not_slider_heads():
    chart = parse_chart_file(CHARTS_DIR / "osu-taiko.osu")[0]
    assert chart["mode"] == "osu-taiko"
    assert chart["markers_seconds"] == [0.5]
    assert chart["diagnostics"]["ignored_tail_count"] == 1


def test_mania_chord_collapses_and_holds_keep_heads():
    chart = parse_chart_file(CHARTS_DIR / "osu-mania.osu")[0]
    assert chart["mode"] == "osu-mania"
    assert chart["declared_meter"] == 7
    assert chart["markers_seconds"] == [0.3, 0.7, 1.2]
    assert chart["diagnostics"]["normalized_marker_count"] == 3


def test_catch_mode_and_malformed_osu_fail():
    with pytest.raises(ChartLabelError) as mode_error:
        parse_chart_file(CHARTS_DIR / "osu-catch.osu")
    assert mode_error.value.code == CODE_UNSUPPORTED_CHART_MODE
    with pytest.raises(ChartLabelError) as unsorted:
        parse_chart_file(CHARTS_DIR / "osu-unsorted.osu")
    assert unsorted.value.code == CODE_MALFORMED_CHART
    with pytest.raises(ChartLabelError) as negative:
        parse_chart_file(CHARTS_DIR / "osu-negative.osu")
    assert negative.value.code == CODE_UNSUPPORTED_TIMING_FEATURE
    with pytest.raises(ChartLabelError) as header:
        parse_osu("[General]\nMode: 0\n", "a" * 64)
    assert header.value.code == CODE_UNSUPPORTED_CHART_FORMAT


def test_unsupported_suffix_is_rejected(tmp_path: Path):
    bad = tmp_path / "chart.bms"
    bad.write_text("#TITLE whatever\n", encoding="utf-8")
    with pytest.raises(ChartLabelError) as error:
        parse_chart_file(bad)
    assert error.value.code == CODE_UNSUPPORTED_CHART_FORMAT


def test_simultaneous_collapse_uses_chain_semantics():
    assert collapse_simultaneous([0.0, 0.0008, 0.0016], 0.001) == [0.0, 0.0016]
    assert collapse_simultaneous([1.0, 1.001], 0.001) == [1.0]


# ----------------------------------------------------------- alignment correctness


def clusters_from(times: list[float]) -> list[dict]:
    return coincident_onset_clusters(times, list(range(1, len(times) + 1)))


def test_exact_equality_matches_with_zero_residual():
    alignment = align_chart_to_clusters([1.0], clusters_from([1.0]))
    assert alignment["matched_marker_count"] == 1
    assert alignment["max_residual"] == 0.0


def test_alignment_boundary_is_pinned_at_fifty_ms():
    clusters = clusters_from([1.0])
    assert align_chart_to_clusters([1.05], clusters)["matched_marker_count"] == 1
    assert align_chart_to_clusters([1.050001], clusters)["matched_marker_count"] == 0
    assert align_chart_to_clusters([1.0500004], clusters)["matched_marker_count"] == 0


def test_coincident_onset_clusters_chain_consecutive_gaps():
    clusters = coincident_onset_clusters([0.0, 0.0008, 0.0016], [9, 8, 7])
    assert clusters == [{"time": 0.0, "onset_ids": [9, 8, 7]}]


def test_matching_is_one_to_one_on_both_sides():
    clusters = clusters_from([1.0, 2.0])
    alignment = align_chart_to_clusters([1.0, 1.01], clusters)
    assert alignment["matched_marker_count"] == 1
    assert alignment["matched_cluster_count"] == 1
    clusters = clusters_from([1.0, 1.01])
    alignment = align_chart_to_clusters([1.0, 2.0], clusters)
    assert alignment["matched_marker_count"] == 1


def test_adversarial_stealing_chooses_maximum_cardinality():
    # Greedy nearest matching would take cluster 1.02 for marker 1.00 and
    # strand marker 1.04; the exact objective keeps both markers matched.
    clusters = clusters_from([0.96, 1.02])
    alignment = align_chart_to_clusters([1.00, 1.04], clusters)
    assert alignment["matched_marker_count"] == 2
    assert alignment["covered_onset_ids"] == [1, 2]


def test_equal_cardinality_prefers_lower_total_error():
    clusters = clusters_from([1.0, 2.0])
    alignment = align_chart_to_clusters([1.04, 1.96], clusters)
    assert [(marker, cluster) for marker, cluster, _ in alignment["matches"]] == [(0, 0), (1, 1)]
    assert alignment["max_residual"] == 0.04


def test_remaining_ties_choose_earlier_onset_indices():
    clusters = clusters_from([1.0, 1.02, 2.0])
    alignment = align_chart_to_clusters([1.01], clusters)
    assert [(marker, cluster) for marker, cluster, _ in alignment["matches"]] == [(0, 0)]


def test_ambiguous_component_is_reported():
    # Two clusters and two markers where two pairings reach the same count
    # and the same total error: (0.0,0.04)+(0.08,0.04)? Distances: pick a
    # symmetric diamond so both perfect matchings sum to the same error.
    clusters = clusters_from([1.0, 1.02])
    markers = [1.01]
    alignment = align_chart_to_clusters(markers, clusters)
    assert alignment["ambiguous_component_count"] == 1


def test_alignment_never_invents_or_removes_events():
    clusters = clusters_from([1.0, 5.0, 9.0])
    alignment = align_chart_to_clusters([1.01, 5.02, 7.5], clusters)
    assert alignment["covered_onset_ids"] == [1, 2]
    assert alignment["unmatched_marker_count"] == 1


def test_low_match_rate_verdict():
    chart = {"markers_seconds": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]}
    clusters = clusters_from([0.0])
    alignment = align_chart_to_clusters(chart["markers_seconds"], clusters)
    assert chart_alignment_verdict(chart, alignment, 10.0) == CODE_ALIGNMENT_MATCH_RATE_TOO_LOW


def test_p95_residual_verdict():
    chart = {"markers_seconds": [1.0 + 0.045 * index for index in range(40)]}
    clusters = clusters_from([1.0])
    alignment = align_chart_to_clusters(chart["markers_seconds"], clusters)
    verdict = chart_alignment_verdict(chart, alignment, 30.0)
    assert verdict in (CODE_ALIGNMENT_MATCH_RATE_TOO_LOW, "alignment_residual_too_high")


def test_song_alignment_calibration_requires_coherent_difficulties():
    clusters = clusters_from([1.0, 2.0, 3.0, 4.0])
    charts = [
        {"markers_seconds": [1.02, 2.02, 3.02, 4.02]},
        {"markers_seconds": [1.021, 2.021, 3.021, 4.021]},
        {"markers_seconds": [1.019, 2.019, 3.019, 4.019]},
    ]
    calibration = estimate_song_alignment_offset(charts, clusters)
    assert calibration["applied"] is True
    assert calibration["offset_seconds"] == pytest.approx(0.02)
    assert calibration["mad_seconds"] == pytest.approx(0.001)
    adjusted = calibrated_chart(charts[0], calibration["offset_seconds"])
    assert adjusted["markers_seconds"] == pytest.approx([1.0, 2.0, 3.0, 4.0])
    assert charts[0]["markers_seconds"][0] == 1.02  # source chart stays immutable


def test_song_alignment_calibration_rejects_disagreement():
    clusters = clusters_from([1.0, 2.0, 3.0, 4.0])
    charts = [
        {"markers_seconds": [0.97, 1.97, 2.97, 3.97]},
        {"markers_seconds": [1.0, 2.0, 3.0, 4.0]},
        {"markers_seconds": [1.03, 2.03, 3.03, 4.03]},
    ]
    calibration = estimate_song_alignment_offset(charts, clusters)
    assert calibration["applied"] is False
    assert calibration["offset_seconds"] == 0.0
    assert calibration["mad_seconds"] == pytest.approx(0.03)


# ------------------------------------------------------- label and split correctness


def _song_with_charts(markers_lists: list[list[float]], audio_sha: str) -> dict:
    entries = [
        make_entry({
            "schema": CHART_CONTRACT,
            "format": "stepmania",
            "mode": "dance-single",
            "chart_sha256": f"{index:064x}",
            "audio_reference": "x.ogg",
            "difficulty_name": f"D{index}",
            "declared_meter": 4,
            "markers_seconds": markers,
            "diagnostics": {"raw_object_count": len(markers), "normalized_marker_count": len(markers),
                            "ignored_tail_count": 0, "ignored_hazard_count": 0},
        }, audio_sha)
        for index, markers in enumerate(markers_lists)
    ]
    songs = group_charts_into_songs(entries)
    return songs[0]


def test_copied_difficulty_votes_once():
    shared = [1.0, 2.0, 3.0, 4.0]
    different = [1.0, 2.5, 3.0, 4.0]
    song = _song_with_charts([shared, list(shared), different], "a" * 64)
    reasons = [exclusion["reason"] for exclusion in song["exclusions"]]
    assert "duplicate_timeline" in reasons
    # Only two unique timelines remain, below the three-chart song gate.
    assert song["charts"] == []
    assert any(reason["reason"] == "insufficient_unique_difficulties" for reason in song["exclusions"])


def test_duplicate_hash_is_content_based_not_name_based():
    shared = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    other = [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]
    third = [2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    song = _song_with_charts([shared, list(shared), other, third], "b" * 64)
    assert len(song["charts"]) == 3
    hashes = [marker_sequence_hash(chart["chart"]["markers_seconds"]) for chart in song["charts"]]
    assert len(set(hashes)) == 3


def test_support_rate_denominator_uses_eligible_unique_charts():
    song = _song_with_charts(
        [[1.0, 2.0, 3.0], [1.0, 2.0, 5.0], [1.0, 9.0, 9.5]], "c" * 64)
    clusters = coincident_onset_clusters([1.0, 2.0, 3.0, 5.0, 9.0], [1, 2, 3, 4, 5])
    alignments = {
        chart["chart"]["chart_sha256"]: align_chart_to_clusters(chart["chart"]["markers_seconds"], clusters)
        for chart in song["charts"]
    }
    labels = build_weak_labels(song, alignments, clusters)
    by_id = {record["onset_id"]: record for record in labels}
    assert by_id[1]["chart_support_count"] == 3
    assert by_id[1]["support_rate"] == 1.0
    assert by_id[3]["support_rate"] == pytest.approx(1 / 3)
    assert by_id[4]["support_rate"] == pytest.approx(1 / 3)
    for record in labels:
        assert record["eligible_chart_count"] == 3
        assert set(record) == {
            "onset_id", "chart_support_count", "eligible_chart_count",
            "support_rate", "sparse_half_support", "dense_half_support",
        }


def test_zero_support_onsets_remain_in_label_and_pair_universe():
    song = _song_with_charts(
        [[1.0, 2.0], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0]], "f" * 64)
    clusters = coincident_onset_clusters([1.0, 2.0, 3.0, 4.0, 4.5], [1, 2, 3, 4, 9])
    alignments = {
        chart["chart"]["chart_sha256"]: align_chart_to_clusters(
            chart["chart"]["markers_seconds"], clusters)
        for chart in song["charts"]
    }
    labels = build_weak_labels(song, alignments, clusters)
    by_id = {record["onset_id"]: record for record in labels}
    assert by_id[9]["chart_support_count"] == 0
    assert by_id[9]["support_rate"] == 0.0
    pairs = build_preference_pairs(
        labels, {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0, 9: 4.5},
        {1: None, 2: None, 3: None, 4: None, 9: None})
    assert any(pair["other_onset_id"] == 9 for pair in pairs)


def test_label_records_carry_no_timestamp():
    song = _song_with_charts([[1.0, 2.0], [1.0, 2.0], [1.0, 4.0]], "d" * 64)
    clusters = coincident_onset_clusters([1.0, 2.0, 4.0], [1, 2, 3])
    alignments = {
        chart["chart"]["chart_sha256"]: align_chart_to_clusters(chart["chart"]["markers_seconds"], clusters)
        for chart in song["charts"]
    }
    labels = build_weak_labels(song, alignments, clusters)
    raw = repr(labels)
    for forbidden in ("time", "seconds", "marker"):
        assert forbidden not in raw.lower().replace("support_rate", "")


def test_odd_middle_chart_joins_dense_half():
    song = _song_with_charts(
        [[1.0, 2.0], [1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]], "e" * 64)
    clusters = coincident_onset_clusters([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], list(range(1, 7)))
    alignments = {
        chart["chart"]["chart_sha256"]: align_chart_to_clusters(chart["chart"]["markers_seconds"], clusters)
        for chart in song["charts"]
    }
    labels = build_weak_labels(song, alignments, clusters)
    by_id = {record["onset_id"]: record for record in labels}
    onset_1 = by_id[1]  # supported by every chart
    assert onset_1["sparse_half_support"] == 1
    assert onset_1["dense_half_support"] == 2


def test_pair_direction_follows_support_gap_and_threshold():
    labels = [
        {"onset_id": 1, "chart_support_count": 3, "eligible_chart_count": 3, "support_rate": 1.0,
         "sparse_half_support": 1, "dense_half_support": 2},
        {"onset_id": 2, "chart_support_count": 1, "eligible_chart_count": 3, "support_rate": 0.333333,
         "sparse_half_support": 1, "dense_half_support": 0},
    ]
    pairs = build_preference_pairs(labels, {1: 10.0, 2: 10.5}, {1: None, 2: None})
    assert len(pairs) == 1
    assert pairs[0]["preferred_onset_id"] == 1
    assert pairs[0]["other_onset_id"] == 2

    reversed_ids = [dict(labels[1]), dict(labels[0])]
    reversed_ids[0]["onset_id"] = 1
    reversed_ids[1]["onset_id"] = 2
    reversed_pair = build_preference_pairs(reversed_ids, {1: 10.0, 2: 10.5}, {1: None, 2: None})
    assert reversed_pair[0]["preferred_onset_id"] == 2
    assert reversed_pair[0]["other_onset_id"] == 1

    near = [
        {"onset_id": 1, "chart_support_count": 2, "eligible_chart_count": 3, "support_rate": 0.666667,
         "sparse_half_support": 1, "dense_half_support": 1},
        {"onset_id": 2, "chart_support_count": 1, "eligible_chart_count": 3, "support_rate": 0.333333,
         "sparse_half_support": 0, "dense_half_support": 1},
    ]
    assert build_preference_pairs(near, {1: 1.0, 2: 1.5}, {1: None, 2: None}) == []


def test_locality_window_gates_distant_pairs_without_structure():
    labels = [
        {"onset_id": 1, "support_rate": 1.0, "chart_support_count": 3, "eligible_chart_count": 3,
         "sparse_half_support": 1, "dense_half_support": 2},
        {"onset_id": 2, "support_rate": 0.0, "chart_support_count": 0, "eligible_chart_count": 3,
         "sparse_half_support": 0, "dense_half_support": 0},
    ]
    distant = build_preference_pairs(labels, {1: 1.0, 2: 20.0}, {1: None, 2: None})
    assert distant == []
    same_segment = build_preference_pairs(labels, {1: 1.0, 2: 20.0}, {1: 0, 2: 0})
    assert len(same_segment) == 1


def test_pair_cap_is_exact_and_deterministic():
    labels = [
        {"onset_id": 1, "support_rate": 1.0, "chart_support_count": 3, "eligible_chart_count": 3,
         "sparse_half_support": 1, "dense_half_support": 2},
    ]
    for index in range(12):
        labels.append({
            "onset_id": 10 + index,
            "support_rate": 0.0,
            "chart_support_count": 0, "eligible_chart_count": 3,
            "sparse_half_support": 0, "dense_half_support": 0,
        })
    onset_times = {1: 100.0}
    onset_times.update({10 + index: 100.5 + 0.1 * index for index in range(12)})
    segment_map = {onset_id: None for onset_id in onset_times}
    pairs = build_preference_pairs(labels, onset_times, segment_map)
    preferred_counts = {}
    for pair in pairs:
        preferred_counts[pair["preferred_onset_id"]] = preferred_counts.get(pair["preferred_onset_id"], 0) + 1
    assert preferred_counts[1] == MAX_PAIRS_PER_EVENT
    again = build_preference_pairs(copy.deepcopy(labels), dict(onset_times), dict(segment_map))
    assert pairs == again


def test_split_assignment_is_stable_when_songs_are_added():
    base_songs = [{"audio_sha256": f"{index:064x}", "charts": [], "exclusions": []} for index in range(12)]
    base = assign_splits(copy.deepcopy(base_songs))
    larger = base_songs + [{"audio_sha256": "f" * 64, "charts": [], "exclusions": []}]
    updated = assign_splits(copy.deepcopy(larger), frozen_assignments=base)
    for audio_sha, split in base.items():
        assert updated[audio_sha] == split, f"{audio_sha} moved split when a song was added"


def test_explicit_holdout_owns_the_only_test_split():
    songs = [{"audio_sha256": f"{index:064x}", "charts": [], "exclusions": []}
             for index in range(18)]
    holdout = {songs[-1]["audio_sha256"], songs[-2]["audio_sha256"]}
    assignments = assign_splits_with_holdout(copy.deepcopy(songs), holdout)
    assert {sha for sha, split in assignments.items() if split == "test"} == holdout
    assert "validation" in assignments.values()
    assert "train" in assignments.values()


def test_duplicate_fingerprints_never_cross_splits():
    songs = [{"audio_sha256": f"{index:064x}", "charts": [], "exclusions": []} for index in range(12)]
    assignments = assign_splits(copy.deepcopy(songs))
    shared_fingerprint = "f" * 64
    fingerprints = {song["audio_sha256"]: shared_fingerprint for song in songs}
    errors = audit_split_leakage(songs, assignments, fingerprints)
    assert errors
    assert all("duplicate_audio_across_splits" in error for error in errors)
    distinct = {song["audio_sha256"]: sha_of(song["audio_sha256"]) for song in songs}
    assert audit_split_leakage(songs, assignments, distinct) == []


def sha_of(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_songs_below_three_unique_charts_are_excluded_as_groups():
    entries = [make_entry(_chart([1.0, 2.0], index), "a" * 64) for index in range(2)]
    songs = group_charts_into_songs(entries)
    assert songs[0]["charts"] == []
    assert any(reason["reason"] == "insufficient_unique_difficulties" for reason in songs[0]["exclusions"])


def _chart(markers: list[float], index: int) -> dict:
    return {
        "schema": CHART_CONTRACT,
        "format": "stepmania",
        "mode": "dance-single",
        "chart_sha256": f"{index:064x}",
        "audio_reference": "x.ogg",
        "difficulty_name": f"D{index}",
        "declared_meter": 4,
        "markers_seconds": markers,
        "diagnostics": {"raw_object_count": len(markers), "normalized_marker_count": len(markers),
                        "ignored_tail_count": 0, "ignored_hazard_count": 0},
    }


# ------------------------------------------------- Round 2-B development splits


def test_development_split_allocates_within_source_strata_without_test():
    songs = []
    source_by_song = {}
    for index in range(12):
        sha = f"{index:064x}"
        source_by_song[sha] = "pack-one" if index < 6 else "pack-two"
        songs.append({"audio_sha256": sha, "charts": [], "exclusions": []})
    assignments = assign_development_splits(songs, source_by_song)
    assert set(assignments.values()) == {"train", "validation"}
    per_source = {}
    for sha, split in assignments.items():
        per_source.setdefault(source_by_song[sha], {}).setdefault(split, 0)
        per_source[source_by_song[sha]][split] += 1
    for counts in per_source.values():
        assert counts.get("validation", 0) >= 1
        assert counts.get("train", 0) >= 3


def test_development_split_requires_two_validation_songs_for_large_strata():
    songs = []
    source_by_song = {}
    for index in range(8):
        sha = f"{index:064x}"
        source_by_song[sha] = "single-pack"
        songs.append({"audio_sha256": sha, "charts": [], "exclusions": []})
    assignments = assign_development_splits(songs, source_by_song)
    validation = [sha for sha, split in assignments.items() if split == "validation"]
    assert len(validation) >= 2


def test_development_split_is_stable_when_songs_are_added():
    # Freeze semantics: existing assignments survive via frozen_assignments;
    # new songs are allocated without moving them (plan section 4.1).
    base_songs = [{"audio_sha256": f"{index:064x}", "charts": [], "exclusions": []}
                  for index in range(10)]
    sources = {f"{index:064x}": "pack" for index in range(10)}
    base = assign_development_splits(copy.deepcopy(base_songs), sources)
    larger = base_songs + [{"audio_sha256": "f" * 64, "charts": [], "exclusions": []}]
    sources["f" * 64] = "pack"
    updated = assign_development_splits(larger, sources, frozen_assignments=base)
    for sha, split in base.items():
        assert updated[sha] == split
    assert updated["f" * 64] in {"train", "validation"}


def test_frozen_development_assignment_values_are_validated():
    songs = [{"audio_sha256": "a" * 64, "charts": [], "exclusions": []}]
    with pytest.raises(ValueError):
        assign_development_splits(songs, {"a" * 64: "pack"}, {"a" * 64: "test"})


def test_consumed_artifact_conflicts_detect_exact_hashes():
    assert consumed_artifact_conflicts(cl.CONSUMED_V2_ARTIFACTS[0], None) == ["dataset.jsonl"]
    assert consumed_artifact_conflicts(None, None, cl.CONSUMED_V2_ARTIFACTS[2]) == ["selected.json"]
    assert consumed_artifact_conflicts("0" * 64, "1" * 64) == []
    assert len(cl.CONSUMED_V2_ARTIFACTS) == 4


def test_partition_leakage_audits_all_four_dimensions():
    songs = [{"audio_sha256": "a" * 64, "charts": [], "exclusions": []},
             {"audio_sha256": "b" * 64, "charts": [], "exclusions": []}]
    assignments = {"a" * 64: "train", "b" * 64: "validation"}
    fingerprints = {"a" * 64: "f" * 64, "b" * 64: "e" * 64}
    charts = {"a" * 64: {"c" * 64}, "b" * 64: {"d" * 64}}
    timelines = {"c" * 64: "t" * 64, "d" * 64: "u" * 64}
    assert audit_partition_leakage(songs, assignments, fingerprints, charts, timelines) == []

    # Distinct audio shas never conflict even inside one split.
    same_audio = {"a" * 64: "train", "b" * 64: "train"}
    assert audit_partition_leakage(songs, same_audio, fingerprints, charts, timelines) == []
    # An unassigned song is itself an audit error.
    partial = {"a" * 64: "train"}
    errors = audit_partition_leakage(songs, partial, fingerprints, charts, timelines)
    assert any("no split assignment" in error for error in errors)

    shared_fingerprint = {"a" * 64: "z" * 64, "b" * 64: "z" * 64}
    errors = audit_partition_leakage(songs, assignments, shared_fingerprint, charts, timelines)
    assert any("fingerprint" in error for error in errors)

    shared_chart = {"a" * 64: {"c" * 64}, "b" * 64: {"c" * 64}}
    errors = audit_partition_leakage(songs, assignments, fingerprints, shared_chart, timelines)
    assert any("chart_hash_across_splits" in error for error in errors)

    shared_timeline = {"c" * 64: "w" * 64, "d" * 64: "w" * 64}
    errors = audit_partition_leakage(songs, assignments, fingerprints, charts, shared_timeline)
    assert any("timeline_hash_across_splits" in error for error in errors)
