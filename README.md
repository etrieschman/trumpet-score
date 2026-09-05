# trumpet-score

Turns a recording into a note sheet for **written Bb trumpet**: the melody with
valve fingerings under every note, the key, and its scale. No rhythm notation —
rhythm comes by ear with the track playing.

```
KEY    E dorian written   (D dorian concert)

       the scale, to jam on:
         B3  C#4    D4   E4   F#4  G4  A4   B4  C#5  D5  E5  F#5  G5  A5
         2   1-2-3  1-3  1-2  2    0   1-2  2   1-2  1   0   2    0   1-2

       notes actually detected, most-played first:
         E 17%  B 15%  A 10%  D 9%  F# 8%  G 7%

------------------------------------------------------------------------

  1:33   B4  A4   B4  E4
         2   1-2  2   1-2

  1:36   E4   G#4~  B4  A4   B4  E4   G4  B4  A4   B4  D5  C#5
         1-2  2-3   2   1-2  2   1-2  0   2   1-2  2   1   1-2
```

`*` marks a pitch outside the playable range, `~` one outside the detected key.

## Install

```bash
uv sync
```

Python 3.11+; uv fetches one if needed. No ffmpeg: `soundfile` reads
wav/flac/ogg/mp3, and `.m4a`/AAC goes through macOS's `afconvert`.

## Use

```bash
uv run transcribe.py song.mp3
```

The first run downloads Demucs weights (~300 MB) and separates the track. Both
are cached, so later runs on the same file return in under a second.

```bash
uv run transcribe.py song.mp3 --min-dur 0.15 --phrase-gap 0.7
```

Runs are reproducible, and each sheet records the flags that produced it.

## Output

One file per song in `./scores/`:

```
scores/
  So What.txt              the note sheet
  .cache/
    So What/               working state, safe to delete
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

## How it works

| stage | |
| --- | --- |
| separation | Demucs isolates one stem from the mix |
| detection | basic-pitch (ONNX) emits polyphonic note events |
| melody | Viterbi path over the events: a note earns its amplitude and pays per semitone of leap from the line so far |
| filtering | overtone suppression, length and range filters, merging of held notes |
| key | Krumhansl-Schmuckler over a duration-weighted pitch-class histogram, across major, minor, dorian and mixolydian |
| rendering | phrase lines broken on silence, fingerings aligned beneath |

Written range is F#3–C6; anything outside is marked and left unfingered. Where a
note has several valid fingerings the sheet shows the first choice, and
`notes.json` carries the alternates.

The **notes actually detected** row is measured from the recording rather than
fitted, so it holds when the key label is wrong.

## Flags

**Separation** (slow, cached)

| flag | |
| --- | --- |
| `--model` | Demucs model. `htdemucs_6s` (default) splits six stems, so guitar and piano leave `other`; `htdemucs_ft` is four stems and four times slower |
| `--stem` | which stem to transcribe: `other` (default, holds horns), `vocals`, `bass`, `none` to skip separation |
| `--shifts N` | average N randomly time-shifted passes; N times slower |
| `--force-separate` | ignore the cached stem |
| `--name` | output filename, so several readings of one song can coexist |

**Detection** (cached): `--onset-threshold`, `--frame-threshold`,
`--min-note-ms` — lower to catch more notes and more garbage. `--force-detect`
ignores the cache.

**Melody and filtering** (fast, re-run freely)

| flag | |
| --- | --- |
| `--melody-rule` | `contour` (default) follows the best-connected line; `top` takes the highest pitch, `loudest` the strongest |
| `--rest-threshold` | how loud a note must be to beat silence (0.18) |
| `--jump-penalty` | cost per semitone of leaping (0.35) |
| `--start` / `--end` | restrict to a window, `mm:ss` or seconds |
| `--min-dur` | drop notes shorter than N seconds (0.08) |
| `--merge-gap` | join same-pitch notes closer than N seconds (0.06) |
| `--octave-shift` | move everything by N octaves |
| `--in-key` | drop notes outside the detected key |
| `--low` / `--high` | concert MIDI bounds |
| `--no-harmonic-filter` | keep detections that look like overtones |

**Rendering**: `--phrase-gap` (silence that starts a new line, 1.0s),
`--max-per-line`, `--bare-names`, `--sharps`, `--key` (e.g. `--key "D dorian"`).

## Tuning

Judge a change against a passage you already know by ear. Note count and `~`
count are both poor proxies: accompaniment bleed sits in the same key and
register as the melody, so neither number sees it.

To trade precision for recall:

```bash
uv run transcribe.py song.mp3 --onset-threshold 0.25 --frame-threshold 0.15 --min-note-ms 30
```

`--rest-threshold` is the first knob for strays while the soloist rests: it
raises how prominent a note must be to interrupt silence, without touching the
line. `--merge-gap` matters most for fast playing, since it fuses same-pitch
notes closer together than its value. `--in-key` and `--low` are blunter — they
clean modal material well but drop real accidentals and real low notes.

## Source audio quality

Demucs is a **stereo** model trained on full-bandwidth audio. Mono input denies
it the spatial cue it uses to separate instruments, and a low bitrate strips the
high harmonics a pitch model needs to tell a fundamental from an overtone.
Low-quality sources leave gaps no setting recovers. Use a stereo rip.

## Known limitations

1. **Demucs has no horn stem.** A trumpet lands in `other` with strings, organ
   and sax. This is the ceiling on quality for a dense mix.
2. **Octave errors.** Overtone suppression catches most, not all. A whole
   passage flagged out of range means a global octave error — try
   `--octave-shift`.
3. **Repeated notes merge.** Fast tongued notes at one pitch become one.
4. **One key per recording.** A tune that modulates gets a single label;
   `--key` overrides.
5. **`--start`/`--end` are not a clean slice.** The melody path is chosen from
   whatever notes compete, so windowing can shift results in dense passages.

## Tests

```bash
uv run tests/test_pipeline.py
```

Covers the fingering chart, transposition, overtone suppression, contour
tracking, note merging, phrase splitting, column alignment, key and mode
detection, scale generation, the sheet header, cache keying, and an end-to-end
run against synthetic audio with known pitches (`tests/make_fixture.py`).

## Sheet music

Not built. CLAUDE.md records the approach and where the earlier implementation
lives.
