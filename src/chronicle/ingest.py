"""Load a point-in-time snapshot from a Scout ``mission.json`` (or compatible).

The expected shape is Scout's mission output - ``brief``, ``created_at``,
``summary``, ``entities[]``, ``edges[]``, ``observations[]`` - but any JSON with
those keys works. The observation time defaults to the file's ``created_at``,
then to the file mtime, so snapshots order themselves sensibly even without an
explicit timestamp.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .models import EdgeIn, EntityIn, ObservationIn, Snapshot


def load_snapshot(path: str | Path, label: str | None = None,
                  observed_at: str | None = None) -> Snapshot:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))

    when = observed_at or data.get("created_at") or _file_mtime(p)
    name = label or data.get("label") or _default_label(p, when)

    entities = [
        EntityIn(
            name=str(e.get("name", "")).strip(),
            type=str(e.get("type", "unknown")),
            attributes=e.get("attributes", {}) or {},
            sources=e.get("sources", []) or [],
        )
        for e in data.get("entities", [])
        if str(e.get("name", "")).strip()
    ]
    edges = [
        EdgeIn(
            source=str(x.get("source", "")).strip(),
            target=str(x.get("target", "")).strip(),
            relationship=str(x.get("relationship", "related")),
            confidence=float(x.get("confidence", 0.5)),
            sources=x.get("sources", []) or [],
        )
        for x in data.get("edges", [])
        if str(x.get("source", "")).strip() and str(x.get("target", "")).strip()
    ]
    observations = [
        ObservationIn(content=str(o.get("content", "")), source=str(o.get("source", "")))
        for o in data.get("observations", [])
        if str(o.get("content", "")).strip()
    ]

    return Snapshot(
        label=name, observed_at=when,
        brief=str(data.get("brief", "")), summary=str(data.get("summary", "")),
        entities=entities, edges=edges, observations=observations,
    )


def _file_mtime(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, tz=UTC).isoformat()


def _default_label(p: Path, when: str) -> str:
    return f"{p.stem}@{when[:10]}"
