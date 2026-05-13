# LSM Hivemind Dashboard Template

A starting point for PMs who want a single web dashboard that summarizes status
across multiple client projects. The dashboard reads plain markdown and JSON
files your agents (or you) produce, then renders project status, morning
briefings, team activity, stuck PRs, and a self-improvement retrospector.

This is a **template repo**, not a turnkey product. Fork it, edit
`config/projects.yml`, point your own agents at the file layout, and shape it
to your workflow. Most PMs will not have the same upstream integrations, so
the goal is parity in *structure*, not feature-for-feature parity.

## What you get out of the box

- A Starlette web app at `dashboard/` with pages for projects, briefings,
  team activity, retrospector, and automations.
- A config-driven project list (`config/projects.yml`) — no code edits needed
  to swap in your own projects.
- Example seed data so the dashboard renders something on first boot.
- A retrospector pipeline that learns from your Claude Code session logs.

## What it does **not** ship with

- No real data fetchers. The originals (Noko, GitHub PR staleness, deploy
  schedules, Jira) are removed. You bring your own scripts that drop files in
  the paths the dashboard reads — see `docs/INTEGRATIONS.md`.
- No bespoke client integrations (the original Hivemind shipped a Bravo/Jira
  module — that has been removed).

## Quick start

```bash
git clone <your-fork-url> my-dashboard
cd my-dashboard/dashboard
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --reload --host 127.0.0.1 --port 8080
```

Open <http://127.0.0.1:8080>. You should see the example projects.

Then edit `config/projects.yml` and `config/dashboard.yml` to describe your
own projects.

## Next steps

- `docs/SETUP.md` — full configuration walkthrough.
- `docs/INTEGRATIONS.md` — how to wire up Noko, GitHub, or your own data sources.

## License

MIT. See `LICENSE`.
