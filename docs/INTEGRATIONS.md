# Integrations

The dashboard is intentionally **read-only against the file system**. It does
not call APIs at request time. Instead, you (or your agents) drop files in the
paths it watches, and the dashboard parses them when a user loads a page.

That separation matters: it keeps the web tier fast, avoids storing
credentials inside the app, and lets each PM bring their own integrations.

## Where the dashboard reads from

| Page              | File(s) it reads                                     |
|-------------------|------------------------------------------------------|
| `/` (dashboard)   | `memory-bank/dashboard.md`                           |
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

## A note on credentials

The dashboard server itself never reads API tokens. Keep credentials in your
fetch scripts (typically in `.env` files outside the repo). The web server
only needs to read the cache files those scripts produce.
