import pytest
import numpy as np
from beatscope.beatgrid import (
    parse_beat_this,
    estimate_bpm,
    quantize_to_beat_grid,
    BeatGridAnalyzer,
)


def test_parse_beat_this_partial_bars(tmp_path):
    f = tmp_path / "test.beats"
    f.write_text("0.20\t2\n0.60\t3\n1.00\t4\n1.40\t1\n1.80\t2\n2.20\t3\n2.60\t4\n3.00\t1\n", encoding="utf-8")
    beats = parse_beat_this(f)
    assert len(beats) == 8
    # bar 0 for pre-downbeat
    assert [b["bar"] for b in beats] == [0, 0, 0, 1, 1, 1, 1, 2]
    assert [b["downbeat"] for b in beats] == [False, False, False, True, False, False, False, True]


def test_parse_beat_this_sequence_gap():
    text = "0.0\t1\n0.5\t2\n1.0\t4\n1.5\t1\n"  # beat 2 -> 4 is a gap
    beats = parse_beat_this(text)
    assert beats[0]["sequence_gap"] is False
    assert beats[1]["sequence_gap"] is False
    assert beats[2]["sequence_gap"] is True
    assert beats[3]["sequence_gap"] is False


def test_estimate_bpm_with_outlier():
    # 120 bpm = 0.5s interval. One interval is an outlier (0.9s)
    beat_times = [0.0, 0.5, 1.0, 1.5, 2.4, 2.9, 3.4, 3.9]
    bpm, conf, var = estimate_bpm(beat_times)
    assert abs(bpm - 120.0) < 1.0


def test_quantize_to_beat_grid_interpolation():
    beats = [
        {"time": 1.0, "beat": 1, "bar": 1, "downbeat": True, "sequence_gap": False},
        {"time": 1.5, "beat": 2, "bar": 1, "downbeat": False, "sequence_gap": False},
        {"time": 2.0, "beat": 3, "bar": 1, "downbeat": False, "sequence_gap": False},
        {"time": 2.5, "beat": 4, "bar": 1, "downbeat": False, "sequence_gap": False},
    ]
    # At t = 1.125 (exact 1/16 step 2 in bar 1)
    q = quantize_to_beat_grid(1.125, beats, subdivision=16)
    assert abs(q["quantized_time"] - 1.125) < 0.001
    assert abs(q["offset_ms"]) < 0.1
    assert q["bar"] == 1
    assert q["beat"] == 1
    assert q["step_in_bar"] == 2


def test_quantize_variable_tempo():
    # Beat 1 is 0.5s long, Beat 2 is 0.4s long
    beats = [
        {"time": 1.0, "beat": 1, "bar": 1, "downbeat": True, "sequence_gap": False},
        {"time": 1.5, "beat": 2, "bar": 1, "downbeat": False, "sequence_gap": False},
        {"time": 1.9, "beat": 3, "bar": 1, "downbeat": False, "sequence_gap": False},
    ]
    # Midpoint of beat 2 should be at 1.5 + 0.2 = 1.7
    q = quantize_to_beat_grid(1.705, beats, subdivision=16)
    assert abs(q["quantized_time"] - 1.7) < 0.001
    assert abs(q["offset_ms"] - 5.0) < 0.1
    assert q["bar"] == 1
    assert q["beat"] == 2
    assert q["step_in_bar"] == 7  # (2-1)*4 + 2 + 1 = 7 (step 3 of beat 2)


def test_analyzer_integration(tmp_path):
    f = tmp_path / "test.beats"
    f.write_text("0.0\t1\n0.5\t2\n1.0\t3\n1.5\t4\n2.0\t1\n", encoding="utf-8")
    analyzer = BeatGridAnalyzer()
    res = analyzer.analyze_beats(f, duration=2.5, subdivision=16)
    assert res.bpm == 120.0
    assert res.origin == 0.0
    assert res.bars >= 1
