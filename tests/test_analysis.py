import wave
import numpy as np
from beatscope.analysis import analyze_audio

def make_wav(path, seconds=2.0, rate=8000, tone=True):
    t = np.arange(int(rate * seconds)) / rate; signal = 0.08 * np.sin(2 * np.pi * 55 * t) if tone else np.zeros_like(t)
    for onset in np.arange(0, seconds, 0.5) if tone else []:
        start = int(onset * rate); signal[start:start + 40] += np.hanning(40) * 0.9
    pcm = np.clip(signal * 32767, -32768, 32767).astype('<i2')
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate); f.writeframes(pcm.tobytes())

def test_analyze_returns_stable_schema(tmp_path):
    path = tmp_path / 'pulse.wav'; make_wav(path); result = analyze_audio(path)
    assert result['version'] == '1.0'; assert result['source']['duration'] == 2.0; assert 0 < result['tempo']['bpm'] <= 180
    assert set(result['events']) == {'bass_808', 'kick', 'snare', 'hihat'}
    assert all('time' in event and 'confidence' in event for event in result['events']['kick'])

def test_silence_and_empty_audio_are_safe(tmp_path):
    silent = tmp_path / 'silent.wav'; make_wav(silent, seconds=0.5, tone=False)
    result = analyze_audio(silent)
    assert result['tempo']['bpm'] == 0.0
    assert all(not events for events in result['events'].values())
    empty = tmp_path / 'empty.wav'; make_wav(empty, seconds=0)
    result = analyze_audio(empty)
    assert result['source']['duration'] == 0.0
    assert result['tempo']['beats'] == []

def test_sustained_tone_has_no_repeated_drum_events(tmp_path):
    rate = 8000; t = np.arange(rate) / rate
    pcm = (0.2 * np.sin(2 * np.pi * 55 * t) * 32767).astype('<i2')
    path = tmp_path / 'tone.wav'
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate); f.writeframes(pcm.tobytes())
    result = analyze_audio(path)
    assert result['tempo']['bpm'] == 0.0
    assert len(result['events']['bass_808']) <= 1
    assert not result['events']['kick']
    assert not result['events']['snare']
    assert not result['events']['hihat']
