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
            "projects": list[dict],          # raw project entries
            "project_names": list[str],      # ordered display names
            "project_colors": dict[str, str],
            "project_github": dict[str, str],
            "noko_dir_to_project": dict[str, str],
            "slug_to_agent_dir": dict[str, str],
            "client_projects": set[str],
        }
    """
    dash = _read_yaml(CONFIG_DIR / "dashboard.yml")
    projects_cfg = _read_yaml(CONFIG_DIR / "projects.yml")

    projects: list[dict] = projects_cfg.get("projects", []) or []

    project_colors: dict[str, str] = {}
    project_github: dict[str, str] = {}
    noko_dir_to_project: dict[str, str] = {}
    slug_to_agent_dir: dict[str, str] = {}
    client_projects: set[str] = set()
    project_names: list[str] = []

    for p in projects:
        name = p["name"]
        project_names.append(name)
        if p.get("color"):
            project_colors[name] = p["color"]
        if p.get("github"):
            project_github[name] = p["github"]
        noko_dir = p.get("noko_dir", name)
        noko_dir_to_project[noko_dir] = name
        slug_to_agent_dir[name] = p.get("agent_dir", name)
        if p.get("client", True):
            client_projects.add(name)

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
        "project_names": project_names,
        "project_colors": project_colors,
        "project_github": project_github,
        "noko_dir_to_project": noko_dir_to_project,
        "slug_to_agent_dir": slug_to_agent_dir,
        "client_projects": client_projects,
    }


def reload() -> dict[str, Any]:
    """Clear the cache and re-read config. Useful in tests."""
    load.cache_clear()
    return load()
