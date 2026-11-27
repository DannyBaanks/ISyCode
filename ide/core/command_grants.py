"""Exact, revocable permissions. A grant never bypasses mode, policy or isolation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from core.ide_state import atomic_write, project_state, state_lock
from core.resident.store import utc_now


@dataclass(frozen=True)
class CommandIdentity:
    workspace: str
    executable: str
    executable_sha256: str
    argv: tuple[str, ...]
    cwd: str
    profile: str

    @property
    def key(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class GrantStore:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.root = project_state(self.workspace)
        self.path = self.root / "command-grants.json"

    def _read(self):
        if self.root.is_symlink() or self.path.is_symlink():
            raise ValueError("Permisos: enlaces simbólicos no admitidos.")
        if not self.path.exists():
            return {}
        if self.path.stat().st_size > 2_000_000:
            raise ValueError("El registro de permisos supera el límite.")
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict):
            raise ValueError("Registro de permisos no válido.")
        for key, value in data.items():
            if not re.fullmatch(r"[0-9a-f]{64}", key) or not isinstance(value, dict) or type(value.get("enabled")) is not bool:
                raise ValueError("Registro de permisos no válido.")
            identity = value.get("identity")
            if not isinstance(identity, dict) or set(identity) != set(CommandIdentity.__dataclass_fields__):
                raise ValueError("Identidad de permiso no válida.")
            if not isinstance(identity["argv"], list) or not all(isinstance(arg, str) for arg in identity["argv"]):
                raise ValueError("Argumentos de permiso no válidos.")
            if any(not isinstance(identity[k], str) for k in identity if k != "argv"):
                raise ValueError("Identidad de permiso no válida.")
            parsed = CommandIdentity(**{**identity, "argv": tuple(identity["argv"])})
            if parsed.key != key or parsed.workspace != str(self.workspace):
                raise ValueError("El permiso no coincide con su proyecto o identidad.")
        return data

    def allowed(self, identity):
        entry = self._read().get(identity.key)
        return bool(entry and entry["enabled"])

    def allow(self, identity):
        if identity.workspace != str(self.workspace):
            raise ValueError("El permiso pertenece a otro proyecto.")
        with state_lock(self.root / "command-grants.lock"):
            records = self._read()
            records[identity.key] = {"identity": asdict(identity), "enabled": True, "created": utc_now()}
            atomic_write(self.path, json.dumps(records, indent=2) + "\n")

    def revoke(self, key):
        with state_lock(self.root / "command-grants.lock"):
            records = self._read()
            if key not in records:
                raise ValueError("El permiso ya no existe.")
            records[key].update(enabled=False, revoked=utc_now())
            atomic_write(self.path, json.dumps(records, indent=2) + "\n")

    def list(self):
        return [{"key": key, **entry} for key, entry in self._read().items()]
