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

## What the tuning knobs actually buy

Measured, not guessed:

- Agua Fria (phone recording, dense mix): defaults 168 raw -> 70 notes. Loose
  settings 536 raw -> 105 notes. The extra 35 are mostly junk; defaults read
  better.
- So What solo (`--start 1:30 --low 58`): defaults 163 raw -> 31 notes. Loose
  settings 391 raw -> 35 notes. **Tripling raw detections bought 4 notes**,
  which says the bottleneck is separation quality, not detection sensitivity.
  The `other` stem still holds piano and sax alongside the trumpet.

These counts predate the determinism fix and will not reproduce exactly. The
rule they suggested — "if raw detections rise and the final count does not, the
bottleneck is separation" — proved WRONG on So What; see "Judge results against
ground truth" below.

## Ensembling: measured, mostly useless here

`--shifts N` restores Demucs's shift trick (N random time offsets, averaged).
It must stay seeded via `random.seed` — Demucs uses Python's `random`, not
torch, so `torch.manual_seed` alone does not make it reproducible.

Measured on Agua Fria: shifts 1 -> 4 -> 8 gave 72 -> 71 -> 72 notes. Same model
at 1 vs 8 shifts agrees on 71/72 notes, so there is no variance to average away.
Two *different* models (htdemucs_6s vs htdemucs) agree on only 57/72.

So error here is bias, not variance. Ensembling across shifts cannot help;
ensembling across diverse models plausibly could, and is unbuilt. Consensus
between two models would mark low-confidence notes the way `~` marks
out-of-key ones, at double the separation cost.

## --start/--end are not a clean slice

Windowing clips events that straddle a boundary rather than dropping them, so a
windowed run now matches the corresponding slice of a full run for most of its
length. It is still not guaranteed identical: melody reduction picks a winner
per frame from whatever events compete, so removing events changes outcomes in
dense passages. Measured on So What (`--start 1:30`): identical for the first 24
notes, diverging over the last ten seconds.

**When a full-track sheet is known good, scroll it rather than re-cutting it.**

## Picking a stem

The default `other` stem is right for horns and is what has worked on So What:
the trumpet enters around 1:30 and the full-track sheet at default settings is
the version that proved playable. `--stem bass` was tried on a hunch that the
head was the bass line; it was wrong. Do not re-theorise the arrangement —
ask which sheet worked.

## RoFormer is not an option for horns (verified)

Checked audio-separator's full catalogue: all 92 RoFormer models are 2-stem
target/residual separators. A listing of `['vocals', 'other']` means "vocals vs
everything else", NOT Demucs's musical `other` stem. Nothing there decomposes a
mix into drums/bass/other, so RoFormer cannot isolate a horn no matter how good
its SDR on vocals. The only models in the catalogue with a real multi-stem
`other` are the Demucs family.

audio-separator also hard-requires ffmpeg (it shells out in its constructor),
which is why ffmpeg is installed on this machine. Nothing in the project uses
it; `brew uninstall ffmpeg` is safe.

Untried Demucs variant worth a look: `hdemucs_mmi` (4-stem, in the catalogue).

## Other TODO

- Separating a horn from the `other` stem is the real ceiling on quality.
  Melodia was tried and removed (see below); RoFormer cannot do it (see above).
  A horn-specific separator would be the real fix and does not exist off-shelf.

- Melodia (Essentia predominant-melody) was built as a second pipeline with a
  consensus stage, then removed at the user's call: agreement with basic-pitch
  was 38/323 on So What, and the merged union read worse than basic-pitch alone.
  Recoverable from git if a second opinion on a disputed note is ever wanted.

- Key detection assumes one key for the whole recording. So What's bridge
  modulates up a semitone and gets folded into one label.
- `--melody-rule loudest` is implemented but never evaluated against `top`.

## Audio quality is the top-of-funnel constraint

The So What test file is 62 kbps MONO. Demucs is a stereo model, so mono
removes spatial separation cues entirely, and low bitrate strips the high
harmonics a pitch model needs to tell fundamentals from partials. Measured
consequence: a 2.3-second hole (91.15-93.47s) with zero detections at loose
thresholds, over a passage the user hears clearly. No parameter recovers this.
Ask for better source audio before tuning.

## Separation must stay deterministic

`apply_model(..., shifts=0)` in separate.py is load-bearing. Demucs defaults to
`shifts=1`, which applies a **random** time shift to the input; with one shift
there is nothing to average, so it only randomizes. Identical input and
settings produced different stems on every run, on MPS *and* CPU, silently
changing the transcription -- a good result could not be reproduced, and
re-running destroyed it. Verified fixed: two runs now yield identical stem
hashes. Do not remove the seed or restore the default shifts.

## Judge results against ground truth, not note counts

I concluded loose thresholds "did not help" So What because the final note count
barely moved (31 -> 35). That was the wrong measure. When the user supplied the
actual notes, loosening turned out to fill a five-second hole in the solo with
exactly the right figure. Count says nothing about correctness; only comparison
against known notes does.

## Things learned the hard way

- The project is a uv project: `uv sync` to set up, `uv run transcribe.py` to run.
  pyproject.toml is the source of truth; there is no requirements.txt.
- essentia is pinned to 2.1b6.dev1389: newer dev builds ship cp314 wheels only.
- basic-pitch pins `resampy<0.4.3`; that resampy imports `pkg_resources`, which
  setuptools 81 removed. Hence `setuptools<81` in requirements.
- Voice Memos' group container is TCC-protected — unreadable even by `head`.
  Recordings must be dragged out to `~/Downloads` first.
- Key detection needs modes, not just major/minor. The repertoire this gets
  pointed at is modal: So What is dorian, Agua Fria is dorian/mixolydian, and a
  major/minor-only fit mislabels both.
