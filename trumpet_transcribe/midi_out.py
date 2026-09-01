"""MIDI byproducts. raw.mid comes straight from detection; this writes the
cleaned melody line at concert pitch, so it plays along with the recording."""
from __future__ import annotations

from pathlib import Path

TRUMPET_PROGRAM = 56


def write_melody(notes: list, path: Path, concert: bool = True) -> Path:
    import pretty_midi

    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=TRUMPET_PROGRAM, name="melody")
    for note in notes:
        pitch = note.concert_midi if concert else note.written_midi
        velocity = int(max(40, min(127, note.velocity * 127))) if note.velocity else 90
        inst.notes.append(
            pretty_midi.Note(
                velocity=velocity,
                pitch=int(pitch),
                start=float(note.onset_s),
                end=float(note.onset_s + note.duration_s),
            )
        )
    pm.instruments.append(inst)
    path.parent.mkdir(parents=True, exist_ok=True)
    pm.write(str(path))
    return path
