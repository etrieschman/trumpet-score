"""Audio loading that does not require ffmpeg.

soundfile handles wav/flac/ogg and (via libsndfile >= 1.1) mp3, but not AAC.
For .m4a/.aac we shell out to afconvert, which ships with macOS. ffmpeg is used
only as a last resort, if it happens to be installed.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

TARGET_SR = 44100  # what the Demucs models expect


class AudioLoadError(RuntimeError):
    pass


def _decode_via_tool(path: Path) -> Path:
    """Transcode to a temp wav using afconvert (macOS) or ffmpeg."""
    tmp = Path(tempfile.mkdtemp(prefix="trumpet_")) / "decoded.wav"
    if shutil.which("afconvert"):
        cmd = ["afconvert", "-f", "WAVE", "-d", "LEI16", str(path), str(tmp)]
    elif shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-v", "error", "-i", str(path), str(tmp)]
    else:
        raise AudioLoadError(
            f"cannot decode {path.name}: no afconvert or ffmpeg available"
        )
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not tmp.exists():
        raise AudioLoadError(f"{cmd[0]} failed on {path.name}: {proc.stderr.strip()}")
    return tmp


def load(path: str | Path, sr: int = TARGET_SR) -> tuple[np.ndarray, int]:
    """Load audio as float32 (channels, samples) at `sr`, always stereo.

    Demucs wants stereo at 44.1k; mono input is duplicated across channels.
    """
    path = Path(path)
    if not path.exists():
        raise AudioLoadError(f"no such file: {path}")
    try:
        data, in_sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:
        data, in_sr = sf.read(str(_decode_via_tool(path)), dtype="float32", always_2d=True)

    wav = data.T  # (channels, samples)
    if wav.shape[0] == 1:
        wav = np.repeat(wav, 2, axis=0)
    elif wav.shape[0] > 2:
        wav = wav[:2]

    if in_sr != sr:
        import librosa

        wav = np.stack([librosa.resample(c, orig_sr=in_sr, target_sr=sr) for c in wav])
    return np.ascontiguousarray(wav), sr


def write_wav(path: str | Path, wav: np.ndarray, sr: int) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), wav.T if wav.ndim > 1 else wav, sr)
