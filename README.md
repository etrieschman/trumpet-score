# trumpet-score

Turns a recording into a note sheet for **written Bb trumpet**: the melody with
valve fingerings under every note, the key, and its scale. No rhythm notation —
you get rhythm by ear with the track playing.

```
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

`*` marks a pitch outside the playable range, `~` a pitch outside the detected
key.

## Install

```bash
uv sync
```

Needs Python 3.11+ — macOS's built-in 3.9 is too old for current torch/demucs;
uv fetches one if needed.

No ffmpeg needed. `soundfile` handles wav/flac/ogg/mp3; `.m4a`/AAC is decoded
with `afconvert`, which ships with macOS.

## Use

```bash
uv run transcribe.py song.mp3
```

The first run downloads Demucs weights (~300 MB) and separates the track; both
are cached, so later runs against the same file return in under a second.

```bash
uv run transcribe.py song.mp3 --min-dur 0.15 --phrase-gap 0.7
```

Runs are reproducible, and each sheet records the flags that produced it.

## Output

One file per song in `./scores/`:

```
scores/
  So What.txt              <- the note sheet
  .cache/
    So What/               <- working state, safe to delete
      stems/other.wav      cached separation
      raw_notes.json       cached detections
      notes.json           the intermediate
      raw.mid, melody.mid  MIDI byproducts
```

`--out DIR` writes elsewhere. `notes.json` is the contract — the renderer reads
only that and never touches audio:

```bash
uv run transcribe.py --from-notes "scores/.cache/So What/notes.json" --max-per-line 8
```

## Flags

**Separation** (slow, cached). `--model` selects the Demucs model:
`htdemucs_6s` (default) splits six stems, so guitar and piano leave `other`;
`htdemucs_ft` is a fine-tuned bag of four models — four times slower, four stems
rather than six, and on test material it read worse: more notes, but the extras
were accompaniment. Judge a model change by playing the passage, not by counting
notes or `~` marks — accompaniment bleed is in the same key as the melody, so
neither number sees it.

`--stem` chooses what to transcribe: `other` (default) holds horns, `vocals` a sung line, `bass` a bass line — pair that with
`--octave-shift 1` to reach trumpet register. `--stem none` skips separation.
`--force-separate` busts the cache. `--name` writes to a different filename, so
several readings of one song can coexist. `--shifts N` averages N randomly
time-shifted separation passes — Demucs's shift trick, N times slower, and on
a low-quality source it changes almost nothing.

**Detection** (cached). `--onset-threshold`, `--frame-threshold`,
`--min-note-ms` — lower to catch more notes and more garbage. `--force-detect`
busts the cache.

**Filtering** (fast, re-run freely):

| flag | |
| --- | --- |
| `--start` / `--end` | restrict to a window, `mm:ss` or seconds |
| `--min-dur` | drop notes shorter than N seconds (0.08) |
| `--merge-gap` | join same-pitch notes closer than N seconds (0.06) |
| `--melody-rule` | `top` keeps the highest voice, `loudest` the strongest |
| `--octave-shift` | move everything by N octaves |
| `--low` / `--high` | concert MIDI bounds for discarding garbage |
| `--no-harmonic-filter` | disable overtone suppression |

**Rendering**: `--phrase-gap` (silence that starts a new line, 1.0s),
`--max-per-line`, `--bare-names`, `--sharps`, `--key` (e.g. `--key "D dorian"`).

## Tuning

Defaults favour precision. To trade that for recall:

```bash
uv run transcribe.py song.mp3 --onset-threshold 0.25 --frame-threshold 0.15 --min-note-ms 30
```

Judge the result against a passage you already know by ear — note count is a
poor proxy for correctness. `--merge-gap` matters most for fast playing, since
it fuses same-pitch notes closer together than its value. `--low` cuts a
register the melody never enters, the cheapest way to drop accompaniment bleed.
Notes marked `~` are the first to distrust.

## How it works

| stage | |
| --- | --- |
| separation | Demucs `htdemucs_6s` isolates a stem |
| detection | basic-pitch (ONNX) emits polyphonic note events |
| filtering | overtone suppression, reduction to one voice, length and range filters, merging of held notes |
| key | Krumhansl-Schmuckler over a duration-weighted pitch-class histogram, across major, minor, dorian and mixolydian |
| rendering | phrase lines broken on silence, fingerings aligned beneath |

Written range is F#3–C6; anything outside is marked and left unfingered rather
than emitted as something unplayable. Where a note has several valid fingerings
the sheet shows the first choice and `notes.json` carries the alternates.

The **notes actually detected** row is measured, not fitted, so it stands even
when the key label is wrong.

## Source audio quality

This matters more than any flag. Demucs is a **stereo** model trained on
full-bandwidth audio: mono input denies it the spatial cue it uses to tell
instruments apart, and a low bitrate strips the high harmonics a pitch model
needs to distinguish a fundamental from an overtone. Low-quality sources leave
gaps no threshold setting can recover. Use a stereo rip.

## Known limitations

1. **Demucs has no horn stem.** A trumpet lands in `other` with strings, organ
   and sax. This is the ceiling on quality for a dense mix.
2. **Octave errors.** Overtone suppression fixes most, not all. A whole passage
   flagged out of range usually means a global octave error — try
   `--octave-shift`.
3. **Repeated notes merge.** Fast tongued notes at one pitch become one.
4. **Melody reduction is a heuristic.** `top` is wrong when the lead sits under
   a harmony part.
5. **One key per recording.** A tune that modulates gets a single label.
   `--key` overrides.
6. **`--start`/`--end` are not a clean slice.** Reduction picks a winner per
   frame from whatever competes, so windowing can shift results in dense
   passages.

## Tests

```bash
uv run tests/test_pipeline.py
```

Covers the fingering chart, transposition, overtone suppression, note merging,
phrase splitting, column alignment, key and mode detection, scale generation,
the sheet header, and an end-to-end run against synthetic audio with known
pitches (`tests/make_fixture.py`).

## Sheet music

Not built — the text sheet plus the recording is faster to learn from. CLAUDE.md
records the approach if it is ever wanted.
