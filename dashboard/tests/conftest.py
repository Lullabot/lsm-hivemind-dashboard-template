"""Shared fixtures for dashboard parser tests."""

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def memory_bank(tmp_path, monkeypatch):
    """Copy fixture files into a temp directory and patch MEMORY_BANK."""
    import data

    mb = tmp_path / "memory-bank"
    mb.mkdir()
    for f in FIXTURES.iterdir():
        if f.is_file():
            shutil.copy(f, mb / f.name)

    monkeypatch.setattr(data, "MEMORY_BANK", mb)
    return mb


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    """Create a minimal agents directory structure with Noko data."""
    import data

    agents = tmp_path / "agents"
    agents.mkdir()

    # Use ProjectAlpha (matches config/projects.yml example).
    project = agents / "ProjectAlpha" / "logs"
    project.mkdir(parents=True)
    noko_data = [
        {
            "user": {"first_name": "Alice", "last_name": "Smith", "id": 1,
                     "profile_image_url": ""},
            "date": "2026-04-18",
            "minutes": 120,
            "description": "SSO work",
            "tags": [{"formatted_name": "#professional"}],
            "billable": True,
        },
        {
            "user": {"first_name": "Alice", "last_name": "Smith", "id": 1,
                     "profile_image_url": ""},
            "date": "2026-04-17",
            "minutes": 90,
            "description": "Code review",
            "tags": [{"formatted_name": "#maintenance"}],
            "billable": True,
        },
    ]
    import json
    (project / "noko-2026-04-18.json").write_text(json.dumps(noko_data))

    monkeypatch.setattr(data, "AGENTS_DIR", agents)
    return agents
