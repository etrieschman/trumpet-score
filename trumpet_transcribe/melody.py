"""Raw polyphonic detections -> one monophonic melody line.

Order: range filter -> reduce to one voice -> segment -> drop blips -> merge
held notes. Reduction precedes the length filter so a short fragment of an
inner voice cannot survive by being the only thing sounding.
"""
from __future__ import annotations

import numpy as np

from . import trumpet
from .intermediate import Note

HOP = 0.01  # 10 ms analysis grid for the reduction


# Intervals above a fundamental where a detector routinely reports a spurious
# note: octave, octave+fifth, two octaves.
HARMONIC_INTERVALS = (12, 19, 24)


def suppress_harmonics(
    events: list,
    min_overlap: float = 0.5,
    amp_ratio: float = 0.8,
) -> list:
    """Drop detections that look like overtones of a louder, lower note."""
    keep = []
    for i, (start_s, end_s, pitch, amp) in enumerate(events):
        span = max(end_s - start_s, 1e-9)
        spurious = False
        for j, (l_start, l_end, l_pitch, l_amp) in enumerate(events):
            if i == j or pitch - l_pitch not in HARMONIC_INTERVALS:
                continue
            overlap = min(end_s, l_end) - max(start_s, l_start)
            if overlap / span >= min_overlap and l_amp >= amp * amp_ratio:
                spurious = True
                break
        if not spurious:
            keep.append([start_s, end_s, pitch, amp])
    return keep


def reduce_to_melody(events: list, rule: str = "top", hop: float = HOP) -> list:
    """Collapse overlapping notes to one voice by pitch ('top') or amplitude
    ('loudest'). See track_contour for the default rule."""
    if not events:
        return []

    end = max(e[1] for e in events)
    frames = int(np.ceil(end / hop)) + 1
    best_pitch = np.full(frames, -1, dtype=np.int16)
    best_score = np.full(frames, -np.inf, dtype=np.float64)
    best_amp = np.zeros(frames, dtype=np.float64)

    for start_s, end_s, pitch, amp in events:
        lo = int(np.floor(start_s / hop))
        hi = max(lo + 1, int(np.ceil(end_s / hop)))
        score = float(pitch) if rule == "top" else float(amp)
        window = slice(lo, hi)
        wins = score > best_score[window]
        idx = np.arange(lo, hi)[wins]
        best_score[idx] = score
        best_pitch[idx] = pitch
        best_amp[idx] = amp

    # Re-segment contiguous runs of equal pitch back into note events.
    segments = []
    run_start = 0
    for i in range(1, frames + 1):
        prev = best_pitch[i - 1]
        cur = best_pitch[i] if i < frames else -2
        if cur != prev:
            if prev >= 0:
                segments.append(
                    [run_start * hop, i * hop, int(prev), float(best_amp[run_start])]
                )
            run_start = i
    return segments


def track_contour(
    events: list,
    hop: float = HOP,
    jump_penalty: float = 0.35,
    rest_score: float = 0.18,
) -> list:
    """Pick the melody as the best-connected path through overlapping notes.

    Viterbi decode whose state is the last pitch that sounded. Sounding a note
    earns its amplitude and costs `jump_penalty` per semitone from that pitch;
    resting earns `rest_score` and leaves the state unchanged, so continuity
    carries across gaps.
    """
    if not events:
        return []

    frames = int(np.ceil(max(e[1] for e in events) / hop)) + 1
    active = [{} for _ in range(frames)]
    for start_s, end_s, pitch, amp in events:
        lo = max(0, int(np.floor(start_s / hop)))
        hi = min(frames, max(lo + 1, int(np.ceil(end_s / hop))))
        for i in range(lo, hi):
            slot = active[i]
            slot[int(pitch)] = max(slot.get(int(pitch), 0.0), float(amp))

    pitches = np.array(sorted({int(e[2]) for e in events}))
    index = {p: i for i, p in enumerate(pitches)}
    n = len(pitches)
    step_cost = jump_penalty * np.abs(pitches[:, None] - pitches[None, :])

    scores = np.zeros(n)
    came_from = np.full((frames, n), -1, dtype=np.int32)   # -1 means "rested"
    for f, slot in enumerate(active):
        nxt = scores + rest_score                          # rest: state unchanged
        for pitch, amp in slot.items():
            j = index[pitch]
            candidates = scores - step_cost[j]
            source = int(np.argmax(candidates))
            sounded = candidates[source] + amp
            if sounded > nxt[j]:
                nxt[j] = sounded
                came_from[f, j] = source
        scores = nxt

    state = int(np.argmax(scores))
    voiced = np.zeros(frames, dtype=bool)
    path = np.zeros(frames, dtype=np.int32)
    for f in range(frames - 1, -1, -1):
        path[f] = state
        source = came_from[f, state]
        if source >= 0:
            voiced[f] = True
            state = int(source)

    segments, run_start = [], None
    for f in range(frames + 1):
        here = int(path[f]) if f < frames and voiced[f] else -1
        previous = int(path[f - 1]) if f > 0 and voiced[f - 1] else -1
        if here != previous:
            if previous >= 0:
                pitch = int(pitches[previous])
                amps = [active[j][pitch] for j in range(run_start, f)
                        if pitch in active[j]]
                segments.append([run_start * hop, f * hop, pitch,
                                 float(max(amps)) if amps else 0.5])
            run_start = f
    return segments


