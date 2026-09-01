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

from trumpet_transcribe import melody, midi_out, render_musicxml, render_text, tempo
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
    ren.add_argument("--format", default="both", choices=["text", "musicxml", "both"],
                     help="which renderers to run (default: both)")

    score = p.add_argument_group("sheet music (stage 2)")
    score.add_argument("--bpm", type=float,
                       help="override the detected tempo")
    score.add_argument("--grid", type=int, default=4, choices=[2, 4, 8],
                       help="quantization grid per beat: 2=8ths, 4=16ths, 8=32nds")
    score.add_argument("--beats-per-measure", type=int, default=4)
    score.add_argument("--key", default="auto",
                       help="key signature, e.g. F, Bb, 'D minor' (default: detected)")
    score.add_argument("--no-trim-start", dest="trim_start", action="store_false",
                       help="keep the empty measures before the first note")
    score.add_argument("--title", help="score title (default: the filename)")
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
        print("[tempo] beat-tracking the mix, then fitting to the detected notes")
        tempo_info = tempo.estimate(source, [n.onset_s for n in notes], grid=args.grid)
        confidence = tempo_info.get("confidence")
        print(f"[tempo] {tempo_info['bpm']} bpm "
              f"({tempo_info['source']}, fit {confidence})")
        if args.bpm:
            print(f"[tempo] overridden by --bpm {args.bpm}; the score will use that")
        elif confidence is not None and confidence < 0.85:
            print(f"[tempo] LOW CONFIDENCE ({confidence}). The rhythm in the score is "
                  f"probably wrong -- pass --bpm if you know the tempo.")

        doc = NoteDocument(
            source=str(source),
            notes=notes,
            tempo=tempo_info,
            params={k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()
                    if k not in {"out", "from_notes"}},
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        doc.to_json(work / NOTES_JSON)
        midi_out.write_melody(doc.notes, work / MELODY_MIDI)

    if doc.tempo is None:
        # A v1 document, or one rendered without audio: fit a grid to the onsets.
        doc.tempo = tempo.estimate_from_onsets([n.onset_s for n in doc.notes])
        print(f"[tempo] no stored tempo; estimated {doc.tempo['bpm']} bpm from onsets")

    root.mkdir(parents=True, exist_ok=True)
    written = []
    if args.format in ("text", "both"):
        sheet = render_text.render(doc, phrase_gap=args.phrase_gap,
                                   max_per_line=args.max_per_line,
                                   show_octaves=not args.bare_names)
        path = root / f"{name}.txt"
        path.write_text(sheet)
        written.append(path)
        print()
        print(sheet)

    if args.format in ("musicxml", "both"):
        score = render_musicxml.render(doc, bpm=args.bpm, grid=args.grid,
                                       beats_per_measure=args.beats_per_measure,
                                       key=args.key, trim_start=args.trim_start,
                                       title=args.title)
        path = root / f"{name}.musicxml"
        path.write_text(score)
        written.append(path)

    print(f"[done] {len(doc.notes)} notes")
    for path in written:
        print(f"       {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
