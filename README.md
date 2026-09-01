# trumpet-score

Takes a recording, isolates the melody, and prints a monospace note sheet in
**written Bb trumpet pitch** with the valve fingering under every note, plus the
key and its scale. No rhythm notation — you get rhythm by ear with the track
playing.

```
# Miles Davis So What.m4a
# Written Bb trumpet pitch (concert +2). First-choice fingerings.
# Phrase break at gaps > 1.0s.
# * = unplayable, shown as --.   ~ = outside the detected key, check these first.
# Settings: --frame-threshold 0.15 --min-note-ms 30.0 --onset-threshold 0.25

KEY    E dorian written   (D dorian concert)

       the scale, to jam on:
         B3  C#4    D4   E4   F#4  G4  A4   B4  C#5  D5  E5  F#5  G5  A5
         2   1-2-3  1-3  1-2  2    0   1-2  2   1-2  1   0   2    0   1-2

       notes actually detected, most-played first:
         E 17%  B 15%  F 15%  A 10%  D 9%  F# 8%  G 7%  A# 5%

------------------------------------------------------------------------

  1:33   B4  A4   B4  E4   E4   E4   G#4~  B4  E4   G#4~  B4  D5
         2   1-2  2   1-2  1-2  1-2  2-3   2   1-2  2-3   2   1
```

## Install

Needs Python 3.11 — macOS's built-in 3.9 is too old for current torch/demucs.

```bash
uv venv --python 3.11 .venv && VIRTUAL_ENV=.venv uv pip install -r requirements.txt
```

No ffmpeg needed. `soundfile` handles wav/flac/ogg/mp3; `.m4a`/AAC is decoded
with `afconvert`, which ships with macOS.

## Use

```bash
.venv/bin/python transcribe.py song.mp3
```

First run downloads the Demucs weights (~300 MB) and takes a while. Every run
after that against the same file is fast, because the slow steps are cached.

Re-run with different filter settings — this touches neither Demucs nor
basic-pitch and returns in well under a second:

```bash
.venv/bin/python transcribe.py song.mp3 --min-dur 0.15 --phrase-gap 0.7
```

Runs are **reproducible**: the same command on the same file gives the same
sheet, every time. Each sheet also records the flags that produced it, so a
result you liked can always be regenerated.

## Output

One file per song, named after it, in `./scores/`:

```
scores/
  So What.txt              <- the note sheet
  .cache/
    So What/               <- working state, safe to delete
      stems/other.wav      cached separation (the slow step)
      raw_notes.json       cached detections
      notes.json           the intermediate
      raw.mid, melody.mid  MIDI byproducts
```

`--out DIR` puts the sheet somewhere else. Deleting `.cache/` costs you nothing
but time.

`notes.json` is the contract: the renderer reads only that file and never
touches audio. Re-render from it without redoing any analysis:

```bash
.venv/bin/python transcribe.py --from-notes "scores/.cache/So What/notes.json" --max-per-line 8
```

## Flags worth knowing

**Separation** (slow, cached): `--stem` picks which Demucs stem to transcribe —
`other` by default, which is where horns land. `--stem vocals` if the line is
sung, `--stem bass` for a bass line (add `--octave-shift 1` or `2` to bring it
into trumpet register), `--stem none` to skip separation entirely.
`--force-separate` busts the cache.

`--name` writes to a different filename, so several readings of one song can
coexist — one sheet for the head, another for the solo.

**Detection** (cached): `--onset-threshold` / `--frame-threshold` / `--min-note-ms`
— lower to catch more notes and more garbage. `--force-detect` busts the cache.

**Filtering** (fast, re-run freely):

- `--start` / `--end` restrict analysis to a window, in `mm:ss` or seconds.
  Timestamps stay absolute so they still line up with the recording
- `--min-dur` drops notes shorter than N seconds (default 0.08) — raise it to kill blips
- `--merge-gap` joins same-pitch notes separated by less than N seconds (default 0.06)
- `--melody-rule top|loudest` — `top` keeps the highest voice, `loudest` the strongest
- `--octave-shift N` moves everything by N octaves
- `--no-harmonic-filter` disables overtone suppression
- `--low` / `--high` concert MIDI bounds for discarding garbage