def merge_repeats(events: list, merge_gap: float) -> list:
    """Join consecutive same-pitch events separated by less than merge_gap.

    Held notes arrive as several detections. Fast rearticulated notes at one
    pitch merge into one; pitch alone cannot separate them.
    """
    merged = []
    for ev in sorted(events, key=lambda e: e[0]):
        if merged and merged[-1][2] == ev[2] and ev[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = max(merged[-1][1], ev[1])
            merged[-1][3] = max(merged[-1][3], ev[3])
        else:
            merged.append(list(ev))
    return merged


def filter_to_key(notes: list, key_info: dict) -> list:
    """Drop notes whose pitch class lies outside the key's scale.

    Estimate `key_info` on the unfiltered notes; filtering first would bias it.
    """
    from . import keysig

    scale = {(key_info["tonic_pc"] + d) % 12
             for d in keysig.DEGREES[key_info["mode"]]}
    return [n for n in notes if n.written_midi % 12 in scale]


def build_notes(
    events: list,
    rule: str = "top",
    low: int = 45,
    high: int = 88,
    min_dur: float = 0.08,
    merge_gap: float = 0.06,
    octave_shift: int = 0,
    flats: bool = True,
    harmonic_filter: bool = True,
    start_s: float = 0.0,
    end_s: float = None,
    jump_penalty: float = 0.35,
    rest_score: float = 0.18,
) -> list:
    """Raw detections -> filtered, transposed, fingered Note objects.

    low/high are concert MIDI bounds, set wider than the trumpet's range so
    near-misses are flagged rather than dropped. start_s/end_s clip to a
    window; timestamps stay absolute.
    """
    # Keep what sounds inside the window, not just what starts in it.
    windowed = [
        [max(s0, start_s), e0 if end_s is None else min(e0, end_s), p0, a0]
        for s0, e0, p0, a0 in events
        if e0 > start_s and (end_s is None or s0 < end_s)
    ]
    shifted = [[s, e, p + 12 * octave_shift, a] for s, e, p, a in windowed]
    in_bounds = [ev for ev in shifted if low <= ev[2] <= high]
    if harmonic_filter:
        in_bounds = suppress_harmonics(in_bounds)
    if rule == "contour":
        voiced = track_contour(in_bounds, jump_penalty=jump_penalty,
                               rest_score=rest_score)
    else:
        voiced = reduce_to_melody(in_bounds, rule=rule)
    long_enough = [ev for ev in voiced if (ev[1] - ev[0]) >= min_dur]
    final = merge_repeats(long_enough, merge_gap)

    notes = []
    for start_s, end_s, concert_midi, amp in final:
        written = trumpet.to_written(concert_midi)
        notes.append(
            Note(
                onset_s=round(start_s, 3),
                duration_s=round(end_s - start_s, 3),
                concert_midi=concert_midi,
                concert_name=trumpet.note_name(concert_midi, flats),
                written_midi=written,
                written_name=trumpet.note_name(written, flats),
                fingering=trumpet.fingering(written),
                in_range=trumpet.in_range(written),
                velocity=round(amp, 4),
                alternates=trumpet.alternates(written),
            )
        )
    return notes
