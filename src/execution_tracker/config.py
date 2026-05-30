"""Simple TOML-based configuration for Execution Tracker.

Location: ~/.config/execution-tracker/config.toml (or $XDG_CONFIG_HOME)

Example:

[fragmentation]
mild_threshold = 5.0
high_threshold = 8.5
rapid_switch_window_minutes = 120

[git]
auto_project = true                 # Auto-fill --project from git repo name
default_vectors = ["coding"]        # Used by `et git import` when no vectors given
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[import-not-found]


CONFIG_DIR_NAME = "execution-tracker"


@dataclass
class FragmentationConfig:
    """Tunable parameters for fragmentation scoring and warnings."""

    mild_threshold: float = 4.5
    high_threshold: float = 7.0
    rapid_switch_window_minutes: int = 90
    # Future: weight for projects vs vectors, etc.


@dataclass
class GitConfig:
    """Git integration settings."""

    auto_project: bool = True
    default_vectors: list[str] = field(default_factory=lambda: ["coding"])


@dataclass
class Config:
    fragmentation: FragmentationConfig = field(default_factory=FragmentationConfig)
    git: GitConfig = field(default_factory=GitConfig)

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """Load config, falling back to sensible defaults."""
        if config_path is None:
            config_path = _get_config_path()

        if not config_path.exists():
            return cls()

        try:
            with config_path.open("rb") as f:
                data: dict[str, Any] = tomllib.load(f)
        except Exception:
            # Never let bad config break the tool
            return cls()

        frag = data.get("fragmentation", {})
        git = data.get("git", {})

        return cls(
            fragmentation=FragmentationConfig(
                mild_threshold=frag.get("mild_threshold", 4.5),
                high_threshold=frag.get("high_threshold", 7.0),
                rapid_switch_window_minutes=frag.get("rapid_switch_window_minutes", 90),
            ),
            git=GitConfig(
                auto_project=git.get("auto_project", True),
                default_vectors=git.get("default_vectors", ["coding"]),
            ),
        )


def _get_config_path() -> Path:
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        base = Path(xdg_config)
    else:
        base = Path.home() / ".config"
    return base / CONFIG_DIR_NAME / "config.toml"


def get_config_dir() -> Path:
    """Return the config directory (creates it if missing)."""
    path = _get_config_path().parent
    path.mkdir(parents=True, exist_ok=True)
    return path
