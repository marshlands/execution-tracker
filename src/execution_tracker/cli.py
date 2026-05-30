"""Typer + Rich CLI for Execution Tracker."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .analyzer import analyze_fragmentation, compute_daily_summary, get_weekly_trend
from .config import Config, get_config_dir
from .git_utils import get_git_info, get_recent_commits
from .models import FocusState, Impact, Ship
from .storage import Storage

app = typer.Typer(
    name="et",
    help="Track daily output vectors. Log what you ship. Get warned when you fragment.",
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()


def get_storage() -> Storage:
    data_dir = _get_data_dir()
    db_path = data_dir / "ships.db"
    return Storage(db_path)


def _get_data_dir() -> Path:
    import os

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "execution-tracker"
    return Path.home() / ".local" / "share" / "execution-tracker"


def _get_state_path() -> Path:
    return _get_data_dir() / "state.json"


def get_config() -> Config:
    """Load user configuration (cached per process is fine for CLI)."""
    return Config.load()


def _maybe_auto_project(requested_project: str | None) -> str | None:
    """Auto-detect git project name when user didn't explicitly pass --project."""
    cfg = get_config()
    if requested_project is not None or not cfg.git.auto_project:
        return requested_project

    info = get_git_info()
    if info:
        return info.project_name
    return None


def load_focus() -> FocusState | None:
    path = _get_state_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return FocusState(**data)
    except Exception:
        return None


def save_focus(focus: FocusState | None) -> None:
    path = _get_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if focus is None:
        if path.exists():
            path.unlink()
        return
    path.write_text(focus.model_dump_json(indent=2))


def _render_ship_row(ship: Ship) -> list[str]:
    ts = ship.timestamp.astimezone().strftime("%H:%M")
    vectors = ", ".join(ship.vectors) if ship.vectors else "-"
    proj = ship.project or "-"
    return [ts, ship.description[:60], proj, vectors, ship.impact.value]


@app.command("log", help="Log something you shipped today.")
def log_ship(
    description: Annotated[str, typer.Argument(help="What did you ship?")],
    vector: Annotated[
        list[str] | None,
        typer.Option(
            "-v",
            "--vector",
            help="Output vector(s) this contributes to (repeatable). Example: -v backend -v api",
        ),
    ] = None,
    project: Annotated[
        str | None, typer.Option("-p", "--project", help="Project or context name")
    ] = None,
    impact: Annotated[
        Impact, typer.Option("-i", "--impact", help="Impact level")
    ] = Impact.MEDIUM,
    duration: Annotated[
        int | None,
        typer.Option("-d", "--duration", help="Minutes spent (optional)"),
    ] = None,
) -> None:
    storage = get_storage()
    auto_project = _maybe_auto_project(project)

    ship = Ship(
        description=description,
        vectors=vector or [],
        project=auto_project,
        impact=impact,
        duration_minutes=duration,
    )
    storage.log_ship(ship)

    # Show immediate feedback + today's state
    console.print(f"[bold green]✓ Logged ship[/bold green]  [dim]{ship.id[:8]}[/dim]")
    if auto_project and auto_project != project:
        console.print(f"[dim]Auto-tagged project:[/dim] [cyan]{auto_project}[/cyan]")
    _show_today(storage, just_logged=ship.id)


@app.command("today", help="Show today's output vectors and fragmentation status.")
def today() -> None:
    storage = get_storage()
    _show_today(storage)


