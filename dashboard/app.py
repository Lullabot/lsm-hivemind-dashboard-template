"""PM Dashboard — Starlette web app for multi-project PM coordination."""

import re
from datetime import datetime, timezone
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from data import _is_my_action, get_all_data, get_all_open_actions, get_health, list_retrospector_dates, load_actions_status, parse_claude_md_escalations, parse_retrospector, parse_consolidation_log, parse_escalation_log, parse_hook_enforcements, parse_meeting_notes, parse_checklists, save_actions_status

MEMORY_BANK = Path(__file__).resolve().parent.parent / "memory-bank"

MEMORY_DIR = Path(__file__).resolve().parent.parent / ".claude" / "memory"

RULES_DIR = Path(__file__).resolve().parent.parent / "memory-bank" / "rules"

BASE_DIR = Path(__file__).resolve().parent

CSS_PATH = BASE_DIR / "static" / "style.css"

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["inline_css_path"] = CSS_PATH


async def dashboard(request):
    data = get_all_data()
    return templates.TemplateResponse(request, "dashboard.html", context=data)


async def briefing(request):
    data = get_all_data()
    return templates.TemplateResponse(request, "briefing.html", context=data)


async def project_detail(request):
    slug = request.path_params["slug"]
    data = get_all_data()
    detail = data["dashboard"]["details"].get(slug)
    project = next(
        (p for p in data["dashboard"]["projects"] if p["name"] == slug), None
    )
    if not detail or not project:
        from starlette.responses import RedirectResponse
        return RedirectResponse(url="/")
    meeting_notes = parse_meeting_notes(slug)
    # Project page mirrors the global Tasks panel: only show items owned by me.
    meeting_notes["all_action_items"] = [
        i for i in meeting_notes["all_action_items"]
        if _is_my_action(i.get("owner", ""))
    ]
    # Merge standing checklist items (personal TODOs) into the action items
    # list so they render alongside meeting actions on the project page.
    checklist_items = parse_checklists(slug)
    if checklist_items:
        meeting_notes["all_action_items"] = checklist_items + meeting_notes["all_action_items"]
    return templates.TemplateResponse(request, "project.html", context={
        **data,
        "project": project,
        "detail": detail,
        "slug": slug,
        "meeting_notes": meeting_notes,
    })


async def people(request):
    data = get_all_data()
    return templates.TemplateResponse(request, "people.html", context=data)


async def retrospector(request):
    data = get_all_data()
    data["retrospector_dates"] = list_retrospector_dates()
    data["current_date"] = None
    data["consolidation_log"] = parse_consolidation_log()
    data["escalation_log"] = parse_escalation_log()
    data["escalation_content"] = parse_claude_md_escalations()
    data["hook_enforcements"] = parse_hook_enforcements()
    return templates.TemplateResponse(request, "retrospector.html", context=data)


async def retrospector_by_date(request):
    date = request.path_params["date"]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        from starlette.responses import RedirectResponse
        return RedirectResponse(url="/retrospector")
    data = get_all_data()
    data["retrospector"] = parse_retrospector(date=date)
    data["retrospector_dates"] = list_retrospector_dates()
    data["current_date"] = date
    data["consolidation_log"] = parse_consolidation_log()
    data["escalation_log"] = parse_escalation_log()
    data["escalation_content"] = parse_claude_md_escalations()
    data["hook_enforcements"] = parse_hook_enforcements()
    return templates.TemplateResponse(request, "retrospector.html", context=data)


async def automations(request):
    data = get_all_data()
    return templates.TemplateResponse(request, "automations.html", context=data)


async def memory_content(request):
    """Return the contents of a memory or rule file by filename. Looks in
    .claude/memory/ first (legacy feedback_principle_*.md files), then falls
    back to memory-bank/rules/ (shared rules consolidated from escalations).
    Only serves .md files to prevent path traversal."""
    filename = request.path_params["filename"]
    if not re.match(r"^[\w.-]+\.md$", filename):
        return PlainTextResponse("Invalid filename", status_code=400)
    path = next(
        (candidate for candidate in (MEMORY_DIR / filename, RULES_DIR / filename) if candidate.exists()),
        None,
    )
    if path is None:
        return PlainTextResponse(
            "This improvement has been proposed but the memory file has not been created yet.",
            status_code=404,
        )
    text = path.read_text()
    body = re.sub(r"^---\n.*?---\n+", "", text, count=1, flags=re.DOTALL)
    return PlainTextResponse(body.strip())


async def health(request):
    """System health check — data source freshness and uptime."""
    data = get_health()
    status_code = 200 if data["status"] == "ok" else 503
    return JSONResponse(data, status_code=status_code)


async def export_json(request):
    return JSONResponse(get_all_data())


