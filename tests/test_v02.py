import math
import struct
import wave

import numpy as np

from beatscope.analysis import analyze_audio
from beatscope.midi import build_midi

def tone_wav(path, frequency, seconds=1.0, rate=8000):
    t = np.arange(int(rate * seconds)) / rate
    pcm = (0.2 * np.sin(2 * np.pi * frequency * t) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate); f.writeframes(pcm.tobytes())

def pulse_wav(path, seconds=4.0, rate=8000):
    signal = np.zeros(int(rate * seconds), dtype=np.float32)
    for onset in np.arange(0, seconds, 0.5):
        start = int(onset * rate); signal[start:start + 80] += np.hanning(80)
    pcm = np.clip(signal * 32767, -32768, 32767).astype('<i2')
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate); f.writeframes(pcm.tobytes())

def test_grid_fields_align_known_120_bpm_pulses(tmp_path):
    pulse_wav_path = tmp_path / 'pulses.wav'
    pulse_wav(pulse_wav_path)
    result = analyze_audio(pulse_wav_path)
    assert result['tempo']['bpm'] > 0
    assert result['grid']['subdivision'] == 16
    events = result['events']['kick']
    assert events
    assert all({'nearest_step', 'bar', 'beat', 'step_in_bar', 'timing_offset_ms', 'velocity'} <= set(event) for event in events)
    assert all(abs(event['timing_offset_ms']) < 100 for event in events)

def test_bass_pitch_estimate_for_55_and_110_hz(tmp_path):
    for frequency, expected in ((55, 33), (110, 45)):
        tone_path = tmp_path / f'{frequency}.wav'
        tone_wav(tone_path, frequency)
        result = analyze_audio(tone_path)
        assert result['bass_notes']
        assert abs(result['bass_notes'][0]['midi'] - expected) <= 1
        assert result['bass_notes'][0]['duration'] > 0.7

def test_midi_header_and_tracks_are_valid():
    beatmap = {'tempo': {'bpm': 120}, 'grid': {'origin': 0}, 'events': {'kick': [{'time': 0, 'velocity': 100}], 'snare': [], 'hihat': []}, 'bass_notes': [{'start': 0, 'duration': 0.5, 'midi': 33, 'velocity': 100}]}
    data = build_midi(beatmap, 'combined')
    assert data[:4] == b'MThd'; assert struct.unpack('>I', data[4:8])[0] == 6
    tracks = struct.unpack('>H', data[10:12])[0]; assert tracks == 3
    offset = 14
    for _ in range(tracks):
        assert data[offset:offset + 4] == b'MTrk'
        length = struct.unpack('>I', data[offset + 4:offset + 8])[0]
        assert data[offset + 8 + length - 3:offset + 8 + length] == b'\xff\x2f\x00'
        offset += 8 + length
    assert offset == len(data)
