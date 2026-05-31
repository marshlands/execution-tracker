"""Fragmentation detection and daily vector analytics."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Config
from .models import DailySummary, FocusState, FragmentationWarning, Ship


def _get_data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "execution-tracker"
    return Path.home() / ".local" / "share" / "execution-tracker"


def _get_state_path() -> Path:
    return _get_data_dir() / "state.json"


def load_focus() -> FocusState | None:
    """Load the current focus thread (if any)."""
    path = _get_state_path()
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text())
        return FocusState(**data)
    except Exception:
        return None


def compute_daily_summary(
    ships: list[Ship], target_date: date, config: Config | None = None
) -> DailySummary:
    """Build a rich daily summary for the given local date.

    When a focus thread is active, vectors used after the focus started
    are heavily discounted for the fragmentation *score* (they no longer
    punish you for staying on task).
    """
    cfg = config or Config()
    day_ships = [s for s in ships if s.timestamp.astimezone().date() == target_date]

    by_vector: Counter[str] = Counter()
    by_project: Counter[str] = Counter()
    by_impact: Counter[str] = Counter()

    for ship in day_ships:
        for v in ship.vectors:
            by_vector[v] += 1
        if ship.project:
            by_project[ship.project] += 1
        by_impact[ship.impact.value] += 1

    unique_vectors = len(by_vector)
    unique_projects = len(by_project)

    # --- Focus-aware fragmentation calculation ---
    focus = load_focus()
    if focus:
        focus_start = focus.started_at
        # Only vectors/projects from ships *before* the focus started count
        # toward the fragmentation penalty. Post-focus work is considered
        # "on task" and heavily discounted.
        pre_focus_vectors: set[str] = set()
        pre_focus_projects: set[str] = set()
        for ship in day_ships:
            ship_ts = ship.timestamp
            f_start = focus_start
            # Normalize timezone awareness for safe comparison
            if ship_ts.tzinfo is not None and f_start.tzinfo is None:
                f_start = f_start.replace(tzinfo=ship_ts.tzinfo)
            elif ship_ts.tzinfo is None and f_start.tzinfo is not None:
                ship_ts = ship_ts.replace(tzinfo=f_start.tzinfo)

            if ship_ts < f_start:
                pre_focus_vectors.update(ship.vectors)
                if ship.project:
                    pre_focus_projects.add(ship.project)

        effective_unique_vectors = len(pre_focus_vectors)
        effective_unique_projects = len(pre_focus_projects)
    else:
        effective_unique_vectors = unique_vectors
        effective_unique_projects = unique_projects

    score = _compute_fragmentation_score(
        day_ships,
        effective_unique_vectors,
        effective_unique_projects,
        focus=focus,
        rapid_switch_window=cfg.fragmentation.rapid_switch_window_minutes,
    )

    return DailySummary(
        date=target_date.isoformat(),
        total_ships=len(day_ships),
        by_vector=dict(sorted(by_vector.items(), key=lambda x: -x[1])),
        by_project=dict(sorted(by_project.items(), key=lambda x: -x[1])),
        by_impact=dict(by_impact),
        unique_vectors=unique_vectors,
        unique_projects=unique_projects,
        vectors_outside_focus=effective_unique_vectors,
        projects_outside_focus=effective_unique_projects,
        fragmentation_score=round(score, 1),
        ships=sorted(day_ships, key=lambda s: s.timestamp, reverse=True),
    )


def _compute_fragmentation_score(
    ships: list[Ship],
    unique_vectors: int,
    unique_projects: int,
    *,
    focus: FocusState | None = None,
    rapid_switch_window: int = 90,
) -> float:
    if not ships:
        return 0.0

    base = (unique_vectors * 1.0) + (unique_projects * 0.6)

    # Penalize rapid context switching
    switches = 0
    prev_primary: str | None = None
    prev_time: datetime | None = None

    focus_start = focus.started_at if focus else None
    focus_thread = focus.thread if focus else None

    for ship in sorted(ships, key=lambda s: s.timestamp):
        # If we're under an active focus and this ship was logged after the
        # focus started, treat the entire focused block as one stable thread.
        if focus_start:
            ship_ts = ship.timestamp
            f_start = focus_start
            if ship_ts.tzinfo is not None and f_start.tzinfo is None:
                f_start = f_start.replace(tzinfo=ship_ts.tzinfo)
            elif ship_ts.tzinfo is None and f_start.tzinfo is not None:
                ship_ts = ship_ts.replace(tzinfo=f_start.tzinfo)

            if ship_ts >= f_start:
                primary = focus_thread or "focus"
            else:
                primary = ship.primary_vector() or ship.project or "unknown"
        else:
            primary = ship.primary_vector() or ship.project or "unknown"

        if prev_primary is not None and prev_time is not None:
            delta = (ship.timestamp - prev_time).total_seconds() / 60
            if primary != prev_primary and delta < rapid_switch_window:
                switches += 1
        prev_primary = primary
        prev_time = ship.timestamp

    switch_penalty = switches * 0.8
    return max(0.0, base + switch_penalty)


def analyze_fragmentation(
    summary: DailySummary, config: Config | None = None
) -> FragmentationWarning:
    """Return an actionable warning based on the daily summary.

    When a focus is active, the fragmentation score only reflects
    vectors used *outside* that focus. This prevents the score from
    punishing you for deep, focused work.
    """
    cfg = config or Config()
    score = summary.fragmentation_score
    uv = summary.unique_vectors          # total vectors (for display)
    up = summary.unique_projects

    mild = cfg.fragmentation.mild_threshold
    high = cfg.fragmentation.high_threshold

    focus = load_focus()

    if score < mild and uv <= 3:
        return FragmentationWarning(
            level="ok",
            message="Strong focus today. Keep it up.",
            suggestions=[],
            unique_threads=uv + up,
            score=score,
        )

    if focus:
        # Much nicer messaging when the user is using focus
        if score < high:
            level = "mild"
            msg = f"Mild fragmentation outside focus. (Focus: {focus.thread})"
            suggestions = [
                "Good job protecting your focus time.",
                "Try to batch any non-focus work into fewer blocks.",
            ]
        else:
            level = "high"
            msg = f"High fragmentation *outside* your focus '{focus.thread}' (score {score})."
            suggestions = [
                "The score now only counts work that broke your focus.",
                "Batch non-Monk-Mode tasks. Protect the focused block.",
                "Consider extending your current focus window.",
            ]
    else:
        if score < high:
            level = "mild"
            msg = f"Mild fragmentation: {uv} vectors and {up} projects touched."
            suggestions = [
                "Batch similar work together when possible.",
                "Consider declaring a focus thread with `et focus`.",
            ]
        else:
            level = "high"
            msg = f"High fragmentation detected ({uv} vectors, {up} projects, score {score})."
            suggestions = [
                "You're switching a lot — your brain pays a heavy tax for this.",
                "Pick the highest-leverage vector and protect a 2-hour block for it.",
                "Use `et focus \"<thread>\"` before deep work sessions.",
            ]

    return FragmentationWarning(
        level=level,
        message=msg,
        suggestions=suggestions,
        unique_threads=uv + up,
        score=score,
    )


def get_weekly_trend(ships: list[Ship]) -> dict:
    """Very lightweight weekly stats."""
    today = date.today()
    trend: dict[str, int] = defaultdict(int)

    for i in range(7):
        d = today - timedelta(days=i)
        day_ships = [s for s in ships if s.timestamp.astimezone().date() == d]
        trend[d.isoformat()] = len(day_ships)

    return dict(sorted(trend.items()))
