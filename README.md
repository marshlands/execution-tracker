# execution-tracker

> Log what you ship. Understand your output vectors. Stop fragmenting your attention.

`et` is a dead-simple, **local-first** CLI for knowledge workers and builders who want to **see the shape of their days** — not just count commits or hours.

> **Your data never leaves your machine.** The GitHub repository contains only the tool. Your actual logs live in `~/.local/share/execution-tracker/ships.db` and are excluded from git.

## Why This Exists

Most productivity tools track time or tasks. Very few track **output vectors** — the actual directions in which you create value.

When you ship 7 small things across 6 different projects in one day, your brain pays a massive context-switching tax. `et` makes that visible and gently (but honestly) tells you when you're fragmenting.

## Core Concepts

- **Ship**: A discrete thing you finished and put into the world (a PR, a doc, a migration, a design decision, a tough email thread, etc.).
- **Output Vector**: A dimension of your work (`backend`, `infra`, `writing`, `research`, `design`, `ops`, `mentoring`...). You define them.
- **Fragmentation**: Spreading yourself across too many vectors or projects without deep focus. `et` calculates a score and gives you warnings + suggestions.

## Data Storage & Privacy

`et` is **local-first by design**. Nothing you log ever leaves your machine unless you explicitly export it.

### Where your data lives

| What            | Default Location                                      | Notes                     |
|-----------------|-------------------------------------------------------|---------------------------|
| Ships & history | `~/.local/share/execution-tracker/ships.db`           | SQLite with WAL mode      |
| Focus state     | `~/.local/share/execution-tracker/state.json`         | Your current deep thread  |
| Configuration   | `~/.config/execution-tracker/config.toml`             | Optional, user-controlled |

The data directory respects the standard `XDG_DATA_HOME` environment variable if you want to relocate it.

### What actually gets stored

Only what **you** explicitly create with `et log` (or `et git import`):

- Description, timestamp, vectors, project, impact level, duration
- Optional metadata (e.g. git commit SHA when importing)

No system monitoring, no keystroke logging, no network calls, and **zero telemetry**.

### Git & GitHub safety

The repository contains **only the tool** — source code, documentation, examples, and build history.

Your personal execution data is explicitly excluded in [`.gitignore`](.gitignore):

- `*.db`, `*.db-wal`, `*.db-shm`
- The `data/` directory
- `.venv/`

This means it is completely safe to clone, develop on, and push this repository (public or private). Your real history — client work, workouts, deep focus sessions, everything — stays on your machine.

### Inspecting, backing up, or migrating your data

```bash
# Explore your ships
sqlite3 ~/.local/share/execution-tracker/ships.db ".tables"
sqlite3 ~/.local/share/execution-tracker/ships.db "
  SELECT datetime(timestamp, 'localtime'), description, project 
  FROM ships 
  ORDER BY timestamp DESC 
  LIMIT 20;
"

# Simple backup
cp -r ~/.local/share/execution-tracker ~/backups/execution-tracker-$(date +%F)
```

You fully own your data. Delete the directory to start over. Copy it to move to another machine. Query it with any SQLite tool.

No accounts. No cloud. No surprises.

## Quick Start

```bash
# 1. Install (editable for now)
cd ~/projects/execution-tracker
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Log your first ship
et log "Shipped user impersonation for support" -v backend -v api -p payments -i high

# 3. See how your day looks
et
# or
et today
```

## Daily Usage

### Log a ship (the main command)

```bash
et log "Fixed the flaky test suite" -v testing -p platform -i medium -d 45
et log "Wrote the RFC for new auth flow" -v writing -v research -p identity
et log "Paired with Alex on the checkout redesign" -v design -p checkout
```

Flags:
- `-v, --vector` — repeatable. These become your personal output dimensions.
- `-p, --project` — the context or initiative. **If omitted, `et` will auto-detect from the current git repo** (configurable).
- `-i, --impact` — `low` | `medium` (default) | `high`
- `-d, --duration` — minutes spent (optional but useful later)

### See today's reality

```bash
et
# or
et today
```

You'll get:
- Breakdown by output vector (counts)
- Project spread
- A **Focus Health** panel with clear color coding
- Actionable suggestions when you're fragmenting
- Your most recent ships

### Declare a focus thread

When you're going deep on one thing:

```bash
et focus "Payments v3 migration"
```

Now when you log things that don't align with this focus, the fragmentation warnings become more sensitive. This is one of the highest-leverage features.

Clear it anytime:

```bash
et focus
```

### Review history

```bash
et week          # 7-day ship counts + trend
et ships -d 14   # detailed list
et ships -v backend -p platform
et vectors       # all vectors you've ever used
```

## The Fragmentation Model (v0.1)

The score is intentionally simple and transparent:

1. Base cost = `unique_vectors + (unique_projects × 0.6)`
2. Rapid switching penalty = each time you change primary vector/project within a 90-minute window
3. Result is shown as `fragmentation_score`

**Interpretation** (rough guide):
- Below your `mild_threshold` → Strong focus day
- Between mild/high → Mild fragmentation (yellow)
- Above `high_threshold` → High fragmentation (red)

You can customize these values (and the rapid-switch window) in the config file.

The suggestions are generated from the same data. Over time this can become smarter.

## Git Integration

`et` can automatically detect the git repository you're in.

### Auto-tagging projects

When you run:

```bash
et log "Landed the new checkout flow" -v backend -i high
```

If you're inside a git repo and didn't pass `-p`, it will tag the ship with the repo name (derived from the folder or `origin` remote).

You can disable this in config:

```toml
[git]
auto_project = false
```

### Importing history from git

```bash
# Import the last 30 commits as ships (deduplicated by SHA)
et git import

# More control
et git import --since "3 weeks ago" -n 100 -v coding -v review
et git import --dry-run          # Preview first
```

Imported commits are tagged with the git SHA in metadata so they are never duplicated on re-runs.

## Configuration

Create `~/.config/execution-tracker/config.toml` (or `$XDG_CONFIG_HOME/...`).

See `config.example.toml` in the repo for the full template.

Key section:

```toml
[fragmentation]
mild_threshold = 5.0
high_threshold = 8.5
rapid_switch_window_minutes = 120
```

This lets you define your personal "geometry" of acceptable context switching.

Run `et config` to see the current effective values and the exact path.

## Philosophy

This tool is built on a few beliefs:

1. **Output > activity**. Hours and tickets lie. Ships don't.
2. **Vectors matter more than volume**. Shipping 5 things in one vector is usually better than 1 thing in 5 vectors.
3. **Fragmentation is the silent killer** of deep work. Most people don't see how badly they're doing it until it's too late.
4. **Lightweight beats perfect**. If it takes more than 8 seconds to log a ship, you won't do it.

## Roadmap (ideas, not promises)

- Weekly + monthly trend reports and charts
- Better deduping + smart conventional-commit parsing on import
- Focus timer that can auto-log blocks
- Vector aliases / grouping in config
- Export to JSON/CSV + simple stats scripts
- Optional TUI dashboard

## Development

```bash
# Install dev deps
pip install -e ".[dev]"

# Run the CLI directly during development
python -m execution_tracker.cli today

# Or after install
et --help
```

## License

MIT