**Rendering**: `--phrase-gap` (silence that starts a new line, default 1.0s),
`--max-per-line`, `--bare-names` (print `G` not `G4`), `--sharps`,
`--key` (override the detected key, e.g. `--key "D dorian"`).

## Tuning

The defaults favour precision. Loosening the detection thresholds trades that
for recall:

```bash
.venv/bin/python transcribe.py song.mp3 --onset-threshold 0.25 --frame-threshold 0.15 --min-note-ms 30
```

**Judge the result against a passage you already know by ear, not by note
count.** Note count is a bad proxy: on So What, loosening barely moved the
count while filling a five-second hole in the solo with exactly the right
figure. The count said "no improvement"; the notes said otherwise.

`--merge-gap` matters most for fast playing — it fuses same-pitch notes closer
together than its value, so repeated notes at speed collapse into one.
`--low` cuts a register you know the melody never enters, the cheapest way to
drop accompaniment bleed. Notes marked `~` are outside the detected key and are
the first things to distrust.

## The key header

The sheet opens with the detected key, that key's scale with fingerings, and the
pitch classes actually present in the recording.

Key detection is Krumhansl-Schmuckler: build a duration-weighted histogram of
the 12 pitch classes, then correlate it against a profile for each candidate key
and take the best fit. The major and minor profiles are empirical, from
probe-tone listening experiments; dorian and mixolydian are derived by putting
the same ordered scale-degree weights on those modes' degrees. Modes matter
here — a major/minor-only fit calls So What "E minor" instead of E dorian.

The **notes actually detected** row is not a model fit, it is measured from the
recording. When the key label looks wrong, trust that row.

## Range and fingerings

Written range is F#3–C6. Anything outside is marked `*` with `--` for a
fingering rather than emitting something unplayable. Where a note has several
valid fingerings the sheet shows the first choice; the alternates are in
`notes.json`.

## Source audio quality matters more than any flag

Demucs is a **stereo** model trained on full-bandwidth audio. Feed it mono and
it gets no spatial information — one of its main cues for telling instruments
apart. Feed it a low-bitrate file and the high harmonics are gone, and those are
exactly what a pitch model uses to distinguish a fundamental from an overtone,
so you get octave errors and missed notes.

A 62 kbps mono file of So What leaves multi-second holes in the solo that no
threshold setting can recover. Get a stereo rip before tuning anything.

## Known limitations

1. **Everything downstream inherits the separation quality**, and Demucs has no
   horn stem — a trumpet lands in `other` together with strings, organ and sax.
   `htdemucs_6s` at least pulls guitar and piano out of that stem. On a dense
   mix this is the weakest step in the pipeline and the real ceiling on quality.
2. **Octave errors.** Brass overtones are strong enough that the detector
   reports partials as their own notes. `suppress_harmonics` drops detections an
   octave (or 12th, or two octaves) above a louder overlapping note, which fixes
   most but not all of it. A whole passage flagged out of range usually means a
   global octave error — try `--octave-shift`.
3. **Repeated notes merge.** Two tongued notes at the same pitch, played fast,
   become one. Not separable from pitch alone without onset strength.
4. **Melody reduction is a heuristic.** `top` is right for a lead line most of
   the time and wrong when the lead sits under a harmony part.
5. **Key detection assumes one key for the whole recording.** A tune that
   modulates (So What's bridge goes up a semitone) gets a single label for all
   of it. `--key` overrides.
6. **`--start`/`--end` are not a clean slice.** Melody reduction picks a winner
   per frame from whatever notes compete, so windowing can change results in
   dense passages. When a full-track sheet works, scroll it rather than re-cut
   it.

## Tests

```bash
.venv/bin/python tests/test_pipeline.py
```

Covers the fingering chart, transposition, harmonic suppression, note merging,
phrase splitting, column alignment, key and mode detection, scale generation,
the sheet header, and an end-to-end run against synthetic audio with known
pitches (`tests/make_fixture.py`).

## Sheet music

Not built, deliberately — the text sheet plus the recording is faster to learn
from. A working MusicXML renderer exists in git history; CLAUDE.md records where
it is and what it would need.
