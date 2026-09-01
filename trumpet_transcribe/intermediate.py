"""The intermediate note document that every renderer reads.

This is the contract between detection and rendering. Stage 1 renders it as a
text note sheet; stage 2 will render the same document as MusicXML. Renderers
must not reach back into the audio or detection layers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3


@dataclass
class Note:
    onset_s: float
    duration_s: float
    concert_midi: int
    concert_name: str
    written_midi: int
    written_name: str
    fingering: str
    in_range: bool
    velocity: float = 0.0
    # Not used by the stage 1 text renderer, which deliberately omits rhythm,
    # but carried so stage 2 can quantize without re-running detection.
    alternates: list = field(default_factory=list)

    @property
    def offset_s(self) -> float:
        return self.onset_s + self.duration_s


@dataclass
class NoteDocument:
    source: str
    notes: list
    params: dict = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    generated_at: str = ""

    def to_json(self, path: Path) -> None:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "source": self.source,
            "generated_at": self.generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "params": self.params,
            "notes": [asdict(n) for n in self.notes],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))

    @classmethod
    def from_json(cls, path: Path) -> "NoteDocument":
        payload = json.loads(Path(path).read_text())
        version = payload.get("schema_version")
        if version > SCHEMA_VERSION:
            raise ValueError(
                f"{path} is schema version {version}, this build only reads up to "
                f"{SCHEMA_VERSION}"
            )
        return cls(
            source=payload["source"],
            notes=[Note(**n) for n in payload["notes"]],
            params=payload.get("params", {}),
            schema_version=version,
            generated_at=payload.get("generated_at", ""),
        )
