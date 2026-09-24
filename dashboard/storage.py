"""Crash-safe writes for the files the dashboard owns.

Every JSON sidecar and memory-bank file the dashboard writes goes through
``atomic_write_text``: the content lands in a temp file in the same directory,
is fsynced, then ``os.replace``d over the target. A crash mid-write leaves the
previous file intact instead of a truncated one (a truncated
meeting-actions-status.json used to load as ``{}`` and silently un-dismiss
every item).

``locked(path)`` serializes read-modify-write cycles on one file across the
threads the server uses (handlers run file IO in a thread pool), so two
concurrent toggles cannot both read the old state and drop each other's update.
It is an in-process lock: the dashboard runs as a single uvicorn process and
no automation script writes these files.
"""

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path):
    key = os.path.realpath(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


@contextmanager
def locked(path):
    """Hold the per-file lock for a read-modify-write of ``path``."""
    lock = _lock_for(path)
    with lock:
        yield


def _fsync_dir(directory):
    """Flush a directory entry so a completed rename survives power loss.

    Best-effort: platforms without O_DIRECTORY (Windows) or filesystems that
    refuse to fsync a directory are skipped rather than failing the write.
    """
    flag = getattr(os, "O_DIRECTORY", None)
    if flag is None:
        return
    try:
        fd = os.open(directory, os.O_RDONLY | flag)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(path, text):
    """Replace ``path`` with ``text`` atomically, keeping its permissions.

    Symlinks are followed (the link target is replaced), matching what
    ``Path.write_text`` did before.
    """
    target = Path(os.path.realpath(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = target.stat().st_mode & 0o777
    except FileNotFoundError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    _fsync_dir(target.parent)


def atomic_write_json(path, data, **dump_kwargs):
    """``atomic_write_text`` for a JSON document (``dump_kwargs`` go to json.dumps)."""
    atomic_write_text(path, json.dumps(data, **dump_kwargs))


class CorruptStateError(RuntimeError):
    """A state file exists but cannot be parsed; refusing to overwrite it."""


def load_json_for_update(path, default):
    """Read a JSON state file for a read-modify-write.

    Unlike the page loaders, which degrade to ``default`` on a bad file, this
    raises ``CorruptStateError``: writing ``default`` plus one change back
    over an unreadable file would destroy whatever it held.
    """
    path = Path(path)
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CorruptStateError(f"{path.name} is unreadable; not overwriting it") from exc
    if not isinstance(data, type(default)):
        raise CorruptStateError(f"{path.name} has an unexpected shape; not overwriting it")
    return data
