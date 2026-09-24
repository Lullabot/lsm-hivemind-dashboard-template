"""Tests for the kenkeep memory-map parser."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

import config
import kenkeep_data

KK = Path(__file__).parent / "fixtures" / "kenkeep"


@pytest.fixture()
def kk_config(monkeypatch):
    """Two projects: Alpha (active) and Old (archived)."""
    fake = {
        "projects": [
            {"name": "Alpha", "kenkeep_tag": "alpha"},
            {"name": "Old", "status": "archived"},
        ],
        "project_colors": {"Alpha": "#6366f1", "Old": "#64748b"},
        "slug_to_agent_dir": {"Alpha": "Alpha", "Old": "Old"},
        "paths": {"agents": KK / "agents", "memory_bank": KK},
    }
    monkeypatch.setattr(config, "load", lambda: fake)
    monkeypatch.delenv("MEMORY_MAP_SCOPE", raising=False)
    return fake


@pytest.fixture()
def sources(kk_config):
    return kenkeep_data.kenkeep_sources(root=KK / "root", agents_dir=KK / "agents")


def _by_orig(graph):
    return {n["orig_id"]: n for n in graph["nodes"]}


def test_sources_skip_archived_projects(sources):
    keys = [s["source_key"] for s in sources]
    assert keys == ["root", "alpha-workspace", "alpha-code"]


def test_scope_l1_limits_to_root(kk_config, monkeypatch):
    monkeypatch.setenv("MEMORY_MAP_SCOPE", "l1")
    sources = kenkeep_data.kenkeep_sources(root=KK / "root", agents_dir=KK / "agents")
    assert [s["layer"] for s in sources] == ["L1"]


def test_parses_both_schemas_and_folded_ids(sources):
    graph = kenkeep_data.parse_kenkeep_nodes(sources)
    nodes = _by_orig(graph)
    long_id = "practice-schema3-with-a-very-long-id-that-kenkeep-folds"
    assert long_id in nodes
    assert nodes[long_id]["summary"] == "Folded description that spans two lines."
    assert nodes["map-schema1"]["kind"] == "map"
    assert nodes["map-schema1"]["summary"] == "Old-style summary."


def test_index_skipped_broken_counted_archived_hidden(sources):
    graph = kenkeep_data.parse_kenkeep_nodes(sources)
    nodes = _by_orig(graph)
    assert "map-archived" not in nodes
    assert "index" not in nodes
    assert graph["stats"]["skipped"] == 1


def test_layers_and_codebase_exclusion(sources):
    graph = kenkeep_data.parse_kenkeep_nodes(sources)
    nodes = _by_orig(graph)
    assert nodes["practice-alpha"]["layer"] == "L2"
    assert nodes["map-alpha-code"]["layer"] == "L3"
    assert graph["stats"]["layers"] == {"L1": 2, "L2": 1, "L3": 1}


def test_project_color_from_source_and_tag(sources):
    nodes = _by_orig(kenkeep_data.parse_kenkeep_nodes(sources))
    assert nodes["practice-alpha"]["color"] == "#6366f1"
    # Root node tagged with the project's kenkeep_tag takes its color.
    assert nodes["map-schema1"]["project"] == "Alpha"


def test_links_relates_and_lineage(sources):
    graph = kenkeep_data.parse_kenkeep_nodes(sources)
    classes = sorted(link["class"] for link in graph["links"])
    assert classes == ["lineage", "relates"]
    lineage = next(link for link in graph["links"] if link["class"] == "lineage")
    assert lineage["target"] == "L2:alpha-workspace:practice-alpha"


def test_body_html_escapes_and_drops_generated_blocks(sources):
    nodes = _by_orig(kenkeep_data.parse_kenkeep_nodes(sources))
    html = nodes["practice-schema3-with-a-very-long-id-that-kenkeep-folds"]["body_html"]
    assert "&lt;script&gt;" in html
    assert "<code>code</code>" in html and "<strong>bold</strong>" in html
    assert "<ul><li>one</li><li>two</li></ul>" in html
    assert "Related" not in html


def test_review_lists_only_pending_conflicts(sources):
    graph = kenkeep_data.parse_kenkeep_nodes(sources)
    review = kenkeep_data.parse_kenkeep_review(sources, graph["nodes"])
    assert [c["title"] for c in review["conflicts"]] == ["Proposed rewrite"]
    assert review["conflicts"][0]["target_id"] == "L1:root:map-schema1"


def test_curation_history(sources, monkeypatch):
    monkeypatch.setattr(kenkeep_data, "_git_added_nodes_by_date", lambda days: {})
    graph = kenkeep_data.parse_kenkeep_nodes(sources)
    records = kenkeep_data.parse_kenkeep_curation_history(
        sources, known_ids={n["id"] for n in graph["nodes"]},
        history_path=KK / "curation-history.jsonl")
    assert [r["date"] for r in records] == ["2026-09-02", "2026-09-01"]
    added = records[0]
    assert added["status"] == "added"
    assert added["nodes_added"] == 2  # index and the duplicate are dropped
    assert [i["present"] for i in added["added_nodes"]] == [True, False]
    assert added["pending"] == 4
    assert records[1]["status"] == "ran-empty"


def test_missing_stores_fall_back_to_example(kk_config, tmp_path):
    sources = kenkeep_data.kenkeep_sources(root=tmp_path, agents_dir=tmp_path / "agents")
    assert sources[0].get("example") is True
    graph = kenkeep_data.parse_kenkeep_nodes(sources)
    assert graph["stats"]["example"] is True
    assert graph["stats"]["total"] > 0


def test_no_store_and_no_example(kk_config, tmp_path, monkeypatch):
    monkeypatch.setattr(kenkeep_data, "EXAMPLE_NODES", tmp_path / "none")
    sources = kenkeep_data.kenkeep_sources(root=tmp_path, agents_dir=tmp_path / "agents")
    graph = kenkeep_data.parse_kenkeep_nodes(sources)
    assert graph["nodes"] == []
    assert graph["stats"]["installed"] is False


def test_routes_render():
    import app
    client = TestClient(app.app)
    assert client.get("/memory-map").status_code == 200
    payload = client.get("/api/memory-map").json()
    assert {"nodes", "links", "stats", "review", "curation"} <= payload.keys()
