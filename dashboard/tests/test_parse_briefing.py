"""Tests for parse_briefing()."""

from data import parse_briefing


def test_parse_briefing_happy_path(memory_bank):
    result = parse_briefing()

    assert result["date"] == "Friday, April 18, 2026"


def test_parse_briefing_time_bars(memory_bank):
    result = parse_briefing()

    assert len(result["time_bars"]) == 3
    bars_by_name = {b["name"]: b for b in result["time_bars"]}
    assert bars_by_name["CATIC"]["hours"] == 45.5
    assert bars_by_name["SDSU"]["hours"] == 89.2
    # SDSU should be 100% (highest)
    assert bars_by_name["SDSU"]["pct"] == 100


def test_parse_briefing_changes(memory_bank):
    result = parse_briefing()

    assert len(result["changes"]) == 2
    assert result["changes"][0]["project"] == "CATIC"
    assert "PR #101" in result["changes"][0]["text"]


def test_parse_briefing_attention(memory_bank):
    result = parse_briefing()

    assert len(result["attention"]) == 2
    assert result["attention"][0]["project"] == "CATIC"


def test_parse_briefing_questions(memory_bank):
    result = parse_briefing()

    assert len(result["questions"]) == 1
    assert result["questions"][0]["label"] == "ManhattanU"


def test_parse_briefing_missing_file(tmp_path, monkeypatch):
    import data
    monkeypatch.setattr(data, "MEMORY_BANK", tmp_path)

    result = parse_briefing()

    assert result["date"] == "Unknown"
    assert result["time_bars"] == []
    assert result["changes"] == []
