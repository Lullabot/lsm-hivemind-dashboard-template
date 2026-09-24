"""Tests for parse_dashboard()."""

from data import parse_dashboard


def test_parse_dashboard_happy_path(memory_bank):
    result = parse_dashboard()

    assert result["updated"] == "2026-04-19"
    assert len(result["projects"]) == 2
    assert result["projects"][0]["name"] == "ProjectAlpha"
    assert result["projects"][0]["status_class"] == "on-track"
    assert result["projects"][1]["name"] == "ProjectBeta"
    assert result["projects"][1]["status_class"] == "at-risk"


def test_parse_dashboard_priorities(memory_bank):
    result = parse_dashboard()

    assert len(result["priorities"]) == 2
    assert result["priorities"][0]["project"] == "ProjectAlpha"
    assert "SSO" in result["priorities"][0]["text"]


def test_parse_dashboard_themes(memory_bank):
    result = parse_dashboard()

    assert len(result["themes"]) == 2
    assert result["themes"][0]["title"] == "Accessibility"


def test_parse_dashboard_details(memory_bank):
    result = parse_dashboard()

    assert "ProjectAlpha" in result["details"]
    projectalpha = result["details"]["ProjectAlpha"]
    assert projectalpha["hours_logged"] == 45.5
    assert projectalpha["hours_total"] == 120
    assert projectalpha["budget_pct"] == 38
    assert len(projectalpha["work_items"]) == 2
    assert projectalpha["blockers"] == "None"
    assert projectalpha["open_prs"] == ["101", "102"]

    projectbeta = result["details"]["ProjectBeta"]
    assert projectbeta["hours_logged"] == 89.2
    assert projectbeta["blockers"] == "DNS propagation delay"


def test_parse_dashboard_missing_file(tmp_path, monkeypatch):
    import data
    monkeypatch.setattr(data, "MEMORY_BANK", tmp_path)

    result = parse_dashboard()

    assert result["updated"] == "Unknown"
    assert result["projects"] == []
    assert result["themes"] == []
    assert result["priorities"] == []
