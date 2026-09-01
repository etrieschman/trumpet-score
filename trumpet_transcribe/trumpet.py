"""Bb trumpet: transposition, note spelling, and valve fingerings.

Concert pitch -> written trumpet pitch is up a major second (+2 semitones).
Everything in this module that says "written" means written Bb trumpet pitch.
"""

# Written-pitch practical range for Bb trumpet.
WRITTEN_LOW = 54   # F#3, the lowest note reachable with 1-2-3
WRITTEN_HIGH = 84  # C6, "high C"

TRANSPOSE = 2  # concert -> written

NAMES_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Written MIDI note -> (first-choice fingering, [alternates]).
# Valves are numbered 1-2-3 from the mouthpiece; "0" is open.
_CHART = {
    54: ("1-2-3", []),          # F#3
    55: ("1-3", []),            # G3
    56: ("2-3", ["1-2-3"]),     # Ab3
    57: ("1-2", ["3"]),         # A3
    58: ("1", []),              # Bb3
    59: ("2", []),              # B3
    60: ("0", []),              # C4
    61: ("1-2-3", ["2-3"]),     # Db4
    62: ("1-3", ["2-3"]),       # D4
    63: ("2-3", ["1-3"]),       # Eb4
    64: ("1-2", ["3"]),         # E4
    65: ("1", []),              # F4
    66: ("2", ["1-2-3"]),       # Gb4
    67: ("0", ["1-3"]),         # G4
    68: ("2-3", []),            # Ab4
    69: ("1-2", ["3"]),         # A4
    70: ("1", []),              # Bb4
    71: ("2", []),              # B4
    72: ("0", []),              # C5
    73: ("1-2", ["3"]),         # Db5
    74: ("1", []),              # D5
    75: ("2", ["1-3"]),         # Eb5
    76: ("0", ["1-2"]),         # E5
    77: ("1", []),              # F5
    78: ("2", []),              # Gb5
    79: ("0", []),              # G5
    80: ("2-3", []),            # Ab5
    81: ("1-2", ["3"]),         # A5
    82: ("1", []),              # Bb5
    83: ("2", []),              # B5
    84: ("0", []),              # C6
}

OUT_OF_RANGE = "--"


def note_name(midi: int, flats: bool = True) -> str:
    names = NAMES_FLAT if flats else NAMES_SHARP
    return f"{names[midi % 12]}{midi // 12 - 1}"


def to_written(concert_midi: int) -> int:
    return concert_midi + TRANSPOSE


def to_concert(written_midi: int) -> int:
    return written_midi - TRANSPOSE


def in_range(written_midi: int) -> bool:
    return WRITTEN_LOW <= written_midi <= WRITTEN_HIGH


def fingering(written_midi: int) -> str:
    """First-choice fingering, or OUT_OF_RANGE if unplayable on a Bb trumpet."""
    entry = _CHART.get(written_midi)
    return entry[0] if entry else OUT_OF_RANGE


def alternates(written_midi: int) -> list:
    entry = _CHART.get(written_midi)
    return list(entry[1]) if entry else []
