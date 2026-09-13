"""Build the licensed chart-consensus ranking dataset from a local corpus.

The corpus registry is an ignored operator file (plan section 3.2):

    {
      "schema": "beatscope-ranking-corpus-local-1",
      "sources": [
        {"id": "...", "root": "<local dir>", "format": "stepmania" | "osu",
         "license": "operator-owned", "permission_note": "...",
         "partition": "auto" | "development" | "test"}
      ]
    }

The script never searches outside the declared roots, excludes one malformed
chart without crashing the build, and writes every artifact under the
``--output`` directory (ignored ``build/`` by default). Committed-quality
manifest bytes contain hashes, counts, exclusions, and licenses - never local
paths, titles, or audio.

Exit codes: 0 on success, 1 on leakage-audit or corpus failure, 2 on usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from beatscope import chart_labels as cl  # noqa: E402
from beatscope.chart_labels import ChartLabelError  # noqa: E402

CORPUS_SCHEMA = "beatscope-ranking-corpus-local-1"
MANIFEST_SCHEMA = "beatscope-response-ranking-manifest-1"
SUPPORTED_FORMATS = ("stepmania", "osu")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iter_chart_files(root: Path, fmt: str):
    suffixes = (".sm", ".ssc") if fmt == "stepmania" else (".osu",)
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in suffixes:
            yield path


def resolve_audio(chart: dict, chart_path: Path, source_root: Path) -> Path | None:
    reference = chart.get("audio_reference", "").strip().strip('"')
    if not reference:
        return None
    candidate = (chart_path.parent / reference).resolve()
    if not candidate.is_file():
        return None
    if source_root.resolve() not in candidate.parents:
        return None  # audio must live inside the declared source root
    return candidate


def analyze_audio(audio_path: Path, cache_dir: Path) -> dict:
    """Analyze one audio file, cached by content hash under ``cache_dir``."""
    from beatscope.pipeline import analyze_track

    audio_sha = sha256_bytes(audio_path.read_bytes())
    cache_path = cache_dir / f"{audio_sha}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("source", {}).get("sha256") == audio_sha:
            return cached, audio_sha
    project = analyze_track(audio_path)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(cl.canonical_json_text(project), encoding="utf-8", newline="\n")
    return project, audio_sha


def load_or_build_evidence(project: dict, evidence_dir: Path) -> dict:
    from beatscope.event_evidence import build_event_evidence

    evidence_dir.mkdir(parents=True, exist_ok=True)
    cache_path = evidence_dir / f"{project['project_id']}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    bundle = build_event_evidence(project)
    cache_path.write_text(cl.canonical_json_text(bundle), encoding="utf-8", newline="\n")
    return bundle


def _jsonl_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def segment_map_for(project: dict, onset_times: dict[int, float]) -> dict[int, int | None]:
    segments = project.get("patterns", {}).get("segments") or []
    mapping: dict[int, int | None] = {}
    for onset_id, time_value in onset_times.items():
        index = None
        for position, segment in enumerate(segments):
            start = float(segment.get("start_time", 0.0))
            end = float(segment.get("end_time", 0.0))
            if start <= time_value < end or (position == len(segments) - 1 and abs(end - time_value) < 1e-9):
                index = position
                break
        mapping[onset_id] = index
    return mapping


def build_dataset(corpus_path: Path, output_dir: Path) -> tuple[dict, str]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if corpus.get("schema") != CORPUS_SCHEMA:
        raise ChartLabelError("malformed_chart", f"corpus schema must be {CORPUS_SCHEMA!r}")

    previous_manifest_path = output_dir / "training-manifest.json"
    frozen_assignments: dict[str, str] = {}
    if previous_manifest_path.is_file():
        previous = json.loads(previous_manifest_path.read_text(encoding="utf-8"))
        if previous.get("schema") == MANIFEST_SCHEMA:
            frozen_assignments = {
                song["audio_sha256"]: song["split"] for song in previous.get("songs", [])
            }

    parsed_dir = output_dir / "parsed"
    projects_dir = output_dir / "projects"
    evidence_dir = output_dir / "evidence"
    for directory in (parsed_dir, projects_dir, evidence_dir):
        directory.mkdir(parents=True, exist_ok=True)

    chart_entries: list[dict] = []
    source_summaries: list[dict] = []
    exclusions: list[dict] = []
    audio_sha_by_chart: dict[str, str] = {}
    analysis_cache: dict[str, tuple[dict, dict]] = {}  # audio sha -> (project, evidence)
    partitions_by_song: dict[str, set[str]] = {}
    partitioned_corpus = any(
        str(source.get("partition", "auto")).strip().lower() != "auto"
        for source in corpus.get("sources", [])
    )

    for source in corpus.get("sources", []):
        source_id = str(source.get("id", "")).strip()
        fmt = str(source.get("format", "")).strip().lower()
        license_class = str(source.get("license", "")).strip()
        permission_note = str(source.get("permission_note", "")).strip()
        partition = str(source.get("partition", "auto")).strip().lower()
        root = Path(str(source.get("root", "")))
        if not source_id or fmt not in SUPPORTED_FORMATS or not root.is_dir() \
                or partition not in {"auto", "development", "test"}:
            exclusions.append({"source_id": source_id, "reason": cl.CODE_MALFORMED_CHART,
                               "detail": "source id/format/root invalid"})
            continue
        if not license_class or license_class.lower() in {"unknown", "unaudited"} \
                or not permission_note:
            exclusions.append({"source_id": source_id, "reason": cl.CODE_UNKNOWN_LICENSE,
                               "detail": "license and permission_note must be recorded before training"})
            source_summaries.append({
                "id": source_id, "format": fmt, "license": license_class or "unknown",
                "chart_file_count": 0, "partition": partition,
            })
            continue
        chart_count = 0
        for chart_path in iter_chart_files(root, fmt):
            try:
                charts = cl.parse_chart_file(chart_path)
            except ChartLabelError as error:
                exclusions.append({
                    "source_id": source_id,
                    "chart_sha256": "",
                    "reason": error.code,
                    "detail": str(error),
                })
                continue
            chart_count += len(charts)
            for chart in charts:
                audio_path = resolve_audio(chart, chart_path, root)
                if audio_path is None:
                    exclusions.append({
                        "source_id": source_id,
                        "chart_sha256": chart["chart_sha256"],
                        "reason": cl.CODE_MISSING_AUDIO,
                        "detail": "audio file missing or outside the source root",
                    })
                    continue
                audio_bytes = audio_path.read_bytes()
                audio_sha = sha256_bytes(audio_bytes)
                if audio_sha in analysis_cache:
                    project, _ = analysis_cache[audio_sha]
                else:
                    project, audio_sha = analyze_audio(audio_path, projects_dir)
                    analysis_cache[audio_sha] = (project, load_or_build_evidence(project, evidence_dir))
                audio_sha_by_chart[chart["chart_sha256"]] = audio_sha
                partitions_by_song.setdefault(audio_sha, set()).add(partition)
                chart_entries.append({
                    "source_id": source_id,
                    "format": fmt,
                    "license": license_class,
                    "chart": chart,
                    "audio_sha256": audio_sha,
                    "audio_duration": float(project["source"]["duration"]),
                    "partition": partition,
                })
        source_summaries.append({
            "id": source_id,
            "format": fmt,
            "license": license_class,
            "chart_file_count": chart_count,
            "partition": partition,
        })

    # Provenance flows through chart_entries; song grouping only needs the
    # audio identity.
    entries_for_grouping = [
        {"chart": entry["chart"], "audio_sha256": entry["audio_sha256"],
         "audio_duration": entry["audio_duration"]}
        for entry in chart_entries
    ]
    song_groups = cl.group_charts_into_songs(entries_for_grouping)

    licenses_by_song: dict[str, set[str]] = {}
    formats_by_song: dict[str, set[str]] = {}
    source_ids_by_song: dict[str, set[str]] = {}
    for entry in chart_entries:
        sha = entry["audio_sha256"]
        licenses_by_song.setdefault(sha, set()).add(entry["license"])
        formats_by_song.setdefault(sha, set()).add(entry["format"])
        source_ids_by_song.setdefault(sha, set()).add(entry["source_id"])
    unknown_license_songs = {
        sha for sha, license_classes in licenses_by_song.items()
        if any(not item or item.lower() in {"unknown", "unaudited"} for item in license_classes)
    }

    retained_groups = []
    for song in song_groups:
        if not song["charts"]:
            continue
        if song["audio_sha256"] in unknown_license_songs:
            song["exclusions"].append({"chart_sha256": "", "reason": cl.CODE_UNKNOWN_LICENSE})
            continue
        partitions = partitions_by_song.get(song["audio_sha256"], {"auto"})
        if len(partitions) != 1 or (partitioned_corpus and "auto" in partitions):
            song["exclusions"].append({
                "chart_sha256": "", "reason": cl.CODE_DUPLICATE_AUDIO_ACROSS_SPLITS,
            })
            continue
        retained_groups.append(song)

    # Alignment verdicts may drop further charts; re-apply the song gate.
    clusters_by_song: dict[str, list[dict]] = {}
    final_groups: list[dict] = []
    chart_records: list[dict] = []
    for song in retained_groups:
        project, evidence = analysis_cache[song["audio_sha256"]]
        onset_times_list = [float(onset["time"]) for onset in project["onsets"]]
        onset_ids = [int(onset["id"]) for onset in project["onsets"]]
        clusters = cl.coincident_onset_clusters(onset_times_list, onset_ids)
        clusters_by_song[song["audio_sha256"]] = clusters
        calibration = (
            cl.estimate_song_alignment_offset(
                [entry["chart"] for entry in song["charts"]], clusters)
            if partitioned_corpus
            else {"applied": False, "offset_seconds": 0.0,
                  "eligible_chart_count": 0, "mad_seconds": None}
        )
        kept_charts: list[dict] = []
        for entry in song["charts"]:
            chart = entry["chart"]
            aligned_chart = cl.calibrated_chart(chart, calibration["offset_seconds"])
            alignment = cl.align_chart_to_clusters(aligned_chart["markers_seconds"], clusters)
            verdict = cl.chart_alignment_verdict(
                aligned_chart, alignment, float(project["source"]["duration"]),
                max_p95_residual_seconds=(cl.V2_MAX_P95_RESIDUAL_SECONDS
                                          if partitioned_corpus
                                          else cl.MAX_P95_RESIDUAL_SECONDS),
            )
            chart_records.append({
                "chart_sha256": chart["chart_sha256"],
                "audio_sha256": song["audio_sha256"],
                "format": chart["format"],
                "difficulty_name": chart["difficulty_name"],
                "declared_meter": chart["declared_meter"],
                "marker_count": len(chart["markers_seconds"]),
                "matched_marker_count": alignment["matched_marker_count"],
                "unmatched_marker_count": alignment["unmatched_marker_count"],
                "matched_cluster_count": alignment["matched_cluster_count"],
                "covered_onset_count": len(alignment["covered_onset_ids"]),
                "median_residual": alignment["median_residual"],
                "p95_residual": alignment["p95_residual"],
                "max_residual": alignment["max_residual"],
                "ambiguous_component_count": alignment["ambiguous_component_count"],
                "calibration_applied": calibration["applied"],
                "calibration_offset_seconds": calibration["offset_seconds"],
                "calibration_mad_seconds": calibration["mad_seconds"],
                "exclusion_reason": verdict,
            })
            if verdict is None:
                kept_charts.append({**entry, "chart": aligned_chart})
            else:
                song["exclusions"].append({"chart_sha256": chart["chart_sha256"], "reason": verdict})
        if len(kept_charts) < cl.MIN_DIFFICULTIES_PER_SONG:
            song["exclusions"].append({
                "chart_sha256": "",
                "reason": cl.CODE_INSUFFICIENT_UNIQUE_DIFFICULTIES,
            })
            continue
        filtered_song = {**song, "charts": kept_charts}
        final_groups.append(filtered_song)

    if partitioned_corpus:
        holdout = {
            song["audio_sha256"] for song in final_groups
            if partitions_by_song[song["audio_sha256"]] == {"test"}
        }
        assignments = cl.assign_splits_with_holdout(final_groups, holdout)
    else:
        assignments = cl.assign_splits(final_groups, frozen_assignments)
    fingerprints = {
        song["audio_sha256"]: cl.audio_fingerprint(
            float(analysis_cache[song["audio_sha256"]][0]["source"]["duration"]),
            [float(onset["time"]) for onset in analysis_cache[song["audio_sha256"]][0]["onsets"]],
        )
        for song in final_groups
    }
    leakage_errors = cl.audit_split_leakage(final_groups, assignments, fingerprints)
    if leakage_errors:
        for error in leakage_errors:
            print(error, file=sys.stderr)
        raise SystemExit(1)

    dataset_lines: list[str] = []
    label_records: dict[str, list[dict]] = {}
    pair_records: dict[str, list[dict]] = {}
    for song in final_groups:
        sha = song["audio_sha256"]
        project, evidence = analysis_cache[sha]
        clusters = clusters_by_song[sha]
        alignments = {
            entry["chart"]["chart_sha256"]: cl.align_chart_to_clusters(
                entry["chart"]["markers_seconds"], clusters)
            for entry in song["charts"]
        }
        sparsest_chart = song["charts"][0]  # grouping already sorts unique charts by density
        sparsest_alignment = alignments[sparsest_chart["chart"]["chart_sha256"]]
        sparsest_supported_onset_ids = sorted(set(sparsest_alignment["covered_onset_ids"]))
        sparsest_matched_count = len(sparsest_supported_onset_ids)
        labels = cl.build_weak_labels(song, alignments, clusters)
        label_records[sha] = labels
        onset_times = {int(onset["id"]): float(onset["time"]) for onset in project["onsets"]}
        strengths = {int(onset["id"]): float(onset["strength"]) for onset in project["onsets"]}
        segment_map = segment_map_for(project, onset_times)
        pairs = cl.build_preference_pairs(labels, onset_times, segment_map)
        pair_records[sha] = pairs
        split = assignments[sha]
        dataset_lines.append(_jsonl_line({
            "kind": "song",
            "dataset_schema": cl.DATASET_SCHEMA,
            "audio_sha256": sha,
            "split": split,
            "format": next(iter(formats_by_song[sha])) if len(formats_by_song[sha]) == 1 else "mixed",
            "source_id": (next(iter(source_ids_by_song[sha]))
                          if len(source_ids_by_song[sha]) == 1 else "mixed"),
            "source_ids": sorted(source_ids_by_song[sha]),
            "source_partition": next(iter(partitions_by_song[sha])),
            "onset_count": len(project["onsets"]),
            "duration": float(project["source"]["duration"]),
            "beat_context_available": bool(evidence["diagnostics"]["beat_context_available"]),
            "structure_context_available": bool(evidence["diagnostics"]["structure_context_available"]),
            "sparsest_matched_count": sparsest_matched_count,
            "sparsest_supported_onset_ids": sparsest_supported_onset_ids,
            "evidence_schema": evidence["schema"],
            "eligible_chart_count": len(song["charts"]),
        }))
        label_by_id = {record["onset_id"]: record for record in labels}
        evidence_by_id = {record["onset_id"]: record for record in evidence["events"]}
        group_by_id = {group["id"]: group for group in evidence.get("groups", [])}
        for onset in project["onsets"]:
            onset_id = int(onset["id"])
            record = label_by_id.get(onset_id)
            event_line = {
                "kind": "event",
                "audio_sha256": sha,
                "split": split,
                "onset_id": onset_id,
                "strength": strengths[onset_id],
                "support_rate": record["support_rate"] if record else 0.0,
                "chart_support_count": record["chart_support_count"] if record else 0,
                "eligible_chart_count": record["eligible_chart_count"] if record
                else len(song["charts"]),
                "evidence": evidence_by_id[onset_id],
                "group": group_by_id.get(evidence_by_id[onset_id].get("group_id")),
            }
            dataset_lines.append(_jsonl_line(event_line))
        for pair in pairs:
            dataset_lines.append(_jsonl_line({
                "kind": "pair",
                "audio_sha256": sha,
                "split": split,
                **pair,
            }))

    dataset_text = "\n".join(dataset_lines) + ("\n" if dataset_lines else "")
    dataset_path = output_dir / "dataset.jsonl"
    dataset_path.write_text(dataset_text, encoding="utf-8", newline="\n")

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "dataset_schema": cl.DATASET_SCHEMA,
        "corpus_schema": CORPUS_SCHEMA,
        "chart_contract": cl.CHART_CONTRACT,
        "dataset_sha256": sha256_bytes(dataset_text.encode("utf-8")),
        "sources": sorted(source_summaries, key=lambda item: item["id"]),
        "songs": [
            {
                "audio_sha256": song["audio_sha256"],
                "split": assignments[song["audio_sha256"]],
                "format": (next(iter(formats_by_song[song["audio_sha256"]]))
                           if len(formats_by_song[song["audio_sha256"]]) == 1 else "mixed"),
                "licenses": sorted(licenses_by_song[song["audio_sha256"]]),
                "license": "+".join(sorted(licenses_by_song[song["audio_sha256"]])),
                "source_ids": sorted(source_ids_by_song[song["audio_sha256"]]),
                "source_partition": next(iter(partitions_by_song[song["audio_sha256"]])),
                "fingerprint": fingerprints[song["audio_sha256"]],
                "retained_chart_count": len(song["charts"]),
                "chart_sha256s": sorted(
                    entry["chart"]["chart_sha256"] for entry in song["charts"]),
                "onset_count": len(analysis_cache[song["audio_sha256"]][0]["onsets"]),
                "supported_event_count": sum(
                    record["chart_support_count"] > 0
                    for record in label_records.get(song["audio_sha256"], [])),
                "preference_pair_count": len(pair_records.get(song["audio_sha256"], [])),
            }
            for song in sorted(final_groups, key=lambda item: item["audio_sha256"])
        ],
        "charts": sorted(chart_records, key=lambda item: item["chart_sha256"]),
        "exclusions": sorted(
            (exclusion for song in song_groups for exclusion in song["exclusions"]),
            key=lambda item: (item["reason"], item["chart_sha256"]),
        ) + sorted(exclusions, key=lambda item: (item["reason"], item.get("source_id", ""))),
        "totals": {
            "song_count": len(final_groups),
            "chart_count": len(chart_records),
            "event_row_count": sum(
                len(analysis_cache[song["audio_sha256"]][0]["onsets"]) for song in final_groups),
            "event_label_count": sum(len(records) for records in label_records.values()),
            "preference_pair_count": sum(len(records) for records in pair_records.values()),
            "exclusion_count": len(
                [exclusion for song in song_groups for exclusion in song["exclusions"]]) + len(exclusions),
        },
    }
    manifest_path = output_dir / "training-manifest.json"
    manifest_path.write_text(cl.canonical_json_text(manifest), encoding="utf-8", newline="\n")
    return manifest, cl.sha256_text(cl.canonical_json_text(manifest))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True,
                        help="ignored operator corpus registry JSON (plan section 3.2)")
    parser.add_argument("--output", type=Path, default=Path("build/event-ranking"),
                        help="ignored output directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be built without writing artifacts")
    args = parser.parse_args(argv)
    if not args.corpus.is_file():
        parser.error(f"corpus registry not found: {args.corpus}")

    if args.dry_run:
        corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
        print(json.dumps({
            "corpus_schema": corpus.get("schema"),
            "sources": [
                {"id": source.get("id"), "format": source.get("format"),
                 "license_recorded": bool(source.get("license"))}
                for source in corpus.get("sources", [])
            ],
        }, indent=2))
        return 0

    try:
        manifest, manifest_sha = build_dataset(args.corpus, args.output)
    except SystemExit as exit_error:
        return int(exit_error.code or 1)
    print(json.dumps({
        "dataset": str(args.output / "dataset.jsonl"),
        "totals": manifest["totals"],
        "manifest_sha256": manifest_sha,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
