# trumpet-transcribe

Takes a recording, isolates the melody, and prints a monospace note sheet in
**written Bb trumpet pitch** with the valve fingering under every note. No
rhythm notation — you get rhythm by ear with the track playing.

```
KEY    E dorian written   (D dorian concert)

       the scale, to jam on:
         B3  C#4    D4   E4   F#4  G4  A4   B4  C#5  D5  E5  F#5  G5  A5
         2   1-2-3  1-3  1-2  2    0   1-2  2   1-2  1   0   2    0   1-2

       notes actually detected, most-played first:
         D 22%  E 19%  A 15%  G 12%  B 11%  C# 9%  F# 8%

------------------------------------------------------------------------

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

- `--start` / `--end` restrict analysis to a window, in `mm:ss` or seconds — the
  fix when the melody instrument only plays part of the track. Timestamps stay
  absolute so they still line up with the recording
- `--min-dur` drops notes shorter than N seconds (default 0.08) — raise it to kill blips
- `--merge-gap` joins same-pitch notes separated by less than N seconds (default 0.06)
- `--melody-rule top|loudest` — `top` keeps the highest voice, `loudest` the strongest
- `--octave-shift N` moves everything by N octaves, for when the detector locks onto the wrong partial
- `--no-harmonic-filter` disables overtone suppression (see below)
- `--low` / `--high` concert MIDI bounds for discarding garbage

**Rendering**: `--phrase-gap` (silence that starts a new line, default 1.0s),
`--max-per-line`, `--bare-names` (print `G` not `G4`), `--sharps`,
`--key` (override the detected key, e.g. `--key "D dorian"`).

## Tuning

The defaults are tuned for precision. Loosening them captures more fast notes
and more junk; on a clean recording that trade is often worth it, on a phone
recording it usually is not. Check the raw-vs-final counts the run prints: if
raw detections double and the final count barely moves, the bottleneck is
separation, not sensitivity, and no threshold will fix it.

```bash
# more notes, more junk
--onset-threshold 0.3 --frame-threshold 0.2 --min-note-ms 30 --min-dur 0.04 --merge-gap 0.03
```

`--merge-gap` is the one that matters most for fast playing: it fuses same-pitch
notes closer together than its value, so repeated notes at speed vanish into
one. `--low` cuts a register you know the melody never enters, which is the
cheapest way to drop accompaniment bleed.

## The key header

The sheet opens with the detected key, the scale to jam on with fingerings, and
the pitch classes actually present in the recording.

Key detection is Krumhansl-Schmuckler: build a duration-weighted histogram of
the 12 pitch classes, then correlate it against a profile for each candidate
key and take the best fit. The profiles for major and minor are empirical, from
probe-tone listening experiments; dorian and mixolydian are derived by putting
the same ordered scale-degree weights on those modes\' degrees. Modes matter
here — a major/minor-only fit calls So What "E minor" instead of E dorian.

The **notes actually detected** row is not a model fit, it is measured from the
recording. When the key label looks wrong, trust that row.

## Range and fingerings

Written range is F#3–C6. Anything outside is marked `*` with `--` for a
fingering rather than emitting something unplayable. Where a note has several
valid fingerings the sheet shows the first choice; the alternates are in
`notes.json`.

## Known limitations

0. **Everything downstream inherits the separation quality.** A phone recording
   of a room is much harder than the original track.
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
5. **Key detection assumes one key for the whole recording.** A tune that
   modulates (So What's bridge goes up a semitone) gets a single label for all
   of it. `--key` overrides.

## Tests

```bash
.venv/bin/python tests/test_pipeline.py
```

Covers the fingering chart, transposition, harmonic suppression, note merging,
phrase splitting, column alignment, and an end-to-end run against synthetic
audio with known pitches (`tests/make_fixture.py`).

## Sheet music

Not built, deliberately — see CLAUDE.md for the approach if it ever gets picked
back up. The text sheet plus the recording is faster to learn from.