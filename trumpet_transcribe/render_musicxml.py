"""Stage 2 renderer: quantized MusicXML with fingerings above the staff.

Reads only the intermediate document, same as the text renderer. Opens in
MuseScore. Quantization is the weak link by design -- the aim is a score that is
90% right and quick to fix by hand, not one that is perfect.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from . import keysig
from .intermediate import NoteDocument

# MusicXML note types, longest first, as (ticks_multiplier_of_quarter, type, dots).
_BASE_TYPES = [
    (4.0, "whole"),
    (2.0, "half"),
    (1.0, "quarter"),
    (0.5, "eighth"),
    (0.25, "16th"),
    (0.125, "32nd"),
]

SHARP_SPELL = [("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0),
               ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0)]
FLAT_SPELL = [("C", 0), ("D", -1), ("D", 0), ("E", -1), ("E", 0), ("F", 0),
              ("G", -1), ("G", 0), ("A", -1), ("A", 0), ("B", -1), ("B", 0)]


def _duration_table(divisions: int):
    """Notatable durations in ticks: (ticks, type, dots, alignment_ticks).

    `alignment` is what a note of this value must start on for the notation to
    be readable -- a dotted value aligns to its undotted base, which is why a
    dotted quarter on beat 3 stays a dotted quarter instead of splitting.
    """
    table = []
    for mult, name in _BASE_TYPES:
        plain = mult * divisions
        if plain == int(plain) and plain >= 1:
            table.append((int(plain), name, 0, int(plain)))
        dotted = plain * 1.5
        if dotted == int(dotted) and dotted >= 1:
            table.append((int(dotted), name, 1, int(plain)))
    return sorted(table, key=lambda e: -e[0])


def _split_duration(start: int, ticks: int, divisions: int) -> list:
    """Break a duration into notatable pieces, respecting where it starts."""
    table = _duration_table(divisions)
    pieces, position, remaining = [], start, ticks
    while remaining > 0:
        for value, name, dots, align in table:
            if value <= remaining and position % align == 0:
                pieces.append((value, name, dots))
                position += value
                remaining -= value
                break
        else:  # pragma: no cover - a 1-tick value always matches
            pieces.append((1, table[-1][1], 0))
            position += 1
            remaining -= 1
    return pieces


def quantize(
    notes: list,
    bpm: float,
    beat_offset: float,
    grid: int = 4,
    beats_per_measure: int = 4,
    trim_start: bool = True,
) -> tuple:
    """Snap notes to a rhythmic grid. Returns (events, divisions, start_tick).

    events are dicts with absolute tick positions; rests are filled in later.
    """
    divisions = grid  # ticks per quarter note
    seconds_per_beat = 60.0 / bpm
    tick_seconds = seconds_per_beat / grid

    placed = []
    for note in notes:
        start = round((note.onset_s - beat_offset) / tick_seconds)
        length = max(1, round(note.duration_s / tick_seconds))
        placed.append({"start": start, "ticks": length, "note": note})
    placed.sort(key=lambda e: e["start"])

    # Enforce monophony after snapping: two notes can quantize onto the same
    # tick, and a note can now overlap the next one.
    cleaned = []
    for event in placed:
        if cleaned and event["start"] < cleaned[-1]["start"] + cleaned[-1]["ticks"]:
            overlap_start = cleaned[-1]["start"]
            if event["start"] <= overlap_start:
                continue  # same tick: keep the earlier (longer) detection
            cleaned[-1]["ticks"] = event["start"] - overlap_start
        if event["ticks"] > 0:
            cleaned.append(event)

    if not cleaned:
        return [], divisions, 0

    measure_ticks = beats_per_measure * divisions
    if trim_start:
        origin = (cleaned[0]["start"] // measure_ticks) * measure_ticks
    else:
        origin = min(0, cleaned[0]["start"])
    for event in cleaned:
        event["start"] -= origin
    return cleaned, divisions, origin


def _build_measures(events: list, divisions: int, beats_per_measure: int) -> list:
    """Lay events out into measures, filling rests and splitting at barlines."""
    measure_ticks = beats_per_measure * divisions
    total = max(e["start"] + e["ticks"] for e in events)
    n_measures = -(-total // measure_ticks)  # ceil
    measures = [[] for _ in range(n_measures)]

    def emit(start: int, ticks: int, note=None):
        """Place a note or rest, splitting across barlines with ties."""
        position, remaining, first = start, ticks, True
        while remaining > 0:
            index = position // measure_ticks
            in_measure = position % measure_ticks
            chunk = min(remaining, measure_ticks - in_measure)
            for value, name, dots in _split_duration(in_measure, chunk, divisions):
                measures[index].append({
                    "kind": "note" if note else "rest",
                    "ticks": value, "type": name, "dots": dots, "note": note,
                    "tie_start": False, "tie_stop": not first,
                    "head": first,
                })
                first = False
                in_measure += value
            position += chunk
            remaining -= chunk

    cursor = 0
    for event in events:
        if event["start"] > cursor:
            emit(cursor, event["start"] - cursor)
        emit(event["start"], event["ticks"], event["note"])
        cursor = event["start"] + event["ticks"]

    tail = n_measures * measure_ticks - cursor
    if tail > 0:
        emit(cursor, tail)

    _link_ties(measures)
    return measures


def _link_ties(measures: list) -> None:
    """Set tie_start on any note piece whose successor is a continuation."""
    flat = [item for measure in measures for item in measure]
    for current, nxt in zip(flat, flat[1:]):
        current["tie_start"] = (
            current["kind"] == "note" and nxt["kind"] == "note" and nxt["tie_stop"]
        )


def _pitch_element(parent, midi: int, use_sharps: bool):
    step, alter = (SHARP_SPELL if use_sharps else FLAT_SPELL)[midi % 12]
    pitch = ET.SubElement(parent, "pitch")
    ET.SubElement(pitch, "step").text = step
    if alter:
        ET.SubElement(pitch, "alter").text = str(alter)
    ET.SubElement(pitch, "octave").text = str(midi // 12 - 1)


def render(
    doc: NoteDocument,
    bpm: float | None = None,
    grid: int = 4,
    beats_per_measure: int = 4,
    key: str = "auto",
    trim_start: bool = True,
    title: str | None = None,
) -> str:
    tempo_info = doc.tempo or {"bpm": 120.0, "beat_offset": 0.0, "source": "default"}
    use_bpm = bpm if bpm else float(tempo_info.get("bpm", 120.0))
    offset = 0.0 if bpm else float(tempo_info.get("beat_offset", 0.0))
    key_info = keysig.estimate(doc.notes) if key == "auto" else keysig.from_name(key)

    events, divisions, _ = quantize(
        doc.notes, use_bpm, offset, grid=grid,
        beats_per_measure=beats_per_measure, trim_start=trim_start,
    )
    measures = _build_measures(events, divisions, beats_per_measure) if events else []

    score = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(score, "work")
    ET.SubElement(work, "work-title").text = title or Path(doc.source).stem

    identification = ET.SubElement(score, "identification")
    encoding = ET.SubElement(identification, "encoding")
    ET.SubElement(encoding, "software").text = "trumpet-sheets"
    ET.SubElement(encoding, "encoding-description").text = (
        f"auto-transcribed; tempo {use_bpm:.1f} bpm ({tempo_info.get('source')}), "
        f"key {key_info['tonic']} {key_info['mode']}, grid 1/{grid * 4}"
    )

    part_list = ET.SubElement(score, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = "Bb Trumpet"
    ET.SubElement(score_part, "part-abbreviation").text = "Bb Tpt."
    instrument = ET.SubElement(score_part, "score-instrument", id="P1-I1")
    ET.SubElement(instrument, "instrument-name").text = "Bb Trumpet"
    midi_instrument = ET.SubElement(score_part, "midi-instrument", id="P1-I1")
    ET.SubElement(midi_instrument, "midi-program").text = "57"

    part = ET.SubElement(score, "part", id="P1")
    for index, items in enumerate(measures, start=1):
        measure = ET.SubElement(part, "measure", number=str(index))
        if index == 1:
            attributes = ET.SubElement(measure, "attributes")
            ET.SubElement(attributes, "divisions").text = str(divisions)
            key_el = ET.SubElement(attributes, "key")
            ET.SubElement(key_el, "fifths").text = str(key_info["fifths"])
            time_el = ET.SubElement(attributes, "time")
            ET.SubElement(time_el, "beats").text = str(beats_per_measure)
            ET.SubElement(time_el, "beat-type").text = "4"
            clef = ET.SubElement(attributes, "clef")
            ET.SubElement(clef, "sign").text = "G"
            ET.SubElement(clef, "line").text = "2"
            # The part is written pitch; tell MuseScore how to reach concert.
            transpose = ET.SubElement(attributes, "transpose")
            ET.SubElement(transpose, "diatonic").text = "-1"
            ET.SubElement(transpose, "chromatic").text = "-2"

            direction = ET.SubElement(measure, "direction", placement="above")
            dtype = ET.SubElement(direction, "direction-type")
            metronome = ET.SubElement(dtype, "metronome")
            ET.SubElement(metronome, "beat-unit").text = "quarter"
            ET.SubElement(metronome, "per-minute").text = str(int(round(use_bpm)))
            ET.SubElement(direction, "sound", tempo=str(int(round(use_bpm))))

        for item in items:
            if item["kind"] == "note" and item["head"]:
                fingering = item["note"].fingering
                direction = ET.SubElement(measure, "direction", placement="above")
                dtype = ET.SubElement(direction, "direction-type")
                words = ET.SubElement(dtype, "words")
                words.set("font-size", "9")
                words.text = fingering

            note_el = ET.SubElement(measure, "note")
            if item["kind"] == "rest":
                ET.SubElement(note_el, "rest")
            else:
                _pitch_element(note_el, item["note"].written_midi, key_info["use_sharps"])
            ET.SubElement(note_el, "duration").text = str(item["ticks"])
            if item["kind"] == "note":
                if item["tie_stop"]:
                    ET.SubElement(note_el, "tie", type="stop")
                if item["tie_start"]:
                    ET.SubElement(note_el, "tie", type="start")
            ET.SubElement(note_el, "voice").text = "1"
            ET.SubElement(note_el, "type").text = item["type"]
            for _ in range(item["dots"]):
                ET.SubElement(note_el, "dot")
            if item["kind"] == "note" and (item["tie_start"] or item["tie_stop"]):
                notations = ET.SubElement(note_el, "notations")
                if item["tie_stop"]:
                    ET.SubElement(notations, "tied", type="stop")
                if item["tie_start"]:
                    ET.SubElement(notations, "tied", type="start")

    ET.indent(score, space="  ")
    body = ET.tostring(score, encoding="unicode")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">\n' + body + "\n"
    )
