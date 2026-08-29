from __future__ import annotations

import wave

import numpy as np

from beatscope.audio_io import load_analysis_audio


def _write_pcm(path, channels: int) -> None:
    frames = np.zeros((80, channels), dtype="<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(frames.tobytes())


def test_load_analysis_audio_preserves_source_channel_count(tmp_path):
    mono = tmp_path / "mono.wav"
    stereo = tmp_path / "stereo.wav"
    _write_pcm(mono, 1)
    _write_pcm(stereo, 2)

    mono_y, _, _, mono_channels, _ = load_analysis_audio(mono, target_sr=8000)
    stereo_y, _, _, stereo_channels, _ = load_analysis_audio(stereo, target_sr=8000)

    assert mono_y.ndim == stereo_y.ndim == 1
    assert mono_channels == 1
    assert stereo_channels == 2
