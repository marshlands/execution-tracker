"""Fragmentation detection and daily vector analytics."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from .config import Config
from .models import DailySummary, FragmentationWarning, Ship


def compute_daily_summary(
    ships: list[Ship], target_date: date, config: Config | None = None
) -> DailySummary:
    """Build a rich daily summary for the given local date."""
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

    score = _compute_fragmentation_score(
        day_ships,
        unique_vectors,
        unique_projects,
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
        fragmentation_score=round(score, 1),
        ships=sorted(day_ships, key=lambda s: s.timestamp, reverse=True),
    )


def _compute_fragmentation_score(
    ships: list[Ship],
    unique_vectors: int,
    unique_projects: int,
    *,
    rapid_switch_window: int = 90,
) -> float:
    if not ships:
        return 0.0

    base = (unique_vectors * 1.0) + (unique_projects * 0.6)

    # Penalize rapid context switching
    switches = 0
    prev_primary: str | None = None
    prev_time: datetime | None = None

    for ship in sorted(ships, key=lambda s: s.timestamp):
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
    """Return an actionable warning based on the daily summary."""
    cfg = config or Config()
    score = summary.fragmentation_score
    uv = summary.unique_vectors
    up = summary.unique_projects

    mild = cfg.fragmentation.mild_threshold
    high = cfg.fragmentation.high_threshold

    if score < mild and uv <= 3:
        return FragmentationWarning(
            level="ok",
            message="Strong focus today. Keep it up.",
            suggestions=[],
            unique_threads=uv + up,
            score=score,
        )

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
