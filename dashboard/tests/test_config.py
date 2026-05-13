"""Tests for the config loader."""

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
