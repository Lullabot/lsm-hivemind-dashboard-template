"""Tests for parse_geekbot()."""

from data import parse_geekbot


def test_parse_geekbot_happy_path(memory_bank):
    result = parse_geekbot()

    assert result["date"] == "Friday, April 18, 2026"
    assert len(result["sections"]) == 3
    assert result["sections"][0]["title"] == "What's new since yesterday?"
    assert "CATIC SSO" in result["sections"][0]["content"]
    assert result["sections"][2]["title"] == "Anything blocking your progress?"


def test_parse_geekbot_raw_content(memory_bank):
    result = parse_geekbot()

    assert result["raw"]  # Non-empty
    assert "Section 1" in result["raw"]


def test_parse_geekbot_missing_file(tmp_path, monkeypatch):
    import data
    monkeypatch.setattr(data, "MEMORY_BANK", tmp_path)

    result = parse_geekbot()

    assert result["date"] == ""
    assert result["raw"] == ""
    assert result["sections"] == []
