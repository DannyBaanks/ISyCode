"""Durable, content-free observations of model features; never grants authority."""
import json
import os
from contextlib import contextmanager
from isycode.platform_storage import storage, held
from isycode.workspace_setup import ensure_state_root, state_root
from datetime import datetime, timezone


def _path():
    return state_root() / "model-capabilities.jsonl"


@contextmanager
def _read_private():
    path = _path()
    if not path.exists() or not storage.private(path.parent):
        raise ValueError('capability observations are missing or unsafe')
    with held(path.with_suffix('.lock')):
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            if not storage.private(path, fd=stream.fileno()) or os.fstat(stream.fileno()).st_nlink != 1:
                raise ValueError('capability observations are not private')
            yield stream


def observed(provider, model, feature):
    result = None
    try:
        with _read_private() as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if (row.get("provider"), row.get("model"), row.get("feature")) == (provider, model, feature) and type(row.get("supported")) is bool:
                    result = row["supported"]
    except (OSError, UnicodeError, ValueError):
        pass
    return result


def record(provider, model, feature, supported):
    if feature not in {"images", "steer", "chat_available"} or type(supported) is not bool:
        raise ValueError("invalid capability observation")
    if not provider or not model or model == "auto":
        return False  # Auto is not a concrete model identity.
    row = dict(provider=provider, model=model, feature=feature, supported=supported,
               observed_at=datetime.now(timezone.utc).isoformat())
    try:
        path = ensure_state_root() / "model-capabilities.jsonl"
        storage.ensure_directory(path.parent, repair=True)
        with held(path.with_suffix('.lock')):
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND
                         | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), 0o600)
            with os.fdopen(fd, "a+", encoding="utf-8", newline="\n") as stream:
                if not storage.private(path, fd=stream.fileno()) or os.fstat(stream.fileno()).st_nlink != 1:
                    raise ValueError('capability observations are not private')
                stream.seek(0)
                prior = stream.read()
                if prior and not prior.endswith("\n"):
                    stream.write("\n")
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return True
    except (OSError, UnicodeError, ValueError):
        return False


def supported_models(feature):
    rows = {}
    try:
        with _read_private() as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict) or not isinstance(row.get("provider"), str) or not isinstance(row.get("model"), str):
                    continue
                if row.get("feature") == feature and type(row.get("supported")) is bool:
                    rows[(row.get("provider"), row.get("model"))] = row["supported"]
    except (OSError, UnicodeError, ValueError):
        pass
    return tuple(sorted(key for key, value in rows.items() if value and all(isinstance(part, str) for part in key)))
