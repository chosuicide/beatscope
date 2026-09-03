"""Generate the rights-safe audio for the WebMCP Director demo.

The demo page must publish music the project owns outright (v0.10 plan
section 17.3), so the track is original material synthesized by this
script: 120 BPM, 30 bars (60 s), sections A (bars 1-10), B (bars 11-20)
and A' (bars 21-30). A and A' share the same arrangement so the structure
analyzer sees a repeated family; B lifts energy, adds sixteenth hats and a
saw lead, which produces the two structural boundaries at bars 11 and 21.

Everything is deterministic numpy: no samples, no randomness beyond the
seeded noise generator, no third-party material, no network.

Usage:
    python scripts/make_webmcp_demo_audio.py <output.wav>
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
BPM = 120.0
BEAT = 60.0 / BPM  # 0.5 s
BAR = 4 * BEAT  # 2 s
BARS = 30
DURATION = BARS * BAR  # 60 s
SECTION_BARS = 10  # A = bars 1-10, B = bars 11-20, A' = bars 21-30
NOISE_SEED = 20260903

# Am - F - C - G, restarting at every section so A' mirrors A.
CHORD_ROOTS = (55.00, 43.65, 65.41, 49.00)  # A1 F1 C2 G1 bass roots
CHORD_TONES = (
    (110.00, 130.81, 164.81),  # A2 C3 E3
    (87.31, 110.00, 130.81),  # F2 A2 C3
    (130.81, 164.81, 196.00),  # C3 E3 G3
    (98.00, 123.47, 146.83),  # G2 B2 D3
)


def place(buffer: np.ndarray, start: float, sound: np.ndarray, gain: float = 1.0) -> None:
    index = int(start * SR)
    if index < 0 or index >= buffer.size:
        return
    end = min(index + sound.size, buffer.size)
    buffer[index:end] += sound[: end - index] * gain


def kick(drive: float = 1.0) -> np.ndarray:
    n = int(0.30 * SR)
    t = np.arange(n) / SR
    pitch = 42 + 110 * np.exp(-t * 34)
    body = np.sin(2 * np.pi * np.cumsum(pitch) / SR) * np.exp(-t * 11)
    click = np.random.default_rng(NOISE_SEED).standard_normal(n) * np.exp(-t * 420) * 0.4
    return (body + click) * drive


def snare() -> np.ndarray:
    n = int(0.18 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(NOISE_SEED + 1)
    noise = rng.standard_normal(n)
    noise = np.diff(np.concatenate([[0.0], noise]))  # brighten toward white
    tone = np.sin(2 * np.pi * 189 * t) * 0.35
    return (noise * 0.8 + tone) * np.exp(-t * 26)


def hat(open_position: bool = False) -> np.ndarray:
    length = 0.16 if open_position else 0.035
    n = int(length * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(NOISE_SEED + 2)
    noise = np.diff(np.concatenate([[0.0], rng.standard_normal(n)]))
    # Cheap high-pass: subtract a short moving average.
    window = 48
    noise = noise - np.convolve(noise, np.ones(window) / window, mode="same")
    return noise * np.exp(-t * (14 if open_position else 90))


def bass_note(freq: float, length: float) -> np.ndarray:
    n = int(length * SR)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * freq * t) + 0.45 * np.sin(4 * np.pi * freq * t)
    env = np.minimum(t / 0.008, 1.0) * np.exp(-t * 5.2)
    return body * env


def chord_pad(tones: tuple[float, ...], length: float) -> np.ndarray:
    n = int(length * SR)
    t = np.arange(n) / SR
    body = np.zeros(n)
    for index, freq in enumerate(tones):
        body += np.sin(2 * np.pi * freq * t + index) * 0.8
        body += np.sin(4 * np.pi * freq * t) * 0.15
    env = np.minimum(t / 0.05, 1.0) * np.minimum((length - t) / 0.12, 1.0)
    return body * np.clip(env, 0.0, 1.0)


def lead_note(freq: float, length: float) -> np.ndarray:
    n = int(length * SR)
    t = np.arange(n) / SR
    body = np.zeros(n)
    for harmonic in range(1, 7):
        body += np.sin(2 * np.pi * freq * harmonic * t) / harmonic
    env = np.minimum(t / 0.004, 1.0) * np.exp(-t * 9)
    return body * env


def render() -> np.ndarray:
    total = int(DURATION * SR)
    mix = np.zeros(total)
    rng = np.random.default_rng(NOISE_SEED + 3)

    for bar in range(BARS):
        bar_start = bar * BAR
        section = bar // SECTION_BARS  # 0 = A, 1 = B, 2 = A'
        in_b = section == 1
        chord_index = (bar % 4) * 2 % 8 // 2  # two bars per chord
        root = CHORD_ROOTS[chord_index]
        tones = CHORD_TONES[chord_index]

        # Bass: eighth-note pulses through every section.
        for step in range(8):
            place(mix, bar_start + step * BEAT / 2, bass_note(root, 0.42), 0.42)

        # Pads: one soft chord per bar.
        place(mix, bar_start, chord_pad(tones, BAR * 0.96), 0.16)

        # Kick: A/A' on beats 1 and 3, B on every beat.
        for beat in range(4):
            if in_b or beat % 2 == 0:
                place(mix, bar_start + beat * BEAT, kick(1.0 if in_b else 0.85), 0.9)

        # Snare backbeat only in B.
        if in_b:
            place(mix, bar_start + 1 * BEAT, snare(), 0.5)
            place(mix, bar_start + 3 * BEAT, snare(), 0.5)

        # Hats: eighths in A/A', sixteenths with an open hat in B.
        hat_grid = 16 if in_b else 8
        for step in range(hat_grid):
            position = bar_start + step * BAR / hat_grid
            open_position = in_b and step % 8 == 4
            place(mix, position, hat(open_position), 0.30 if in_b else 0.22)

        # Saw lead arpeggio only in B (16th notes, two octaves of chord tones).
        if in_b:
            arp = (0, 1, 2, 1, 0, 2, 1, 2, 0, 1, 2, 1, 2, 1, 0, 1)
            for step in range(16):
                tone = tones[arp[step] % 3] * (2 if arp[step] >= 3 else 1)
                place(mix, bar_start + step * BEAT / 4, lead_note(tone, 0.11), 0.30)

    # Gentle noise floor keeps the analyzer from seeing digital silence.
    mix += rng.standard_normal(total) * 0.00035

    peak = float(np.max(np.abs(mix)))
    if peak > 0:
        mix = mix / peak * 0.88
    edge = int(0.005 * SR)
    mix[:edge] *= np.linspace(0.0, 1.0, edge)
    mix[-edge:] *= np.linspace(1.0, 0.0, edge)
    return (mix * 32767).astype(np.int16)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    samples = render()
    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(samples.tobytes())
    print(f"wrote {output} ({samples.size / SR:.3f} s, {output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
