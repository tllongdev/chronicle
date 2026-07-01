"""Render diffs and timelines to the console (rich) and to markdown."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape

from .models import DiffResult, EntityTimeline, FieldChange

_KIND_STYLE = {
    "first_seen": "green",
    "changed": "yellow",
    "disappeared": "red",
    "reappeared": "cyan",
    "observation": "dim",
}


def _fmt_change(c: FieldChange) -> str:
    return f"{c.field}: {c.before!r} -> {c.after!r}"


def print_diff(console: Console, diff: DiffResult) -> None:
    console.print(
        f"\n[bold]Change report[/bold]  [dim]{escape(diff.from_label)}[/dim] "
        f"[bold]->[/bold] [dim]{escape(diff.to_label)}[/dim]"
    )
    console.print(
        f"[dim]{diff.from_observed_at} -> {diff.to_observed_at}[/dim]\n"
    )
    if diff.is_empty():
        console.print("[dim]No changes between these snapshots.[/dim]")
        return

    def section(title: str, items: list[str], style: str) -> None:
        if not items:
            return
        console.print(f"[bold {style}]{title} ({len(items)})[/bold {style}]")
        for line in items:
            console.print(f"  [{style}]•[/{style}] {escape(line)}")
        console.print()

    section("Entities added", [f"{e.name} ({e.type})" for e in diff.entities_added], "green")
    section("Entities removed", [f"{e.name} ({e.type})" for e in diff.entities_removed], "red")
    section(
        "Entities changed",
        [f"{e.name} ({e.type}): " + "; ".join(_fmt_change(c) for c in e.changes)
         for e in diff.entities_changed],
        "yellow",
    )
    section(
        "Relationships added",
        [f"{e.source} -{e.relationship}-> {e.target}" for e in diff.edges_added], "green")
    section(
        "Relationships removed",
        [f"{e.source} -{e.relationship}-> {e.target}" for e in diff.edges_removed], "red")
    section(
        "Relationships changed",
        [f"{e.source} -{e.relationship}-> {e.target}: "
         + "; ".join(_fmt_change(c) for c in e.changes) for e in diff.edges_changed],
        "yellow",
    )


def print_timeline(console: Console, tl: EntityTimeline) -> None:
    console.print(f"\n[bold]{escape(tl.name)}[/bold] [dim]({escape(tl.type)})[/dim]")
    if not tl.events:
        console.print("[dim]No recorded history.[/dim]")
        return
    for ev in tl.events:
        style = _KIND_STYLE.get(ev.kind, "white")
        head = f"  [{style}]{ev.observed_at[:19]}[/{style}]  [{style}]{ev.kind}[/{style}]"
        head += f"  [dim]({escape(ev.snapshot_label)})[/dim]"
        console.print(head)
        if ev.detail:
            console.print(f"      [dim]{escape(ev.detail)}[/dim]")
        for c in ev.changes:
            console.print(f"      [dim]- {escape(_fmt_change(c))}[/dim]")


def diff_to_markdown(diff: DiffResult) -> str:
    lines = [
        f"# Change Report: {diff.from_label} -> {diff.to_label}",
        f"\n_{diff.from_observed_at} -> {diff.to_observed_at}_\n",
    ]
    if diff.is_empty():
        lines.append("No changes between these snapshots.\n")
        return "\n".join(lines)

    def block(title: str, items: list[str]) -> None:
        if not items:
            return
        lines.append(f"## {title} ({len(items)})\n")
        lines.extend(f"- {i}" for i in items)
        lines.append("")

    block("Entities added", [f"**{e.name}** ({e.type})" for e in diff.entities_added])
    block("Entities removed", [f"**{e.name}** ({e.type})" for e in diff.entities_removed])
    block("Entities changed",
          [f"**{e.name}** ({e.type}) - " + "; ".join(_fmt_change(c) for c in e.changes)
           for e in diff.entities_changed])
    block("Relationships added",
          [f"{e.source} → {e.relationship} → {e.target}" for e in diff.edges_added])
    block("Relationships removed",
          [f"{e.source} → {e.relationship} → {e.target}" for e in diff.edges_removed])
    block("Relationships changed",
          [f"{e.source} → {e.relationship} → {e.target} - "
           + "; ".join(_fmt_change(c) for c in e.changes) for e in diff.edges_changed])
    return "\n".join(lines) + "\n"
