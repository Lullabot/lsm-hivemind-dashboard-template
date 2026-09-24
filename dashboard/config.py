"""Config loader for the dashboard.

Reads config/projects.yml and config/dashboard.yml at import time. Anything
project-specific in the dashboard code should pull from this module rather
than embedding strings.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


VALID_STATUSES = {"active", "archived"}
VALID_CATEGORIES = {"client", "internal", "bucket"}


def project_category(entry: dict) -> str:
    """Return a project's category, honoring the older ``client`` boolean.

    ``category`` wins when set. Without it, ``client: false`` means internal
    and anything else means client, which is how the template behaved before
    categories existed.
    """
    if entry.get("category"):
        return entry["category"]
    return "client" if entry.get("client", True) else "internal"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    """Return the merged configuration as a plain dict.

    Shape:
        {
            "title": str,
            "owner_aliases": list[str],
            "paths": {"memory_bank": Path, "agents": Path},
            "status_map": dict[str, str],
            "staleness": {"warn_days": int, "crit_days": int},
            "person_colors": list[str],
            "person_aliases": dict[str, str],
            "projects": list[dict],          # raw entries, archived included
            "active_projects": list[dict],   # entries with status != archived
            "archived_projects": list[str],  # names of archived projects
            "project_names": list[str],      # ordered display names (active only)
            "project_colors": dict[str, str],
            "project_github": dict[str, str],
            "noko_dir_to_project": dict[str, str],
            "slug_to_agent_dir": dict[str, str],
            "client_projects": set[str],
            "project_categories": dict[str, str],
            "kenkeep_tags": dict[str, str],  # kenkeep tag -> project name
        }

    Every derived map covers active projects only. Archived projects stay in
    ``projects`` so the history is visible, but they never reach a view.
    """
    dash = _read_yaml(CONFIG_DIR / "dashboard.yml")
    projects_cfg = _read_yaml(CONFIG_DIR / "projects.yml")

    projects: list[dict] = projects_cfg.get("projects", []) or []
    for p in projects:
        if "name" not in p:
            raise ValueError(f"config/projects.yml: every project needs a name ({p!r})")
        status = p.get("status", "active")
        if status not in VALID_STATUSES:
            raise ValueError(f"config/projects.yml: {p['name']} has unknown status {status!r}")
        category = p.get("category")
        if category is not None and category not in VALID_CATEGORIES:
            raise ValueError(f"config/projects.yml: {p['name']} has unknown category {category!r}")
    active_projects = [p for p in projects if p.get("status", "active") == "active"]
    archived_projects = [p["name"] for p in projects if p.get("status") == "archived"]

    project_colors: dict[str, str] = {}
    project_github: dict[str, str] = {}
    noko_dir_to_project: dict[str, str] = {}
    slug_to_agent_dir: dict[str, str] = {}
    client_projects: set[str] = set()
    project_names: list[str] = []
    project_categories: dict[str, str] = {}
    kenkeep_tags: dict[str, str] = {}

    for p in active_projects:
        name = p["name"]
        project_names.append(name)
        if p.get("color"):
            project_colors[name] = p["color"]
        if p.get("github"):
            project_github[name] = p["github"]
        noko_dir = p.get("noko_dir", name)
        noko_dir_to_project[noko_dir] = name
        slug_to_agent_dir[name] = p.get("agent_dir", name)
        category = project_category(p)
        project_categories[name] = category
        if category == "client":
            client_projects.add(name)
        if p.get("kenkeep_tag"):
            kenkeep_tags[p["kenkeep_tag"]] = name

    paths_cfg = dash.get("paths", {}) or {}
    memory_bank = Path(os.environ.get("HIVEMIND_MEMORY_BANK") or paths_cfg.get("memory_bank") or "memory-bank")
    agents_dir = Path(os.environ.get("HIVEMIND_AGENTS_DIR") or paths_cfg.get("agents") or "agents")
    if not memory_bank.is_absolute():
        memory_bank = REPO_ROOT / memory_bank
    if not agents_dir.is_absolute():
        agents_dir = REPO_ROOT / agents_dir

    return {
        "title": dash.get("title", "PM Dashboard"),
        "owner_aliases": [a.lower() for a in (dash.get("owner_aliases") or [])],
        "paths": {"memory_bank": memory_bank, "agents": agents_dir},
        "status_map": dash.get("status_map") or {},
        "staleness": dash.get("staleness") or {"warn_days": 3, "crit_days": 7},
        "person_colors": dash.get("person_colors") or [],
        "person_aliases": dash.get("person_aliases") or {},
        "projects": projects,
        "active_projects": active_projects,
        "archived_projects": archived_projects,
        "project_names": project_names,
        "project_colors": project_colors,
        "project_github": project_github,
        "noko_dir_to_project": noko_dir_to_project,
        "slug_to_agent_dir": slug_to_agent_dir,
        "client_projects": client_projects,
        "project_categories": project_categories,
        "kenkeep_tags": kenkeep_tags,
    }


def reload() -> dict[str, Any]:
    """Clear the cache and re-read config. Useful in tests."""
    load.cache_clear()
    return load()