def _show_today(storage: Storage, just_logged: str | None = None) -> None:
    today_date = date.today()
    cfg = get_config()
    recent = storage.get_recent_ships(days=2)
    summary = compute_daily_summary(recent, today_date, config=cfg)
    warning = analyze_fragmentation(summary, config=cfg)

    # Header
    title = Text()
    title.append("Today's Execution — ", style="bold")
    title.append(today_date.isoformat(), style="cyan")

    console.print(Panel(title, box=box.ROUNDED, padding=(0, 1)))

    # Vector breakdown
    if summary.by_vector:
        vec_table = Table(title="Output Vectors", box=box.SIMPLE_HEAVY)
        vec_table.add_column("Vector", style="magenta")
        vec_table.add_column("Ships", justify="right", style="bold")
        for v, count in summary.by_vector.items():
            vec_table.add_row(v, str(count))
        console.print(vec_table)
    else:
        console.print("[dim]No ships logged yet today.[/dim]")

    # Quick stats
    stats = (
        f"[bold]{summary.total_ships}[/bold] ships  •  "
        f"[bold]{summary.unique_vectors}[/bold] vectors  •  "
        f"[bold]{summary.unique_projects}[/bold] projects  •  "
        f"frag score [bold]{summary.fragmentation_score}[/bold]"
    )
    console.print(stats)

    # Fragmentation warning
    color = {"ok": "green", "mild": "yellow", "high": "red"}[warning.level]
    warn_panel = Panel(
        f"[{color}]{warning.message}[/{color}]",
        title=f"[bold {color}]Focus Health: {warning.level.upper()}[/bold {color}]",
        border_style=color,
    )
    console.print(warn_panel)

    if warning.suggestions:
        for s in warning.suggestions:
            console.print(f"  → {s}")

    # Recent ships
    if summary.ships:
        ship_table = Table(title="Today's Ships", box=box.MINIMAL_DOUBLE_HEAD)
        ship_table.add_column("Time", style="dim")
        ship_table.add_column("What I shipped")
        ship_table.add_column("Project", style="cyan")
        ship_table.add_column("Vectors", style="magenta")
        ship_table.add_column("Impact", style="green")

        for ship in summary.ships[:8]:  # last 8 is plenty
            row = _render_ship_row(ship)
            if ship.id == just_logged:
                row = [f"[bold green]{x}[/bold green]" for x in row]
            ship_table.add_row(*row)
        console.print(ship_table)

    # Current focus (if any)
    focus = load_focus()
    if focus:
        age = (datetime.now(focus.started_at.tzinfo) - focus.started_at).seconds // 60
        console.print(
            f"\n[bold blue]Current focus[/bold blue]: {focus.thread} "
            f"[dim](started {age}m ago)[/dim]"
        )


@app.command("week", help="Show the last 7 days of shipping activity.")
def week() -> None:
    storage = get_storage()
    ships = storage.get_recent_ships(days=8)
    trend = get_weekly_trend(ships)

    table = Table(title="Last 7 Days", box=box.SIMPLE)
    table.add_column("Date")
    table.add_column("Ships", justify="right")

    total = 0
    for d, count in trend.items():
        total += count
        style = "green" if count >= 3 else ("yellow" if count >= 1 else "dim")
        table.add_row(d, Text(str(count), style=style))

    console.print(table)
    console.print(f"\n[bold]Total ships (7d):[/bold] {total}")


@app.command("ships", help="List recent ships (with optional filters).")
def list_ships(
    days: Annotated[int, typer.Option("-d", "--days", help="How many days back")] = 7,
    vector: Annotated[str | None, typer.Option("-v", "--vector")] = None,
    project: Annotated[str | None, typer.Option("-p", "--project")] = None,
) -> None:
    storage = get_storage()
    ships = storage.get_recent_ships(days=days)

    if vector:
        ships = [s for s in ships if vector.lower() in [vv.lower() for vv in s.vectors]]
    if project:
        ships = [s for s in ships if s.project and project.lower() in s.project.lower()]

    if not ships:
        console.print("[dim]No ships found matching filters.[/dim]")
        return

    table = Table(box=box.MINIMAL)
    table.add_column("When", style="dim")
    table.add_column("Description")
    table.add_column("Project", style="cyan")
    table.add_column("Vectors", style="magenta")

    for s in ships[:30]:
        when = s.timestamp.astimezone().strftime("%Y-%m-%d %H:%M")
        table.add_row(when, s.description[:55], s.project or "-", ", ".join(s.vectors) or "-")

    console.print(table)


@app.command(
    "focus",
    help="Declare current deep focus thread (makes fragmentation warnings smarter).",
)
def set_focus(
    thread: Annotated[
        str | None,
        typer.Argument(help="What thread/project are you locked into? (omit to clear)"),
    ] = None,
) -> None:
    if thread is None or thread.strip() == "":
        save_focus(None)
        console.print("[yellow]Focus cleared.[/yellow]")
        return

    focus = FocusState(thread=thread.strip(), started_at=datetime.now())
    save_focus(focus)
    console.print(f"[bold blue]Focus set:[/bold blue] {focus.thread}")
    console.print("[dim]Future logs that don't align will be flagged more strongly.[/dim]")


