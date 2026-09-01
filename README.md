# trumpet-transcribe

Takes a recording, isolates the melody, and prints a monospace note sheet in
**written Bb trumpet pitch** with the valve fingering under every note. No
rhythm notation — you get rhythm by ear with the track playing.

```
  0:15   A4   B4  G4  A4   G4  E4   D4   F4  E4   C4  B3  D4
         1-2  2   0   1-2  0   1-2  1-3  1   1-2  0   2   1-3
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

## Output

Two files per song, named after it, in `./scores/`:

```
scores/
  So What.txt              <- the note sheet
  So What.musicxml         <- the score, opens in MuseScore
  .cache/
    So What/               <- working state, safe to delete
      stems/other.wav      cached separation (the slow step)
      raw_notes.json       cached detections
      notes.json           the intermediate
      raw.mid, melody.mid  MIDI byproducts
```

`--out DIR` puts the sheet somewhere else. `--format text` writes only the text
sheet. Deleting `.cache/` costs you nothing but time.

`notes.json` is the contract: both renderers read only that file and never touch
audio. Re-render from it without redoing any analysis:

```bash
.venv/bin/python transcribe.py --from-notes "scores/.cache/So What/notes.json" --max-per-line 8
```

## Flags worth knowing

**Separation** (slow, cached): `--stem` picks which Demucs stem holds the
melody — `other` by default, which is where horns land. Use `--stem vocals` if
the melody is sung, `--stem none` to skip separation entirely. `--force-separate`
busts the cache.

**Detection** (cached): `--onset-threshold` / `--frame-threshold` — lower to
catch more notes and more garbage. `--force-detect` busts the cache.

**Filtering** (fast, re-run freely):

- `--min-dur` drops notes shorter than N seconds (default 0.08) — raise it to kill blips
- `--merge-gap` joins same-pitch notes separated by less than N seconds (default 0.06)
- `--melody-rule top|loudest` — `top` keeps the highest voice, `loudest` the strongest
- `--octave-shift N` moves everything by N octaves, for when the detector locks onto the wrong partial
- `--no-harmonic-filter` disables overtone suppression (see below)
- `--low` / `--high` concert MIDI bounds for discarding garbage

**Rendering**: `--phrase-gap` (silence that starts a new line, default 1.0s),
`--max-per-line`, `--bare-names` (print `G` not `G4`), `--sharps`.

## Range and fingerings

Written range is F#3–C6. Anything outside is marked `*` with `--` for a
fingering rather than emitting something unplayable. Where a note has several
valid fingerings the sheet shows the first choice; the alternates are in
`notes.json`.

## Known limitations

1. **Demucs has no horn stem.** A trumpet lands in `other` together with
   strings, organ, and sax. `htdemucs_6s` at least pulls guitar and piano out of
   that stem. On a dense mix this is the weakest step in the whole pipeline.
2. **Octave errors.** Brass overtones are strong enough that the detector
   reports partials as their own notes. `suppress_harmonics` drops detections
   sitting an octave (or 12th, or two octaves) above a louder overlapping note,
   which fixes most of it. A whole passage flagged out of range usually means a
   global octave error — try `--octave-shift`.
3. **Repeated notes merge.** Two tongued notes at the same pitch, played fast,
   become one. Not separable from pitch alone without onset strength.
4. **Melody reduction is a heuristic.** `top` is right for a lead line most of
   the time and wrong when the lead sits under a harmony part.
5. **Accidental spelling has no key context.** You get `Gb4` where a reading
   trumpet player would write `F#4`. `--sharps` flips the global preference.

## Tests

```bash
.venv/bin/python tests/test_pipeline.py
```

Covers the fingering chart, transposition, harmonic suppression, note merging,
phrase splitting, column alignment, and an end-to-end run against synthetic
audio with known pitches (`tests/make_fixture.py`).

## Stage 2 (not built)

MusicXML output with quantized rhythm and fingerings above the staff. It slots
in as a new `trumpet_transcribe/render_musicxml.py` plus a `--format` branch in
the CLI; nothing else moves, since `notes.json` already carries durations.
Expect quantization to be the weak link — supplying a known BPM will beat
trying to beat-track the mix.
