"""Tests for parse_retrospector()."""

from data import parse_retrospector


def test_parse_retrospector_happy_path(memory_bank):
    result = parse_retrospector()

    assert result["date"] == "2026-04-18"
    assert result["sessions"] == "8 sessions (1.2 MB)"
    assert result["failures"] == 5


def test_parse_retrospector_improvements(memory_bank):
    result = parse_retrospector()

    assert len(result["improvements"]) == 2
    imp = result["improvements"][0]
    assert imp["category"] == "Tool Discipline"
    assert imp["source_agent"] == "SDSU"
    assert imp["confidence"] == "High"
    # Details from JSON should be merged
    assert "Read before Edit" in imp["description"]
    assert imp["proposed_change"]  # Non-empty
    assert imp["reasoning"]  # Non-empty


def test_parse_retrospector_effectiveness(memory_bank):
    result = parse_retrospector()

    assert len(result["effectiveness"]) == 1
    eff = result["effectiveness"][0]
    assert eff["source_agent"] == "SDSU"
    assert eff["verdict"] == "Effective"


def test_parse_retrospector_meta(memory_bank):
    result = parse_retrospector()

    assert "error categorization" in result["meta"]


def test_parse_retrospector_missing_file(tmp_path, monkeypatch):
    import data
    monkeypatch.setattr(data, "MEMORY_BANK", tmp_path)

    result = parse_retrospector()

    assert result["date"] == "Unknown"
    assert result["failures"] == 0
    assert result["improvements"] == []
