```text
  _____ _                     _      _
 / ____| |                   (_)    | |
| |    | |__  _ __ ___  _ __  _  ___| | ___
| |    | '_ \| '__/ _ \| '_ \| |/ __| |/ _ \
| |____| | | | | | (_) | | | | | (__| |  __/   longitudinal
 \_____|_| |_|_|  \___/|_| |_|_|\___|_|\___|   intelligence
```

**A longitudinal intelligence layer.** Most OSINT and intelligence tools give you a
snapshot: who's connected to whom, right now. Chronicle adds the missing axis -
**time**. Feed it repeated captures of the same subject and it folds them into a
bitemporal store, then tells you what appeared, what changed, what went dark,
and lets you *replay the whole picture* on a slider.

Think of it as the **memory** that sits behind a **sensor** like
[Scout](https://github.com/tllongdev/scout): Scout collects; Chronicle remembers
and tracks change.

- **Bitemporal by design** - every entity, relationship, and attribute is versioned by
  *when it was true* and *when you learned it*, with provenance. Nothing is overwritten.
- **Change detection** - a precise diff between any two captures: added / removed / changed
  entities and relationships, down to the field.
- **Entity timelines** - reconstruct the dated history of any entity: first seen, each change,
  when it disappeared or came back.
- **Time-scrub graph** - an interactive HTML graph with a slider (and a Play button) that
  animates how the intelligence picture evolved.
- **Format-friendly** - ingests Scout's `mission.json` out of the box, or any JSON with the
  same `entities` / `edges` / `observations` shape.

---

## Quick start (60 seconds, no keys, no accounts)

```bash
git clone https://github.com/tllongdev/chronicle.git
cd chronicle
pip install -e .        # or: uv pip install -e .

# Ingest two point-in-time captures of the same subject
chronicle ingest samples/acme-2026-01-15.json samples/acme-2026-04-20.json

# What changed between them?
chronicle diff

# How did one entity evolve?
chronicle timeline "Acme Robotics"

# Replay the whole picture on a time slider
chronicle graph && open output/timeline.html
```

The bundled sample tells a real-feeling story: a robotics startup that, over three
months, doubles headcount, swaps out its founder-CEO, spins up a defense
subsidiary, churns investors, and picks up a **sanctioned director** - exactly the
kind of drift a point-in-time scan would miss.

### With Docker

```bash
./run.sh ingest samples/acme-2026-01-15.json samples/acme-2026-04-20.json
./run.sh diff
./run.sh graph          # writes output/timeline.html on the host
```

---

## Commands

| Command | What it does |
|---|---|
| `chronicle ingest <file...>` | Fold one or more snapshots into the store (`--label`, `--at` to override) |
| `chronicle log` | List ingested snapshots in time order |
| `chronicle diff [FROM] [TO]` | Change report between two snapshots (defaults to the last two; `--save report.md`) |
| `chronicle timeline "<name>"` | Chronological history of a matching entity |
| `chronicle graph` | Render the time-scrub HTML graph (`--out path.html`) |

**Snapshot refs** can be a label, an index (`0`, `1`, `-1`), or `first` / `latest`.
The store lives at `./chronicle.db` (override with `CHRONICLE_DB`).

### Example: `chronicle diff`

```
Change report  acme-2026-01-15@2026-01-15 -> acme-2026-04-20@2026-04-20

Entities added (4)
  • Mark Vale (person)
  • Acme Defense LLC (organization)
  • Orion Ventures (organization)
  • Viktor Sokolov (person)

Entities removed (1)
  • Nimbus Capital (organization)

Entities changed (2)
  • Acme Robotics (organization): ceo: 'Jane Doe' -> 'Mark Vale'; employees: '120' -> '260'; ...
  • Jane Doe (person): role: 'CEO' -> 'Board Member'
```

---

## How it works

```
   Snapshot 1        Snapshot 2        Snapshot N
 (Scout mission)   (Scout mission)        ...
       |                 |                 |
       +--------+--------+-----------------+
                v
        ┌───────────────────────────┐
        │   ingest / identity        │   entity_key = type + name
        │   resolution               │   (pluggable: swap in a real id)
        └───────────────────────────┘
                v
        ┌───────────────────────────┐
        │   bitemporal SQLite store  │   append-only version rows
        │   (observed vs valid time) │   + per-snapshot presence rows
        └───────────────────────────┘
                v
      ┌─────────────┬──────────────┬──────────────┐
      v             v              v              v
    diff         timeline        graph         log
  (what          (entity        (time-scrub    (snapshots
   changed)       history)       HTML)          over time)
```

**Why append-only + presence rows?** Version rows are written only when a value
first appears or actually changes, so history stays compact but lossless.
Per-snapshot *presence* rows are what make add/remove detection between two
captures exact, and let Chronicle reconstruct the picture *as it stood* at any
point in time.

**Identity resolution** currently keys on normalized `type + name`. That's the one
seam to extend for production use - drop in a resolver (fuzzy match, or a shared
master id like a Tamr `tamr_id`) and the rest of the system is unchanged.

---

## Project layout

```
src/chronicle/
  models.py     # Snapshot inputs + diff/timeline result types (pydantic)
  ingest.py     # load a Scout mission.json (or compatible) into a Snapshot
  store.py      # the bitemporal SQLite store: ingest, point-in-time queries, diff, timeline
  graph.py      # time-scrub HTML (vis-network) rendering
  report.py     # rich console + markdown rendering of diffs and timelines
  cli.py        # ingest / log / diff / timeline / graph
samples/        # two snapshots that tell a story
```

---

## Where this fits

Chronicle is a proof-of-concept for **longitudinal intelligence** - the idea that the
value of collected intelligence compounds when you keep it, version it, and watch it
change. Pair it with a collector (like Scout) on a schedule and you get a living,
auditable picture instead of a stack of disconnected reports: change alerts,
reconstructable timelines, and provenance for every claim.

This is an early, single-operator tool, not a hardened production service. It's a
clean, self-hostable foundation to build those ideas on.

## License

MIT - see [LICENSE](LICENSE).
