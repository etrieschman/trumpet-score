"""Tempo estimation, so stage 2 needs no input from the user.

Beat tracking runs on the ORIGINAL mix, not the isolated melody stem: the stem
has had the drums removed, which is exactly the information a beat tracker
wants. The result is stored in the intermediate so renderers never touch audio.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


def estimate_from_audio(path: Path, sr: int = 22050) -> dict:
    import librosa

    from .audio import load

    wav, in_sr = load(path)
    mono = wav.mean(axis=0)
    y = librosa.resample(mono, orig_sr=in_sr, target_sr=sr)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    bpm = float(np.atleast_1d(tempo)[0])
    if not np.isfinite(bpm) or bpm <= 0:
        return {"bpm": 120.0, "beat_offset": 0.0, "source": "default", "confidence": 0.0}
    return {
        "bpm": round(bpm, 2),
        "beat_offset": round(float(beats[0]), 3) if len(beats) else 0.0,
        "source": "audio",
        "confidence": None,  # beat_track gives no usable score; None means "trust it"
    }


# How far off the grid an onset may be before it counts as a miss. Detection
# jitter is tens of milliseconds, so this is a real tolerance, not a fudge.
ONSET_TOLERANCE_S = 0.05


def _grid_fit(onsets: np.ndarray, bpm: float, phase: float, grid: int = 4) -> float:
    """Fraction of onsets landing on a bpm/phase grid, in [0, 1].

    Error is measured in SECONDS, not in fractions of a grid step. Normalizing
    by the step is what a first pass does, and it silently rewards slow tempos:
    a coarser grid tolerates more absolute jitter, so halving the tempo always
    scores better than the truth.
    """
    if onsets.size == 0:
        return 0.0
    step = 60.0 / bpm / grid
    positions = (onsets - phase) / step
    error_seconds = np.abs(positions - np.round(positions)) * step
    return float(np.mean(np.clip(1.0 - error_seconds / ONSET_TOLERANCE_S, 0.0, 1.0)))


def refine_with_onsets(info: dict, onsets, grid: int = 4) -> dict:
    """Correct a beat-tracked tempo against where the notes actually fall.

    Beat tracking is done on percussive salience and is routinely off by a
    metrical factor, or just off -- it reported 117 bpm for audio that is exactly
    100. The criterion that actually matters for notation is whether the
    detected notes land on the grid, so score the tracker's estimate and its
    metrical relatives against the onsets and keep the best.
    """
    onsets = np.asarray(sorted(onsets), dtype=float)
    if onsets.size < 4:
        return info

    base = float(info.get("bpm", 120.0))
    free = estimate_from_onsets(onsets, grid)["bpm"]
    candidates = set()
    for anchor in (base, free):
        for ratio in (1 / 3, 0.5, 2 / 3, 1.0, 1.5, 2.0, 3.0):
            related = anchor * ratio
            if 40.0 <= related <= 240.0:
                for nudge in np.arange(-0.06, 0.0601, 0.004):
                    candidates.add(round(related * (1 + nudge), 2))

    scored = []
    for bpm in candidates:
        step = 60.0 / bpm / grid
        for phase in np.linspace(0.0, step, 12, endpoint=False):
            scored.append((_grid_fit(onsets, bpm, float(phase), grid), bpm, float(phase)))
    top = max(scored)[0]
    # Among near-equal fits prefer the tempo closest to the tracker's estimate:
    # a denser grid always fits slightly better, and that bias favours nonsense.
    score, bpm, phase = min(
        (s for s in scored if s[0] >= top - 0.02), key=lambda s: abs(s[1] - base)
    )
    return {
        "bpm": round(bpm, 2),
        "beat_offset": round(phase, 3),
        "source": f"{info.get('source', 'audio')}+onsets",
        "confidence": round(score, 3),
    }


def estimate(source, onsets, grid: int = 4) -> dict:
    """Full tempo estimate: beat-track the mix, then refine against the notes."""
    try:
        info = estimate_from_audio(source)
    except Exception as exc:
        print(f"[tempo] beat tracking failed ({exc.__class__.__name__}), using onsets")
        info = estimate_from_onsets(onsets, grid)
    return refine_with_onsets(info, onsets, grid)


def estimate_from_onsets(onsets, grid: int = 4) -> dict:
    """Fallback when no audio is available: fit a grid to the note onsets alone.

    Weaker than beat tracking -- it has no percussive information to work with,
    only where notes happen to start -- but better than assuming 120.
    """
    onsets = np.asarray(sorted(onsets), dtype=float)
    if onsets.size < 4:
        return {"bpm": 120.0, "beat_offset": 0.0, "source": "default", "confidence": 0.0}

    scored = []
    for bpm in np.arange(50.0, 200.5, 0.5):
        step = 60.0 / bpm / grid
        for phase in np.linspace(0.0, step, 8, endpoint=False):
            scored.append((_grid_fit(onsets, bpm, float(phase), grid), float(bpm), float(phase)))
    top = max(scored)[0]
    # Halving or doubling a tempo fits the grid exactly as well, so ties are the
    # normal case, not the exception. Break them toward a conventional tempo.
    score, bpm, phase = min(
        (s for s in scored if s[0] >= top - 0.02), key=lambda s: abs(s[1] - 110.0)
    )
    return {
        "bpm": round(bpm, 2),
        "beat_offset": round(phase, 3),
        "source": "onsets",
        "confidence": round(score, 3),
    }
