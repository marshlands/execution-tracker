"""Pydantic data models for Execution Tracker."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Impact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Ship(BaseModel):
    """A single completed output / 'ship'.

    The `metadata` field supports arbitrary JSON-serializable values
    (strings, numbers, booleans, nested objects, etc.). It is intended
    for tool-specific extra information (e.g. git SHA, time taken, etc.).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    description: str
    project: str | None = None
    impact: Impact = Impact.MEDIUM
    duration_minutes: int | None = None
    vectors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("vectors")
    @classmethod
    def normalize_vectors(cls, v: list[str]) -> list[str]:
        # Lowercase, strip, dedupe while preserving order
        seen: set[str] = set()
        result: list[str] = []
        for item in v:
            cleaned = item.strip().lower()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Description cannot be empty")
        return v

    @field_validator("metadata", mode="before")
    @classmethod
    def ensure_metadata_is_dict(cls, v: Any) -> dict[str, Any]:
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        return {}

    def primary_vector(self) -> str | None:
        return self.vectors[0] if self.vectors else None


class DailySummary(BaseModel):
    """Aggregated output vectors for a single calendar day (local time)."""

    date: str  # YYYY-MM-DD
    total_ships: int
    by_vector: dict[str, int]  # vector -> ship count
    by_project: dict[str, int]
    by_impact: dict[str, int]
    unique_vectors: int
    unique_projects: int
    vectors_outside_focus: int = 0
    projects_outside_focus: int = 0
    fragmentation_score: float  # 0.0 (focused) .. higher = more fragmented
    ships: list[Ship] = Field(default_factory=list)  # detailed for display


class FragmentationWarning(BaseModel):
    """Actionable warning when the user appears to be fragmenting."""

    level: str  # "ok", "mild", "high"
    message: str
    suggestions: list[str] = Field(default_factory=list)
    unique_threads: int
    score: float


class FocusState(BaseModel):
    """Current sticky focus context (optional but powerful for warnings)."""

    thread: str
    started_at: datetime
    project: str | None = None
