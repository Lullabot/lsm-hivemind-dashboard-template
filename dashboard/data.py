"""Dashboard — parse memory-bank markdown files into structured data.

Project-specific lookups (colors, GitHub repos, Noko dir mappings, owner
aliases) come from `config/projects.yml` and `config/dashboard.yml` via the
`config.load()` helper. Edit those files, not this one.
"""

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from config import load as load_config

_CFG = load_config()
ROOT = Path(__file__).resolve().parent.parent
MEMORY_BANK = _CFG["paths"]["memory_bank"]
AGENTS_DIR = _CFG["paths"]["agents"]

PROJECT_COLORS = _CFG["project_colors"]
NOKO_DIR_TO_PROJECT = _CFG["noko_dir_to_project"]
PERSON_COLORS = _CFG["person_colors"] or ["#64748b"]
PROJECT_GITHUB_REPOS = _CFG["project_github"]
CLIENT_PROJECTS = _CFG["client_projects"]
DEFAULT_COLOR = "#64748b"


def md_links_to_html(text):
    """Convert markdown links [text](url) to HTML <a> tags."""
    return re.sub(
        r'\[([^\]]+)\]\((https?://[^)]+)\)',
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        text,
    )


STALENESS_CACHE = Path(__file__).resolve().parent / "data" / "staleness-cache.json"
DEPLOY_SCHEDULE_CACHE = Path(__file__).resolve().parent / "data" / "deployment-schedule.json"

# PR staleness thresholds (in days)
STALE_WARN_DAYS = _CFG["staleness"].get("warn_days", 3)
STALE_CRIT_DAYS = _CFG["staleness"].get("crit_days", 7)

# Status string -> CSS class, driven by config/dashboard.yml.
STATUS_MAP = {k.lower(): v for k, v in _CFG["status_map"].items()}


def parse_dashboard():
    """Parse memory-bank/dashboard.md into structured data."""
    path = MEMORY_BANK / "dashboard.md"
    if not path.exists():
        return {"updated": "Unknown", "projects": [], "themes": [], "priorities": []}

    text = path.read_text()

    # Last updated
    m = re.search(r"Last Updated:\*?\*?\s*(.+)", text)
    updated = m.group(1).strip() if m else "Unknown"

    # Project status table
    projects = []
    table_match = re.search(
        r"\| Project \| Client \| Type \| Status \| Summary \|\n\|[-| ]+\|\n((?:\|.+\|\n?)+)",
        text,
    )
    if table_match:
        for line in table_match.group(1).strip().split("\n"):
            cols = [c.strip() for c in line.strip("|").split("|")]
            if len(cols) >= 5:
                status_raw = cols[3].strip().lower()
                status_class = STATUS_MAP.get(status_raw, "unknown")
                projects.append({
                    "name": cols[0].strip(),
                    "client": cols[1].strip(),
                    "type": cols[2].strip(),
                    "status": cols[3].strip(),
                    "status_class": status_class,
                    "summary": cols[4].strip(),
                    "color": PROJECT_COLORS.get(cols[0].strip(), "#64748b"),
                })

    # Top priorities
    priorities = []
    prio_match = re.search(
        r"## Top Priorities by Project\n\n((?:- .+\n?)+)", text
    )
    if prio_match:
        for line in prio_match.group(1).strip().split("\n"):
            m2 = re.match(r"- \*\*(.+?):\*\*\s*(.+)", line)
            if m2:
                priorities.append({"project": m2.group(1), "text": m2.group(2)})

    # Cross-project themes
    themes = []
    themes_match = re.search(
        r"## Cross-Project Themes\n\n((?:- .+\n?)+)", text
    )
    if themes_match:
        for line in themes_match.group(1).strip().split("\n"):
            m3 = re.match(r"- \*\*(.+?)\*\*\s*[-—]\s*(.+)", line)
            if m3:
                themes.append({"title": m3.group(1), "detail": m3.group(2)})

    # Project details (full sections)
    details = {}
    detail_pattern = re.compile(
        r"### (\w[\w ]*)\n\n(.+?)(?=\n### |\Z)", re.DOTALL
    )
    for dm in detail_pattern.finditer(text):
        name = dm.group(1).strip()
        body = dm.group(2).strip()

        # Extract budget
        budget_match = re.search(r"\*\*Budget:\*\*\s*(.+)", body)
        budget_text = budget_match.group(1).strip() if budget_match else ""

        # Parse budget numbers
        hours_match = re.search(r"([\d,.]+)\s*hours?\s*logged", budget_text)
        total_match = re.search(r"of\s*~?([\d,.]+)\s*(?:total|hrs)", budget_text)
        pct_match = re.search(r"\((\d+)%", budget_text)

        hours_logged = float(hours_match.group(1).replace(",", "")) if hours_match else 0
        hours_total = float(total_match.group(1).replace(",", "")) if total_match else 0
        pct = int(pct_match.group(1)) if pct_match else (
            round(hours_logged / hours_total * 100) if hours_total > 0 else 0
        )

        # Extract active work items
        work_items = []
        work_match = re.search(
            r"\*\*Active Work:\*\*\n\n((?:\d+\..+\n?)+)", body
        )
        if work_match:
            for wline in work_match.group(1).strip().split("\n"):
                wm = re.match(r"\d+\.\s*(.+)", wline)
                if wm:
                    work_items.append(wm.group(1).strip())

        # Extract blockers/risks
        blocker_match = re.search(r"\*\*(?:Blockers?|Risks?):\*\*\s*(.+)", body)
        blockers = blocker_match.group(1).strip() if blocker_match else ""

        # Extract open PRs
        pr_match = re.search(r"\*\*Open PRs:\*\*\s*(.+)", body)
        open_prs_text = pr_match.group(1).strip() if pr_match else ""
        open_prs = re.findall(r"#(\d+)", open_prs_text)

        # Extract status line
        status_match = re.search(r"\*\*Current Status:\s*(.+?)(?:\s*\(.*?\))?\s*\*\*", body)
        current_status = status_match.group(1).strip() if status_match else ""

        details[name] = {
            "current_status": current_status,
            "budget_text": budget_text,
            "hours_logged": hours_logged,
            "hours_total": hours_total,
            "budget_pct": pct,
            "work_items": work_items,
            "blockers": blockers,
            "open_prs": open_prs,
            "color": PROJECT_COLORS.get(name, "#64748b"),
        }

    return {
        "updated": updated,
        "projects": projects,
        "themes": themes,
        "priorities": priorities,
        "details": details,
    }


