"""Persistent switches for implemented runtime tools; never register schema-only tools."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from core.ide_state import atomic_write, project_state, state_lock


class ToolSettings:
    def __init__(self, workspace: str | Path):
        self.path = project_state(workspace) / "tools.json"

    def _load(self):
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict) or any(not isinstance(value, bool) for value in data.values()):
            raise ValueError("La configuración de herramientas no es válida.")
        return data

    def available(self, name):
        if name == "run_command":
            from core.runtime.linux import installation_status
            return installation_status()["installed"]
        # Legacy Python interpreter execution is intentionally unavailable.
        return name in {"read", "write", "edit", "project_tree", "glob", "grep", "verify", "resident_query", "resident_scan"}

    def enabled(self, name):
        return self.available(name) and self._load().get(name, True)

    def set_enabled(self, name, enabled):
        if not self.available(name):
            raise ValueError("Esta herramienta no tiene un runtime habilitado.")
        with state_lock(self.path.with_suffix(".lock")):
            values = self._load()
            values[name] = bool(enabled)
            atomic_write(self.path, json.dumps(values, indent=2) + "\n")

    def catalog(self):
        from core.agent.run import AVAILABLE_TOOLS
        return [{**copy.deepcopy(tool["function"]), "builtin": True,
                 "available": self.available(tool["function"]["name"]),
                 "enabled": self.enabled(tool["function"]["name"])} for tool in AVAILABLE_TOOLS]
