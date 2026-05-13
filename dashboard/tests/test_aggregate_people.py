"""Tests for parse_noko_entries(), aggregate_people(), and aggregate_project_hours()."""

from data import parse_noko_entries, aggregate_people, aggregate_project_hours


def test_parse_noko_entries(agents_dir):
    entries = parse_noko_entries()

    assert len(entries) == 2
    assert all(e["person"] == "Alice Smith" for e in entries)
    assert all(e["project"] == "ProjectAlpha" for e in entries)


def test_aggregate_people(agents_dir):
    entries = parse_noko_entries()
    people = aggregate_people(entries)

    assert len(people) == 1
    alice = people[0]
    assert alice["name"] == "Alice Smith"
    assert alice["total_hours"] == 3.5  # 120 + 90 = 210 min = 3.5h
    assert alice["billable_hours"] == 3.5
    assert alice["billable_pct"] == 100
    assert len(alice["projects"]) == 1
    assert alice["projects"][0]["name"] == "ProjectAlpha"


def test_aggregate_people_empty():
    people = aggregate_people([])
    assert people == []


def test_aggregate_people_work_type_split(agents_dir):
    entries = parse_noko_entries()
    people = aggregate_people(entries)

    alice = people[0]
    alpha = alice["projects"][0]
    assert alpha["name"] == "ProjectAlpha"
    # 120 min professional, 90 min maintenance, total 210 min
    assert alpha["professional_pct"] == 57  # 120/210 = 57%
    assert alpha["maintenance_pct"] == 43   # 90/210 = 43%


def test_aggregate_project_hours(agents_dir):
    entries = parse_noko_entries()
    result = aggregate_project_hours(entries)

    assert "ProjectAlpha" in result
    alpha = result["ProjectAlpha"]
    assert alpha["total_hours"] == 3.5
    assert alpha["professional_hours"] == 2.0  # 120 min
    assert alpha["maintenance_hours"] == 1.5   # 90 min
    assert alpha["untagged_hours"] == 0.0
    assert alpha["professional_pct"] == 57
    assert alpha["maintenance_pct"] == 43
    assert alpha["untagged_pct"] == 0


def test_aggregate_project_hours_empty():
    result = aggregate_project_hours([])
    assert result == {}


def test_aggregate_project_hours_untagged():
    entries = [
        {
            "person": "Bob Jones",
            "person_id": 2,
            "avatar": "",
            "project": "ProjectBeta",
            "date": "2026-04-18",
            "minutes": 60,
            "description": "Meeting",
            "tags": [],
            "billable": True,
        },
    ]
    result = aggregate_project_hours(entries)
    assert result["ProjectBeta"]["untagged_hours"] == 1.0
    assert result["ProjectBeta"]["untagged_pct"] == 100
    assert result["ProjectBeta"]["maintenance_hours"] == 0.0
    assert result["ProjectBeta"]["professional_hours"] == 0.0


def test_parse_noko_entries_no_agents(tmp_path, monkeypatch):
    import data
    monkeypatch.setattr(data, "AGENTS_DIR", tmp_path)

    entries = parse_noko_entries()
    assert entries == []
