"""Generate a synthetic melody with known pitches, for verifying the pipeline."""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
# Concert pitches: a C major scale up to C5, then a gap, then a short phrase.
MELODY = [60, 62, 64, 65, 67, 69, 70, 72]
PHRASE_TWO = [67, 65, 62, 60]


def tone(midi, dur, sr=SR):
    f = 440.0 * 2 ** ((midi - 69) / 12)
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    # A few harmonics, brass-ish, so the detector sees a realistic spectrum.
    wav = sum(a * np.sin(2 * np.pi * f * h * t) for h, a in [(1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15)])
    env = np.minimum(1.0, np.minimum(t / 0.03, (dur - t) / 0.05))
    return (wav * env / 2.0).astype(np.float32)


def main(out="tests/fixture.wav"):
    parts, expected = [], []
    cursor = 0.0
    for group, gap_after in [(MELODY, 1.5), (PHRASE_TWO, 0.0)]:
        for midi in group:
            expected.append((round(cursor, 2), midi))
            parts.append(tone(midi, 0.5))
            parts.append(np.zeros(int(SR * 0.1), dtype=np.float32))
            cursor += 0.6
        if gap_after:
            parts.append(np.zeros(int(SR * gap_after), dtype=np.float32))
            cursor += gap_after
    sf.write(out, np.concatenate(parts), SR)
    Path(out).with_suffix(".expected.txt").write_text(
        "\n".join(f"{t} {m}" for t, m in expected)
    )
    print(f"wrote {out}: {len(expected)} notes, {cursor:.1f}s")


if __name__ == "__main__":
    main(*sys.argv[1:])
