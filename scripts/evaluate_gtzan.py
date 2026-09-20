"""Model-level held-out evaluation on GTZAN, from the released spectrograms.

final0 was trained on everything except GTZAN, so GTZAN is the held-out set - the
same one the paper's Table 2 reports on. Its audio is licence-restricted and no
longer distributed, but the authors released the *spectrograms* they trained on,
as a per-dataset archive (gtzan.zip, 292.7 MB; the whole collection is 131 GB), so
the model can be scored on held-out material without the audio.

What this measures and what it does not:

- It measures the model, on a spectrogram path verified to be faithful: computing
  LogMelSpect here and calling spect2frames gives element-wise identical frames to
  Audio2Frames on the same audio (1508 frames, shape (1508, 128)).
- It does not measure the product. Decoding, onset extraction and the export path
  are not in this loop, so a number from here says nothing about them. The full
  product evaluation needs the audio, which is a separate matter of obtaining it.

Usage:
    python scripts/evaluate_gtzan.py --spectrograms build/gtzan/gtzan \
        --annotations build/bt_annotations/gtzan/annotations/beats [--limit 50]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from beatscope.public_benchmark import evaluate_events  # noqa: E402


def read_annotation(path: Path) -> tuple[list[float], list[float], int]:
    """Beats, downbeats, and how many beats carried no beat position.

    The annotations are time and beat position per line, but 276 of GTZAN's 59558
    rows carry a time only. The first version skipped those rows, which dropped
    reference beats and made every F1 computed against them incomparable. A beat
    with no position is still a beat; it is simply not a downbeat, and the count is
    returned so a report can state how much of the reference carried no position.
    """
    beats: list[float] = []
    downbeats: list[float] = []
    positionless = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        time = float(fields[0])
        beats.append(time)
        if len(fields) < 2:
            positionless += 1
        elif int(fields[1]) == 1:
            downbeats.append(time)
    return beats, downbeats, positionless


def load_spectrograms(root: Path) -> dict[str, np.ndarray]:
    """Every track's spectrogram, keyed by track id.

    The released archive is one .npz holding an array per track under
    "<track_id>/track". A directory of per-track files is also accepted, so the
    script works whichever shape the data arrives in.
    """
    if root.is_file() and root.suffix == ".npz":
        with np.load(root, allow_pickle=False) as data:
            return {key.split("/")[0]: data[key] for key in data.files}
    found: dict[str, np.ndarray] = {}
    for path in sorted(root.rglob("*")):
        if path.suffix in (".npy", ".npz", ".pt", ".spect") and path.is_file():
            found[path.stem] = np.load(path) if path.suffix != ".pt" else path  # .pt loaded by the caller
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spectrograms",
        type=Path,
        required=True,
        help="the released gtzan.npz, or a directory of per-track spectrogram files",
    )
    parser.add_argument("--annotations", type=Path, required=True, help="directory of .beats annotations")
    parser.add_argument("--model", default="final0")
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="tracks to score; 0 (the default) means all, because a silent sample of one genre is not a result",
    )
    parser.add_argument("--output", type=Path, default=Path("build/gtzan-evaluation.json"))
    args = parser.parse_args()

    if not args.spectrograms.exists():
        raise SystemExit(
            f"no spectrograms at {args.spectrograms}. Download gtzan.zip from the Zenodo record "
            "(13922116), unpack gtzan.npz from it, and point this at the .npz; it is 292.7 MB, and "
            "the audio it was made from is not required for this evaluation."
        )
    if not args.annotations.is_dir():
        raise SystemExit(
            f"no annotations at {args.annotations}. Clone CPJKU/beat_this_annotations and point this "
            "at its gtzan/annotations/beats directory."
        )

    try:
        import torch
        from beat_this.inference import Audio2Frames
        from beat_this.model.postprocessor import Postprocessor
    except ImportError as exc:
        raise SystemExit(f"Beat This is not installed here: {exc}") from None

    annotations = {path.stem: path for path in args.annotations.glob("*.beats")}
    spectrograms = load_spectrograms(args.spectrograms)
    if not annotations or not spectrograms:
        raise SystemExit(
            f"found {len(spectrograms)} spectrograms and {len(annotations)} annotations; one of the "
            "two is empty"
        )

    frames = Audio2Frames(checkpoint_path=args.model, device=args.device)
    postprocess = Postprocessor(type="minimal")
    rows = []
    unmatched = 0
    positionless_total = 0
    selected = sorted(spectrograms.items()) if args.limit <= 0 else sorted(spectrograms.items())[: args.limit]
    for track_id, spectrogram in selected:
        annotation = annotations.get(track_id)
        if annotation is None:
            unmatched += 1
            continue
        # The released spectrograms are float16 and the checkpoint is float32, so
        # the array has to be widened; convolutions reject the mismatch.
        beat_logits, downbeat_logits = frames.spect2frames(
            torch.as_tensor(spectrogram, dtype=torch.float32, device=args.device)
        )
        beats, downbeats = postprocess(beat_logits, downbeat_logits)
        reference, reference_downbeats, positionless = read_annotation(annotation)
        positionless_total += positionless
        rows.append(
            {
                "track_id": track_id,
                "annotated_beats": len(reference),
                "annotated_downbeats": len(reference_downbeats),
                "beats_without_position": positionless,
                "f_measure": evaluate_events(reference, [float(value) for value in beats])["f_measure"],
                "downbeat_f_measure": (
                    evaluate_events(reference_downbeats, [float(value) for value in downbeats])["f_measure"]
                    if len(reference_downbeats) > 1 and len(downbeats) > 1
                    else None
                ),
            }
        )

    if not rows:
        raise SystemExit("no spectrogram matched an annotation; check the file naming in both roots")

    beat_values = [row["f_measure"] for row in rows]
    downbeat_values = [row["downbeat_f_measure"] for row in rows if row["downbeat_f_measure"] is not None]
    print(f"  {len(rows)} tracks scored from {len(spectrograms)} spectrograms and {len(annotations)} annotations")
    if unmatched:
        print(f"  {unmatched} spectrograms had no annotation of the same name")
    print(f"  macro Beat F1 {statistics.fmean(beat_values):.4f} (n={len(beat_values)})")
    if downbeat_values:
        print(f"  macro Downbeat F1 {statistics.fmean(downbeat_values):.4f} (n={len(downbeat_values)})")
    print(f"  reference rows with no beat position: {positionless_total}")
    print("  this is the model on held-out material, not the product: no decoding, onsets or export in this loop")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"model": args.model, "tracks": rows}, indent=2), encoding="utf-8")
    print(f"  written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
