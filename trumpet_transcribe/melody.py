"""Turn raw polyphonic detections into one clean monophonic melody line.

Order matters here: range filter -> monophonic reduction -> segment -> drop
blips -> merge held notes. Reduction happens before the length filter so that a
short fragment of an inner voice cannot survive by being the only thing present.
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
    """Drop detections that look like overtones of a louder, lower note.

    Brass has a violently strong overtone series and basic-pitch happily reports
    the partials as their own notes. Without this, a sustained note arrives as
    the octave (while the partial is detected) followed by the fundamental,
    which both doubles the note count and gets the octave wrong.
    """
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
    """Collapse overlapping note events to a single voice.

    'top' keeps the highest sounding pitch (right for a lead line most of the
    time); 'loudest' keeps the strongest, which helps when the melody sits under
    a higher harmony part.
    """
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


def merge_repeats(events: list, merge_gap: float) -> list:
    """Join consecutive same-pitch events separated by less than merge_gap.

    A held note frequently arrives as several detections. The cost is that two
    genuinely rearticulated notes at the same pitch, tongued fast, merge into
    one -- unavoidable without onset strength, and cheap when rhythm is coming
    from the ear anyway.
    """
    merged = []
    for ev in sorted(events, key=lambda e: e[0]):
        if merged and merged[-1][2] == ev[2] and ev[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = max(merged[-1][1], ev[1])
            merged[-1][3] = max(merged[-1][3], ev[3])
        else:
            merged.append(list(ev))
    return merged


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
) -> list:
    """Raw detections -> filtered, transposed, fingered Note objects.

    low/high are concert MIDI bounds for discarding obvious garbage; they are
    deliberately wider than the trumpet's range so that near-misses survive to
    be flagged rather than silently dropped.

    start_s/end_s restrict the window before anything else runs. Timestamps stay
    absolute so they still line up with the recording.
    """
    windowed = [ev for ev in events if ev[0] >= start_s and (end_s is None or ev[0] < end_s)]
    shifted = [[s, e, p + 12 * octave_shift, a] for s, e, p, a in windowed]
    in_bounds = [ev for ev in shifted if low <= ev[2] <= high]
    if harmonic_filter:
        in_bounds = suppress_harmonics(in_bounds)
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
