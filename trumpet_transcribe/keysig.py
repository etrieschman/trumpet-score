"""Key estimation, so accidentals are spelled sensibly with no user input.

Krumhansl-Schmuckler: correlate a duration-weighted pitch-class histogram
against major and minor profiles, take the best of the 24 keys. Used only to
choose a key signature and a sharp/flat preference -- it never changes a pitch.
"""
from __future__ import annotations

import numpy as np

MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)

# Major tonic pitch class -> key signature in fifths.
MAJOR_FIFTHS = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 1: -5, 8: -4, 3: -3, 10: -2, 5: -1}

NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def estimate(notes) -> dict:
    """Return {'fifths', 'tonic', 'mode', 'use_sharps'} for a list of Notes.

    Weighting by duration matters: a passing sixteenth should not count as much
    as a held whole note when deciding what key we are in.
    """
    histogram = np.zeros(12)
    for note in notes:
        histogram[note.written_midi % 12] += max(note.duration_s, 0.05)
    if histogram.sum() == 0:
        return {"fifths": 0, "tonic": "C", "mode": "major", "use_sharps": True}
    histogram /= histogram.sum()

    best = (-2.0, 0, "major")
    for tonic in range(12):
        rotated = np.roll(histogram, -tonic)
        for profile, mode in ((MAJOR_PROFILE, "major"), (MINOR_PROFILE, "minor")):
            score = float(np.corrcoef(rotated, profile)[0, 1])
            if score > best[0]:
                best = (score, tonic, mode)

    _, tonic, mode = best
    # A minor key takes its relative major's signature.
    major_pc = tonic if mode == "major" else (tonic + 3) % 12
    fifths = MAJOR_FIFTHS[major_pc]
    return {
        "fifths": fifths,
        "tonic": (SHARP_NAMES if fifths > 0 else NAMES)[tonic],
        "mode": mode,
        "use_sharps": fifths > 0,
    }


def from_name(name: str) -> dict:
    """Parse an explicit --key like 'F', 'Bb', 'D minor'."""
    parts = name.strip().split()
    tonic_name = parts[0]
    mode = "minor" if len(parts) > 1 and parts[1].lower().startswith("min") else "major"
    lookup = {n: i for i, n in enumerate(NAMES)}
    lookup.update({n: i for i, n in enumerate(SHARP_NAMES)})
    if tonic_name not in lookup:
        raise ValueError(f"unrecognized key: {name}")
    tonic = lookup[tonic_name]
    major_pc = tonic if mode == "major" else (tonic + 3) % 12
    fifths = MAJOR_FIFTHS[major_pc]
    return {"fifths": fifths, "tonic": tonic_name, "mode": mode, "use_sharps": fifths > 0}
