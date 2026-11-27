"""Private IDE state and additive metadata migration; no implicit secret import."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from contextlib import contextmanager, asynccontextmanager


def state_home() -> Path:
    return Path(os.environ.get("ISYCODE_IDE_HOME", str(Path.home() / ".isycode-ide"))).expanduser().resolve()


def project_state(project: str | Path) -> Path:
    path = Path(project).resolve() / ".isycode-ide"
    if path.is_symlink():
        raise ValueError("La carpeta de estado del proyecto no puede ser un enlace simbólico.")
    return path


def atomic_write(path: Path, content: str) -> None:
    """Replace one state file atomically, with restrictive file permissions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        # This is our own transient file, never a pre-existing user artifact.
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def state_lock(path: Path, *, blocking=True):
    """Serialize read-modify-write transactions across GUI/TUI processes."""
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise ValueError("El proyecto tiene otra operación en curso; vuelve a intentarlo cuando termine.") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


@asynccontextmanager
async def async_state_lock(path: Path):
    """Cross-process lock without blocking an asyncio loop awaiting its owner."""
    import asyncio
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "a") as stream:
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def migrate_provider_metadata(source: Path | None = None, destination: Path | None = None) -> dict:
    """Copy legacy provider metadata once; preserve conflicts and every source file.

    Only the documented public fields are imported. Secrets, arbitrary extra
    headers and subscription credentials are deliberately excluded.
    """
    import yaml
    source = Path(source or Path.home() / ".isyvm" / "config.yaml")
    destination = Path(destination or state_home() / "config.yaml")
    if not source.is_file():
        return {"status": "absent", "imported": [], "conflicts": []}
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict) or not isinstance(data.get("providers", {}), dict):
        raise ValueError("La configuración antigua no contiene un mapa de providers.")
    fields = {"provider", "model", "endpoint", "timeout", "max_tokens", "temperature", "auth"}
    with state_lock(destination.with_suffix(".lock")):
        target = yaml.safe_load(destination.read_text()) if destination.exists() else {}
        target = target or {}
        if not isinstance(target, dict) or not isinstance(target.get("providers", {}), dict):
            raise ValueError("La configuración del IDE no es válida; no se reemplazó.")
        providers = target.setdefault("providers", {})
        imported, conflicts = [], []
        from core.agent.providers.registry import validate_config
        for name, config in data.get("providers", {}).items():
            if not isinstance(config, dict):
                conflicts.append(str(name)); continue
            public = {key: value for key, value in config.items() if key in fields}
            try:
                public = validate_config(name, public)
            except (ValueError, TypeError):
                conflicts.append(str(name)); continue
            if name in providers:
                if providers[name] != public:
                    conflicts.append(name)
                continue
            providers[name] = public
            imported.append(name)
        if imported:
            atomic_write(destination, yaml.safe_dump(target, sort_keys=False))
        manifest_path = destination.parent / "migration-providers.json"
        history = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
        record = {"source": str(source.resolve()), "sha256": digest,
                  "destination": str(destination.resolve()), "imported": imported,
                  "conflicts": conflicts, "credentials_imported": False}
        if not any(item.get("sha256") == digest and item.get("conflicts") == conflicts for item in history):
            history.append(record)
            atomic_write(manifest_path, json.dumps(history, ensure_ascii=False, indent=2) + "\n")
        return {"status": "conflict" if conflicts else "imported" if imported else "unchanged",
                "imported": imported, "conflicts": conflicts, "source_sha256": digest}


def migrate_project_metadata(project: str | Path) -> dict:
    """Additive copy of known legacy host state; never copy secrets or grants."""
    project = Path(project).resolve()
    source = project / ".isyvm"
    target = project_state(project)
    if not source.is_dir():
        return {"status": "absent", "imported": [], "conflicts": []}
    if source.is_symlink():
        raise ValueError("El origen de migración no puede ser un enlace simbólico.")
    candidates = [source / "mode.json", source / "todos.jsonl"]
    candidates.extend((source / "plans").glob("*.jsonl"))
    candidates.extend((source / "resident").glob("*.jsonl"))
    candidates.extend((source / "resident" / "sessions").glob("*.jsonl"))
    imported, conflicts, records = [], [], []
    with state_lock(target / "migration.lock"):
        for path in sorted(set(candidates)):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            if path.resolve() != source.resolve() / relative:
                conflicts.append(str(relative)); continue
            destination = target / relative
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if destination.exists():
                if destination.is_symlink() or hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                    conflicts.append(str(relative))
                continue
            if destination.parent.resolve() != target.resolve() / relative.parent:
                conflicts.append(str(relative)); continue
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Exclusive create: migration never replaces an existing file.
            try:
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                conflicts.append(str(relative)); continue
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            imported.append(str(relative))
            records.append({"source": str(path), "destination": str(destination), "sha256": digest})
        manifest = target / "migration-project.json"
        history = json.loads(manifest.read_text()) if manifest.exists() else []
        if records or conflicts:
            history.append({"files": records, "conflicts": conflicts, "resident_kind": "technical-history-not-chat", "credentials_imported": False})
            atomic_write(manifest, json.dumps(history, ensure_ascii=False, indent=2) + "\n")
    return {"status": "conflict" if conflicts else "imported" if imported else "unchanged",
            "imported": imported, "conflicts": conflicts}