@app.command("config", help="Show config file location and current effective settings.")
def show_config() -> None:
    cfg = get_config()
    path = get_config_dir() / "config.toml"
    console.print(f"[bold]Config file:[/bold] {path}")
    console.print(f"[dim](create it to customize fragmentation thresholds)[/dim]\n")

    console.print("[bold cyan]Fragmentation[/bold cyan]")
    console.print(f"  mild_threshold  = {cfg.fragmentation.mild_threshold}")
    console.print(f"  high_threshold  = {cfg.fragmentation.high_threshold}")
    console.print(f"  rapid_switch    = {cfg.fragmentation.rapid_switch_window_minutes} minutes")

    console.print("\n[bold cyan]Git[/bold cyan]")
    console.print(f"  auto_project    = {cfg.git.auto_project}")
    console.print(f"  default_vectors = {cfg.git.default_vectors}")


@app.command("vectors", help="List all output vectors you've used so far.")
def list_vectors() -> None:
    storage = get_storage()
    vectors = storage.get_all_vectors()

    if not vectors:
        console.print("[dim]No vectors recorded yet. Start with `et log -v backend \"...\"`[/dim]")
        return

    table = Table(title="Your Output Vectors", box=box.SIMPLE)
    table.add_column("Vector", style="magenta bold")
    for v in vectors:
        table.add_row(v)
    console.print(table)


@app.command("init", help="Initialize (or repair) the local database.")
def init_db() -> None:
    storage = get_storage()
    console.print(f"[green]Database ready at[/green] {storage.db_path}")
    console.print("You're good to go. Try: [bold]et log -v coding \"Fixed the thing\"[/bold]")


# --------------------------------------------------------------------------- #
# Git integration
# --------------------------------------------------------------------------- #

git_app = typer.Typer(
    name="git",
    help="Git integration commands (auto project detection + commit import).",
    add_completion=False,
)
app.add_typer(git_app, name="git")


@git_app.command("import", help="Import recent git commits as ships (deduplicated by SHA).")
def git_import(
    limit: Annotated[int, typer.Option("-n", "--limit", help="Max commits to import")] = 30,
    since: Annotated[
        str | None,
        typer.Option("--since", help='e.g. "2 weeks ago", "2025-05-01"'),
    ] = None,
    vector: Annotated[
        list[str],
        typer.Option("-v", "--vector", help="Vectors to attach (defaults from config)"),
    ] = [],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview only, don't write")] = False,
) -> None:
    cfg = get_config()
    info = get_git_info()

    if info is None:
        console.print("[red]Not inside a git repository.[/red]")
        raise typer.Exit(1)

    console.print(
        f"[bold]Repo:[/bold] [cyan]{info.project_name}[/cyan]  "
        f"(branch: {info.current_branch or 'detached'})"
    )

    commits = get_recent_commits(limit=limit, since=since)

    if not commits:
        console.print("[dim]No commits found in the requested range.[/dim]")
        return

    storage = get_storage()
    imported = 0
    skipped = 0

    default_vectors = vector or cfg.git.default_vectors

    for c in commits:
        sha = c["sha"]
        # Check if we already imported this commit
        existing = [
            s
            for s in storage.get_recent_ships(days=365)
            if s.metadata.get("git_sha") == sha
        ]
        if existing:
            skipped += 1
            continue

        desc = c["subject"]
        if len(desc) > 120:
            desc = desc[:117] + "..."

        ship = Ship(
            description=desc,
            vectors=default_vectors,
            project=info.project_name,
            metadata={"git_sha": sha, "git_author": c["author"]},
        )

        if dry_run:
            console.print(f"[yellow]DRY[/yellow]  {sha[:7]}  {desc}")
        else:
            storage.log_ship(ship)
            imported += 1
            console.print(f"[green]✓[/green]  {sha[:7]}  {desc}")

    summary = (
        f"Imported [bold]{imported}[/bold] new ships, "
        f"skipped [dim]{skipped}[/dim] already-imported commits."
    )
    console.print(f"\n{summary}")
    if dry_run:
        console.print("[yellow]Dry run — nothing was written.[/yellow]")


# Default command when user just types `et`
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        # Default to "today" experience
        storage = get_storage()
        _show_today(storage)


if __name__ == "__main__":
    app()
