"""Tests for crash-safe writes and the locked read-modify-write helpers."""

import json
import threading

import pytest

import data
from storage import CorruptStateError, atomic_write_json, atomic_write_text, load_json_for_update


def test_atomic_write_creates_parents_and_leaves_no_temp(tmp_path):
    target = tmp_path / "nested" / "file.json"
    atomic_write_json(target, {"a": 1})
    assert json.loads(target.read_text()) == {"a": 1}
    assert [p.name for p in target.parent.iterdir()] == ["file.json"]


def test_atomic_write_keeps_permissions(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("old")
    target.chmod(0o600)
    atomic_write_text(target, "new")
    assert target.read_text() == "new"
    assert target.stat().st_mode & 0o777 == 0o600


def test_failed_write_keeps_previous_content(tmp_path):
    target = tmp_path / "f.json"
    target.write_text('{"keep": true}')
    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": object()})
    assert json.loads(target.read_text()) == {"keep": True}
    assert [p.name for p in tmp_path.iterdir()] == ["f.json"]


def test_load_json_for_update_refuses_corrupt_file(tmp_path):
    target = tmp_path / "state.json"
    assert load_json_for_update(target, {}) == {}
    target.write_text("{truncated")
    with pytest.raises(CorruptStateError):
        load_json_for_update(target, {})
    target.write_text("[]")
    with pytest.raises(CorruptStateError):
        load_json_for_update(target, {})


@pytest.fixture()
def actions_file(tmp_path, monkeypatch):
    path = tmp_path / "meeting-actions-status.json"
    monkeypatch.setattr(data, "ACTIONS_STATUS_FILE", path)
    return path


def test_toggle_action_dismissed_round_trip(actions_file):
    assert data.toggle_action_dismissed("abc123abc123") is True
    assert "abc123abc123" in data.load_actions_status()
    assert data.toggle_action_dismissed("abc123abc123") is False
    assert data.load_actions_status() == {}


def test_concurrent_toggles_do_not_drop_updates(actions_file):
    keys = [f"{i:012x}" for i in range(40)]
    threads = [threading.Thread(target=data.toggle_action_dismissed, args=(k,)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(data.load_actions_status()) == set(keys)


def test_toggle_refuses_to_clobber_corrupt_file(actions_file):
    actions_file.write_text("{truncated")
    with pytest.raises(CorruptStateError):
        data.toggle_action_dismissed("abc123abc123")
    assert actions_file.read_text() == "{truncated"


def test_save_memory_bank_file_whitelist(memory_bank):
    data.save_memory_bank_file("weekly-report.md", "hello")
    assert (memory_bank / "weekly-report.md").read_text() == "hello"
    with pytest.raises(ValueError):
        data.save_memory_bank_file("../escape.md", "nope")
