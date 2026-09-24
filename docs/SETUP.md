# Setup

This guide walks through forking the template and configuring it for your
projects.

## 1. Fork & clone

Click "Use this template" on the GitHub repo, then clone your fork:

```bash
git clone <your-fork-url> my-dashboard
cd my-dashboard
```

## 2. Install dependencies

```bash
cd dashboard
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Python 3.11+ recommended.

## 3. Describe your projects

Open `config/projects.yml`. Replace the example projects with your own. This file is the single project roster: the dashboard reads it through `dashboard/config.py`, and any automation scripts you add should read the same file (PyYAML or `yq`). Keep it as the only list of projects so adding, renaming, or archiving one is a single edit.

```yaml
projects:
  - name: AcmeCorp
    color: "#6366f1"
    status: active
    category: client
    github: acme-org/website
    kenkeep_tag: acme

  - name: Internal
    color: "#64748b"
    category: internal

  - name: OldClient
    color: "#a855f7"
    status: archived
    archived_on: 2026-04-30
    category: client
```

| Field | Required | Meaning |
|-------|----------|---------|
| `name` | yes | Display name, also the URL slug and the key used in `dashboard.md` / `dashboard.json`. |
| `color` | no | Hex color for charts and badges. Grey if omitted. |
| `status` | no | `active` (default) or `archived`. Archived projects stay in the file for the record but are hidden from every dashboard view and skipped by scripts. Add `archived_on` if you want the date on record. |
| `category` | no | `client`, `internal`, or `bucket` (a non-client pool such as support or practice time). Only `client` projects count toward billable-people aggregates. |
| `client` | no | Older boolean form of `category`. `client: false` means internal. Ignored when `category` is set. |
| `github` | no | `owner/repo`, used for PR staleness. |
| `noko_dir` / `agent_dir` | no | Subdirectory of `agents/` for time-entry dumps and meeting notes. Default to `name`. |
| `kenkeep_tag` | no | Tag that marks this project's nodes in a kenkeep knowledge base, used to color them on the memory map. |

Scripts can read extra keys you add (calendar keywords, time-tracker IDs, chat channels). The dashboard ignores keys it doesn't know. An unknown `status` or `category` value fails loudly at startup rather than silently hiding a project.

## 4. Set top-level dashboard options

Open `config/dashboard.yml`:

- `title` — what shows in the browser tab and page header.
- `owner_aliases` — names that count as "you" for the global Tasks panel.
  Leave empty to show every action item.
- `paths.memory_bank` / `paths.agents` — where the dashboard looks for
  markdown/JSON inputs. The defaults work if you keep the directory layout
  from the template.

## 5. Lay out the data files

The dashboard reads these paths (all under the repo root by default):

```
memory-bank/
├── dashboard.md              # project status table + per-project details
├── dashboard.json            # optional structured twin of dashboard.md (see INTEGRATIONS.md)
├── morning-briefing.md       # daily briefing
├── geekbot-standup.md        # daily standup
├── weekly-report.md          # weekly PM update
├── retrospector-report.md    # latest retrospector report
└── retrospector-report-details.json

agents/
└── <ProjectName>/
    ├── CLAUDE.md             # per-project agent instructions
    ├── logs/                 # Noko JSON time-entry dumps go here
    └── pm/
        └── meetings/
            └── reports/
                └── YYYY-MM-DD_<title>.md
```

The template ships with example seed data so the app boots without anything
extra. Replace those files with your own content as your real data lands.

## 6. Run the server

```bash
cd dashboard
.venv/bin/uvicorn app:app --reload --host 127.0.0.1 --port 8080
```

## 7. Optional — schedule the retrospector

The retrospector analyzes your Claude Code session logs and surfaces repeat
patterns. It needs scripts and a launchd (or cron) job. The template lists
the expected outputs in `dashboard/data.py`'s `get_automations()` — wire
your own scripts to produce the same files and the automations page will
light up.

## Troubleshooting

- **Empty dashboard** — make sure `memory-bank/dashboard.md` exists and has
  the project status table.
- **Missing colors** — every project name in `dashboard.md` must also appear
  in `config/projects.yml` with `status: active`. The dashboard falls back to grey otherwise.
- **Dashboard ignores `dashboard.json`** — the sidecar is skipped when it is invalid JSON, has no named projects, or is more than a minute older than `dashboard.md`. Regenerate both together.
- **No people on /people** — Noko entries live at
  `agents/<Project>/logs/<date>-entries.json`. Without those files, the
  team-activity page is empty by design.
