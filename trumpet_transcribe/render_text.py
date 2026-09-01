"""Stage 1 renderer: a monospace note sheet, no rhythm notation.

Reads only the intermediate document. Phrase lines break on silence.
"""
from __future__ import annotations

from .intermediate import NoteDocument
from .trumpet import OUT_OF_RANGE

GUTTER = 2
LABEL_WIDTH = 6   # fits up to 99:59
INDENT = LABEL_WIDTH + 3


def timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


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


def render(
    doc: NoteDocument,
    phrase_gap: float = 1.0,
    max_per_line: int = 12,
    show_octaves: bool = True,
) -> str:
    lines = split_phrases(doc.notes, phrase_gap, max_per_line)
    out = [
        f"# {doc.source}",
        f"# written Bb trumpet pitch (concert +2), first-choice fingerings",
        f"# phrase break at gaps > {phrase_gap}s   |   {OUT_OF_RANGE} = outside practical range",
        "",
    ]

    flagged = 0
    for phrase in lines:
        cells = []
        for note in phrase:
            name = note.written_name if show_octaves else note.written_name.rstrip("0123456789")
            if not note.in_range:
                name += "*"
                flagged += 1
            cells.append((name, note.fingering))

        widths = [max(len(n), len(f)) + GUTTER for n, f in cells]
        label = timestamp(phrase[0].onset_s).rjust(LABEL_WIDTH) + "   "
        name_row = label + "".join(n.ljust(w) for (n, _), w in zip(cells, widths))
        fing_row = " " * INDENT + "".join(f.ljust(w) for (_, f), w in zip(cells, widths))
        out.append(name_row.rstrip())
        out.append(fing_row.rstrip())
        out.append("")

    if flagged:
        out.append(f"# {flagged} note(s) marked * fall outside F#3-C6 written and have no fingering.")
        out.append("# Try --octave-shift if a whole passage is flagged; that usually means")
        out.append("# the detector locked onto the wrong harmonic partial.")
        out.append("")
    if not doc.notes:
        out.append("# No notes survived filtering. Try a different --stem or lower --min-dur.")
    return "\n".join(out)
