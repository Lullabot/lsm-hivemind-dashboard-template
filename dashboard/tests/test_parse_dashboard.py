"""Tests for parse_dashboard()."""

from data import parse_dashboard


def test_parse_dashboard_happy_path(memory_bank):
    result = parse_dashboard()

    assert result["updated"] == "2026-04-19"
    assert len(result["projects"]) == 2
    assert result["projects"][0]["name"] == "CATIC"
    assert result["projects"][0]["status_class"] == "on-track"
    assert result["projects"][1]["name"] == "SDSU"
    assert result["projects"][1]["status_class"] == "at-risk"


def test_parse_dashboard_priorities(memory_bank):
    result = parse_dashboard()

    assert len(result["priorities"]) == 2
    assert result["priorities"][0]["project"] == "CATIC"
    assert "SSO" in result["priorities"][0]["text"]


def test_parse_dashboard_themes(memory_bank):
    result = parse_dashboard()

    assert len(result["themes"]) == 2
    assert result["themes"][0]["title"] == "Accessibility"


def test_parse_dashboard_details(memory_bank):
    result = parse_dashboard()

    assert "CATIC" in result["details"]
    catic = result["details"]["CATIC"]
    assert catic["hours_logged"] == 45.5
    assert catic["hours_total"] == 120
    assert catic["budget_pct"] == 38
    assert len(catic["work_items"]) == 2
    assert catic["blockers"] == "None"
    assert catic["open_prs"] == ["101", "102"]

    sdsu = result["details"]["SDSU"]
    assert sdsu["hours_logged"] == 89.2
    assert sdsu["blockers"] == "DNS propagation delay"


def test_parse_dashboard_missing_file(tmp_path, monkeypatch):
    import data
    monkeypatch.setattr(data, "MEMORY_BANK", tmp_path)

    result = parse_dashboard()

    assert result["updated"] == "Unknown"
    assert result["projects"] == []
    assert result["themes"] == []
    assert result["priorities"] == []
