"""The bitemporal store - Chronicle's memory.

An append-only SQLite database that records, for every entity and relationship,
the full history of what we knew and when we knew it. Nothing is overwritten:
each observed change adds a new version row, and per-snapshot *presence* rows let
us reconstruct the intelligence picture as it stood at any point in time (and
detect when things appear or disappear).

Design notes
- ``entity_key`` / ``edge_key`` give a stable identity across snapshots. The MVP
  keys on normalized name+type; swapping in a resolver (e.g. a Tamr-style id) is
  a single-function change.
- Version rows are written only when a value first appears or actually changes,
  so history stays compact while remaining lossless.
- Presence rows are written every snapshot, which is what makes add/remove
  detection between two snapshots exact.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import (
    DiffResult,
    EdgeChange,
    EntityChange,
    EntityTimeline,
    FieldChange,
    IngestResult,
    Snapshot,
    TimelineEvent,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    brief       TEXT DEFAULT '',
    summary     TEXT DEFAULT '',
    ingested_at TEXT NOT NULL,
    seq         INTEGER
);
CREATE TABLE IF NOT EXISTS entity_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_key    TEXT NOT NULL,
    name          TEXT NOT NULL,
    type          TEXT NOT NULL,
    attributes    TEXT NOT NULL,
    sources       TEXT NOT NULL,
    change_type   TEXT NOT NULL,            -- added | changed
    changed_fields TEXT NOT NULL DEFAULT '[]',
    observed_at   TEXT NOT NULL,
    snapshot_id   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entity_presence (
    entity_key  TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (entity_key, snapshot_id)
);
CREATE TABLE IF NOT EXISTS edge_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_key      TEXT NOT NULL,
    source        TEXT NOT NULL,
    target        TEXT NOT NULL,
    relationship  TEXT NOT NULL,
    confidence    REAL NOT NULL,
    change_type   TEXT NOT NULL,
    changed_fields TEXT NOT NULL DEFAULT '[]',
    observed_at   TEXT NOT NULL,
    snapshot_id   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edge_presence (
    edge_key    TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (edge_key, snapshot_id)
);
CREATE TABLE IF NOT EXISTS observations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT NOT NULL,
    source      TEXT DEFAULT '',
    observed_at TEXT NOT NULL,
    snapshot_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ev_key ON entity_versions(entity_key, observed_at);
CREATE INDEX IF NOT EXISTS idx_edv_key ON edge_versions(edge_key, observed_at);
"""


def entity_key(name: str, type_: str) -> str:
    return f"{type_.strip().lower()}:{name.strip().lower()}"