API_ENDPOINTS = [
    {
        "method": "GET",
        "path": "/health",
        "description": "System health check. Returns data source freshness, uptime, "
                       "and overall status. Returns 200 when all sources are fresh, "
                       "503 when degraded or stale.",
        "category": "Core",
        "params": [],
        "example_response": '{\n  "status": "ok",\n  "uptime_seconds": 12345,\n'
                            '  "sources": {\n    "morning_briefing": {\n'
                            '      "age_seconds": 3600,\n      "age_human": "1h ago",\n'
                            '      "status": "ok",\n      "path_exists": true\n    }\n  }\n}',
    },
    {
        "method": "GET",
        "path": "/api/data",
        "description": "Full dashboard data export. Returns all project statuses, "
                       "briefing, people activity, staleness, retrospector, and "
                       "automation metadata in a single payload.",
        "category": "Core",
        "params": [],
        "example_response": '{\n  "dashboard": { "projects": [...], "details": {...} },\n'
                            '  "briefing": { "date": "...", "sections": [...] },\n'
                            '  "people": [ { "name": "...", "total_hours": 0 } ],\n'
                            '  "retrospector": { "date": "...", "improvements": [...] },\n'
                            '  "automations": [...],\n'
                            '  "stats": { "total_projects": 5, "total_hours": 0 }\n}',
    },
    {
        "method": "GET",
        "path": "/api/memory/{filename}",
        "description": "Read a memory file by filename. Returns the file body with "
                       "YAML frontmatter stripped. Only serves .md files from the "
                       "memory directory.",
        "category": "Memory",
        "params": [
            {"name": "filename", "type": "string", "description": "Memory file name, e.g. feedback_principle_git_workflow.md"},
        ],
        "example_response": "Use the pre-computed agent field from each failure object.\n"
                            "This is pre-computed from the session directory path...",
    },
    {
        "method": "GET",
        "path": "/api/retrospector/{date}",
        "description": "Retrospector report for a specific date. Returns the parsed "
                       "report including improvements, effectiveness tracking, and "
                       "meta-observations.",
        "category": "Retrospector",
        "params": [
            {"name": "date", "type": "YYYY-MM-DD", "description": "Report date, e.g. 2026-04-18"},
        ],
        "example_response": '{\n  "date": "2026-04-18",\n  "sessions": "11 sessions (2.3 MB)",\n'
                            '  "failures": 29,\n  "improvements": [...],\n'
                            '  "effectiveness": [...]\n}',
    },
    {
        "method": "GET",
        "path": "/api/project/{slug}",
        "description": "Per-project detail data including open PRs, recent activity, "
                       "hours logged, and memory bank status.",
        "category": "Projects",
        "params": [
            {"name": "slug", "type": "string", "description": "Project slug (see config/projects.yml)"},
        ],
        "example_response": '{\n  "name": "ProjectAlpha",\n  "status": "on-track",\n'
                            '  "open_prs": [...],\n  "hours_logged": 12.5,\n'
                            '  "recent_activity": [...]\n}',
    },
]


async def api_explorer(request):
    data = get_all_data()
    return templates.TemplateResponse(request, "api.html", context={
        **data,
        "endpoints": API_ENDPOINTS,
    })


async def api_retrospector_date(request):
    date = request.path_params["date"]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return JSONResponse({"error": "Invalid date format"}, status_code=400)
    return JSONResponse(parse_retrospector(date=date))


async def api_project(request):
    slug = request.path_params["slug"]
    data = get_all_data()
    detail = data["dashboard"]["details"].get(slug)
    if not detail:
        return JSONResponse({"error": f"Project '{slug}' not found"}, status_code=404)
    project = next(
        (p for p in data["dashboard"]["projects"] if p["name"] == slug), None
    )
    return JSONResponse({**(project or {}), **detail})


async def api_geekbot_save(request):
    """Save edited geekbot standup content back to file."""
    body = await request.json()
    content = body.get("content", "")
    path = MEMORY_BANK / "geekbot-standup.md"
    path.write_text(content)
    return JSONResponse({"ok": True})


async def api_weekly_save(request):
    """Save edited weekly report content back to file."""
    body = await request.json()
    content = body.get("content", "")
    path = MEMORY_BANK / "weekly-report.md"
    path.write_text(content)
    return JSONResponse({"ok": True})


async def api_action_toggle(request):
    """Toggle an action item's dismissed state."""
    body = await request.json()
    key = body.get("key", "")
    if not re.match(r"^[a-f0-9]{12}$", key):
        return JSONResponse({"error": "Invalid key"}, status_code=400)
    status = load_actions_status()
    if key in status:
        del status[key]
        dismissed = False
    else:
        status[key] = {
            "dismissed_at": datetime.now(timezone.utc).isoformat(),
        }
        dismissed = True
    save_actions_status(status)
    return JSONResponse({"ok": True, "dismissed": dismissed})


async def api_actions_status(request):
    """Return all dismissed action item keys."""
    return JSONResponse(load_actions_status())


async def api_actions_open(request):
    """Return all open action items across all projects."""
    return JSONResponse(get_all_open_actions())


routes = [
    Route("/", dashboard, name="dashboard"),
    Route("/briefing", briefing, name="briefing"),
    Route("/people", people, name="people"),
    Route("/retrospector/{date}", retrospector_by_date, name="retrospector_date"),
    Route("/retrospector", retrospector, name="retrospector"),
    Route("/automations", automations, name="automations"),
    Route("/project/{slug}", project_detail, name="project_detail"),
    Route("/api", api_explorer, name="api_explorer"),
    Route("/health", health, name="health"),
    Route("/api/data", export_json, name="export"),
    Route("/api/memory/{filename}", memory_content, name="memory_content"),
    Route("/api/retrospector/{date}", api_retrospector_date, name="api_retrospector_date"),
    Route("/api/project/{slug}", api_project, name="api_project"),
    Route("/api/geekbot/save", api_geekbot_save, name="api_geekbot_save", methods=["POST"]),
    Route("/api/weekly/save", api_weekly_save, name="api_weekly_save", methods=["POST"]),
    Route("/api/actions/toggle", api_action_toggle, name="api_action_toggle", methods=["POST"]),
    Route("/api/actions/status", api_actions_status, name="api_actions_status"),
    Route("/api/actions/open", api_actions_open, name="api_actions_open"),
    Mount("/static", app=StaticFiles(directory=BASE_DIR / "static"), name="static"),
]

app = Starlette(debug=True, routes=routes)
