"""Tests for the config loader."""

import pytest

from config import load


def test_load_returns_dict():
    cfg = load()
    assert isinstance(cfg, dict)


def test_load_includes_example_projects():
    cfg = load()
    assert "ProjectAlpha" in cfg["project_names"]
    assert cfg["project_colors"]["ProjectAlpha"].startswith("#")


def test_client_projects_set():
    cfg = load()
    assert "ProjectAlpha" in cfg["client_projects"]
    # Internal is marked client: false in the example config.
    assert "Internal" not in cfg["client_projects"]


def test_paths_resolved_absolute():
    cfg = load()
    assert cfg["paths"]["memory_bank"].is_absolute()
    assert cfg["paths"]["agents"].is_absolute()


def _write_projects(tmp_path, monkeypatch, body):
    import config
    (tmp_path / "projects.yml").write_text(body)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    config.load.cache_clear()


def test_archived_projects_hidden_from_views():
    cfg = load()
    assert "ProjectLegacy" in [p["name"] for p in cfg["projects"]]
    assert cfg["archived_projects"] == ["ProjectLegacy"]
    assert "ProjectLegacy" not in cfg["project_names"]
    assert "ProjectLegacy" not in cfg["project_colors"]
    assert "ProjectLegacy" not in cfg["project_github"]
    assert all(p["name"] != "ProjectLegacy" for p in cfg["active_projects"])


def test_categories_and_kenkeep_tags():
    cfg = load()
    assert cfg["project_categories"]["Internal"] == "internal"
    assert cfg["project_categories"]["ProjectAlpha"] == "client"
    assert cfg["kenkeep_tags"]["project-alpha"] == "ProjectAlpha"


def test_legacy_client_boolean_still_works(tmp_path, monkeypatch):
    import config
    _write_projects(tmp_path, monkeypatch, "projects:\n  - name: A\n  - name: B\n    client: false\n  - name: C\n    category: bucket\n")
    try:
        cfg = config.load()
        assert cfg["client_projects"] == {"A"}
        assert cfg["project_categories"] == {"A": "client", "B": "internal", "C": "bucket"}
    finally:
        config.load.cache_clear()


def test_unknown_status_rejected(tmp_path, monkeypatch):
    import config
    _write_projects(tmp_path, monkeypatch, "projects:\n  - name: A\n    status: paused\n")
    try:
        with pytest.raises(ValueError):
            config.load()
    finally:
        config.load.cache_clear()