def parse_briefing():
    """Parse memory-bank/morning-briefing.md into structured data."""
    path = MEMORY_BANK / "morning-briefing.md"
    if not path.exists():
        return {"date": "Unknown", "time_bars": [], "changes": [], "attention": [], "questions": []}

    text = path.read_text()

    # Date from title
    m = re.search(r"# Morning Briefing [-—–]+ (.+)", text)
    date = m.group(1).strip() if m else "Unknown"

    # Time balance bars
    time_bars = []
    bar_match = re.search(r"```text\n(.+?)```", text, re.DOTALL)
    if bar_match:
        for line in bar_match.group(1).strip().split("\n"):
            bm = re.match(r"\s*(\S[\w .]+?)\s{2,}(\S+)\s+([\d.]+)h", line)
            if bm:
                name = bm.group(1).strip()
                hours = float(bm.group(3))
                time_bars.append({
                    "name": name,
                    "hours": hours,
                    "color": PROJECT_COLORS.get(name, "#64748b"),
                })

    # Normalize bars to percentages
    max_hours = max((b["hours"] for b in time_bars), default=1)
    for bar in time_bars:
        bar["pct"] = round(bar["hours"] / max_hours * 100)

    # What changed overnight
    changes = []
    changes_match = re.search(
        r"## What Changed Overnight\n\n((?:- .+\n?)+)", text
    )
    if changes_match:
        for line in changes_match.group(1).strip().split("\n"):
            cm = re.match(r"- \*\*(.+?)(?:\*\*)?:\*?\*?\s*(.+)", line)
            if cm:
                changes.append({"project": cm.group(1), "text": md_links_to_html(cm.group(2))})

    # Needs attention
    attention = []
    att_match = re.search(
        r"## Needs Attention Today\n\n((?:- .+\n?)+)", text
    )
    if att_match:
        for line in att_match.group(1).strip().split("\n"):
            # Format: - **ProjectName: bold summary text.** rest of text
            am = re.match(r"- \*\*(\w[\w ]*?):\s*(.+)", line)
            if am:
                project = am.group(1)
                rest = am.group(2).replace("**", "").strip()
                attention.append({"project": project, "text": md_links_to_html(rest)})

    # Open questions
    questions = []
    q_match = re.search(
        r"## Open Questions Needing Response\n\n((?:- .+\n?)+)", text
    )
    if q_match:
        for line in q_match.group(1).strip().split("\n"):
            qm = re.match(r"- \*\*(.+?)(?:\*\*)?(?:\s*[-—]\s*)(.+)", line)
            if qm:
                questions.append({"label": qm.group(1), "text": qm.group(2)})

    # Self-improvement summary
    self_improvement = ""
    si_match = re.search(
        r"## Self-Improvement\n\n((?:.+\n?)+)", text
    )
    if si_match:
        self_improvement = si_match.group(1).strip()

    return {
        "date": date,
        "time_bars": time_bars,
        "changes": changes,
        "attention": attention,
        "questions": questions,
        "self_improvement": self_improvement,
    }


def parse_geekbot():
    """Parse memory-bank/geekbot-standup.md into structured data."""
    path = MEMORY_BANK / "geekbot-standup.md"
    if not path.exists():
        return {"date": "", "raw": "", "sections": []}

    text = path.read_text()

    # Date from title
    m = re.search(r"# Geekbot Standup [-—–]+ (.+)", text)
    date = m.group(1).strip() if m else ""

    # Extract the raw content (everything after the title line)
    raw = re.sub(r"^# Geekbot Standup [-—–]+.+\n+", "", text).strip()

    # Parse sections (Section 1, Section 2, Section 3)
    sections = []
    section_pattern = re.compile(
        r"\*Section \d+ \((.+?)\):\*\n(.*?)(?=\*Section \d+|\Z)", re.DOTALL
    )
    for sm in section_pattern.finditer(raw):
        sections.append({
            "title": sm.group(1).strip(),
            "content": sm.group(2).strip(),
        })

    return {"date": date, "raw": raw, "sections": sections}


def parse_weekly():
    """Parse memory-bank/weekly-report.md into structured data."""
    path = MEMORY_BANK / "weekly-report.md"
    if not path.exists():
        return {"date": "", "raw": "", "projects": []}

    text = path.read_text()

    # Date from title
    m = re.search(r"# Weekly PM Update [-—–]+ (.+)", text)
    date = m.group(1).strip() if m else ""

    # Extract the raw content (everything after the title line)
    raw = re.sub(r"^# Weekly PM Update [-—–]+.+\n+", "", text).strip()

    # Parse per-project blocks
    projects = []
    # Split on bold project headers (*PROJECT_NAME*)
    project_pattern = re.compile(
        r"\*(\w[\w ]*)\*\n(.*?)(?=\n\*\w[\w ]*\*\n|\Z)", re.DOTALL
    )
    for pm in project_pattern.finditer(raw):
        name = pm.group(1).strip()
        body = pm.group(2).strip()

        concerns = ""
        plan = ""
        concerns_match = re.search(
            r":warning:\s*\*CONCERNS\*\n(.*?)(?=:dart:|\Z)", body, re.DOTALL
        )
        if concerns_match:
            concerns = concerns_match.group(1).strip()
        plan_match = re.search(
            r":dart:\s*\*PLAN FOR NEXT WEEK\*\n(.*)", body, re.DOTALL
        )
        if plan_match:
            plan = plan_match.group(1).strip()

        projects.append({"name": name, "concerns": concerns, "plan": plan})

    return {"date": date, "raw": raw, "projects": projects}


