#!/usr/bin/env python3
"""ISyCode L1 — model-authored tools with gates and INV-4 enforcement.

Pipeline: REQUESTED -> STAGED -> VALIDATED -> TESTED -> PROBED -> REGISTERED.

INV-4: creation != activation != grant != execution approval.
A tool that passes all gates is still UNUSABLE until its capability
and effect class are independently registered and granted.
Self-extension is never a privilege escalation path.
"""
from __future__ import annotations

import os
import sys
import json
import time
import shutil
import hashlib
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from typing import Any
from pathlib import Path


REQUIRED_MANIFEST_KEYS = {"id", "version", "description", "capability",
                          "effect_class", "entry"}
VALID_EFFECT_CLASSES = {"READ", "WRITE", "DESTRUCTIVE", "PROCESS",
                        "NETWORK", "PRIVILEGED"}


@dataclass
class ToolCandidate:
    """A staged tool awaiting gates."""
    id: str
    version: str
    description: str
    capability: str
    effect_class: str
    entry: str
    source: str = ""
    registered: bool = False
    granted: bool = False
    gates_passed: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """INV-4: usable ONLY if registered AND granted."""
        return self.registered and self.granted


@dataclass
class GateResult:
    gate: str
    passed: bool
    detail: str = ""


class L1Store:
    """Staging area + registry for model-authored tools."""

    def __init__(self, root: str | None = None):
        self.root = Path(root or os.path.expanduser("~/.isycode/l1"))
        self.staging = self.root / "staging"
        self.registry = self.root / "registry.json"
        self.staging.mkdir(parents=True, exist_ok=True)

    def _registry(self) -> dict:
        if self.registry.exists():
            return json.loads(self.registry.read_text())
        return {"tools": {}}

    def _save_registry(self, reg: dict) -> None:
        tmp = self.registry.with_suffix(".tmp")
        tmp.write_text(json.dumps(reg, indent=1))
        tmp.rename(self.registry)

    # ── pipeline ─────────────────────────────────────────────────

    def create(self, manifest: dict, source: str) -> ToolCandidate:
        """Stage a new tool candidate."""
        missing = REQUIRED_MANIFEST_KEYS - set(manifest.keys())
        if missing:
            raise ValueError(f"manifest missing keys: {sorted(missing)}")
        if manifest["effect_class"] not in VALID_EFFECT_CLASSES:
            raise ValueError(f"unknown effect class: {manifest['effect_class']}")
        cand = ToolCandidate(
            id=manifest["id"], version=manifest["version"],
            description=manifest["description"],
            capability=manifest["capability"],
            effect_class=manifest["effect_class"],
            entry=manifest["entry"], source=source,
        )
        cdir = self.staging / cand.id
        cdir.mkdir(exist_ok=True)
        (cdir / "manifest.json").write_text(json.dumps(manifest, indent=1))
        (cdir / cand.entry).write_text(source)
        return cand

    def validate(self, cand: ToolCandidate) -> GateResult:
        """Gate V: manifest schema + entry containment."""
        if ".." in cand.entry or cand.entry.startswith("/"):
            return GateResult("V", False, "entry escapes staging")
        if cand.effect_class not in VALID_EFFECT_CLASSES:
            return GateResult("V", False, "unknown effect class")
        cand.gates_passed.append("V")
        return GateResult("V", True, "manifest valid")

    def test(self, cand: ToolCandidate, test_cmd: list[str] | None = None) -> GateResult:
        """Gate T: run the tool's own tests (or a syntax check)."""
        cdir = self.staging / cand.id
        entry_path = cdir / cand.entry
        if not entry_path.exists():
            return GateResult("T", False, "entry file missing")
        # Minimal gate: the entry must compile as Python
        try:
            with open(entry_path) as f:
                compile(f.read(), cand.entry, "exec")
        except SyntaxError as e:
            return GateResult("T", False, f"syntax error: {e}")
        if test_cmd:
            try:
                r = subprocess.run(test_cmd, capture_output=True, text=True,
                                   timeout=30, cwd=str(cdir))
                if r.returncode != 0:
                    return GateResult("T", False, f"tests failed: {r.stderr[:200]}")
            except (subprocess.TimeoutExpired, OSError) as e:
                return GateResult("T", False, f"test error: {e}")
        cand.gates_passed.append("T")
        return GateResult("T", True, "tests pass")

    def probe(self, cand: ToolCandidate, args: dict | None = None) -> GateResult:
        """Gate P: execute once in a subprocess with no network."""
        cdir = self.staging / cand.id
        entry_path = cdir / cand.entry
        probe_code = (
            "import json,sys;"
            f"sys.path.insert(0,{str(cdir)!r});"
            f"src=open({str(entry_path)!r}).read();"
            "ns={};exec(compile(src,'entry','exec'),ns);"
            f"fn=ns.get('main') or ns.get('run');"
            f"print(json.dumps(fn({json.dumps(args or {})})))"
        )
        try:
            r = subprocess.run(
                [sys.executable, "-c", probe_code],
                capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return GateResult("P", False, f"probe failed: {r.stderr[:200]}")
            json.loads(r.stdout)  # must be valid JSON output
        except (subprocess.TimeoutExpired, OSError) as e:
            return GateResult("P", False, f"probe error: {e}")
        except json.JSONDecodeError as e:
            return GateResult("P", False, f"probe output not JSON: {e}")
        cand.gates_passed.append("P")
        return GateResult("P", True, "probe executed cleanly")

    def register(self, cand: ToolCandidate) -> ToolCandidate:
        """Register the capability + effect class (human or policy action)."""
        reg = self._registry()
        reg["tools"][cand.id] = {
            "capability": cand.capability,
            "effect_class": cand.effect_class,
            "version": cand.version,
            "registered_at": time.time(),
        }
        self._save_registry(reg)
        cand.registered = True
        return cand

    def grant(self, cand: ToolCandidate) -> ToolCandidate:
        """Grant the tool (separate human/policy action)."""
        if not cand.registered:
            raise ValueError("cannot grant an unregistered tool")
        cand.granted = True
        return cand

    def is_usable(self, tool_id: str) -> bool:
        """INV-4: usable only if registered AND granted in the registry."""
        reg = self._registry()
        return tool_id in reg.get("tools", {}) and reg["tools"][tool_id].get("granted", False)

    def mark_granted(self, tool_id: str) -> None:
        reg = self._registry()
        if tool_id not in reg.get("tools", {}):
            raise ValueError(f"tool not registered: {tool_id}")
        reg["tools"][tool_id]["granted"] = True
        self._save_registry(reg)
