from __future__ import annotations

import hashlib
import json
from pathlib import Path

from beatscope import event_ranker as er
from scripts.train_event_ranker_v5 import (
    cross_source_evaluate,
    eligible,
    fold_partitions,
    select_candidate,
)
from tests.test_event_ranker import make_event


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "event_ranking_v5"


def _song(source: str, offset: float) -> dict:
    events = {}
    for onset_id in range(1, 13):
        preferred = onset_id <= 6
        strength = 0.7 + offset if preferred else 0.3 - offset
        events[onset_id] = {
            "onset_id": onset_id, "strength": strength,
            "support_rate": 1.0 if preferred else 0.0,
            "evidence": make_event(onset_id, 0.8 if preferred else 0.2,
                                   strength=strength),
            "group": None,
        }
    pairs = [{"preferred_onset_id": preferred, "other_onset_id": other}
             for preferred in range(1, 7) for other in range(7, 13)]
    return {
        "events": events, "pairs": pairs,
        "meta": {"source_id": source, "onset_count": 12, "duration": 6.0,
                 "sparsest_matched_count": 6,
                 "sparsest_supported_onset_ids": list(range(1, 7))},
    }


def _songs() -> dict[str, dict]:
    return {f"song-{index}": _song(f"source-{index}", index * 0.01)
            for index in range(4)}


def test_source_folds_are_disjoint_and_cover_each_song_once():
    songs = _songs()
    validation_counts = {sha: 0 for sha in songs}
    for _source, train_ids, validation_ids in fold_partitions(songs):
        assert not train_ids & validation_ids
        assert train_ids | validation_ids == set(songs)
        for sha in validation_ids:
            validation_counts[sha] += 1
    assert set(validation_counts.values()) == {1}


def test_cross_source_evaluation_scores_every_held_source():
    report = cross_source_evaluate(
        _songs(), "full", (2, 1, 0.05, 2, 1.0, 0.5))
    assert report["validated_song_count"] == 4
    assert len(report["folds"]) == 4
    assert set(report["source_deltas"]) == {f"source-{index}" for index in range(4)}


def _candidate(name: str, *, top_precision: float, minimum_source: float = 0.01,
               non_metric: float = 0.01) -> dict:
    return {
        "name": name, "feature_view": "full", "trees": 24,
        "deltas_vs_strength": {"pairwise_accuracy": 0.01, "ndcg_at_10": 0.01,
                                "recall_at_k": 0.01,
                                "top_support_precision_at_k": top_precision},
        "bootstrap_pairwise": {"lower_95": 0.001},
        "dense_tertile_delta": 0.01,
        "source_deltas": {"a": minimum_source, "b": 0.02},
        "non_metric_pairwise_delta": non_metric,
    }


def test_selection_prioritizes_top_event_utility_with_hard_safety():
    lower = _candidate("lower", top_precision=0.01)
    higher = _candidate("higher", top_precision=0.02)
    assert eligible(higher)
    assert select_candidate([lower, higher]) is higher

    unsafe = _candidate("unsafe", top_precision=0.9, minimum_source=-0.005001)
    assert not eligible(unsafe)
    assert select_candidate([lower, unsafe]) is lower


def test_non_metric_and_bootstrap_are_blocking_requirements():
    no_non_metric = _candidate("no-non-metric", top_precision=0.02, non_metric=0.0)
    no_significance = _candidate("no-significance", top_precision=0.02)
    no_significance["bootstrap_pairwise"]["lower_95"] = 0.0
    assert not eligible(no_non_metric)
    assert not eligible(no_significance)


def test_frozen_cross_source_candidate_matches_its_lock():
    lock = json.loads((FIXTURES / "candidate-lock.json").read_text())
    files = {
        "selection_report_sha256": "selection-report.json",
        "candidate_sha256": "selected-candidate.json",
        "non_metric_candidate_sha256": "selected-non-metric-candidate.json",
    }
    for field, filename in files.items():
        assert hashlib.sha256((FIXTURES / filename).read_bytes()).hexdigest() == lock[field]
    full = json.loads((FIXTURES / "selected-candidate.json").read_text())
    non_metric = json.loads((FIXTURES / "selected-non-metric-candidate.json").read_text())
    report = json.loads((FIXTURES / "selection-report.json").read_text())
    assert er.validate_boost_model_json(full) == []
    assert er.validate_boost_model_json(non_metric) == []
    assert full["promotion"]["status"] == non_metric["promotion"]["status"] == "pending"
    assert full["training"]["dataset_sha256"] == lock["development_dataset_sha256"]
    assert full["training"]["manifest_sha256"] == lock["development_manifest_sha256"]
    assert report["selected"] == lock["selected"]


def test_frozen_report_proves_every_source_was_held_out():
    report = json.loads((FIXTURES / "selection-report.json").read_text())
    selected = next(row for row in report["candidates"] if row["name"] == report["selected"])
    assert selected["validated_song_count"] == report["song_count"] == 55
    assert {fold["held_source"] for fold in selected["folds"]} == set(report["source_ids"])
    assert all(delta > 0.0 for delta in selected["source_deltas"].values())
    assert selected["bootstrap_pairwise"]["lower_95"] > 0.0
    assert selected["deltas_vs_strength"]["top_support_precision_at_k"] > 0.0
