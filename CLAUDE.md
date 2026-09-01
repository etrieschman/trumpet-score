# trumpet-sheets — working notes

Turn a recording into a Bb trumpet part: a monospace note sheet (stage 1) and
quantized MusicXML (stage 2). See README.md for usage.

## Status

**Stage 1 — done and verified.** Separation, detection, filtering, transposition,
fingerings, text sheet, MIDI byproducts, caching. 9 tests pass, including an
end-to-end run against synthetic audio with known pitches.

**Stage 2 — working, not yet hardened.** MusicXML renders and parses cleanly in
music21; key and tempo are detected automatically so a plain run needs no input.
Never yet opened in MuseScore by a human, and the tempo detector is the weak
spot (see TODO).

## Architecture

`notes.json` is the contract. Analysis writes it; renderers read only it and
never touch audio. Adding a renderer means adding a module and a `--format`
choice — nothing else moves.

```
audio.py      decode (no ffmpeg; afconvert for m4a)
separate.py   Demucs htdemucs_6s -> stem wav        [cached in <out>/stems/]
detect.py     basic-pitch -> raw note events        [cached in raw_notes.json]
melody.py     harmonic suppression, monophonic reduction, filtering, merging
tempo.py      beat-track the mix, refine against note onsets
keysig.py     Krumhansl-Schmuckler key estimate
trumpet.py    concert->written transpose, fingering chart, range check
intermediate.py    the notes.json schema (v2)
render_text.py     stage 1 sheet
render_musicxml.py stage 2 score
```

## TODO

1. **Tempo detection is the weak link, as expected.** On So What it reports
   195 bpm (true is ~136) with `confidence 0.674`. The confidence number is
   meaningful — below ~0.85 the tempo should not be trusted. Next steps: warn
   loudly in the CLI when confidence is low, and try metrical relatives of the
   reported value over a longer onset window. `--bpm` is the escape hatch and
   works.
2. **No triplet support.** `--grid` is 2/4/8 only; a triplet passage gets
   mangled into 16ths. Proper support needs `<time-modification>` in the
   MusicXML emitter and a triplet-aware duration table. Matters for jazz.
3. **Time signature is assumed 4/4.** `--beats-per-measure` changes the count
   but the beat unit is always a quarter, so 6/8 is not expressible.
4. **Syncopation is notated conservatively.** A note landing off the beat
   becomes tied pieces (dotted eighth + 16th). That is correct notation, but
   worth eyeballing in MuseScore to see whether it reads well.
5. **No stage 2 tests yet.** Stage 1 has coverage; `render_musicxml.py` and
   `tempo.py` are verified only by hand against the fixture. Worth adding: a
   quantization test, a duration-decomposition test, and a music21 round-trip.
   `music21` is installed in the venv for exactly this but is not in
   requirements.txt yet.
6. **Open the output in MuseScore and look at it.** Never done.

## Things learned the hard way

- `uv venv` does not install pip. Use `VIRTUAL_ENV=.venv uv pip install ...`.
- basic-pitch pins `resampy<0.4.3`; that resampy imports `pkg_resources`, which
  setuptools 81 removed. Hence `setuptools<81` in requirements.
- Voice Memos' group container is TCC-protected — unreadable even by `head`.
  Recordings must be dragged out to `~/Downloads` first.
- Grid-fit tempo scoring must measure error in SECONDS. Normalizing by the grid
  step rewards slow tempos, because a coarser grid tolerates more jitter, and
  the detector will confidently report half the true tempo.
