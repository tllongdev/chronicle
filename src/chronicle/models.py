"""Data structures for Chronicle.

Chronicle ingests point-in-time intelligence *snapshots* - most naturally the
`mission.json` produced by Scout, but any file with the same entity/edge shape
works - and folds them into a bitemporal store. These models describe the
inbound snapshot and the results Chronicle computes (diffs and timelines).

Two time axes matter here:
- **observed_time**: when we *learned* something (the snapshot's timestamp).
- **valid_time**: when something was *true* in the world.

The MVP keys everything off observed_time (append-only history of what we knew
and when); valid_time is carried through from source attributes where present.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EntityIn(BaseModel):
    """An entity as it appears inside a snapshot."""

    name: str
    type: str = "unknown"
    attributes: dict[str, Any] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)


class EdgeIn(BaseModel):
    """A directed relationship inside a snapshot."""

    source: str
    target: str
    relationship: str
    confidence: float = 0.5
    sources: list[str] = Field(default_factory=list)


class ObservationIn(BaseModel):
    """A free-text fact recorded inside a snapshot."""

    content: str
    source: str = ""


class Snapshot(BaseModel):
    """One point-in-time intelligence capture, ready to ingest."""

    label: str
    observed_at: str
    brief: str = ""
    summary: str = ""
    entities: list[EntityIn] = Field(default_factory=list)
    edges: list[EdgeIn] = Field(default_factory=list)
    observations: list[ObservationIn] = Field(default_factory=list)


# ── Result types ────────────────────────────────────────────────────────────


class FieldChange(BaseModel):
    """A single attribute that changed between two observations."""

    field: str
    before: Any = None
    after: Any = None


class EntityChange(BaseModel):
    key: str
    name: str
    type: str
    changes: list[FieldChange] = Field(default_factory=list)


class EdgeChange(BaseModel):
    key: str
    source: str
    target: str
    relationship: str
    changes: list[FieldChange] = Field(default_factory=list)


class DiffResult(BaseModel):
    """What changed between two snapshots (from_label -> to_label)."""

    from_label: str
    to_label: str
    from_observed_at: str
    to_observed_at: str
    entities_added: list[EntityChange] = Field(default_factory=list)
    entities_removed: list[EntityChange] = Field(default_factory=list)
    entities_changed: list[EntityChange] = Field(default_factory=list)
    edges_added: list[EdgeChange] = Field(default_factory=list)
    edges_removed: list[EdgeChange] = Field(default_factory=list)
    edges_changed: list[EdgeChange] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.entities_added, self.entities_removed, self.entities_changed,
            self.edges_added, self.edges_removed, self.edges_changed,
        ])


class TimelineEvent(BaseModel):
    """A single dated event in an entity's known history."""

    observed_at: str
    snapshot_label: str
    kind: str  # first_seen | changed | disappeared | reappeared | observation
    detail: str = ""
    changes: list[FieldChange] = Field(default_factory=list)


class EntityTimeline(BaseModel):
    key: str
    name: str
    type: str
    events: list[TimelineEvent] = Field(default_factory=list)


class IngestResult(BaseModel):
    snapshot_label: str
    observed_at: str
    entities_seen: int
    entities_added: int
    entities_changed: int
    edges_seen: int
    edges_added: int
    edges_changed: int
