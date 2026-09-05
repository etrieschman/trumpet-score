# trumpet-score — working notes

A recording in, a written-Bb-trumpet note sheet out: pitches, valve fingerings,
key, scale. No rhythm notation. See README.md for usage.

`uv sync` to set up, `uv run transcribe.py` to run. pyproject.toml is the source
of truth; there is no requirements.txt.

## Architecture

`notes.json` is the contract. Analysis writes it; renderers read only it and
never touch audio. A new renderer is a new module and nothing else moves.

```
audio.py         decode (no ffmpeg; afconvert for m4a)
separate.py      Demucs -> stem wav                    [cached]
detect.py        basic-pitch -> raw note events        [cached]
melody.py        contour tracking, overtone suppression, filters, merging
keysig.py        Krumhansl-Schmuckler key + mode, scale generation
trumpet.py       concert->written transpose, fingering chart, range check
intermediate.py  the notes.json schema (v5)
render_text.py   the note sheet
```

Deliverables go to `scores/<song>.txt`; working state to
`scores/.cache/<song>/`, which is disposable. `--out DIR` moves the root.

## Load-bearing details

**Separation determinism.** `separate.py` pins both `random.seed` and
`torch.manual_seed`. Demucs draws its time shifts from Python's `random`, so
seeding torch alone leaves runs unreproducible — identical inputs then yield
different stems and silently different transcriptions.

**Detection cache keys on stem content, not size.** Every separation model
writes a stem of identical size for a given input, so a size-keyed cache serves
one model's detections for another model's audio.

**Contour tracking keeps its pitch state through rests.** The Viterbi state is
the last pitch that sounded; resting preserves it. A rest state with free
transitions in and out lets any note rejoin the line after a 50ms gap, which is
the stray-note problem in disguise.

**Contour amplitudes are raw.** basic-pitch amplitudes are model confidences and
already comparable across tracks; normalising them by the track maximum makes
`--rest-threshold` mean something different per song.

**basic-pitch pins `resampy<0.4.3`**, and that resampy imports `pkg_resources`,
removed in setuptools 81. Hence `setuptools<81`.

## What has been ruled out

**RoFormer cannot isolate a horn.** All 92 RoFormer models in audio-separator
are 2-stem target/residual separators; a listing of `['vocals', 'other']` means
"vocals vs everything else", not Demucs's musical `other` stem. The only models
with a real multi-stem `other` are the Demucs family. audio-separator also
hard-requires ffmpeg, which is why ffmpeg is installed here; nothing in the
project uses it.

**Melodia as a second pipeline.** Essentia predominant-melody extraction plus a
consensus stage; agreement with basic-pitch was 38/323 on So What and the merged
union read worse than basic-pitch alone. Removed. In git history if a second
opinion on a disputed note is ever wanted.

**Shift ensembling.** `--shifts N` exists and does almost nothing here: the same
model at 1 vs 8 shifts agrees on 71/72 notes. The error is bias, not variance.
Two different models agree on only 57/72, so cross-model consensus is the
version that could work, and is unbuilt.

**htdemucs_ft as a default.** More notes, but the extras are accompaniment.
`htdemucs_6s` reads better on both test tracks. Worth trying when a specific
passage is missing.

## Evaluating changes

Note count and out-of-key rate are both poor proxies. Accompaniment bleed sits
in the same key and register as the melody, so neither number sees the failure
mode that matters. Ask for a passage the user knows by ear and compare against
it; every metric proposed here has at some point pointed the wrong way.

## TODO

- Separating a horn from the `other` stem is the real ceiling. No off-the-shelf
  horn separator exists.
- Sheet music: MusicXML with quantized rhythm and fingerings above the staff.
  A working implementation is at `git show 3fecc51` (`render_musicxml.py`,
  `tempo.py`) — recover rather than rewrite. Blocker is tempo: it reported 195
  bpm for So What (true ~136) and 216 for Agua Fria (true ~108), both roughly
  double. Halving errors are the thing to attack. Restoring it also means
  restoring a `tempo` field to the intermediate. No triplet support; 4/4 only.
- Key detection assumes one key per recording; So What's bridge modulates.
- `--melody-rule loudest` is implemented but never evaluated against `contour`.
- Voice Memos' group container is TCC-protected and unreadable even by `head`;
  recordings must be dragged to `~/Downloads` first.
