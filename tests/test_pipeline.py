"""Checks for the parts that are cheap to get subtly wrong.

Run with pytest, or directly:  .venv/bin/python tests/test_pipeline.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trumpet_transcribe import keysig, melody, render_text, trumpet
from trumpet_transcribe.intermediate import Note, NoteDocument

# Concert -> (written name, first-choice fingering), checked against a standard chart.
CHART_SPOTS = [
    (58, "C4", "0"),    # concert Bb3 is written C, open
    (60, "D4", "1-3"),
    (64, "Gb4", "2"),
    (65, "G4", "0"),
    (70, "C5", "0"),
    (77, "G5", "0"),
    (82, "C6", "0"),    # top of the practical range
]


def test_transposition_and_fingerings():
    for concert, name, fing in CHART_SPOTS:
        written = trumpet.to_written(concert)
        assert trumpet.note_name(written) == name, (concert, name)
        assert trumpet.fingering(written) == fing, (concert, fing)


def test_range_flagging():
    assert trumpet.in_range(trumpet.WRITTEN_LOW)
    assert trumpet.in_range(trumpet.WRITTEN_HIGH)
    assert not trumpet.in_range(trumpet.WRITTEN_HIGH + 1)
    assert trumpet.fingering(trumpet.WRITTEN_HIGH + 1) == trumpet.OUT_OF_RANGE


def test_harmonic_suppression_drops_the_octave():
    # A fundamental plus a quieter octave partial over the same span.
    events = [[0.0, 1.0, 60, 0.9], [0.1, 0.6, 72, 0.5]]
    kept = melody.suppress_harmonics(events)
    assert [e[2] for e in kept] == [60]


def test_harmonic_suppression_keeps_a_real_octave_leap():
    # Sequential, non-overlapping: a genuine octave jump must survive.
    events = [[0.0, 0.5, 60, 0.9], [0.6, 1.1, 72, 0.9]]
    kept = melody.suppress_harmonics(events)
    assert [e[2] for e in kept] == [60, 72]


def test_merge_repeats_joins_split_held_notes():
    events = [[0.0, 0.5, 60, 0.8], [0.52, 1.0, 60, 0.8], [1.5, 2.0, 60, 0.8]]
    merged = melody.merge_repeats(events, merge_gap=0.06)
    assert len(merged) == 2
    assert merged[0][1] == 1.0          # first two joined
    assert merged[1][0] == 1.5          # the distant one stayed separate


def _note(onset, dur, concert):
    written = trumpet.to_written(concert)
    return Note(onset, dur, concert, trumpet.note_name(concert), written,
                trumpet.note_name(written), trumpet.fingering(written),
                trumpet.in_range(written))


def test_phrase_split_on_silence():
    notes = [_note(0.0, 0.4, 60), _note(0.5, 0.4, 62), _note(3.0, 0.4, 64)]
    lines = render_text.split_phrases(notes, phrase_gap=1.0, max_per_line=12)
    assert [len(l) for l in lines] == [2, 1]


def test_columns_stay_aligned_with_wide_fingerings():
    # written F#3 is 1-2-3, the widest cell; the row above must not shift.
    notes = [_note(0.0, 0.4, 52), _note(0.5, 0.4, 58)]
    sheet = render_text.render(NoteDocument(source="x", notes=notes))
    # Phrase rows come after the header's horizontal rule.
    body = sheet.split("---\n", 1)[-1]
    rows = [r for r in body.splitlines() if r and not r.startswith("#")]
    names, fings = rows[0], rows[1]
    assert "1-2-3" in fings
    # Each fingering starts at the same column as its note name.
    for cell in ("1-2-3", "0"):
        assert names[fings.index(cell)] != " ", (names, fings)


def test_key_detection_handles_modes():
    """A dorian tune must not be mislabelled as its relative major or minor."""
    # D dorian: the C major note set, but centred on D.
    scale = [62, 64, 65, 67, 69, 71, 72]
    notes = []
    for i, pitch in enumerate(scale + [62, 62, 69]):  # tonic and fifth emphasised
        notes.append(_note(i * 0.5, 0.5, pitch - trumpet.TRANSPOSE))
    info = keysig.estimate(notes)
    assert info["mode"] in ("dorian", "mixolydian"), info
    assert info["fifths"] == 0, info  # parent key is C major either way


def test_scale_spans_an_octave_with_room_either_side():
    info = keysig.from_name("F")
    pitches = keysig.scale_pitches(info)
    tonics = [p for p in pitches if p % 12 == info["tonic_pc"]]
    assert len(tonics) >= 2, "should cover a full octave of the tonic"
    assert min(pitches) < tonics[0] and max(pitches) > tonics[-1]
    assert all(trumpet.in_range(p) for p in pitches)


def test_sheet_header_names_the_key():
    notes = [_note(i * 0.5, 0.4, p) for i, p in enumerate([60, 62, 64, 65, 67])]
    sheet = render_text.render(NoteDocument(source="x", notes=notes))
    assert "KEY" in sheet
    assert "the scale, to jam on:" in sheet
    assert "notes actually detected" in sheet


def test_document_roundtrip(tmp_path=None):
    import tempfile
    tmp = Path(tmp_path or tempfile.mkdtemp())
    doc = NoteDocument(source="song.mp3", notes=[_note(0.0, 0.5, 60)], params={"min_dur": 0.08})
    doc.to_json(tmp / "notes.json")
    back = NoteDocument.from_json(tmp / "notes.json")
    assert back.notes[0].written_name == "D4"
    assert back.params["min_dur"] == 0.08


def test_end_to_end_on_fixture():
    """The whole pipeline on synthetic audio with known pitches."""
    import tempfile
    out = Path(tempfile.mkdtemp())
    fixture = ROOT / "tests" / "fixture.wav"
    if not fixture.exists():
        subprocess.run([sys.executable, str(ROOT / "tests" / "make_fixture.py")],
                       cwd=ROOT, check=True)
    subprocess.run(
        [sys.executable, str(ROOT / "transcribe.py"), str(fixture),
         "--out", str(out), "--stem", "none"],
        cwd=ROOT, check=True, capture_output=True,
    )
    # Deliverables sit in the output root; working state is cached beside them.
    assert (out / "fixture.txt").exists()
    doc = NoteDocument.from_json(out / ".cache" / "fixture" / "notes.json")
    expected_concert = [60, 62, 64, 65, 67, 69, 70, 72, 67, 65, 62, 60]
    assert [n.concert_midi for n in doc.notes] == expected_concert
    assert [n.fingering for n in doc.notes[:8]] == \
        ["1-3", "1-2", "2", "0", "1-2", "2", "0", "1"]
    assert all(n.in_range for n in doc.notes)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print(f"\n{'all passed' if not failures else f'{failures} failed'}")
    sys.exit(1 if failures else 0)
