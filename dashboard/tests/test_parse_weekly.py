"""Tests for parse_weekly()."""

from data import parse_weekly


def test_parse_weekly_happy_path(memory_bank):
    result = parse_weekly()

    assert result["date"] == "Week of April 14, 2026"
    assert len(result["projects"]) == 2


def test_parse_weekly_project_sections(memory_bank):
    result = parse_weekly()

    catic = result["projects"][0]
    assert catic["name"] == "CATIC"
    assert "SSO" in catic["concerns"]
    assert "accessibility audit" in catic["plan"]

    sdsu = result["projects"][1]
    assert sdsu["name"] == "SDSU"
    assert "90%" in sdsu["concerns"]


def test_parse_weekly_missing_file(tmp_path, monkeypatch):
    import data
    monkeypatch.setattr(data, "MEMORY_BANK", tmp_path)

    result = parse_weekly()

    assert result["date"] == ""
    assert result["projects"] == []
