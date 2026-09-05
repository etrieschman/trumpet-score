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

# One sheet per song in the scores directory; working state goes in a hidden
# cache beside it.
DEFAULT_ROOT = Path("scores")
CACHE_DIR = ".cache"
NOTES_JSON = "notes.json"
MELODY_MIDI = "melody.mid"
SHEET_EXT = ".txt"


# Flags whose stored value is False when the flag is present.
NEGATED_FLAGS = {"harmonic_filter": "--no-harmonic-filter"}
# Not worth recording: they say where things went, not what was produced.
UNRECORDED = {"out", "from_notes", "audio", "force_separate", "force_detect",
              "model", "device", "name"}


def settings_used(args) -> str:
    """The non-default flags for this run, so a sheet says how to reproduce itself."""
    defaults = vars(build_parser().parse_args([]))
    flags = []
    for key, value in sorted(vars(args).items()):
        if key in UNRECORDED or value == defaults[key]:
            continue
        if isinstance(value, bool):
            flags.append(NEGATED_FLAGS.get(key, f"--{key.replace('_', '-')}"))
        else:
            text = str(value)
            flags.append(f"--{key.replace('_', '-')} "
                         f"{text if ' ' not in text else repr(text)}")
    return " ".join(flags)


def parse_time(value: str) -> float:
    """Accept either mm:ss or plain seconds."""
    if ":" in value:
        minutes, _, seconds = value.partition(":")
        return int(minutes) * 60 + float(seconds)
    return float(value)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("audio", nargs="?", help="input audio (mp3/m4a/wav/flac)")
    p.add_argument("--name", metavar="NAME",
                   help="output filename to use instead of the audio file's, so "
                        "several takes of one song can coexist")
    p.add_argument("--out", type=Path, default=None, metavar="DIR",
                   help=f"where to write the sheet (default: ./{DEFAULT_ROOT}/)")

    sep = p.add_argument_group("separation (slow, cached)")
    sep.add_argument("--stem", default=DEFAULT_STEM,
                     choices=["other", "vocals", "guitar", "piano", "drums", "bass", "none"],
                     help="which Demucs stem holds the melody (default: other)")
    sep.add_argument("--model", default=DEFAULT_MODEL, help="Demucs model name")
    sep.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    sep.add_argument("--shifts", type=int, default=1, metavar="N",
                     help="average N randomly time-shifted separation passes; "
                          "higher is cleaner and N times slower (default 1)")
    sep.add_argument("--force-separate", action="store_true", help="ignore cached stem")

    det = p.add_argument_group("detection (cached)")
    det.add_argument("--onset-threshold", type=float, default=0.5)
    det.add_argument("--frame-threshold", type=float, default=0.3)
    det.add_argument("--min-note-ms", type=float, default=60.0)
    det.add_argument("--force-detect", action="store_true", help="ignore cached detections")

    filt = p.add_argument_group("filtering (fast, re-run freely)")
    filt.add_argument("--start", type=parse_time, default=0.0, metavar="TIME",
                      help="ignore everything before this point (mm:ss or seconds)")
    filt.add_argument("--end", type=parse_time, default=None, metavar="TIME",
                      help="ignore everything after this point (mm:ss or seconds)")
    filt.add_argument("--melody-rule", default="contour",
                      choices=["contour", "top", "loudest"],
                      help="how to pick one line from overlapping notes: "
                           "contour follows the best-connected melodic path "
                           "(default), top takes the highest pitch, loudest the "
                           "strongest")
    filt.add_argument("--jump-penalty", type=float, default=0.35,
                      help="cost per semitone of leaping, for --melody-rule "
                           "contour. Higher clings to a smoother line")
    filt.add_argument("--rest-threshold", type=float, default=0.18,
                      help="how loud a note must be, relative to the loudest in "
                           "the track, to beat silence. Raise it to drop quiet "
                           "strays while the soloist rests")
    filt.add_argument("--min-dur", type=float, default=0.08,
                      help="drop notes shorter than this many seconds")
    filt.add_argument("--merge-gap", type=float, default=0.06,
                      help="join same-pitch notes separated by less than this")
    filt.add_argument("--low", type=int, default=45, help="lowest concert MIDI to keep")
    filt.add_argument("--high", type=int, default=88, help="highest concert MIDI to keep")
    filt.add_argument("--no-harmonic-filter", dest="harmonic_filter",
                      action="store_false",
                      help="keep detections that look like overtones of a lower note")
    filt.add_argument("--in-key", action="store_true",
                      help="drop notes outside the detected key (or --key). In "
                           "modal material an isolated out-of-key note is "
                           "usually an artifact, not a passing tone")
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
        name = args.name or Path(doc.source).stem
    else:
        if not args.audio:
            build_parser().error("an audio file is required (or use --from-notes)")
        source = Path(args.audio)
        name = args.name or source.stem
        work = root / CACHE_DIR / name
        work.mkdir(parents=True, exist_ok=True)

        stem_path = separate(source, work, stem=args.stem, model_name=args.model,
                             device=args.device, shifts=args.shifts,
                             force=args.force_separate)
        events = detect(stem_path, work,
                        onset_threshold=args.onset_threshold,
                        frame_threshold=args.frame_threshold,
                        min_note_ms=args.min_note_ms,
                        force=args.force_detect)
        notes = melody.build_notes(
            events, rule=args.melody_rule, low=args.low, high=args.high,
            min_dur=args.min_dur, merge_gap=args.merge_gap,
            octave_shift=args.octave_shift, flats=not args.sharps,
            harmonic_filter=args.harmonic_filter,
            start_s=args.start, end_s=args.end,
            jump_penalty=args.jump_penalty, rest_score=args.rest_threshold)

        if args.in_key and notes:
            from trumpet_transcribe import keysig
            key_info = (keysig.estimate(notes) if args.key == "auto"
                        else keysig.from_name(args.key))
            kept = melody.filter_to_key(notes, key_info)
            print(f"[in-key] {len(notes) - len(kept)} of {len(notes)} notes dropped "
                  f"as outside {key_info['tonic']} {key_info['mode']}")
            notes = kept

        doc = NoteDocument(
            source=str(source), notes=notes,
            params={k: (str(v) if isinstance(v, Path) else v)
                    for k, v in vars(args).items() if k not in UNRECORDED},
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        doc.to_json(work / NOTES_JSON)
        midi_out.write_melody(doc.notes, work / MELODY_MIDI)

    root.mkdir(parents=True, exist_ok=True)
    sheet = render_text.render(doc, phrase_gap=args.phrase_gap,
                               max_per_line=args.max_per_line,
                               show_octaves=not args.bare_names,
                               key=args.key, force_sharps=args.sharps)
    path = root / f"{name}{SHEET_EXT}"
    path.write_text(sheet)

    print()
    print(sheet)
    print(f"[done] {len(doc.notes)} notes -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
