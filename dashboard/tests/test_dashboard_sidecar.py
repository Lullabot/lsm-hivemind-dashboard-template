"""Tests for the dashboard.json structured sidecar."""

import json
import os
import time

from data import load_dashboard_sidecar, parse_dashboard

SIDECAR = {
    "updated": "2026-04-20",
    "projects": [
        {"name": "ProjectAlpha", "client": "Example Org", "type": "Retainer", "status": "**On Track**", "summary": "From JSON"},
        {"name": "ProjectBeta", "status": "At Risk", "summary": "Also JSON"},
    ],
    "priorities": [{"project": "ProjectAlpha", "text": "Ship it"}, {"text": "no project, dropped"}],
    "themes": [{"title": "Accessibility", "detail": "audits"}, "Plain string theme"],
}


def _write(mb, payload):
    path = mb / "dashboard.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return path


def test_valid_sidecar_wins_for_table(memory_bank):
    _write(memory_bank, SIDECAR)
    result = parse_dashboard()

    assert result["source"] == "json"
    assert result["updated"] == "2026-04-20"
    assert [p["name"] for p in result["projects"]] == ["ProjectAlpha", "ProjectBeta"]
    assert result["projects"][0]["status"] == "On Track"
    assert result["projects"][0]["status_class"] == "on-track"
    assert result["projects"][1]["client"] == "ProjectBeta"  # defaults to name
    assert result["priorities"] == [{"project": "ProjectAlpha", "text": "Ship it"}]
    assert result["themes"][1] == {"title": "", "detail": "Plain string theme"}
    # Detail sections still come from the markdown.
    assert result["details"]["ProjectAlpha"]["hours_logged"] == 45.5


def test_missing_sidecar_falls_back_to_markdown(memory_bank):
    assert load_dashboard_sidecar() is None
    result = parse_dashboard()
    assert result["source"] == "markdown"
    assert result["projects"][0]["summary"] == "SOW 2 stability work"


def test_invalid_json_falls_back(memory_bank):
    _write(memory_bank, "{not json")
    assert load_dashboard_sidecar() is None
    assert parse_dashboard()["source"] == "markdown"


def test_wrong_shape_falls_back(memory_bank):
    _write(memory_bank, {"projects": "nope"})
    assert load_dashboard_sidecar() is None
    _write(memory_bank, {"projects": []})
    assert load_dashboard_sidecar() is None
    _write(memory_bank, {"projects": [{"summary": "no name"}]})
    assert load_dashboard_sidecar() is None


def test_stale_sidecar_ignored(memory_bank):
    path = _write(memory_bank, SIDECAR)
    old = time.time() - 3600
    os.utime(path, (old, old))
    assert load_dashboard_sidecar() is None
    assert parse_dashboard()["source"] == "markdown"


def test_sidecar_without_markdown(memory_bank):
    (memory_bank / "dashboard.md").unlink()
    _write(memory_bank, SIDECAR)
    result = parse_dashboard()
    assert result["source"] == "json"
    assert result["details"] == {}
    assert len(result["projects"]) == 2


def test_archived_projects_dropped_from_sidecar(memory_bank, monkeypatch):
    import data
    monkeypatch.setattr(data, "ARCHIVED_PROJECTS", {"ProjectBeta"})
    _write(memory_bank, {**SIDECAR, "priorities": SIDECAR["priorities"] + [{"project": "ProjectBeta", "text": "old"}]})
    result = parse_dashboard()
    assert result["source"] == "json"
    assert [p["name"] for p in result["projects"]] == ["ProjectAlpha"]
    assert all(p["project"] != "ProjectBeta" for p in result["priorities"])
    assert "ProjectBeta" not in result["details"]


def test_archived_projects_dropped_from_markdown(memory_bank, monkeypatch):
    import data
    monkeypatch.setattr(data, "ARCHIVED_PROJECTS", {"ProjectAlpha"})
    result = parse_dashboard()
    assert result["source"] == "markdown"
    assert "ProjectAlpha" not in [p["name"] for p in result["projects"]]
    assert "ProjectAlpha" not in result["details"]
