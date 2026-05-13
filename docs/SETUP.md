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

Open `config/projects.yml`. Replace the example projects with your own. Each
entry needs at least a `name` and `color`. GitHub repos and agent
directories are optional.

```yaml
projects:
  - name: AcmeCorp
    color: "#6366f1"
    github: acme-org/website
    client: true

  - name: Internal
    color: "#64748b"
    client: false
```

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
  in `config/projects.yml`. The dashboard falls back to grey otherwise.
- **No people on /people** — Noko entries live at
  `agents/<Project>/logs/<date>-entries.json`. Without those files, the
  team-activity page is empty by design.
