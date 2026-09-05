"""Polyphonic note detection (basic-pitch), cached on disk.

Emits note events rather than an f0 curve. Polyphonic, so melody reduction
happens downstream in melody.py.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

RAW_NOTES = "raw_notes.json"
RAW_MIDI = "raw.mid"


def _model_path():
    """Prefer the ONNX weights; basic-pitch picks CoreML first on macOS."""
    from basic_pitch import ICASSP_2022_MODEL_PATH

    onnx = Path(ICASSP_2022_MODEL_PATH).parent / "nmp.onnx"
    return onnx if onnx.exists() else ICASSP_2022_MODEL_PATH


def _cache_key(stem_path: Path, params: dict) -> dict:
    # Hash the stem's contents, not its size: every separation model writes a
    # stem of identical size for a given input, so a size-keyed cache serves
    # one model's detections for another model's audio.
    digest = hashlib.md5(stem_path.read_bytes()).hexdigest()
    return {"stem": str(stem_path.resolve()), "digest": digest, "params": params}


def detect(
    stem_path: Path,
    out_dir: Path,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    min_note_ms: float = 60.0,
    min_freq: float = 130.0,   # ~C3, below any practical concert trumpet note
    max_freq: float = 1400.0,  # ~F6, above written high C
    force: bool = False,
) -> list:
    """Return raw note events as [start_s, end_s, midi, amplitude] lists."""
    params = {
        "onset_threshold": onset_threshold,
        "frame_threshold": frame_threshold,
        "min_note_ms": min_note_ms,
        "min_freq": min_freq,
        "max_freq": max_freq,
    }
    raw_path = out_dir / RAW_NOTES
    key = _cache_key(stem_path, params)

    if not force and raw_path.exists():
        try:
            cached = json.loads(raw_path.read_text())
            if cached.get("key") == key:
                print(f"[detect] reusing cached detections: {raw_path}")
                return cached["events"]
        except (json.JSONDecodeError, KeyError):
            pass

    from basic_pitch.inference import predict

    print("[detect] running basic-pitch")
    _, midi_data, note_events = predict(
        str(stem_path),
        _model_path(),
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=min_note_ms,
        minimum_frequency=min_freq,
        maximum_frequency=max_freq,
        melodia_trick=True,
    )

    events = [[float(s), float(e), int(p), float(a)] for s, e, p, a, *_ in note_events]
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps({"key": key, "events": events}, indent=2))
    midi_data.write(str(out_dir / RAW_MIDI))
    print(f"[detect] {len(events)} raw note events -> {raw_path}")
    return events
