"""Merge the output of several detection pipelines into one note list.

Pipelines that fail differently are the point: a note both of them found is
worth more than a note only one found, and the merged sheet records which.
"""
from __future__ import annotations

from dataclasses import replace

# Pipelines place the same note up to ~0.3s apart: Melodia segments a smoothed
# f0 contour, basic-pitch reports model onsets.
DEFAULT_TOLERANCE = 0.3


def merge(named: dict, tolerance: float = DEFAULT_TOLERANCE,
          mode: str = "union") -> list:
    """Combine {pipeline_name: [Note, ...]} into one list with sources recorded.

    Notes of the same written pitch whose onsets fall within `tolerance` count
    as the same note. `union` keeps everything and lets the sheet mark what only
    one pipeline saw; `agreed` keeps only notes every pipeline found, which is
    far sparser but much higher confidence.
    """
    tagged = []
    for name, notes in named.items():
        for note in notes:
            tagged.append((note.onset_s, note, name))
    tagged.sort(key=lambda item: item[0])

    clusters = []
    for onset, note, name in tagged:
        for cluster in clusters:
            if (cluster["pitch"] == note.written_midi
                    and abs(cluster["onset"] - onset) <= tolerance):
                cluster["sources"].add(name)
                cluster["duration"] = max(cluster["duration"], note.duration_s)
                break
        else:
            clusters.append({
                "onset": onset, "pitch": note.written_midi, "note": note,
                "duration": note.duration_s, "sources": {name},
            })

    if mode == "agreed":
        clusters = [c for c in clusters if len(c["sources"]) == len(named)]
    merged = [
        replace(c["note"], onset_s=c["onset"], duration_s=c["duration"],
                sources=sorted(c["sources"]))
        for c in clusters
    ]
    merged.sort(key=lambda n: n.onset_s)
    return _resolve_overlaps(merged)


def _resolve_overlaps(notes: list) -> list:
    """Keep the result monophonic: clip a note that runs into the next onset."""
    out = []
    for note in notes:
        if out:
            previous = out[-1]
            if note.onset_s < previous.onset_s + previous.duration_s:
                clipped = round(note.onset_s - previous.onset_s, 3)
                if clipped <= 0:
                    continue
                out[-1] = replace(previous, duration_s=clipped)
        out.append(note)
    return out
