"""Lightweight git integration using subprocess (no extra dependencies)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import NamedTuple


class GitInfo(NamedTuple):
    repo_root: Path
    project_name: str          # Clean name derived from folder or remote
    current_branch: str | None


def is_git_repo(cwd: Path | None = None) -> bool:
    """Quick check whether we're inside a git working tree."""
    try:
        _run_git(["rev-parse", "--is-inside-work-tree"], cwd)
        return True
    except Exception:
        return False


def get_git_info(cwd: Path | None = None) -> GitInfo | None:
    """Return useful information about the current git repo, or None."""
    if not is_git_repo(cwd):
        return None

    try:
        repo_root = Path(
            _run_git(["rev-parse", "--show-toplevel"], cwd).strip()
        ).resolve()

        # Prefer the folder name of the repo root as the project name.
        # Users can override with remote name if they prefer (future option).
        project_name = repo_root.name

        # Try to get a nicer name from the origin remote if it exists
        try:
            remote_url = _run_git(
                ["config", "--get", "remote.origin.url"], cwd
            ).strip()
            if remote_url:
                # git@github.com:user/repo.git  or  https://github.com/user/repo.git
                name = remote_url.rstrip(".git").split("/")[-1].split(":")[-1]
                if name:
                    project_name = name
        except Exception:
            pass

        branch = None
        try:
            branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).strip()
            if branch == "HEAD":
                branch = None
        except Exception:
            pass

        return GitInfo(repo_root=repo_root, project_name=project_name, current_branch=branch)

    except Exception:
        return None


def get_recent_commits(
    limit: int = 20,
    since: str | None = None,
    cwd: Path | None = None,
) -> list[dict[str, str]]:
    """
    Return recent commits as list of dicts with keys:
    sha, message, author, date, body (optional)
    """
    fmt = "%H%x00%an%x00%ad%x00%s%x00%b"
    args = [
        "log",
        f"--format={fmt}",
        "--date=iso-strict",
        "--no-merges",
        f"-n{limit}",
    ]
    if since:
        args.insert(2, f"--since={since}")

    try:
        output = _run_git(args, cwd)
    except Exception:
        return []

    commits: list[dict[str, str]] = []
    for line in output.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\x00")
        if len(parts) < 4:
            continue
        sha, author, date, subject = parts[:4]
        body = parts[4] if len(parts) > 4 else ""
        commits.append(
            {
                "sha": sha,
                "author": author,
                "date": date,
                "subject": subject.strip(),
                "body": body.strip(),
            }
        )
    return commits


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run a git command and return stdout as text. Raises on non-zero exit."""
    cmd = ["git"] + args
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout
