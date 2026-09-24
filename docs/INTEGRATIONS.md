# Integrations

The dashboard is intentionally **read-only against the file system**. It does
not call APIs at request time. Instead, you (or your agents) drop files in the
paths it watches, and the dashboard parses them when a user loads a page.

That separation matters: it keeps the web tier fast, avoids storing
credentials inside the app, and lets each PM bring their own integrations.

## Where the dashboard reads from

| Page              | File(s) it reads                                     |
|-------------------|------------------------------------------------------|
| `/` (dashboard)   | `memory-bank/dashboard.json` (preferred) + `memory-bank/dashboard.md` |
| `/briefing`       | `memory-bank/morning-briefing.md`, `geekbot-standup.md`, `weekly-report.md` |
| `/people`         | `agents/<Project>/logs/*.json` (Noko-style)          |
| `/retrospector`   | `memory-bank/retrospector-report.md` + sibling JSON  |
| PR staleness      | `dashboard/data/staleness-cache.json`                |
| Deploys           | `dashboard/data/deployment-schedule.json`            |
| Project pages     | `agents/<Project>/pm/meetings/reports/*.md`          |

## How to add an integration

You have two patterns to pick from.

### Pattern A — your agent writes the file

You already work with an agent. Tell it to update the file. Example for the
morning briefing: a `morning-briefing.sh` script that wakes an LLM, hands it
GitHub + Noko data, and asks it to overwrite `memory-bank/morning-briefing.md`
in the shape the parser expects (`parse_briefing()` in `dashboard/data.py`).

This is how the original Hivemind worked. The template ships without the
scripts; you bring your own.

### Pattern B — a thin shell script

If you don't want an agent in the loop, a shell script that hits an API and
writes JSON to `dashboard/data/<something>.json` works fine. The dashboard
will pick it up as long as you add a parser to `dashboard/data.py`.

## Specific integrations

### Structured dashboard sidecar (`dashboard.json`)

Parsing a status table out of prose is fragile. An agent that bolds a status, adds a column, or reorders rows can make a project vanish from the dashboard without an error. Whatever writes `memory-bank/dashboard.md` should also write `memory-bank/dashboard.json` with the same content in structured form:

```json
{
  "updated": "2026-05-13",
  "projects": [
    {"name": "ProjectAlpha", "client": "Example Org", "type": "Active development", "status": "On track", "summary": "Sprint 4 in flight."}
  ],
  "priorities": [
    {"project": "ProjectAlpha", "text": "Land the search-relevance experiment."}
  ],
  "themes": [
    {"title": "Accessibility audits", "detail": "Both client projects have audits scheduled."}
  ]
}
```

`name` is required and must match a `name` in `config/projects.yml` for colors to apply. `client` defaults to the project name. `status` is mapped to a CSS class through `status_map` in `config/dashboard.yml`. A theme can also be a plain string.

The dashboard uses the sidecar for the status table, priorities, and themes when it is present, parses as valid JSON, has at least one named project, and is no more than a minute older than `dashboard.md`. Otherwise it falls back to parsing the markdown, so a stale or broken sidecar never hides newer prose. The per-project detail sections (budget, active work, blockers, open PRs) still come from `dashboard.md`. `parse_dashboard()` reports which path it took in its `source` field (`json`, `markdown`, or `none`).

If you generate these files with an LLM, ask for both in the same prompt and have it write the JSON last, after the markdown, so the timestamps line up.


### GitHub PR staleness

The dashboard reads `dashboard/data/staleness-cache.json` with shape:

```json
{
  "fetched_at": "2026-05-13T07:00:00Z",
  "data": {
    "prs": {"ProjectName": [{...}, ...]},
    "stale_items": [{...}, ...]
  }
}
```

Write a script that uses `gh pr list --json ...` per project, classifies by
age against `STALE_WARN_DAYS` / `STALE_CRIT_DAYS`, and writes the cache. The
existing `refresh_staleness()` function in `data.py` shows the exact shape.

### Noko time entries

Drop daily JSON dumps at `agents/<Project>/logs/YYYY-MM-DD.json`. Each entry
should look like:

```json
{"date": "2026-05-13", "user": {"first_name": "...", "last_name": "..."},
 "minutes": 60, "description": "...", "tags": [{"name": "maintenance"}, ...]}
```

See `parse_noko_entries()` in `data.py` for the full expected shape.

### Custom integration

To add a brand new data source:

1. Decide where the cache file lives (probably `dashboard/data/<name>.json`).
2. Write a fetcher script that produces it. Run it on a schedule.
3. Add a `load_<name>()` function to `dashboard/data.py` that reads the file.
4. Add the result to `get_all_data()` so templates can render it.
5. Add a template partial that shows it.
6. Optional: add the source to the freshness panel in `get_health()`.

## Writing files from the dashboard

The dashboard writes a few files of its own: `dashboard/data/meeting-actions-status.json` (dismissed action items), `dashboard/data/staleness-cache.json` (from `refresh_staleness()`), and the editable standup and weekly-report markdown. All of these go through `dashboard/storage.py`:

- `atomic_write_text` / `atomic_write_json` write to a temp file in the same directory, fsync it, then rename it over the target. A crash mid-write leaves the previous file intact instead of a truncated one.
- `locked(path)` serializes a read-modify-write on one file across the server's worker threads, so two quick clicks can't both read the old state and drop each other's update. It is an in-process lock, which is enough because the dashboard runs as a single uvicorn process.
- `load_json_for_update` raises `CorruptStateError` instead of returning an empty default when the file exists but can't be parsed, so a write never replaces an unreadable file with an empty one.

Use the same helpers for any new state file you add. Fetch scripts that write cache files outside the server should follow the same pattern (write to a temp file, then rename).

## A note on credentials

The dashboard server itself never reads API tokens. Keep credentials in your
fetch scripts (typically in `.env` files outside the repo). The web server
only needs to read the cache files those scripts produce.
