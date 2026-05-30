"""SQLite-backed storage for ships and vectors."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .models import Impact, Ship

if TYPE_CHECKING:
    from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS ships (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    description TEXT NOT NULL,
    project TEXT,
    impact TEXT NOT NULL DEFAULT 'medium',
    duration_minutes INTEGER,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ship_vectors (
    ship_id TEXT NOT NULL,
    vector TEXT NOT NULL,
    PRIMARY KEY (ship_id, vector),
    FOREIGN KEY (ship_id) REFERENCES ships(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ships_timestamp ON ships(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ship_vectors_vector ON ship_vectors(vector);
"""


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)

            # Lightweight migration for existing databases
            self._migrate_schema(conn)

            cur = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'")
            row = cur.fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
            conn.commit()

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Add new columns for older schema versions."""
        # Add metadata column if missing (added in v2)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(ships)").fetchall()]
        if "metadata" not in cols:
            conn.execute("ALTER TABLE ships ADD COLUMN metadata TEXT DEFAULT '{}'")

    def log_ship(self, ship: Ship) -> None:
        with closing(self._connect()) as conn:
            metadata_json = json.dumps(ship.metadata or {})
            conn.execute(
                """
                INSERT INTO ships (id, timestamp, description, project, impact, duration_minutes, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ship.id,
                    ship.timestamp.isoformat(),
                    ship.description,
                    ship.project,
                    ship.impact.value,
                    ship.duration_minutes,
                    metadata_json,
                ),
            )
            if ship.vectors:
                conn.executemany(
                    "INSERT OR IGNORE INTO ship_vectors (ship_id, vector) VALUES (?, ?)",
                    [(ship.id, v) for v in ship.vectors],
                )
            conn.commit()

    def get_recent_ships(self, days: int = 7) -> list[Ship]:
        """Return ships from the last N days (UTC based cutoff)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT s.*, GROUP_CONCAT(sv.vector) as vectors
                FROM ships s
                LEFT JOIN ship_vectors sv ON s.id = sv.ship_id
                WHERE s.timestamp >= ?
                GROUP BY s.id
                ORDER BY s.timestamp DESC
                """,
                (cutoff.isoformat(),),
            ).fetchall()

        return [self._row_to_ship(row) for row in rows]

    def get_ships_for_date(self, day: date) -> list[Ship]:
        """Ships whose *local* calendar date matches the given day."""
        # We store UTC timestamps. For "today" we filter by local date.
        # Simple approach: fetch a wider window and filter in Python (fine for personal use).
        ships = self.get_recent_ships(days=2)  # safe window
        return [s for s in ships if s.timestamp.astimezone().date() == day]

    def get_all_vectors(self) -> list[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT DISTINCT vector FROM ship_vectors ORDER BY vector"
            ).fetchall()
        return [r[0] for r in rows]

    def _row_to_ship(self, row: sqlite3.Row) -> Ship:
        vectors = row["vectors"].split(",") if row["vectors"] else []
        try:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
        except Exception:
            meta = {}
        return Ship(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            description=row["description"],
            project=row["project"],
            impact=Impact(row["impact"]),
            duration_minutes=row["duration_minutes"],
            vectors=vectors,
            metadata=meta if isinstance(meta, dict) else {},
        )
