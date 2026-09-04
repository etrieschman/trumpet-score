"""Melody extraction with Melodia (Essentia), run on the mix itself.

Salience-based: it estimates the predominant melody's f0 directly from
polyphonic audio, with no source separation. That makes its errors largely
independent of the Demucs + basic-pitch path, which is what makes the two
worth comparing.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

RAW_NOTES = "raw_notes.melodia.json"
HOP = 128
FRAME = 2048


def _cache_key(source: Path, params: dict) -> dict:
    st = source.stat()
    return {"source": str(source.resolve()), "size": st.st_size,
            "mtime": int(st.st_mtime), "params": params}


def detect(
    source: Path,
    out_dir: Path,
    label: str = "stem",
    voicing_tolerance: float = 0.2,
    min_duration: float = 0.1,
    force: bool = False,
) -> list:
    """Return note events as [start_s, end_s, concert_midi, confidence]."""
    params = {"voicing_tolerance": voicing_tolerance, "min_duration": min_duration,
              "label": label}
    raw_path = out_dir / RAW_NOTES
    key = _cache_key(source, params)

    if not force and raw_path.exists():
        try:
            cached = json.loads(raw_path.read_text())
            if cached.get("key") == key:
                print(f"[melodia] reusing cached detections: {raw_path}")
                return cached["events"]
        except (json.JSONDecodeError, KeyError):
            pass

    import essentia.standard as es

    from .audio import load

    # Decoded here rather than by Essentia's own loader, which wants ffmpeg.
    wav, sr = load(source)
    mono = np.ascontiguousarray(wav.mean(axis=0).astype(np.float32))

    print("[melodia] running predominant-melody extraction")
    pitch, confidence = es.PredominantPitchMelodia(
        frameSize=FRAME, hopSize=HOP, sampleRate=sr,
        voicingTolerance=voicing_tolerance,
    )(mono)
    onsets, durations, midi = es.PitchContourSegmentation(
        hopSize=HOP, sampleRate=sr, minDuration=min_duration,
    )(pitch, mono)

    frame_seconds = HOP / sr
    events = []
    for onset, duration, note in zip(onsets, durations, midi):
        lo = int(onset / frame_seconds)
        hi = max(lo + 1, int((onset + duration) / frame_seconds))
        window = confidence[lo:hi]
        amp = float(np.mean(window)) if len(window) else 0.5
        events.append([float(onset), float(onset + duration), int(round(note)), amp])

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps({"key": key, "events": events}, indent=2))
    print(f"[melodia] {len(events)} note events -> {raw_path}")
    return events
