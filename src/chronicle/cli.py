"""Chronicle CLI - fold intelligence snapshots into a timeline and query change.

    chronicle ingest <file...>     Add one or more snapshots (Scout mission.json)
    chronicle log                  List ingested snapshots in time order
    chronicle diff [FROM] [TO]     Change report between two snapshots
    chronicle timeline "<name>"    Chronological history of an entity
    chronicle graph                Render the time-scrubbable graph (HTML)
    chronicle help                 Show this help

Snapshot refs: a label, an index (0, 1, -1...), or 'first'/'latest'.
The store lives at ./chronicle.db (override with CHRONICLE_DB).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .graph import render_timescrub_html
from .ingest import load_snapshot
from .report import diff_to_markdown, print_diff, print_timeline
from .store import Store

_BANNER = r"""
  _____ _                     _      _
 / ____| |                   (_)    | |
| |    | |__  _ __ ___  _ __  _  ___| | ___
| |    | '_ \| '__/ _ \| '_ \| |/ __| |/ _ \
| |____| | | | | | (_) | | | | | (__| |  __/   longitudinal
 \_____|_| |_|_|  \___/|_| |_|_|\___|_|\___|   intelligence
"""


def _db_path() -> str:
    return os.getenv("CHRONICLE_DB", "chronicle.db")


def _out_dir() -> Path:
    d = Path(os.getenv("CHRONICLE_OUT", "output"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def main() -> int:
    console = Console()
    args = sys.argv[1:]
    command = args[0].lower() if args else ""

    if command in {"", "help", "-h", "--help"}:
        console.print(f"[bold cyan]{_BANNER}[/bold cyan]")
        console.print(escape(__doc__ or ""))
        return 0

    store = Store(_db_path())
    try:
        if command == "ingest":
            return _cmd_ingest(console, store, args[1:])
        if command == "log":
            return _cmd_log(console, store)
        if command == "diff":
            return _cmd_diff(console, store, args[1:])
        if command == "timeline":
            return _cmd_timeline(console, store, args[1:])
        if command == "graph":
            return _cmd_graph(console, store, args[1:])
        console.print(f"[red]Unknown command:[/red] {escape(command)}")
        console.print("Run [bold]chronicle help[/bold] for usage.")
        return 2
    finally:
        store.close()


def _pop_opt(args: list[str], name: str) -> str | None:
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            val = args[i + 1]
            del args[i:i + 2]
            return val
    return None


def _cmd_ingest(console: Console, store: Store, args: list[str]) -> int:
    label = _pop_opt(args, "--label")
    at = _pop_opt(args, "--at")
    files = [a for a in args if not a.startswith("-")]
    if not files:
        console.print("[red]Provide at least one snapshot file.[/red]")
        return 2
    for f in files:
        if not Path(f).exists():
            console.print(f"[red]Not found:[/red] {escape(f)}")
            continue
        snap = load_snapshot(f, label=label, observed_at=at)
        res = store.ingest(snap)
        console.print(
            f"[green]✓[/green] Ingested [bold]{escape(res.snapshot_label)}[/bold] "
            f"[dim]({res.observed_at})[/dim]: "
            f"{res.entities_seen} entities ([green]+{res.entities_added}[/green] new, "
            f"[yellow]~{res.entities_changed}[/yellow] changed), "
            f"{res.edges_seen} relationships ([green]+{res.edges_added}[/green] new)."
        )
    return 0


def _cmd_log(console: Console, store: Store) -> int:
    snaps = store.list_snapshots()
    if not snaps:
        console.print("[dim]No snapshots yet. Ingest one with `chronicle ingest`.[/dim]")
        return 0
    table = Table(title="[bold]Snapshots[/bold]", title_justify="left", border_style="cyan")
    table.add_column("#", justify="right")
    table.add_column("Observed")
    table.add_column("Label")
    table.add_column("Brief", style="dim")
    for i, s in enumerate(snaps):
        table.add_row(str(i), s["observed_at"][:19], escape(s["label"]),
                      escape((s["brief"] or "")[:60]))
    console.print(table)
    return 0


def _cmd_diff(console: Console, store: Store, args: list[str]) -> int:
    snaps = store.list_snapshots()
    if len(snaps) < 2:
        console.print("[yellow]Need at least two snapshots to diff.[/yellow]")
        return 1
    save = _pop_opt(args, "--save")
    positional = [a for a in args if not a.startswith("-")]
    from_ref = positional[0] if len(positional) > 0 else "-2"
    to_ref = positional[1] if len(positional) > 1 else "-1"
    diff = store.diff(from_ref, to_ref)
    if diff is None:
        console.print("[red]Could not resolve one of the snapshot refs.[/red]")
        return 2
    print_diff(console, diff)
    if save:
        Path(save).write_text(diff_to_markdown(diff), encoding="utf-8")
        console.print(f"\n[dim]Saved report to {escape(save)}[/dim]")
    return 0


def _cmd_timeline(console: Console, store: Store, args: list[str]) -> int:
    query = " ".join(a for a in args if not a.startswith("-")).strip()
    if not query:
        console.print("[red]Provide an entity name, e.g. `chronicle timeline \"Acme\"`.[/red]")
        return 2
    timelines = store.timeline(query)
    if not timelines:
        console.print(f"[dim]No entity matching '{escape(query)}'.[/dim]")
        return 0
    for tl in timelines:
        print_timeline(console, tl)
    return 0


def _cmd_graph(console: Console, store: Store, args: list[str]) -> int:
    if not store.list_snapshots():
        console.print("[yellow]Nothing to graph yet - ingest some snapshots first.[/yellow]")
        return 1
    out = _pop_opt(args, "--out") or str(_out_dir() / "timeline.html")
    path = render_timescrub_html(store, out, title="longitudinal intelligence")
    console.print(f"[green]✓[/green] Time-scrub graph written to [bold]{escape(str(path))}[/bold]")
    console.print("[dim]Open it in a browser and drag the slider (or hit Play).[/dim]")
    return 0
