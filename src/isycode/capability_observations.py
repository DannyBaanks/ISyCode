"""Durable, content-free observations of model features; never grants authority."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
try:
    import fcntl
except ImportError:
    fcntl = None


def _path():
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return base / "isycode" / "model-capabilities.jsonl"


def observed(provider, model, feature):
    result = None
    try:
        with _path().open() as stream:
            if fcntl is not None:
                fcntl.flock(stream, fcntl.LOCK_SH)
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if (row.get("provider"), row.get("model"), row.get("feature")) == (provider, model, feature) and type(row.get("supported")) is bool:
                    result = row["supported"]
    except (OSError, UnicodeError):
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
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a+") as stream:
            if fcntl is not None:
                fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            prior = stream.read()
            if prior and not prior.endswith("\n"):
                stream.write("\n")
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return True
    except (OSError, UnicodeError):
        return False


def supported_models(feature):
    rows = {}
    try:
        with _path().open() as stream:
            if fcntl is not None:
                fcntl.flock(stream, fcntl.LOCK_SH)
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict) or not isinstance(row.get("provider"), str) or not isinstance(row.get("model"), str):
                    continue
                if row.get("feature") == feature and type(row.get("supported")) is bool:
                    rows[(row.get("provider"), row.get("model"))] = row["supported"]
    except (OSError, UnicodeError):
        pass
    return tuple(sorted(key for key, value in rows.items() if value and all(isinstance(part, str) for part in key)))