def parse_noko_entries():
    """Load all Noko JSON files from agents/*/logs/ and aggregate by person."""
    all_entries = []

    for agent_dir in AGENTS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        logs_dir = agent_dir / "logs"
        if not logs_dir.exists():
            continue
        project_name = NOKO_DIR_TO_PROJECT.get(agent_dir.name, agent_dir.name)

        # Find the most recent noko JSON file
        noko_files = sorted(logs_dir.glob("noko-*.json"), reverse=True)
        if not noko_files:
            continue

        latest = noko_files[0]
        try:
            entries = json.loads(latest.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        for entry in entries:
            user = entry.get("user", {})
            name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
            if not name:
                continue
            all_entries.append({
                "person": name,
                "person_id": user.get("id"),
                "avatar": user.get("profile_image_url", ""),
                "project": project_name,
                "date": entry.get("date", ""),
                "minutes": entry.get("minutes", 0),
                "description": entry.get("description", ""),
                "tags": [t.get("formatted_name", "") for t in entry.get("tags", [])],
                "billable": entry.get("billable", False),
            })

    return all_entries


def aggregate_people(entries):
    """Aggregate Noko entries into per-person summaries."""
    people = defaultdict(lambda: {
        "name": "",
        "avatar": "",
        "total_minutes": 0,
        "billable_minutes": 0,
        "projects": defaultdict(lambda: {"minutes": 0, "entries": 0, "maintenance_minutes": 0, "professional_minutes": 0}),
        "daily": defaultdict(int),
        "tags": defaultdict(int),
        "entry_count": 0,
    })

    for e in entries:
        p = people[e["person"]]
        p["name"] = e["person"]
        p["avatar"] = e["avatar"]
        p["total_minutes"] += e["minutes"]
        if e["billable"]:
            p["billable_minutes"] += e["minutes"]
        p["projects"][e["project"]]["minutes"] += e["minutes"]
        p["projects"][e["project"]]["entries"] += 1
        if "#professional" in e["tags"]:
            p["projects"][e["project"]]["professional_minutes"] += e["minutes"]
        elif "#maintenance" in e["tags"]:
            p["projects"][e["project"]]["maintenance_minutes"] += e["minutes"]
        p["daily"][e["date"]] += e["minutes"]
        for tag in e["tags"]:
            p["tags"][tag] += 1
        p["entry_count"] += 1

    # Only include people with client project activity (configured in projects.yml).
    result = []
    color_idx = 0
    for person_name in sorted(people, key=lambda k: people[k]["total_minutes"], reverse=True):
        p = people[person_name]

        # Skip people with no client project hours
        has_client_time = any(
            proj in CLIENT_PROJECTS for proj in p["projects"]
        )
        if not has_client_time:
            continue

        total_hours = round(p["total_minutes"] / 60, 1)
        billable_hours = round(p["billable_minutes"] / 60, 1)
        billable_pct = round(p["billable_minutes"] / p["total_minutes"] * 100) if p["total_minutes"] > 0 else 0

        # Build project breakdown sorted by hours
        proj_list = []
        for proj_name in sorted(p["projects"], key=lambda k: p["projects"][k]["minutes"], reverse=True):
            pd = p["projects"][proj_name]
            proj_hours = round(pd["minutes"] / 60, 1)
            maint_pct = round(pd["maintenance_minutes"] / pd["minutes"] * 100) if pd["minutes"] > 0 else 0
            prof_pct = round(pd["professional_minutes"] / pd["minutes"] * 100) if pd["minutes"] > 0 else 0
            proj_list.append({
                "name": proj_name,
                "hours": proj_hours,
                "entries": pd["entries"],
                "color": PROJECT_COLORS.get(proj_name, "#64748b"),
                "pct": round(pd["minutes"] / p["total_minutes"] * 100) if p["total_minutes"] > 0 else 0,
                "maintenance_pct": maint_pct,
                "professional_pct": prof_pct,
            })

        # Daily activity for sparkline (last 14 days)
        daily_sorted = sorted(p["daily"].items())
        daily_hours = [{"date": d, "hours": round(m / 60, 1)} for d, m in daily_sorted]

        # Top tags
        top_tags = sorted(p["tags"].items(), key=lambda x: x[1], reverse=True)[:5]

        result.append({
            "name": person_name,
            "avatar": p["avatar"],
            "total_hours": total_hours,
            "billable_hours": billable_hours,
            "billable_pct": billable_pct,
            "projects": proj_list,
            "daily": daily_hours,
            "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
            "entry_count": p["entry_count"],
            "color": PERSON_COLORS[color_idx % len(PERSON_COLORS)],
        })
        color_idx += 1

    return result


# Team members shown in the briefing yesterday-time section. Maps display
# name -> short label. Pulled from config/dashboard.yml (person_aliases). Empty
# dict disables the yesterday-time panel.
TEAM_MEMBERS = dict(_CFG["person_aliases"])


def aggregate_yesterday_time(entries):
    """Aggregate Noko entries for the previous working day, grouped by project then person.

    Only includes client projects and configured team members.
    """
    from datetime import date, timedelta

    today = date.today()
    # Walk back to find the previous working day (skip weekends)
    yesterday = today - timedelta(days=1)
    while yesterday.weekday() >= 5:  # 5=Sat, 6=Sun
        yesterday -= timedelta(days=1)
    target_date = yesterday.isoformat()

    # Group: project -> person -> minutes (client projects + team only)
    by_project = defaultdict(lambda: defaultdict(int))
    for e in entries:
        if e["date"] == target_date and e["project"] in CLIENT_PROJECTS and e["person"] in TEAM_MEMBERS:
            by_project[e["project"]][e["person"]] += e["minutes"]

    # Find max project hours for bar scaling
    max_mins = max(
        (sum(people.values()) for people in by_project.values()),
        default=1,
    )

    # Assign stable colors to team members
    team_names = sorted(TEAM_MEMBERS.keys())
    person_color = {
        name: PERSON_COLORS[i % len(PERSON_COLORS)]
        for i, name in enumerate(team_names)
    }

    # Build structured result sorted by project hours descending
    result = []
    for project in sorted(by_project, key=lambda p: sum(by_project[p].values()), reverse=True):
        people = by_project[project]
        total_mins = sum(people.values())
        person_list = [
            {
                "name": TEAM_MEMBERS[name],
                "full_name": name,
                "hours": round(mins / 60, 1),
                "pct": round(mins / total_mins * 100) if total_mins else 0,
                "color": person_color.get(name, "#64748b"),
            }
            for name, mins in sorted(people.items(), key=lambda x: x[1], reverse=True)
        ]
        result.append({
            "project": project,
            "color": PROJECT_COLORS.get(project, "#64748b"),
            "total_hours": round(total_mins / 60, 1),
            "bar_pct": round(total_mins / max_mins * 100),
            "people": person_list,
        })

    return {"date": target_date, "projects": result}


def aggregate_project_hours(entries):
    """Aggregate Noko entries into per-project maintenance/professional splits."""
    projects = defaultdict(lambda: {
        "total_minutes": 0,
        "maintenance_minutes": 0,
        "professional_minutes": 0,
        "untagged_minutes": 0,
    })

    for e in entries:
        p = projects[e["project"]]
        minutes = e["minutes"]
        tags = e["tags"]
        p["total_minutes"] += minutes

        has_professional = "#professional" in tags
        has_maintenance = "#maintenance" in tags

        if has_professional:
            p["professional_minutes"] += minutes
        elif has_maintenance:
            p["maintenance_minutes"] += minutes
        else:
            p["untagged_minutes"] += minutes

    result = {}
    for proj_name, p in projects.items():
        total = p["total_minutes"]
        result[proj_name] = {
            "total_hours": round(total / 60, 1),
            "maintenance_hours": round(p["maintenance_minutes"] / 60, 1),
            "professional_hours": round(p["professional_minutes"] / 60, 1),
            "untagged_hours": round(p["untagged_minutes"] / 60, 1),
            "maintenance_pct": round(p["maintenance_minutes"] / total * 100) if total > 0 else 0,
            "professional_pct": round(p["professional_minutes"] / total * 100) if total > 0 else 0,
            "untagged_pct": round(p["untagged_minutes"] / total * 100) if total > 0 else 0,
        }

    return result


def _gh_fetch_prs(repo):
    """Fetch open PRs from a GitHub repo via gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--repo", repo, "--state", "open",
             "--json", "number,createdAt,updatedAt,reviewDecision,title,author,isDraft",
             "--limit", "50"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return []


def load_staleness():
    """Read staleness data from cache file. Never fetches from GitHub.

    The cache is populated by:
    - Morning briefing (daily at 7:03 AM via launchd)
    - Manual: cd dashboard && .venv/bin/python3 -c "from data import refresh_staleness; refresh_staleness()"
    """
    if STALENESS_CACHE.exists():
        try:
            cache = json.loads(STALENESS_CACHE.read_text())
            return cache["data"]
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    return {"prs": {}, "stale_items": []}


def load_deploy_schedule():
    """Read deployment schedule from cache file.

    The cache is populated by:
    - Morning briefing (daily via launchd, calls fetch-deploy-schedule.sh)
    - Manual: cd automation/scripts && ./fetch-deploy-schedule.sh
    """
    if DEPLOY_SCHEDULE_CACHE.exists():
        try:
            cache = json.loads(DEPLOY_SCHEDULE_CACHE.read_text())
            # Recompute days_until from current date (cache may be stale).
            # Compare calendar dates in the deployment's local timezone so a
            # release scheduled for tomorrow morning isn't truncated to "0 days"
            # when the timedelta is < 24h.
            projects = cache.get("projects", {})
            for project_data in projects.values():
                for env_type in ("staging", "production"):
                    deploy = project_data.get(env_type)
                    if deploy and deploy.get("start"):
                        try:
                            start_str = deploy["start"]
                            start_dt = datetime.fromisoformat(start_str)
                            if start_dt.tzinfo is None:
                                start_dt = start_dt.replace(tzinfo=timezone.utc)
                            today = datetime.now(start_dt.tzinfo).date()
                            deploy["days_until"] = (start_dt.date() - today).days
                        except (ValueError, TypeError):
                            pass
            return {
                "fetched_at": cache.get("fetched_at", ""),
                "projects": projects,
            }
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    return {"fetched_at": "", "projects": {}}




def refresh_staleness():
    """Fetch fresh PR staleness data from GitHub and write cache.

    Called by morning-briefing.sh, not by the dashboard server.
    """
    now = datetime.now(timezone.utc)
    data = {"prs": {}, "stale_items": []}

    for project, repo in PROJECT_GITHUB_REPOS.items():
        prs = _gh_fetch_prs(repo)
        project_prs = []

        for pr in prs:
            created = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
            updated = datetime.fromisoformat(pr["updatedAt"].replace("Z", "+00:00"))
            age_days = (now - created).days
            idle_days = (now - updated).days
            is_bot = pr.get("author", {}).get("is_bot", False)
            is_draft = pr.get("isDraft", False)
            review = pr.get("reviewDecision", "")

            # Determine staleness level
            if idle_days >= STALE_CRIT_DAYS:
                staleness = "critical"
            elif idle_days >= STALE_WARN_DAYS:
                staleness = "warning"
            else:
                staleness = "fresh"

            # Determine reason
            if review == "CHANGES_REQUESTED":
                reason = "Changes requested"
            elif review == "" and age_days >= STALE_WARN_DAYS and not is_bot:
                reason = "No review"
            elif idle_days >= STALE_CRIT_DAYS:
                reason = "No activity"
            else:
                reason = ""

            pr_data = {
                "number": pr["number"],
                "title": pr["title"],
                "author": pr.get("author", {}).get("login", "unknown"),
                "is_bot": is_bot,
                "is_draft": is_draft,
                "age_days": age_days,
                "idle_days": idle_days,
                "review_decision": review,
                "staleness": staleness,
                "reason": reason,
                "project": project,
                "repo": repo,
            }
            project_prs.append(pr_data)

            if staleness != "fresh" and not is_bot:
                data["stale_items"].append(pr_data)

        data["prs"][project] = project_prs

    data["stale_items"].sort(key=lambda x: x["idle_days"], reverse=True)

    STALENESS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    STALENESS_CACHE.write_text(json.dumps({
        "fetched_at": now.isoformat(),
        "data": data,
    }, indent=2))

    return data


def retrospector_trend(limit=14):
    """Return failure counts from recent archived retrospector reports.

    Returns a list of {date, failures} dicts, oldest first, up to *limit* days.
    """
    reports_dir = MEMORY_BANK / "retrospector-reports"
    if not reports_dir.is_dir():
        return []

    points = []
    for f in sorted(reports_dir.glob("*.json"), reverse=True)[:limit]:
        m = re.match(r"(\d{4}-\d{2}-\d{2})\.json$", f.name)
        if not m:
            continue
        try:
            data = json.loads(f.read_text())
            failures = len(data.get("improvements", []))
            # Try to get actual failure count from companion .md
            md_path = f.with_suffix(".md")
            if md_path.exists():
                md_text = md_path.read_text()
                fm = re.search(r"Failures detected:\s*(\d+)", md_text)
                if fm:
                    failures = int(fm.group(1))
            points.append({"date": m.group(1), "failures": failures})
        except (json.JSONDecodeError, OSError):
            continue

    points.reverse()  # oldest first
    return points


def list_retrospector_dates():
    """Scan memory-bank/retrospector-reports/ for archived reports.

    Returns a sorted list of date strings (YYYY-MM-DD), most recent first.
    """
    reports_dir = MEMORY_BANK / "retrospector-reports"
    if not reports_dir.is_dir():
        return []
    dates = []
    for f in reports_dir.glob("*.md"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})\.md$", f.name)
        if m:
            dates.append(m.group(1))
    dates.sort(reverse=True)
    return dates


MEMORY_DIR = ROOT / ".claude" / "memory"


def _resolve_retro_target(target):
    """Resolve a retrospector target_file to its full filesystem path."""
    if target.startswith("memory/"):
        return str(MEMORY_DIR / target.removeprefix("memory/"))
    if target.startswith("~/"):
        return str(Path.home() / target[2:])
    return str(ROOT / target)


HISTORY_JSONL = ROOT / "automation" / "scripts" / "retrospector-history.jsonl"


def _history_target_counts():
    """Count how many times each target_file appears across the full JSONL history."""
    counts = defaultdict(int)
    if not HISTORY_JSONL.exists():
        return counts
    for line in HISTORY_JSONL.read_text().splitlines():
        try:
            entry = json.loads(line)
            target = entry.get("target_file", "")
            if target:
                counts[target] += 1
        except (json.JSONDecodeError, KeyError):
            continue
    return counts


def _escalation_recommendation(target, count):
    """Return an actionable recommendation based on proposal count and target type."""
    basename = target.rsplit("/", 1)[-1] if "/" in target else target
    if count >= 8:
        return (
            f"Proposed {count} times with no effect. "
            "Memory-based fixes are not working for this pattern. "
            "Promote the rule to CLAUDE.md (always loaded) or add a "
            "pre-commit hook to enforce it mechanically."
        )
    # 5-7 proposals
    if "claude_tool_discipline" in basename:
        return (
            f"Proposed {count} times. Tool discipline rules are reflexive "
            "habits that memory can't override. Move the top rules into "
            "CLAUDE.md under a '## Tool Discipline' section."
        )
    if "shell_cli" in basename or "git_workflow" in basename:
        return (
            f"Proposed {count} times. Consider adding a shell alias or "
            "wrapper script that enforces the correct behavior, rather "
            "than relying on memory."
        )
    return (
        f"Proposed {count} times. The memory-only approach isn't sticking. "
        "Consider promoting to CLAUDE.md or adding automated enforcement."
    )


def parse_retrospector(date=None):
    """Parse a retrospector report into structured data.

    If *date* is None, read from the current (latest) report files:
        memory-bank/retrospector-report.md
        memory-bank/retrospector-report-details.json

    If *date* is a YYYY-MM-DD string, read from the archive:
        memory-bank/retrospector-reports/{date}.md
        memory-bank/retrospector-reports/{date}.json
    """
    if date:
        path = MEMORY_BANK / "retrospector-reports" / f"{date}.md"
        details_path = MEMORY_BANK / "retrospector-reports" / f"{date}.json"
    else:
        path = MEMORY_BANK / "retrospector-report.md"
        details_path = MEMORY_BANK / "retrospector-report-details.json"

    if not path.exists():
        return {"date": "Unknown", "sessions": "", "failures": 0,
                "improvements": [], "branch": "", "effectiveness": [],
                "meta": "", "report_path": ""}

    text = path.read_text()

    # Date from title
    m = re.search(r"# Retrospector Report -- (.+)", text)
    date_label = m.group(1).strip() if m else "Unknown"

    # Sessions summary
    sessions_match = re.search(r"Total:\s*(.+)", text)
    sessions = sessions_match.group(1).strip() if sessions_match else ""

    failures_match = re.search(r"Failures detected:\s*(\d+)", text)
    failures = int(failures_match.group(1)) if failures_match else 0

    # Load full details from companion JSON (written by retrospector.sh)
    details = {}
    if details_path.exists():
        try:
            details = json.loads(details_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    details_by_index = {}
    for i, imp in enumerate(details.get("improvements", [])):
        details_by_index[i] = imp

    # Improvements table
    improvements = []
    # Support both old format (5 cols) and new format with Agent column (6 cols)
    table_match = re.search(
        r"(\| # \| Category \| (?:Agent \| )?Target \| Confidence \| Description \|)\n\|[-| ]+\|\n((?:\|.+\|\n?)+)",
        text,
    )
    if table_match:
        has_agent_col = "Agent" in table_match.group(1)
        for idx, line in enumerate(table_match.group(2).strip().split("\n")):
            cols = [c.strip() for c in line.strip("|").split("|")]
            detail = details_by_index.get(idx, {})
            if has_agent_col and len(cols) >= 6:
                target = cols[3].strip()
                change_made = detail.get("change_made")
                if change_made and change_made.get("file"):
                    target_path = _resolve_retro_target(
                        "memory/" + change_made["file"])
                else:
                    target_path = _resolve_retro_target(target)
                improvements.append({
                    "number": cols[0].strip(),
                    "category": cols[1].strip(),
                    "source_agent": cols[2].strip(),
                    "target": target,
                    "target_path": target_path,
                    "confidence": cols[4].strip(),
                    "description": detail.get("description", cols[5].strip()),
                    "proposed_change": detail.get("proposed_change", ""),
                    "reasoning": detail.get("reasoning", ""),
                    "change_made": change_made,
                })
            elif len(cols) >= 5:
                target = cols[2].strip()
                change_made = detail.get("change_made")
                if change_made and change_made.get("file"):
                    target_path = _resolve_retro_target(
                        "memory/" + change_made["file"])
                else:
                    target_path = _resolve_retro_target(target)
                improvements.append({
                    "number": cols[0].strip(),
                    "category": cols[1].strip(),
                    "source_agent": detail.get("source_agent", "root"),
                    "target": target,
                    "target_path": target_path,
                    "confidence": cols[3].strip(),
                    "description": detail.get("description", cols[4].strip()),
                    "proposed_change": detail.get("proposed_change", ""),
                    "reasoning": detail.get("reasoning", ""),
                    "change_made": change_made,
                })

    # Branch
    branch_match = re.search(r"`(self-improvement/[\w-]+)`", text)
    branch = branch_match.group(1) if branch_match else ""

    # Effectiveness tracking
    effectiveness = []
    # Support both old format (5 cols) and new format with Agent column (6 cols)
    eff_match = re.search(
        r"(\| Past Improvement \| (?:Agent \| )?Date \| Status \| Recurrences \| Verdict \|)\n\|[-| ]+\|\n((?:\|.+\|\n?)+)",
        text,
    )
    if eff_match:
        eff_has_agent = "Agent" in eff_match.group(1)
        for line in eff_match.group(2).strip().split("\n"):
            cols = [c.strip() for c in line.strip("|").split("|")]
            if "No historical data" in cols[0]:
                continue
            if eff_has_agent and len(cols) >= 6:
                imp_name = cols[0].strip()
                effectiveness.append({
                    "improvement": imp_name,
                    "improvement_path": _resolve_retro_target(imp_name),
                    "source_agent": cols[1].strip(),
                    "date": cols[2].strip(),
                    "status": cols[3].strip(),
                    "recurrences": cols[4].strip(),
                    "verdict": cols[5].strip(),
                })
            elif len(cols) >= 5:
                imp_name = cols[0].strip()
                effectiveness.append({
                    "improvement": imp_name,
                    "improvement_path": _resolve_retro_target(imp_name),
                    "source_agent": "root",
                    "date": cols[1].strip(),
                    "status": cols[2].strip(),
                    "recurrences": cols[3].strip(),
                    "verdict": cols[4].strip(),
                })

    # Count proposals from full history (JSONL), not just this report
    history_counts = _history_target_counts()
    # Fall back to in-report counting if history file is missing
    from collections import Counter
    report_counts = Counter(e["improvement"] for e in effectiveness)
    for eff in effectiveness:
        target = eff["improvement"]
        eff["times_proposed"] = history_counts.get(target, report_counts[target])

    # Identify repeat offenders that need escalation (5+ proposals),
    # but exclude targets that have already been escalated
    ESCALATION_THRESHOLD = 5
    already_escalated = {
        e["target"] for e in parse_escalation_log()
    }
    escalations = []
    seen_targets = set()
    for eff in effectiveness:
        target = eff["improvement"]
        if target in seen_targets or target in already_escalated:
            continue
        count = eff["times_proposed"]
        if count >= ESCALATION_THRESHOLD:
            seen_targets.add(target)
            escalations.append({
                "target": target,
                "times_proposed": count,
                "recommendation": _escalation_recommendation(target, count),
            })
    escalations.sort(key=lambda e: e["times_proposed"], reverse=True)

    # Meta-improvement (everything after ## Meta-Improvement heading)
    meta_match = re.search(r"## Meta-Improvement\n\n(.+)", text, re.DOTALL)
    meta = meta_match.group(1).strip() if meta_match else ""

    return {
        "date": date_label,
        "sessions": sessions,
        "failures": failures,
        "improvements": improvements,
        "branch": branch,
        "effectiveness": effectiveness,
        "escalations": escalations,
        "meta": meta,
        "report_path": str(path),
    }


_ESCALATION_SECTION_TO_RULE_FILE = {
    "Claude Tool Discipline": "tool-discipline.md",
    "Shell Cli Tools": "shell-cli.md",
    "Gws Cli": "gws-cli.md",
    "Gh Cli": "gh-cli.md",
    "Git Workflow": "git-workflow.md",
    "Project Facts": "ddev-drupal.md",
}


def parse_claude_md_escalations():
    """Return a dict mapping escalation section name to its rule-file content.

    Escalation log entries reference section names like "Claude Tool Discipline"
    (originally headers under the ## Retrospector Escalations section in
    CLAUDE.md). After consolidation, those sections moved to
    memory-bank/rules/<file>.md as topical files imported via @-include.
    This function reads the corresponding rule file for each known section.
    """
    rules_dir = ROOT / "memory-bank" / "rules"
    sections = {}
    for section_name, filename in _ESCALATION_SECTION_TO_RULE_FILE.items():
        path = rules_dir / filename
        if path.exists():
            sections[section_name] = path.read_text().strip()
    return sections


def parse_consolidation_log():
    """Parse the consolidation history log."""
    path = MEMORY_BANK / "retrospector-consolidation-log.json"
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text())
        return entries if isinstance(entries, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def parse_escalation_log():
    """Parse the escalation history log."""
    path = MEMORY_BANK / "retrospector-escalation-log.json"
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text())
        return entries if isinstance(entries, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def parse_hook_enforcements():
    """Parse the log of hook-based enforcements installed in response to retrospector meta-improvements."""
    path = MEMORY_BANK / "retrospector-hook-enforcements.json"
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text())
        return entries if isinstance(entries, list) else []
    except (json.JSONDecodeError, OSError):
        return []


_APP_START_TIME = datetime.now(timezone.utc)

# Freshness thresholds (seconds)
FRESH_THRESHOLD = 4 * 3600      # < 4 hours = green
STALE_THRESHOLD = 24 * 3600     # < 24 hours = yellow, >= 24 hours = red


def _file_age_seconds(path):
    """Return seconds since file was last modified, or None if missing."""
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds()


def _json_fetched_age(path):
    """Return seconds since the fetched_at timestamp in a JSON cache file."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        fetched_at = data.get("fetched_at", "")
        if not fetched_at:
            return _file_age_seconds(path)
        dt = datetime.fromisoformat(fetched_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except (json.JSONDecodeError, ValueError, OSError):
        return _file_age_seconds(path)


def _freshness_status(age_seconds):
    """Return 'ok', 'warning', or 'error' based on age."""
    if age_seconds is None:
        return "error"
    if age_seconds < FRESH_THRESHOLD:
        return "ok"
    if age_seconds < STALE_THRESHOLD:
        return "warning"
    return "error"


def _format_age(age_seconds):
    """Format age as human-readable string like '2h ago' or '3d ago'."""
    if age_seconds is None:
        return "missing"
    age = int(age_seconds)
    if age < 60:
        return f"{age}s ago"
    if age < 3600:
        return f"{age // 60}m ago"
    if age < 86400:
        return f"{age // 3600}h ago"
    return f"{age // 86400}d ago"


def get_health():
    """Return system health data for /health endpoint and freshness indicators."""
    now = datetime.now(timezone.utc)
    uptime = (now - _APP_START_TIME).total_seconds()

    sources = {}
    source_defs = [
        ("morning_briefing", MEMORY_BANK / "morning-briefing.md", "file"),
        ("dashboard_md", MEMORY_BANK / "dashboard.md", "file"),
        ("staleness_cache", STALENESS_CACHE, "json"),
        ("deploy_schedule", DEPLOY_SCHEDULE_CACHE, "json"),
        ("retrospector", MEMORY_BANK / "retrospector-report.md", "file"),
    ]

    overall = "ok"
    for name, path, kind in source_defs:
        if kind == "json":
            age = _json_fetched_age(path)
        else:
            age = _file_age_seconds(path)
        status = _freshness_status(age)
        sources[name] = {
            "age_seconds": round(age) if age is not None else None,
            "age_human": _format_age(age),
            "status": status,
            "path_exists": path.exists(),
        }
        if status == "error":
            overall = "error"
        elif status == "warning" and overall != "error":
            overall = "degraded"

    # Auto memory index health — 200 lines or 25KB, whichever comes first
    memory_index = MEMORY_DIR / "MEMORY.md"
    if memory_index.exists():
        content = memory_index.read_text()
        line_count = len(content.splitlines())
        size_kb = len(content.encode("utf-8")) / 1024
        line_limit = 200
        size_limit_kb = 25
        line_pct = line_count / line_limit
        size_pct = size_kb / size_limit_kb
        pct = max(line_pct, size_pct)
        # Determine which constraint is tighter
        if size_pct > line_pct:
            age_human = f"{size_kb:.1f}/{size_limit_kb}KB"
        else:
            age_human = f"{line_count}/{line_limit} lines"
        if pct >= 0.95:
            mem_status = "error"
        elif pct >= 0.80:
            mem_status = "warning"
        else:
            mem_status = "ok"
        sources["memory_index"] = {
            "age_seconds": None,
            "age_human": age_human,
            "compact_age": f"{round(pct * 100)}%",
            "status": mem_status,
            "path_exists": True,
            "path": str(memory_index),
            "line_count": line_count,
            "line_limit": line_limit,
            "size_kb": round(size_kb, 1),
            "size_limit_kb": size_limit_kb,
        }
        if mem_status == "error":
            overall = "error"
        elif mem_status == "warning" and overall != "error":
            overall = "degraded"

    # Retrospector target health — detect regression to legacy memory/feedback_principle_*
    # paths after the 2026-05-05 migration. Counts entries from the last 7 days
    # whose target_file is in the deprecated location AND lacks migration_note
    # (i.e., a fresh write, not a migrated row).
    if HISTORY_JSONL.exists():
        cutoff = (now - timedelta(days=7)).date().isoformat()
        legacy_recent = 0
        total_recent = 0
        try:
            for line in HISTORY_JSONL.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("date", "") < cutoff:
                    continue
                total_recent += 1
                tf = rec.get("target_file", "")
                if tf.startswith("memory/feedback_principle_") and "migration_note" not in rec:
                    legacy_recent += 1
        except (json.JSONDecodeError, OSError):
            legacy_recent = -1  # parse failure
        if legacy_recent < 0:
            rt_status = "warning"
            rt_human = "parse error"
        elif legacy_recent == 0:
            rt_status = "ok"
            rt_human = f"0 legacy / {total_recent} (7d)"
        else:
            rt_status = "warning"
            rt_human = f"{legacy_recent} legacy / {total_recent} (7d)"
        sources["retrospector_targets"] = {
            "age_seconds": None,
            "age_human": rt_human,
            "compact_age": str(legacy_recent) if legacy_recent >= 0 else "?",
            "status": rt_status,
            "path_exists": True,
            "path": str(HISTORY_JSONL),
            "legacy_recent": legacy_recent,
            "total_recent": total_recent,
        }
        if rt_status == "warning" and overall != "error":
            overall = "degraded"

    return {
        "version": "1.0.0",
        "status": overall,
        "uptime_seconds": round(uptime),
        "sources": sources,
    }


# Map dashboard project slugs to agent directory names (from config/projects.yml).
PROJECT_SLUG_TO_DIR = _CFG["slug_to_agent_dir"]


def parse_meeting_notes(slug, max_meetings=3):
    """Parse recent meeting reports for a project.

    Scans agents/{dir}/pm/meetings/reports/ for date-prefixed .md files,
    extracts Action Items and Decisions sections from the most recent ones.

    Returns a dict with:
      meetings: list of {date, title, filename, action_items, decisions}
      all_action_items: flattened list across meetings (most recent first)
    """
    agent_dir_name = PROJECT_SLUG_TO_DIR.get(slug)
    if not agent_dir_name:
        return {"meetings": [], "all_action_items": []}

    reports_dir = AGENTS_DIR / agent_dir_name / "pm" / "meetings" / "reports"
    if not reports_dir.is_dir():
        return {"meetings": [], "all_action_items": []}

    # Find all date-prefixed .md files (recursively, in case meetings are organized into year/ subdirs)
    report_files = []
    for md_file in reports_dir.rglob("*.md"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)\.md$", md_file.name)
        if m:
            report_files.append((m.group(1), m.group(2), md_file))

    # Sort by date descending, take most recent
    report_files.sort(key=lambda x: x[0], reverse=True)
    report_files = report_files[:max_meetings]

    meetings = []
    all_action_items = []

    for date_str, name_slug, filepath in report_files:
        text = filepath.read_text()

        # Extract title from first heading
        title_match = re.match(r"#\s+(.+)", text)
        title = title_match.group(1).strip() if title_match else name_slug.replace("-", " ").title()

        # Parse Action Items section (handles multi-line items with continuation)
        action_items = []
        ai_match = re.search(
            r"## Action Items\n\n?((?:(?:- .+|  .+)\n?)+)", text
        )
        if ai_match:
            # Join continuation lines (indented) with preceding bullet
            raw_items = []
            for line in ai_match.group(1).strip().split("\n"):
                if line.startswith("- "):
                    raw_items.append(line[2:].strip())
                elif line.startswith("  ") and raw_items:
                    raw_items[-1] += " " + line.strip()

            for raw in raw_items:
                # Extract owner: "— Name", "- Name" at end, or "Name:" at start,
                # or "[Name] description" (bracket style)
                owner = ""
                desc = raw
                bracket_match = re.match(r"\[([^\]]+)\]\s+(.+)", raw)
                if bracket_match:
                    owner = bracket_match.group(1).strip()
                    desc = bracket_match.group(2).strip()
                else:
                    owner_match = re.search(r"\s+[—–-]+\s+(\w[\w ]*?)(?:\s*\(.*?\))?\s*$", raw)
                    if owner_match:
                        owner = owner_match.group(1).strip()
                        desc = raw[:owner_match.start()].strip()
                    else:
                        # "Name: description" prefix format
                        prefix_match = re.match(r"(\w[\w ]+?):\s+(.+)", raw)
                        if prefix_match:
                            owner = prefix_match.group(1).strip()
                            desc = prefix_match.group(2).strip()

                # Extract issue references
                issues = re.findall(r"#(\d+)", desc)

                # Only surface items without a GitHub issue
                if issues:
                    continue

                # Stable key for dismiss tracking
                key = hashlib.md5(
                    f"{date_str}:{desc}".encode()
                ).hexdigest()[:12]

                action_items.append({
                    "key": key,
                    "description": desc,
                    "owner": owner,
                    "date": date_str,
                    "meeting": title,
                })

        # Parse Decisions section
        decisions = []
        dec_match = re.search(
            r"## Decisions\n\n?((?:- .+\n?)+)", text
        )
        if dec_match:
            for line in dec_match.group(1).strip().split("\n"):
                dec = re.match(r"- (.+)", line)
                if dec:
                    decisions.append(dec.group(1).strip())

        meetings.append({
            "date": date_str,
            "title": title,
            "filename": filepath.name,
            "action_items": action_items,
            "decisions": decisions,
        })

        all_action_items.extend(action_items)

    return {
        "meetings": meetings,
        "all_action_items": all_action_items,
    }


def parse_checklists(slug):
    """Parse standing checklist files for a project.

    Scans agents/{dir}/pm/docs/checklists/*.md for files containing a
    `## Action Items` heading. Extracts unchecked `- [ ]` bullets (and
    plain `- ` bullets); skips checked `- [x]` items.

    Returns a flat list of action item dicts with the same shape as
    parse_meeting_notes' all_action_items, with `meeting` set to
    "Checklist: {stem}" and `date` set to the filename stem so the UI
    can distinguish them from meeting items.
    """
    agent_dir_name = PROJECT_SLUG_TO_DIR.get(slug)
    if not agent_dir_name:
        return []

    checklists_dir = AGENTS_DIR / agent_dir_name / "pm" / "docs" / "checklists"
    if not checklists_dir.is_dir():
        return []

    items = []
    for md_file in sorted(checklists_dir.glob("*.md")):
        text = md_file.read_text()
        stem = md_file.stem

        ai_match = re.search(
            r"## Action Items\n\n?((?:(?:- .+|  .+)\n?)+)", text
        )
        if not ai_match:
            continue

        # Walk lines, tracking whether the current bullet was skipped
        raw_items = []
        skip_current = False
        for line in ai_match.group(1).rstrip("\n").split("\n"):
            if line.startswith("- "):
                body = line[2:]
                if body.startswith("[x]") or body.startswith("[X]"):
                    skip_current = True
                    continue
                skip_current = False
                if body.startswith("[ ]"):
                    body = body[3:].lstrip()
                raw_items.append(body.strip())
            elif line.startswith("  ") and raw_items and not skip_current:
                raw_items[-1] += " " + line.strip()

        for raw in raw_items:
            owner = ""
            desc = raw
            bracket_match = re.match(r"\[([^\]]+)\]\s+(.+)", raw)
            if bracket_match:
                owner = bracket_match.group(1).strip()
                desc = bracket_match.group(2).strip()
            else:
                owner_match = re.search(r"\s+[—–-]+\s+(\w[\w ]*?)(?:\s*\(.*?\))?\s*$", raw)
                if owner_match:
                    owner = owner_match.group(1).strip()
                    desc = raw[:owner_match.start()].strip()
                else:
                    prefix_match = re.match(r"(\w[\w ]+?):\s+(.+)", raw)
                    if prefix_match:
                        owner = prefix_match.group(1).strip()
                        desc = prefix_match.group(2).strip()

            if re.search(r"#\d+", desc):
                continue

            key = hashlib.md5(
                f"checklist:{stem}:{desc}".encode()
            ).hexdigest()[:12]

            items.append({
                "key": key,
                "description": desc,
                "owner": owner,
                "date": stem,
                "meeting": f"Checklist: {stem}",
                "is_checklist": True,
            })

    return items


# ---- Action item dismiss status (shared by app.py and panel) ----

ACTIONS_STATUS_FILE = Path(__file__).resolve().parent / "data" / "meeting-actions-status.json"


def load_actions_status():
    """Load dismissed action item keys from JSON sidecar."""
    if ACTIONS_STATUS_FILE.exists():
        try:
            return json.loads(ACTIONS_STATUS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_actions_status(data):
    """Write dismissed action item keys to JSON sidecar."""
    ACTIONS_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIONS_STATUS_FILE.write_text(json.dumps(data, indent=2))


# Owner aliases come from config/dashboard.yml. Empty list disables the
# "is this mine?" filter (every action item is surfaced).
MY_OWNER_NAMES = set(_CFG["owner_aliases"])


def _is_my_action(owner):
    """True when an action item's owner matches a configured alias.

    Returns True for every item when no aliases are configured.
    """
    if not MY_OWNER_NAMES:
        return True
    return owner.strip().lower() in MY_OWNER_NAMES


def get_all_open_actions():
    """Return all non-dismissed action items grouped by project.

    Only items owned by the configured owner_aliases are surfaced (unless
    owner_aliases is empty, in which case everything is shown). Internal
    (non-client) projects are skipped.
    """
    dismissed = load_actions_status()
    projects = []
    for slug in PROJECT_SLUG_TO_DIR:
        if slug not in CLIENT_PROJECTS:
            continue
        notes = parse_meeting_notes(slug)
        meeting_items = [
            i for i in notes["all_action_items"]
            if i["key"] not in dismissed and _is_my_action(i.get("owner", ""))
        ]
        # Checklist items are the PM's personal TODO list — surface them all
        # unless dismissed.
        checklist_items = [
            i for i in parse_checklists(slug)
            if i["key"] not in dismissed
        ]
        items = checklist_items + meeting_items
        if items:
            projects.append({
                "name": slug,
                "color": PROJECT_COLORS.get(slug, DEFAULT_COLOR),
                "items": items,
            })
    return {
        "projects": projects,
        "total_open": sum(len(p["items"]) for p in projects),
    }




def get_all_data():
    """Return combined dashboard + briefing + people + staleness + retrospector data."""
    dashboard = parse_dashboard()
    briefing = parse_briefing()
    geekbot = parse_geekbot()
    weekly = parse_weekly()
    noko_entries = parse_noko_entries()
    people = aggregate_people(noko_entries)
    work_type = aggregate_project_hours(noko_entries)
    yesterday_time = aggregate_yesterday_time(noko_entries)
    staleness = load_staleness()
    deployments = load_deploy_schedule()
    retrospector = parse_retrospector()

    # Compute aggregate stats
    total_prs = sum(
        len(d.get("open_prs", []))
        for d in dashboard.get("details", {}).values()
    )
    at_risk = sum(
        1 for p in dashboard.get("projects", [])
        if p["status_class"] == "at-risk"
    )
    total_projects = len(dashboard.get("projects", []))
    total_hours = sum(
        d.get("hours_logged", 0)
        for d in dashboard.get("details", {}).values()
    )

    stale_count = len(staleness.get("stale_items", []))

    return {
        "dashboard": dashboard,
        "briefing": briefing,
        "geekbot": geekbot,
        "weekly": weekly,
        "people": people,
        "work_type": work_type,
        "yesterday_time": yesterday_time,
        "staleness": staleness,
        "deployments": deployments,
        "retrospector": retrospector,
        "retro_trend": retrospector_trend(),
        "automations": get_automations(),
        "run_history": parse_run_history(),
        "health": get_health(),
        "stats": {
            "total_projects": total_projects,
            "at_risk": at_risk,
            "total_prs": total_prs,
            "total_hours": round(total_hours, 1),
            "team_size": len(people),
            "stale_prs": stale_count,
        },
    }


def get_automations():
    """Return metadata about all dashboard automation jobs.

    These entries are display-only — they describe scripts and launchd plists
    you might wire up. Edit this list (or remove entries) to match your own
    automations. The dashboard reads launchctl + the .plist files at the
    paths below to surface live status.
    """
    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    jobs = [
        {
            "name": "Morning Briefing",
            "label": "com.pmdashboard.dashboard-update",
            "schedule": "Weekdays at 6:00 AM PT",
            "frequency": "daily",
            "description": (
                "Scans GitHub repos, fetches Noko budgets, corrects stale "
                "memory bank data, updates dashboard and briefing."
            ),
            "script": "automation/scripts/morning-briefing.sh",
            "outputs": [
                "memory-bank/dashboard.md",
                "memory-bank/morning-briefing.md",
            ],
            "logs": [
                ".claude/logs/dashboard-update.log",
                ".claude/logs/dashboard-update-error.log",
            ],
            "dashboard_page": "/briefing",
            "children": [
                {
                    "name": "Geekbot Standup",
                    "schedule": "Weekdays",
                    "frequency": "daily",
                    "description": (
                        "Generates daily standup from Noko, memory banks, "
                        "GitHub issues, and calendar events."
                    ),
                    "script": "automation/scripts/llm-geekbot.sh",
                    "outputs": ["memory-bank/geekbot-standup.md"],
                    "dashboard_page": "/briefing",
                },
                {
                    "name": "Weekly PM Update",
                    "schedule": "Fridays only",
                    "frequency": "weekly",
                    "description": (
                        "Generates per-project CONCERNS and PLAN FOR NEXT "
                        "WEEK for Slack."
                    ),
                    "script": "automation/scripts/llm-weekly.sh",
                    "outputs": ["memory-bank/weekly-report.md"],
                    "dashboard_page": "/briefing",
                },
            ],
        },
        {
            "name": "Retrospector",
            "label": "com.pmdashboard.retrospector",
            "schedule": "Weekdays at 11:59 PM PT",
            "frequency": "daily",
            "description": (
                "Analyzes session logs for failures, classifies improvements "
                "via Claude, proposes changes on a review branch."
            ),
            "script": "automation/scripts/retrospector.sh",
            "outputs": [
                "memory-bank/retrospector-report.md",
                "memory-bank/retrospector-report-details.json",
            ],
            "logs": [
                ".claude/logs/retrospector.log",
                ".claude/logs/retrospector-error.log",
            ],
            "dashboard_page": "/retrospector",
        },
        {
            "name": "Memory Consolidator",
            "label": "com.pmdashboard.consolidator",
            "schedule": "Fridays at 11:30 PM PT",
            "frequency": "weekly",
            "description": (
                "Merges feedback_*.md memory files into principle files "
                "to prevent memory bloat."
            ),
            "script": "automation/scripts/retrospector.sh --phase consolidate",
            "outputs": [
                "memory-bank/retrospector-consolidation-log.json",
            ],
            "logs": [
                ".claude/logs/consolidator.log",
                ".claude/logs/consolidator-error.log",
            ],
            "dashboard_page": "/retrospector",
        },
        {
            "name": "Dashboard Web Server",
            "label": "com.pmdashboard.dashboard",
            "schedule": "Always running (KeepAlive)",
            "frequency": "service",
            "description": (
                "Starlette web app serving the PM dashboard. "
                "Auto-restarts on crash via macOS KeepAlive. "
                "Runs with --reload so Python and CSS changes take "
                "effect automatically."
            ),
            "script": "dashboard/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080 --reload",
            "outputs": [],
            "logs": [
                ".claude/logs/dashboard-server.log",
                ".claude/logs/dashboard-server-error.log",
            ],
        },
    ]

    # Check launchd status for each job
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=5,
        )
        launchctl_output = result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        launchctl_output = ""

    for job in jobs:
        plist_path = launch_agents_dir / f"{job['label']}.plist"
        job["installed"] = plist_path.exists()
        job["running"] = job["label"] in launchctl_output

        # Check last log timestamp
        for log_path_str in job["logs"]:
            log_path = ROOT / log_path_str
            if log_path.exists():
                mtime = datetime.fromtimestamp(
                    log_path.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M")
                job["last_activity"] = mtime
                break
        else:
            job["last_activity"] = None

    return jobs


def parse_run_history(days=14):
    """Parse automation log files for daily run history.

    Returns a dict of {job_name: {date_str: status}} where status is
    'ok', 'error', or absent (not run).
    """
    logs_dir = ROOT / ".claude" / "logs"
    today = datetime.now()

    # Date strings for the window
    date_range = []
    for i in range(days - 1, -1, -1):
        d = today - __import__("datetime").timedelta(days=i)
        date_range.append(d.strftime("%Y-%m-%d"))

    # Patterns: (job_name, log_file, success_pattern, error_pattern)
    job_patterns = [
        (
            "Morning Briefing",
            logs_dir / "dashboard-update.log",
            r"Morning briefing complete\.",
            r"error|Error|FAILED",
        ),
        (
            "Retrospector",
            logs_dir / "retrospector.log",
            r"=== Retrospector complete ===",
            r"error|Error|FAILED",
        ),
        (
            "Consolidator",
            logs_dir / "retrospector.log",
            r"Consolidation complete:",
            None,
        ),
    ]

    history = {}
    for job_name, log_path, success_re, _error_re in job_patterns:
        runs = {}
        if not log_path.exists():
            history[job_name] = runs
            continue

        try:
            text = log_path.read_text()
        except OSError:
            history[job_name] = runs
            continue

        # Find all success lines with timestamps
        for line in text.split("\n"):
            if not re.search(success_re, line):
                continue
            # Extract date from log line formats:
            #   "Mon Apr 14 07:07:48 PDT 2026: ..."
            dm = re.match(
                r"[A-Z][a-z]{2} +([A-Z][a-z]{2}) +(\d+) +[\d:]+ +\w+ +(\d{4}):", line
            )
            if dm:
                try:
                    dt = datetime.strptime(
                        f"{dm.group(1)} {dm.group(2)} {dm.group(3)}",
                        "%b %d %Y",
                    )
                    date_str = dt.strftime("%Y-%m-%d")
                    if date_str in date_range:
                        runs[date_str] = "ok"
                except ValueError:
                    pass

        history[job_name] = runs

    return {"dates": date_range, "jobs": history}
