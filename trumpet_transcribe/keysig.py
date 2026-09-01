"""Key estimation.

Krumhansl-Schmuckler: correlate a duration-weighted pitch-class histogram
against a profile per candidate key, take the best fit. Chooses a key signature
and a sharp/flat preference; it never changes a pitch.
"""
from __future__ import annotations

import numpy as np

# Scale degrees in semitones above the tonic, and which major key supplies the
# signature (D dorian and C major share a signature; the tonic is what differs).
DEGREES = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
}
PARENT_OFFSET = {"major": 0, "minor": 3, "dorian": -2, "mixolydian": -7}

MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)

def _modal_profile(mode: str) -> np.ndarray:
    """Build a profile for a mode from the major profile's degree weights.

    Krumhansl measured only major and minor. The ordered scale-degree weights
    (tonic strongest, then fifth, then third) carry over: place them on the
    mode's degrees, fill chromatic positions with the average non-scale weight.
    """
    major_degrees = DEGREES["major"]
    degree_weights = [MAJOR_PROFILE[d] for d in major_degrees]
    non_scale = float(np.mean([MAJOR_PROFILE[i] for i in range(12)
                               if i not in major_degrees]))
    profile = np.full(12, non_scale)
    for degree, weight in zip(DEGREES[mode], degree_weights):
        profile[degree] = weight
    return profile


PROFILES = {
    "major": MAJOR_PROFILE,
    "minor": MINOR_PROFILE,
    "dorian": _modal_profile("dorian"),
    "mixolydian": _modal_profile("mixolydian"),
}

# Major tonic pitch class -> key signature in fifths.
MAJOR_FIFTHS = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 1: -5, 8: -4, 3: -3, 10: -2, 5: -1}

NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def estimate(notes) -> dict:
    """Estimate the key of a list of Notes.

    Duration-weighted, so a passing sixteenth counts for less than a held
    whole note.
    """
    histogram = np.zeros(12)
    for note in notes:
        histogram[note.written_midi % 12] += max(note.duration_s, 0.05)
    if histogram.sum() == 0:
        return {"fifths": 0, "tonic": "C", "mode": "major", "use_sharps": True}
    histogram /= histogram.sum()

    ranked = []
    for tonic in range(12):
        rotated = np.roll(histogram, -tonic)
        for mode, profile in PROFILES.items():
            ranked.append((float(np.corrcoef(rotated, profile)[0, 1]), tonic, mode))
    ranked.sort(reverse=True)
    score, tonic, mode = ranked[0]
    runner_score, runner_tonic, runner_mode = ranked[1]
    # A minor key takes its relative major's signature.
    major_pc = (tonic + PARENT_OFFSET[mode]) % 12
    fifths = MAJOR_FIFTHS[major_pc]
    names = SHARP_NAMES if fifths > 0 else NAMES
    return {
        "fifths": fifths,
        "tonic": names[tonic],
        "tonic_pc": tonic,
        "mode": mode,
        "use_sharps": fifths > 0,
        "confidence": round(score, 3),
        # How clear the win was. A small margin usually means a modal tune,
        # where the profiles fit several keys about equally well.
        "margin": round(score - runner_score, 3),
        "runner_up": f"{names[runner_tonic]} {runner_mode}",
        "histogram": [round(float(v), 4) for v in histogram],
    }


def from_name(name: str) -> dict:
    """Parse an explicit --key like 'F', 'Bb', 'D minor'."""
    parts = name.strip().split()
    tonic_name = parts[0]
    mode = "major"
    if len(parts) > 1:
        requested = parts[1].lower()
        for candidate in DEGREES:
            if candidate.startswith(requested[:3]):
                mode = candidate
                break
    lookup = {n: i for i, n in enumerate(NAMES)}
    lookup.update({n: i for i, n in enumerate(SHARP_NAMES)})
    if tonic_name not in lookup:
        raise ValueError(f"unrecognized key: {name}")
    tonic = lookup[tonic_name]
    major_pc = (tonic + PARENT_OFFSET[mode]) % 12
    fifths = MAJOR_FIFTHS[major_pc]
    return {"fifths": fifths, "tonic": tonic_name, "tonic_pc": tonic, "mode": mode,
            "use_sharps": fifths > 0, "confidence": None, "margin": None,
            "runner_up": None, "histogram": None}



def scale_pitches(key_info: dict, low: int = 54, high: int = 84,
                  below: int = 5, above: int = 17) -> list:
    """Written MIDI notes of the key's scale, around the middle of the staff.

    Roughly a full octave with a few scale steps either side, clamped to the
    playable range -- enough to see where the key sits under the fingers.
    """
    tonic_pc = key_info["tonic_pc"]
    degrees = DEGREES[key_info["mode"]]
    base = tonic_pc
    while base < 57:      # centre the tonic in the lower-middle register
        base += 12
    while base >= 69:
        base -= 12
    return [
        pitch
        for pitch in range(base - below, base + above + 1)
        if (pitch - tonic_pc) % 12 in degrees and low <= pitch <= high
    ]


def detected_pitch_classes(key_info: dict, limit: int = 8,
                           use_sharps: bool = None) -> list:
    """Pitch classes actually present, most-played first.

    Measured from the recording rather than fitted, so it stands when the key
    label is wrong.
    """
    histogram = key_info.get("histogram")
    if not histogram:
        return []
    if use_sharps is None:
        use_sharps = key_info["use_sharps"]
    names = SHARP_NAMES if use_sharps else NAMES
    ordered = sorted(range(12), key=lambda pc: -histogram[pc])
    return [(names[pc], histogram[pc]) for pc in ordered[:limit] if histogram[pc] > 0.02]