def edge_key(source: str, relationship: str, target: str) -> str:
    return f"{source.strip().lower()}|{relationship.strip().lower()}|{target.strip().lower()}"


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ── ingest ──────────────────────────────────────────────────────────────

    def ingest(self, snap: Snapshot) -> IngestResult:
        import uuid

        snap_id = uuid.uuid4().hex[:12]
        seq = self._next_seq(snap.observed_at)
        self.conn.execute(
            "INSERT INTO snapshots (id, label, observed_at, brief, summary, ingested_at, seq)"
            " VALUES (?,?,?,?,?,?,?)",
            (snap_id, snap.label, snap.observed_at, snap.brief, snap.summary, _now(), seq),
        )

        e_added = e_changed = 0
        for e in snap.entities:
            key = entity_key(e.name, e.type)
            prev = self._value_as_of(key, snap.observed_at, exclusive=True)
            attrs = dict(e.attributes)
            if prev is None:
                self._insert_entity_version(key, e.name, e.type, attrs, e.sources,
                                            "added", [], snap.observed_at, snap_id)
                e_added += 1
            else:
                delta = _attr_delta(prev["attributes"], attrs)
                if prev["type"] != e.type:
                    delta.append(FieldChange(field="type", before=prev["type"], after=e.type))
                if delta:
                    self._insert_entity_version(
                        key, e.name, e.type, attrs, e.sources, "changed",
                        [d.model_dump() for d in delta], snap.observed_at, snap_id,
                    )
                    e_changed += 1
            self.conn.execute(
                "INSERT OR REPLACE INTO entity_presence VALUES (?,?,?)",
                (key, snap_id, snap.observed_at),
            )

        ed_added = ed_changed = 0
        for edge in snap.edges:
            key = edge_key(edge.source, edge.relationship, edge.target)
            prev = self._edge_value_as_of(key, snap.observed_at, exclusive=True)
            if prev is None:
                self._insert_edge_version(key, edge, "added", [], snap.observed_at, snap_id)
                ed_added += 1
            elif abs(prev["confidence"] - edge.confidence) > 1e-9:
                delta = [FieldChange(field="confidence", before=prev["confidence"],
                                     after=edge.confidence)]
                self._insert_edge_version(key, edge, "changed",
                                          [d.model_dump() for d in delta],
                                          snap.observed_at, snap_id)
                ed_changed += 1
            self.conn.execute(
                "INSERT OR REPLACE INTO edge_presence VALUES (?,?,?)",
                (key, snap_id, snap.observed_at),
            )

        for obs in snap.observations:
            self.conn.execute(
                "INSERT INTO observations (content, source, observed_at, snapshot_id)"
                " VALUES (?,?,?,?)",
                (obs.content, obs.source, snap.observed_at, snap_id),
            )

        self.conn.commit()
        return IngestResult(
            snapshot_label=snap.label, observed_at=snap.observed_at,
            entities_seen=len(snap.entities), entities_added=e_added, entities_changed=e_changed,
            edges_seen=len(snap.edges), edges_added=ed_added, edges_changed=ed_changed,
        )

    def _next_seq(self, observed_at: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) c FROM snapshots WHERE observed_at <= ?", (observed_at,)
        ).fetchone()
        return int(row["c"])

    def _insert_entity_version(self, key: str, name: str, type_: str, attrs: dict[str, Any],
                               sources: list[str], change_type: str,
                               changed_fields: list[dict[str, Any]],
                               observed_at: str, snap_id: str) -> None:
        self.conn.execute(
            "INSERT INTO entity_versions (entity_key,name,type,attributes,sources,"
            "change_type,changed_fields,observed_at,snapshot_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (key, name, type_, json.dumps(attrs), json.dumps(sources), change_type,
             json.dumps(changed_fields), observed_at, snap_id),
        )

    def _insert_edge_version(self, key: str, edge: Any, change_type: str,
                             changed_fields: list[dict[str, Any]],
                             observed_at: str, snap_id: str) -> None:
        self.conn.execute(
            "INSERT INTO edge_versions (edge_key,source,target,relationship,confidence,"
            "change_type,changed_fields,observed_at,snapshot_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (key, edge.source, edge.target, edge.relationship, edge.confidence,
             change_type, json.dumps(changed_fields), observed_at, snap_id),
        )

    # ── point-in-time queries ────────────────────────────────────────────────

    def _value_as_of(self, key: str, observed_at: str,
                     exclusive: bool = False) -> dict[str, Any] | None:
        op = "<" if exclusive else "<="
        row = self.conn.execute(
            f"SELECT * FROM entity_versions WHERE entity_key=? AND observed_at {op} ?"
            " ORDER BY observed_at DESC, id DESC LIMIT 1",
            (key, observed_at),
        ).fetchone()
        if row is None:
            return None
        return {
            "name": row["name"], "type": row["type"],
            "attributes": json.loads(row["attributes"]),
            "sources": json.loads(row["sources"]),
        }

    def _edge_value_as_of(self, key: str, observed_at: str,
                          exclusive: bool = False) -> dict[str, Any] | None:
        op = "<" if exclusive else "<="
        row = self.conn.execute(
            f"SELECT * FROM edge_versions WHERE edge_key=? AND observed_at {op} ?"
            " ORDER BY observed_at DESC, id DESC LIMIT 1",
            (key, observed_at),
        ).fetchone()
        if row is None:
            return None
        return {"source": row["source"], "target": row["target"],
                "relationship": row["relationship"], "confidence": row["confidence"]}

    # ── snapshots ─────────────────────────────────────────────────────────────

    def list_snapshots(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM snapshots ORDER BY observed_at ASC, seq ASC"
        ).fetchall())

    def resolve_snapshot(self, ref: str) -> sqlite3.Row | None:
        snaps = self.list_snapshots()
        if not snaps:
            return None
        if ref in {"latest", "last"}:
            return snaps[-1]
        if ref in {"first", "earliest"}:
            return snaps[0]
        if ref.lstrip("-").isdigit():
            idx = int(ref)
            try:
                return snaps[idx]
            except IndexError:
                return None
        for s in snaps:
            if s["label"] == ref or s["id"] == ref:
                return s
        return None

    def _entity_keys_in(self, snap_id: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT entity_key FROM entity_presence WHERE snapshot_id=?", (snap_id,)
        ).fetchall()
        return {r["entity_key"] for r in rows}

    def _edge_keys_in(self, snap_id: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT edge_key FROM edge_presence WHERE snapshot_id=?", (snap_id,)
        ).fetchall()
        return {r["edge_key"] for r in rows}

    # ── diff ──────────────────────────────────────────────────────────────────

    def diff(self, from_ref: str, to_ref: str) -> DiffResult | None:
        a = self.resolve_snapshot(from_ref)
        b = self.resolve_snapshot(to_ref)
        if a is None or b is None:
            return None
        result = DiffResult(
            from_label=a["label"], to_label=b["label"],
            from_observed_at=a["observed_at"], to_observed_at=b["observed_at"],
        )
        keys_a = self._entity_keys_in(a["id"])
        keys_b = self._entity_keys_in(b["id"])
        for key in sorted(keys_b - keys_a):
            v = self._value_as_of(key, b["observed_at"])
            if v:
                result.entities_added.append(EntityChange(key=key, name=v["name"], type=v["type"]))
        for key in sorted(keys_a - keys_b):
            v = self._value_as_of(key, a["observed_at"])
            if v:
                result.entities_removed.append(
                    EntityChange(key=key, name=v["name"], type=v["type"]))
        for key in sorted(keys_a & keys_b):
            va = self._value_as_of(key, a["observed_at"])
            vb = self._value_as_of(key, b["observed_at"])
            if not va or not vb:
                continue
            delta = _attr_delta(va["attributes"], vb["attributes"])
            if va["type"] != vb["type"]:
                delta.append(FieldChange(field="type", before=va["type"], after=vb["type"]))
            if delta:
                result.entities_changed.append(
                    EntityChange(key=key, name=vb["name"], type=vb["type"], changes=delta)
                )

        ekeys_a = self._edge_keys_in(a["id"])
        ekeys_b = self._edge_keys_in(b["id"])
        for key in sorted(ekeys_b - ekeys_a):
            v = self._edge_value_as_of(key, b["observed_at"])
            if v:
                result.edges_added.append(EdgeChange(
                    key=key, source=v["source"], target=v["target"],
                    relationship=v["relationship"]))
        for key in sorted(ekeys_a - ekeys_b):
            v = self._edge_value_as_of(key, a["observed_at"])
            if v:
                result.edges_removed.append(EdgeChange(
                    key=key, source=v["source"], target=v["target"],
                    relationship=v["relationship"]))
        for key in sorted(ekeys_a & ekeys_b):
            va = self._edge_value_as_of(key, a["observed_at"])
            vb = self._edge_value_as_of(key, b["observed_at"])
            if va and vb and abs(va["confidence"] - vb["confidence"]) > 1e-9:
                result.edges_changed.append(EdgeChange(
                    key=key, source=vb["source"], target=vb["target"],
                    relationship=vb["relationship"],
                    changes=[FieldChange(field="confidence",
                                         before=va["confidence"], after=vb["confidence"])]))
        return result

    # ── timeline ───────────────────────────────────────────────────────────────

    def timeline(self, query: str) -> list[EntityTimeline]:
        q = f"%{query.strip().lower()}%"
        keys = [r["entity_key"] for r in self.conn.execute(
            "SELECT DISTINCT entity_key FROM entity_versions WHERE LOWER(name) LIKE ?"
            " OR entity_key LIKE ?", (q, q)
        ).fetchall()]
        snaps = self.list_snapshots()
        label_by_id = {s["id"]: s["label"] for s in snaps}
        out: list[EntityTimeline] = []
        for key in keys:
            versions = self.conn.execute(
                "SELECT * FROM entity_versions WHERE entity_key=? ORDER BY observed_at ASC, id ASC",
                (key,),
            ).fetchall()
            if not versions:
                continue
            name = versions[-1]["name"]
            type_ = versions[-1]["type"]
            tl = EntityTimeline(key=key, name=name, type=type_)
            for v in versions:
                changes = [FieldChange(**c) for c in json.loads(v["changed_fields"])]
                kind = "first_seen" if v["change_type"] == "added" else "changed"
                detail = ("first observed" if kind == "first_seen"
                          else f"{len(changes)} field(s) changed")
                tl.events.append(TimelineEvent(
                    observed_at=v["observed_at"],
                    snapshot_label=label_by_id.get(v["snapshot_id"], "?"),
                    kind=kind, detail=detail, changes=changes,
                ))
            for gap in self._presence_transitions(key, snaps):
                tl.events.append(gap)
            tl.events.sort(key=lambda e: e.observed_at)
            out.append(tl)
        return out

    def _presence_transitions(self, key: str, snaps: list[sqlite3.Row]) -> list[TimelineEvent]:
        present_ids = {r["snapshot_id"] for r in self.conn.execute(
            "SELECT snapshot_id FROM entity_presence WHERE entity_key=?", (key,)
        ).fetchall()}
        events: list[TimelineEvent] = []
        was_present = False
        seen_once = False
        for s in snaps:
            here = s["id"] in present_ids
            if seen_once and was_present and not here:
                events.append(TimelineEvent(
                    observed_at=s["observed_at"], snapshot_label=s["label"],
                    kind="disappeared", detail="no longer present in this snapshot"))
            if seen_once and not was_present and here:
                events.append(TimelineEvent(
                    observed_at=s["observed_at"], snapshot_label=s["label"],
                    kind="reappeared", detail="present again after being absent"))
            was_present = here
            seen_once = seen_once or here
        return events

    # ── graph state per snapshot (for the time-scrub view) ──────────────────────

    def snapshot_states(self) -> list[dict[str, Any]]:
        snaps = self.list_snapshots()
        states: list[dict[str, Any]] = []
        prev_ekeys: set[str] = set()
        prev_edge_keys: set[str] = set()
        prev_entity_vals: dict[str, dict[str, Any]] = {}
        for s in snaps:
            ekeys = self._entity_keys_in(s["id"])
            edge_keys = self._edge_keys_in(s["id"])
            nodes = []
            for key in ekeys:
                v = self._value_as_of(key, s["observed_at"])
                if not v:
                    continue
                if key not in prev_ekeys:
                    status = "new"
                elif prev_entity_vals.get(key) != v:
                    status = "changed"
                else:
                    status = "existing"
                nodes.append({
                    "id": key, "label": v["name"], "type": v["type"],
                    "status": status,
                    "title": _node_title(v),
                })
            edges = []
            for key in edge_keys:
                v = self._edge_value_as_of(key, s["observed_at"])
                if not v:
                    continue
                edges.append({
                    "from": entity_key_guess(v["source"], nodes),
                    "to": entity_key_guess(v["target"], nodes),
                    "label": v["relationship"],
                    "status": "new" if key not in prev_edge_keys else "existing",
                })
            states.append({
                "label": s["label"], "observed_at": s["observed_at"],
                "brief": s["brief"], "nodes": nodes, "edges": edges,
            })
            prev_ekeys = ekeys
            prev_edge_keys = edge_keys
            prev_entity_vals = {
                k: self._value_as_of(k, s["observed_at"]) for k in ekeys  # type: ignore[misc]
            }
        return states


def entity_key_guess(name: str, nodes: list[dict[str, Any]]) -> str:
    """Best-effort map an edge endpoint name to a node id present in this state."""
    low = name.strip().lower()
    for n in nodes:
        if n["label"].strip().lower() == low:
            return n["id"]
    return f"unknown:{low}"


def _node_title(v: dict[str, Any]) -> str:
    parts = [f"{v['name']} ({v['type']})"]
    for k, val in (v.get("attributes") or {}).items():
        parts.append(f"{k}: {val}")
    return "\n".join(parts)


def _attr_delta(before: dict[str, Any], after: dict[str, Any]) -> list[FieldChange]:
    changes: list[FieldChange] = []
    for field in sorted(set(before) | set(after)):
        b = before.get(field)
        a = after.get(field)
        if b != a:
            changes.append(FieldChange(field=field, before=b, after=a))
    return changes
