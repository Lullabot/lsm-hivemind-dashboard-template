"""Tests for parse_weekly()."""

from data import parse_weekly


def test_parse_weekly_happy_path(memory_bank):
    result = parse_weekly()

    assert result["date"] == "Week of April 14, 2026"
    assert len(result["projects"]) == 2


def test_parse_weekly_project_sections(memory_bank):
    result = parse_weekly()

    projectalpha = result["projects"][0]
    assert projectalpha["name"] == "ProjectAlpha"
    assert "SSO" in projectalpha["concerns"]
    assert "accessibility audit" in projectalpha["plan"]

    projectbeta = result["projects"][1]
    assert projectbeta["name"] == "ProjectBeta"
    assert "90%" in projectbeta["concerns"]


def test_parse_weekly_missing_file(tmp_path, monkeypatch):
    import data
    monkeypatch.setattr(data, "MEMORY_BANK", tmp_path)

    result = parse_weekly()

    assert result["date"] == ""
    assert result["projects"] == []
