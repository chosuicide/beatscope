import wave

import numpy as np

from beatscope.rhythm import _grid_event, _overview, analyze_rhythm, parse_beat_this


def test_beat_this_parser_and_offset(tmp_path):
    beats = tmp_path / 'x.beats'
    beats.write_text('# comment\n0.00\t1\n0.50\t2\n1.00\t3\n1.50\t4\n', encoding='utf-8')
    parsed = parse_beat_this(beats)
    assert parsed[0]['time'] == 0.0
    assert parsed[0]['beat'] == 1
    assert parsed[0]['sequence_gap'] is False
    assert parsed[0]['downbeat'] is True
    assert parsed[0]['bar'] == 1

    event = _grid_event(0.13, 0.0, 120, 16, 0.8, {'all': .8, 'low': .2, 'mid': .5, 'high': .1})
    assert event['nearest_step'] == 1
    assert abs(event['offset_ms'] - 5) < 0.01
    assert event['bar'] == 1 and event['step_in_bar'] == 2
    event32 = _grid_event(0.13, 0.0, 120, 32, 0.8, {'all': .8, 'low': .2, 'mid': .5, 'high': .1})
    assert event32['nearest_step'] == 2
    assert abs(event32['quantized_time'] - event['quantized_time']) < 0.001


def test_beat_phase_bars_start_at_downbeat(tmp_path):
    beats = tmp_path / 'phase.beats'
    beats.write_text('2.28\t2\n2.76\t3\n3.22\t4\n3.68\t1\n4.14\t2\n4.62\t3\n5.08\t4\n5.52\t1\n', encoding='utf-8')
    result = parse_beat_this(beats)
    bars = [beat['bar'] for beat in result]
    assert bars == [0, 0, 0, 1, 1, 1, 1, 2]


def test_overview_labels_repeat_and_break():
    onsets = [{'bar': bar, 'step_in_bar': step, 'strength': .5} for bar in (1, 2) for step in (1, 5, 9, 13)] + [{'bar': 4, 'step_in_bar': 15, 'strength': .9}]
    result = _overview(onsets, 4, 16)
    assert result[1]['label'] == 'repeat'
    assert result[2]['label'] == 'break'
    assert result[3]['label'] in ('fill', 'change')
    assert result[0]['group'] == 'A' and result[1]['group'] == 'A'


def test_rhythm_schema_from_short_wav(tmp_path):
    rate = 8000
    seconds = 2
    signal = np.zeros(rate * seconds, dtype=np.float32)
    for start in (0, 4000, 8000, 12000):
        signal[start:start + 60] = np.hanning(60)
    audio = tmp_path / 'drums.wav'
    with wave.open(str(audio), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes((signal * 32767).astype('<i2').tobytes())
    beat_file = tmp_path / 'beats.beats'
    beat_file.write_text('0.0\t2\n0.5\t3\n1.0\t4\n1.5\t1\n2.0\t2', encoding='utf-8')
    result = analyze_rhythm(audio, audio, beat_file)
    assert result['schema_version'] == '3.0'
    assert result['grid']['default_subdivision'] == 16
    assert [beat['bar'] for beat in result['beats']] == [0, 0, 0, 1, 1]
    if result['onsets']:
        assert set(result['onsets'][0]['bands']) == {'all', 'low', 'mid', 'high'}
