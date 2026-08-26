"""Song structure analysis, bar rhythm vectorization, and pattern grouping."""
from __future__ import annotations

from typing import Any
import numpy as np

from .beatgrid import quantize_to_beat_grid


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1D float vectors."""
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0 if np.allclose(a, b) else 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def build_bar_vector(onsets_in_bar: list[dict[str, Any]], subdivision: int = 16) -> np.ndarray:
    """Build a 66-dimensional bar feature vector (16*4 band steps + mean_energy + onset_count)."""
    bands = ("all", "low", "mid", "high")
    grid_matrix = np.zeros((4, subdivision), dtype=np.float32)

    for onset in onsets_in_bar:
        step = onset.get("step_in_bar", 1) - 1
        if 0 <= step < subdivision:
            b_dict = onset.get("bands", {})
            for b_idx, b_name in enumerate(bands):
                val = float(b_dict.get(b_name, onset.get("strength", 0.0)))
                grid_matrix[b_idx, step] = max(grid_matrix[b_idx, step], val)

    flattened = grid_matrix.flatten()  # 64 elements
    mean_energy = float(grid_matrix[0].mean())
    onset_count_norm = float(min(1.0, len(onsets_in_bar) / 16.0))

    vec = np.concatenate([flattened, [mean_energy, onset_count_norm]]).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm > 1e-6:
        vec /= norm
    return vec


def analyze_song_structure(
    onsets: list[dict[str, Any]],
    beats: list[dict[str, Any]],
    bars: int,
    subdivision: int = 16,
) -> list[dict[str, Any]]:
    """Analyze bar-by-bar repetition, fills, breaks, and section similarity groups."""
    # Organize onsets by bar using beatgrid quantization
    bar_onsets: dict[int, list[dict[str, Any]]] = {b: [] for b in range(1, bars + 1)}
    for onset in onsets:
        q = quantize_to_beat_grid(float(onset["raw_time"]), beats, subdivision=subdivision)
        b = q["bar"]
        if 1 <= b <= bars:
            bar_onsets[b].append({**onset, **q})

    bar_vectors: list[np.ndarray] = []
    mean_energies: list[float] = []

    for b in range(1, bars + 1):
        ons = bar_onsets[b]
        vec = build_bar_vector(ons, subdivision)
        bar_vectors.append(vec)
        all_strengths = [float(o.get("strength", 0.0)) for o in ons]
        mean_energies.append(float(np.mean(all_strengths)) if all_strengths else 0.0)

    # Threshold for breaks: low energy and few onsets
    song_energy_p20 = float(np.percentile(mean_energies, 20)) if mean_energies else 0.05
    break_energy_thresh = max(0.04, min(0.12, song_energy_p20))

    centroids: list[np.ndarray] = []
    labels: list[dict[str, Any]] = []

    for idx, vec in enumerate(bar_vectors):
        bar_num = idx + 1
        ons = bar_onsets[bar_num]
        mean_e = mean_energies[idx]
        prev_sim = cosine_similarity(vec, bar_vectors[idx - 1]) if idx > 0 else 0.0

        is_break = (mean_e < break_energy_thresh and len(ons) <= 1)

        if is_break:
            group = "BREAK"
            label = "break"
        else:
            # Check for fill: last beat (last 4 steps) significantly higher than previous 3 beats
            parts_per_beat = subdivision // 4
            last_beat_steps = range(3 * parts_per_beat, 4 * parts_per_beat)
            first_beats_steps = range(0, 3 * parts_per_beat)
            
            last_beat_energy = max([float(o.get("strength", 0.0)) for o in ons if o.get("step_in_bar", 1) - 1 in last_beat_steps] or [0.0])
            first_beats_energy = np.mean([float(o.get("strength", 0.0)) for o in ons if o.get("step_in_bar", 1) - 1 in first_beats_steps] or [0.0])
            
            is_fill = (last_beat_energy > max(0.20, float(first_beats_energy) * 1.6))

            # Match or create centroid
            sims = [cosine_similarity(vec, c) for c in centroids]
            if sims and max(sims) >= 0.86:
                best_idx = int(np.argmax(sims))
                group = chr(65 + best_idx)
                # Update centroid with rolling blend
                centroids[best_idx] = 0.8 * centroids[best_idx] + 0.2 * vec
                label = "fill" if is_fill else "repeat" if prev_sim >= 0.82 else "change"
            else:
                group = chr(65 + len(centroids))
                centroids.append(vec.copy())
                label = "fill" if is_fill else "change"

        labels.append({
            "bar": bar_num,
            "label": label,
            "group": group,
            "mean_strength": round(mean_e, 4),
            "similarity_previous": round(prev_sim, 4),
            "vector": [round(float(x), 4) for x in vec[:16]],  # store first 16 steps summary for compact json
        })

    return labels
