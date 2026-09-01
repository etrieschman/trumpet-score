"""The note sheet: aligned note names and fingerings, no rhythm notation.

Reads only the intermediate document. Phrase lines break on silence.
"""
from __future__ import annotations

from . import keysig, trumpet
from .intermediate import NoteDocument
from .trumpet import OUT_OF_RANGE

GUTTER = 2
LABEL_WIDTH = 6   # fits up to 99:59
INDENT = LABEL_WIDTH + 3


def timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def _aligned_rows(cells: list, label: str = "") -> list:
    """Two rows sharing one set of column widths -- the whole alignment trick."""
    widths = [max(len(top), len(bottom)) + GUTTER for top, bottom in cells]
    prefix = label.rjust(LABEL_WIDTH) + "   " if label else " " * INDENT
    top_row = prefix + "".join(t.ljust(w) for (t, _), w in zip(cells, widths))
    bottom_row = " " * INDENT + "".join(b.ljust(w) for (_, b), w in zip(cells, widths))
    return [top_row.rstrip(), bottom_row.rstrip()]


def split_phrases(notes: list, phrase_gap: float, max_per_line: int) -> list:
    """Break wherever silence exceeds phrase_gap, or the line gets too wide."""
    if not notes:
        return []
    lines, current = [], [notes[0]]
    for prev, note in zip(notes, notes[1:]):
        gap = note.onset_s - (prev.onset_s + prev.duration_s)
        if gap > phrase_gap or len(current) >= max_per_line:
            lines.append(current)
            current = []
        current.append(note)
    if current:
        lines.append(current)
    return lines


def _key_header(key_info: dict, use_sharps: bool, show_octaves: bool) -> list:
    # The sheet is in written pitch, so name the written key first; the concert
    # key is what everyone else in the room is calling it.
    concert_pc = (key_info["tonic_pc"] - trumpet.TRANSPOSE) % 12
    names = keysig.SHARP_NAMES if use_sharps else keysig.NAMES
    concert = f"{names[concert_pc]} {key_info['mode']}"

    line = f"KEY    {key_info['tonic']} {key_info['mode']} written   ({concert} concert)"
    margin = key_info.get("margin")
    if margin is not None and margin < 0.05:
        line += f"   -- close call, could be {key_info['runner_up']}"
    out = [line, ""]

    cells = []
    for pitch in keysig.scale_pitches(key_info):
        name = trumpet.note_name(pitch, flats=not use_sharps)
        if not show_octaves:
            name = name.rstrip("0123456789")
        cells.append((name, trumpet.fingering(pitch)))
    if cells:
        out += ["       the scale, to jam on:"] + _aligned_rows(cells) + [""]

    played = keysig.detected_pitch_classes(key_info, use_sharps=use_sharps)
    if played:
        summary = "  ".join(f"{n} {int(round(w * 100))}%" for n, w in played)
        out += ["       notes actually detected, most-played first:",
                " " * INDENT + summary, ""]
    return out


def render(
    doc: NoteDocument,
    phrase_gap: float = 1.0,
    max_per_line: int = 12,
    show_octaves: bool = True,
    key: str = "auto",
    force_sharps: bool = False,
) -> str:
    out = [
        f"# {doc.source}",
        "# Written Bb trumpet pitch (concert +2). First-choice fingerings.",
        f"# Phrase break at gaps > {phrase_gap}s.",
        f"# * = unplayable, shown as {OUT_OF_RANGE}.   ~ = outside the detected key,"
        " check these first.",
        f"# Settings: {doc.params.get('settings') or 'defaults'}",
        "",
    ]
    use_sharps = False
    key_info = None
    if doc.notes:
        key_info = keysig.estimate(doc.notes) if key == "auto" else keysig.from_name(key)  # noqa: E501
        # Spell accidentals to match the key, so the phrase rows agree with the
        # scale above them -- F# in a sharp key, never Gb.
        use_sharps = force_sharps or key_info["use_sharps"]
        out += _key_header(key_info, use_sharps, show_octaves)
        out += ["-" * 72, ""]

    scale = set()
    if key_info:
        scale = {(key_info["tonic_pc"] + d) % 12 for d in keysig.DEGREES[key_info["mode"]]}

    flagged = outside = 0
    for phrase in split_phrases(doc.notes, phrase_gap, max_per_line):
        cells = []
        for note in phrase:
            name = trumpet.note_name(note.written_midi, flats=not use_sharps)
            if not show_octaves:
                name = name.rstrip("0123456789")
            if not note.in_range:
                name += "*"
                flagged += 1
            elif scale and note.written_midi % 12 not in scale:
                # Either a chromatic passing tone or a detection error. Worth
                # seeing at a glance -- an isolated one in a modal tune is
                # almost always the latter.
                name += "~"
                outside += 1
            cells.append((name, note.fingering))
        out += _aligned_rows(cells, label=timestamp(phrase[0].onset_s)) + [""]

    if outside:
        out.append(f"# {outside} note(s) marked ~ fall outside the detected key -- chromatic")
        out.append("# passing tones, or detection errors. Check these first.")
        out.append("")
    if flagged:
        out.append(f"# {flagged} note(s) marked * fall outside F#3-C6 written and have no fingering.")
        out.append("# Try --octave-shift if a whole passage is flagged; that usually means")
        out.append("# the detector locked onto the wrong harmonic partial.")
        out.append("")
    if not doc.notes:
        out.append("# No notes survived filtering. Try a different --stem or lower --min-dur.")
    return "\n".join(out)
