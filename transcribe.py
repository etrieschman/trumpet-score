#!/usr/bin/env python3
"""Learn a melody on trumpet: mp3 -> note sheet with valve fingerings.

    python transcribe.py song.mp3 --out ./output

Separation and detection results are cached under --out, so re-running with
different filter settings is fast.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from trumpet_transcribe import melody, midi_out, render_text
from trumpet_transcribe.detect import detect
from trumpet_transcribe.intermediate import NoteDocument
from trumpet_transcribe.separate import DEFAULT_MODEL, DEFAULT_STEM, separate

# Deliverables land in the scores directory, one file per song. Everything
# else -- stems, raw detections, the intermediate, MIDI -- is working state and
# lives in a hidden cache beside them, so the folder you actually open stays
# readable.
DEFAULT_ROOT = Path("scores")
CACHE_DIR = ".cache"
NOTES_JSON = "notes.json"
MELODY_MIDI = "melody.mid"
SHEET_EXT = ".txt"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("audio", nargs="?", help="input audio (mp3/m4a/wav/flac)")
    p.add_argument("--out", type=Path, default=None, metavar="DIR",
                   help=f"where to write the sheet (default: ./{DEFAULT_ROOT}/)")

    sep = p.add_argument_group("separation (slow, cached)")
    sep.add_argument("--stem", default=DEFAULT_STEM,
                     choices=["other", "vocals", "guitar", "piano", "drums", "bass", "none"],
                     help="which Demucs stem holds the melody (default: other)")
    sep.add_argument("--model", default=DEFAULT_MODEL, help="Demucs model name")
    sep.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    sep.add_argument("--force-separate", action="store_true", help="ignore cached stem")

    det = p.add_argument_group("detection (cached)")
    det.add_argument("--onset-threshold", type=float, default=0.5)
    det.add_argument("--frame-threshold", type=float, default=0.3)
    det.add_argument("--min-note-ms", type=float, default=60.0)
    det.add_argument("--force-detect", action="store_true", help="ignore cached detections")

    filt = p.add_argument_group("filtering (fast, re-run freely)")
    filt.add_argument("--melody-rule", default="top", choices=["top", "loudest"])
    filt.add_argument("--min-dur", type=float, default=0.08,
                      help="drop notes shorter than this many seconds")
    filt.add_argument("--merge-gap", type=float, default=0.06,
                      help="join same-pitch notes separated by less than this")
    filt.add_argument("--low", type=int, default=45, help="lowest concert MIDI to keep")
    filt.add_argument("--high", type=int, default=88, help="highest concert MIDI to keep")
    filt.add_argument("--no-harmonic-filter", dest="harmonic_filter",
                      action="store_false",
                      help="keep detections that look like overtones of a lower note")
    filt.add_argument("--octave-shift", type=int, default=0, help="shift result by N octaves")

    ren = p.add_argument_group("rendering")
    ren.add_argument("--phrase-gap", type=float, default=1.0,
                     help="silence in seconds that starts a new phrase line")
    ren.add_argument("--max-per-line", type=int, default=12)
    ren.add_argument("--bare-names", action="store_true",
                     help="print G instead of G4 (loses octave information)")
    ren.add_argument("--sharps", action="store_true", help="spell accidentals with sharps")
    ren.add_argument("--from-notes", type=Path, metavar="NOTES_JSON",
                     help="skip all analysis and re-render an existing notes.json")
    ren.add_argument("--key", default="auto",
                     help="key for the header, e.g. F, Bb, 'D minor' (default: detected)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root: Path = args.out or DEFAULT_ROOT

    if args.from_notes:
        doc = NoteDocument.from_json(args.from_notes)
        name = Path(doc.source).stem
    else:
        if not args.audio:
            build_parser().error("an audio file is required (or use --from-notes)")
        source = Path(args.audio)
        name = source.stem
        work = root / CACHE_DIR / name
        work.mkdir(parents=True, exist_ok=True)

        stem_path = separate(source, work, stem=args.stem, model_name=args.model,
                             device=args.device, force=args.force_separate)
        events = detect(stem_path, work,
                        onset_threshold=args.onset_threshold,
                        frame_threshold=args.frame_threshold,
                        min_note_ms=args.min_note_ms,
                        force=args.force_detect)
        notes = melody.build_notes(events, rule=args.melody_rule, low=args.low,
                                   high=args.high, min_dur=args.min_dur,
                                   merge_gap=args.merge_gap,
                                   octave_shift=args.octave_shift,
                                   flats=not args.sharps,
                                   harmonic_filter=args.harmonic_filter)
        doc = NoteDocument(
            source=str(source),
            notes=notes,
            params={k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()
                    if k not in {"out", "from_notes"}},
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        doc.to_json(work / NOTES_JSON)
        midi_out.write_melody(doc.notes, work / MELODY_MIDI)

    root.mkdir(parents=True, exist_ok=True)
    sheet = render_text.render(doc, phrase_gap=args.phrase_gap,
                               max_per_line=args.max_per_line,
                               show_octaves=not args.bare_names,
                               key=args.key)
    path = root / f"{name}{SHEET_EXT}"
    path.write_text(sheet)

    print()
    print(sheet)
    print(f"[done] {len(doc.notes)} notes -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
