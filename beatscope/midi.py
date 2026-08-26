"""Small dependency-free Standard MIDI File writer for DAW import."""
from __future__ import annotations
import struct
from pathlib import Path
from typing import Any

TPQ = 480
DRUM_NOTES = {"kick": 36, "snare": 38, "hihat": 42}

def _varlen(value: int) -> bytes:
    value = max(0, int(value)); out = bytearray([value & 0x7F]); value >>= 7
    while value:
        out.insert(0, (value & 0x7F) | 0x80); value >>= 7
    return bytes(out)

def _track(events: list[tuple[int, int, bytes]], name: str = "") -> bytes:
    body = bytearray()
    if name: encoded = name.encode("ascii", errors="replace")[:127]; body += b"\x00\xff\x03" + _varlen(len(encoded)) + encoded
    previous = 0
    for tick, order, message in sorted(events, key=lambda item: (item[0], item[1])):
        body += _varlen(tick - previous) + message; previous = tick
    body += b"\x00\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + body

def _meta_track(bpm: float) -> bytes:
    micros = int(round(60_000_000 / bpm)) if bpm else 500_000
    events = [(0, 0, b"\xff\x51\x03" + micros.to_bytes(3, "big")), (0, 0, b"\xff\x58\x04\x04\x02\x18\x08")]
    return _track(events, "BeatScope")

def _tick(seconds: float, bpm: float, origin: float) -> int:
    return max(0, int(round((seconds - origin) * bpm / 60 * TPQ))) if bpm else 0

def _drum_track(beatmap: dict[str, Any]) -> bytes:
    events: list[tuple[int, int, bytes]] = []
    bpm = float(beatmap.get("tempo", {}).get("bpm") or 0); origin = float(beatmap.get("grid", {}).get("origin") or 0)
    for label, note in DRUM_NOTES.items():
        for event in beatmap.get("events", {}).get(label, []):
            tick = _tick(float(event.get("time", 0)), bpm, origin); velocity = int(event.get("velocity", 100) or 100)
            events += [(tick, 1, bytes((0x99, note, min(127, max(1, velocity))))), (tick + 30, 0, bytes((0x89, note, 0)))]
    return _track(events, "Drums")

def _bass_track(beatmap: dict[str, Any]) -> bytes:
    events: list[tuple[int, int, bytes]] = []; bpm = float(beatmap.get("tempo", {}).get("bpm") or 0); origin = float(beatmap.get("grid", {}).get("origin") or 0)
    for note in beatmap.get("bass_notes", []):
        pitch = int(note.get("midi", 36)); start = _tick(float(note.get("start", 0)), bpm, origin); duration = max(30, _tick(float(note.get("duration", 0.1)), bpm, 0)); velocity = int(note.get("velocity", 100) or 100)
        events += [(start, 1, bytes((0x90, max(0, min(127, pitch)), min(127, max(1, velocity))))), (start + duration, 0, bytes((0x80, max(0, min(127, pitch)), 0)))]
    return _track(events, "808 Bass")

def build_midi(beatmap: dict[str, Any], kind: str = "combined") -> bytes:
    tracks = [_meta_track(float(beatmap.get("tempo", {}).get("bpm") or 120))]
    if kind in ("drums", "combined"): tracks.append(_drum_track(beatmap))
    if kind in ("808", "combined", "bass"): tracks.append(_bass_track(beatmap))
    header = b"MThd" + struct.pack(">IHHH", 6, 1 if len(tracks) > 1 else 0, len(tracks), TPQ)
    return header + b"".join(tracks)

def write_midi_exports(beatmap: dict[str, Any], directory: str | Path, stem: str) -> dict[str, str]:
    target = Path(directory); target.mkdir(parents=True, exist_ok=True); outputs: dict[str, str] = {}
    for kind in ("drums", "808", "combined"):
        path = target / f"{stem}.{kind}.mid"; path.write_bytes(build_midi(beatmap, kind)); outputs[kind] = str(path)
    return outputs
