# trumpet-score — working notes

Turn a recording into a Bb trumpet note sheet: written pitch, valve fingerings,
detected key. No rhythm notation — rhythm comes by ear with the track playing.
See README.md for usage.

## Status

**Done and verified.** Separation, detection, filtering, transposition,
fingerings, key detection, the text sheet, MIDI byproducts, caching. 12 tests
pass, including an end-to-end run against synthetic audio with known pitches.

Sheet-music output was built and then deliberately removed — see below.

## Architecture

`notes.json` is the contract. Analysis writes it; renderers read only it and
never touch audio. Adding a renderer means adding a module — nothing else moves.

```
audio.py      decode (no ffmpeg; afconvert for m4a)
separate.py   Demucs htdemucs_6s -> stem wav        [cached]
detect.py     basic-pitch -> raw note events        [cached]
melody.py     harmonic suppression, monophonic reduction, filtering, merging
keysig.py     Krumhansl-Schmuckler key + mode, scale generation
trumpet.py    concert->written transpose, fingering chart, range check
intermediate.py    the notes.json schema (v3)
render_text.py     the note sheet
```

## Output layout

One deliverable per song: `scores/<song>.txt`. All working state (stems, raw
detections, notes.json, MIDI) goes in `scores/.cache/<song>/` and is safe to
delete. `--out DIR` moves the root.

## TODO — sheet music, if it ever comes back

It was built (MusicXML, opened in MuseScore, fingerings above the staff) and
removed in favour of the text sheet. **The working implementation is in git
history: `git show 3fecc51`** — `render_musicxml.py` and `tempo.py`. Recover
rather than rewrite. What was there and what it needs:

1. **Restore the `tempo` field to the intermediate.** Schema went v2 -> v3 when
   it was dropped. Renderers must not touch audio, so tempo has to be detected
   during analysis and stored.
2. **Tempo detection was the blocker, and it is not solved.** The approach:
   beat-track the mix with librosa (Ellis dynamic programming), then score
   candidate tempos and their metrical relatives by how well the *detected note
   onsets* land on the grid. It got the synthetic fixture exactly right (100 bpm
   from a tracker that said 117) but reported 195 for So What (true ~136) and
   216 for Agua Fria (true ~108) — both roughly double. **Halving errors are the
   failure mode to attack first.** It emitted a confidence score that correctly
   flagged both failures, so gating on confidence and asking for `--bpm` is a
   reasonable fallback.
3. **Measure grid-fit error in SECONDS, not fractions of a grid step.** This
   caused a real bug: a coarser grid tolerates more absolute jitter, so
   normalized error systematically prefers half the true tempo.
4. **No triplet support.** `--grid` was 2/4/8 only. Needs
   `<time-modification>` in the emitter and a triplet-aware duration table.
   Matters for jazz.
5. **4/4 assumed.** The beat unit was always a quarter, so 6/8 was not
   expressible.
6. The duration decomposition (greedy longest-first, with each value required to
   align to its own undotted base) was the part that worked well — it notates
   syncopation as tied pieces correctly. Keep it.

## Other TODO

- Key detection assumes one key for the whole recording. So What's bridge
  modulates up a semitone and gets folded into one label.
- `--melody-rule loudest` is implemented but never evaluated against `top`.

## Things learned the hard way

- `uv venv` does not install pip. Use `VIRTUAL_ENV=.venv uv pip install ...`.
- basic-pitch pins `resampy<0.4.3`; that resampy imports `pkg_resources`, which
  setuptools 81 removed. Hence `setuptools<81` in requirements.
- Voice Memos' group container is TCC-protected — unreadable even by `head`.
  Recordings must be dragged out to `~/Downloads` first.
- Key detection needs modes, not just major/minor. The repertoire this gets
  pointed at is modal: So What is dorian, Agua Fria is dorian/mixolydian, and a
  major/minor-only fit mislabels both.
