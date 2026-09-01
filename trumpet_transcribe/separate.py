"""Source separation (Demucs).

The slowest step, so the stem is cached and reused unless the input file or
model choice changes.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .audio import load, write_wav

DEFAULT_MODEL = "htdemucs_6s"

# htdemucs_6s stems: drums, bass, other, vocals, guitar, piano. Horns land in
# "other"; the 6-stem model pulls guitar and piano out of it.
DEFAULT_STEM = "other"


def _cache_key(source: Path, model_name: str, stem: str) -> dict:
    st = source.stat()
    return {
        "source": str(source.resolve()),
        "size": st.st_size,
        "mtime": int(st.st_mtime),
        "model": model_name,
        "stem": stem,
    }


def _pick_device(requested: str) -> str:
    import torch

    if requested != "auto":
        return requested
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


def separate(
    source: Path,
    out_dir: Path,
    stem: str = DEFAULT_STEM,
    model_name: str = DEFAULT_MODEL,
    device: str = "auto",
    force: bool = False,
) -> Path:
    """Return a path to the isolated stem wav, separating only if needed."""
    stems_dir = out_dir / "stems"
    stem_path = stems_dir / f"{stem}.wav"
    cache_path = stems_dir / "cache.json"
    key = _cache_key(source, model_name, stem)

    if not force and stem_path.exists() and cache_path.exists():
        try:
            if json.loads(cache_path.read_text()) == key:
                print(f"[separate] reusing cached stem: {stem_path}")
                return stem_path
        except json.JSONDecodeError:
            pass

    if stem == "none":
        wav, sr = load(source)
        write_wav(stem_path, wav, sr)
        cache_path.write_text(json.dumps(key))
        return stem_path

    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    wav, sr = load(source)
    print(f"[separate] loading {model_name} (first run downloads weights)")
    model = get_model(model_name)
    model.eval()
    if stem not in model.sources:
        raise ValueError(f"{model_name} has no stem {stem!r}; choose from {model.sources}")

    dev = _pick_device(device)
    tensor = torch.from_numpy(wav)
    ref = tensor.mean(0)
    tensor = (tensor - ref.mean()) / (ref.std() + 1e-8)

    print(f"[separate] running Demucs on {dev} ({wav.shape[1] / sr:.0f}s of audio)")
    # shifts=0 keeps runs reproducible; Demucs otherwise applies a random
    # time shift with nothing to average it against.
    torch.manual_seed(0)
    try:
        sources = apply_model(model, tensor[None], device=dev, progress=True,
                              split=True, shifts=0)[0]
    except Exception as exc:  # MPS backends still hit unimplemented ops
        if dev == "cpu":
            raise
        print(f"[separate] {dev} failed ({exc.__class__.__name__}), retrying on cpu")
        sources = apply_model(model, tensor[None], device="cpu", progress=True,
                              split=True, shifts=0)[0]

    sources = sources * ref.std() + ref.mean()
    picked = sources[model.sources.index(stem)].cpu().numpy().astype(np.float32)

    write_wav(stem_path, picked, sr)
    cache_path.write_text(json.dumps(key))
    print(f"[separate] wrote {stem_path}")
    return stem_path
