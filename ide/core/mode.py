"""Host-owned execution mode state for ISyCODE."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from .ide_state import project_state, atomic_write


PLAN = "plan"
CODER = "coder"
MODES = {PLAN, CODER}


@dataclass
class ModeController:
    project_root: Path

    @property
    def path(self) -> Path:
        return project_state(self.project_root) / "mode.json"

    def current(self) -> str:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            mode = value.get("mode")
            return mode if mode in MODES else PLAN
        except (OSError, json.JSONDecodeError):
            return PLAN

    def set(self, mode: str) -> str:
        mode = mode.lower().strip()
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode}; expected plan or coder")
        atomic_write(self.path, json.dumps({"mode": mode}, indent=2) + "\n")
        return mode

    def toggle(self) -> str:
        return self.set(CODER if self.current() == PLAN else PLAN)
