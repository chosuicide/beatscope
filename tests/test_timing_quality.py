from beatscope.timing_quality import timing_quality


def test_low_support_alias_is_flagged_without_rewriting_facts():
    rhythm = {"tempo": {"global_bpm": 120, "segments": [{"start": 8, "end": 12, "bpm": 180, "score": .1}]}}
    quality = timing_quality(rhythm)
    assert quality["status"] == "needs-crosscheck"
    assert quality["suspect_tempo_regions"][0]["subdivision_alias_candidate"] == 1.5
    assert rhythm["tempo"]["segments"][0]["bpm"] == 180


def test_supported_real_tempo_change_is_not_rejected():
    quality = timing_quality({"tempo": {"global_bpm": 120, "segments": [{"start": 8, "end": 12, "bpm": 180, "score": .8}]}})
    assert quality["suspect_tempo_regions"] == []
    assert quality["status"] == "not-perceptually-verified"


def test_missing_support_does_not_invent_confidence():
    quality = timing_quality({"tempo": {"global_bpm": 120, "segments": [{"bpm": 240}]}, "onsets": [{"strength": 1}, {"strength": .5}]})
    assert quality["suspect_tempo_regions"] == []
    assert quality["onset_strength_ceiling"] == {"count": 1, "total": 2}


def test_nonfinite_or_zero_tempo_does_not_break_export():
    quality = timing_quality({"tempo": {"global_bpm": 0, "segments": [{"bpm": float('nan'), "score": .1}]}})
    assert quality["suspect_tempo_regions"] == []
