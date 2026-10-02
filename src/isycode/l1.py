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
import json
import re
import asyncio
import stat
import time
import shutil
import hashlib
import tempfile
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path


REQUIRED_MANIFEST_KEYS = {"id", "version", "description", "capability",
                          "effect_class", "entry"}
VALID_EFFECT_CLASSES = {"READ", "WRITE", "DESTRUCTIVE", "PROCESS",
                        "NETWORK", "PRIVILEGED"}
TOOL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
ENTRY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
MAX_SOURCE_BYTES = 128 * 1024


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
        self.root = Path(root or os.path.expanduser("~/.isycode/l1")).expanduser()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("L1 state root must be a real directory")
        self.staging = self.root / "staging"
        self.registry = self.root / "registry.json"
        self.staging.mkdir(mode=0o700, exist_ok=True)
        if self.staging.is_symlink() or not self.staging.is_dir():
            raise ValueError("L1 staging must be a real directory")
        if os.name == "posix":
            self.root.chmod(0o700)
            self.staging.chmod(0o700)

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
        """Validate every path component before writing an inert candidate."""
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be an object")
        missing = REQUIRED_MANIFEST_KEYS - set(manifest.keys())
        if missing:
            raise ValueError(f"manifest missing keys: {sorted(missing)}")
        if any(not isinstance(manifest.get(key), str) for key in REQUIRED_MANIFEST_KEYS):
            raise ValueError("manifest fields must be strings")
        if manifest["effect_class"] not in VALID_EFFECT_CLASSES:
            raise ValueError(f"unknown effect class: {manifest['effect_class']}")
        tool_id, entry = manifest["id"], manifest["entry"]
        if not TOOL_ID_RE.fullmatch(tool_id) or tool_id in {".", ".."}:
            raise ValueError("tool id must be a simple path-safe identifier")
        if (not ENTRY_RE.fullmatch(entry) or entry in {".", "..", "manifest.json"}
                or "/" in entry or "\\" in entry):
            raise ValueError("entry must be one simple file name inside the candidate")
        if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("tool source must be bounded UTF-8 text")
        cand = ToolCandidate(
            id=tool_id, version=manifest["version"],
            description=manifest["description"], capability=manifest["capability"],
            effect_class=manifest["effect_class"], entry=entry, source=source,
        )
        cdir = self.staging / tool_id
        cdir.mkdir(mode=0o700, exist_ok=False)
        try:
            self._write_new(cdir / "manifest.json", json.dumps(manifest, indent=1))
            self._write_new(cdir / entry, source)
        except BaseException:
            shutil.rmtree(cdir, ignore_errors=True)
            raise
        return cand

    @staticmethod
    def _write_new(path: Path, text: str) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())

    def validate(self, cand: ToolCandidate) -> GateResult:
        """Gate V: manifest schema + entry containment."""
        if (not isinstance(cand.id, str) or not TOOL_ID_RE.fullmatch(cand.id)
                or not isinstance(cand.entry, str) or not ENTRY_RE.fullmatch(cand.entry)
                or cand.entry == "manifest.json"):
            return GateResult("V", False, "tool identity or entry escapes staging")
        if cand.effect_class not in VALID_EFFECT_CLASSES:
            return GateResult("V", False, "unknown effect class")
        cand.gates_passed.append("V")
        return GateResult("V", True, "manifest valid")

    def test(self, cand: ToolCandidate, test_cmd: list[str] | None = None) -> GateResult:
        """Gate T: compile the entry; arbitrary host test commands are not run."""
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
        if test_cmd is not None:
            return GateResult("T", False,
                              "custom test commands are disabled; run probes in the sandbox")
        cand.gates_passed.append("T")
        return GateResult("T", True, "tests pass")

    def probe(self, cand: ToolCandidate, args: dict | None = None) -> GateResult:
        """Run candidate code only in the existing network-denied command sandbox."""
        if os.name != "posix":
            return GateResult("P", False, "verified Bubblewrap/seccomp sandbox is unavailable")
        try:
            directory_fd = os.open(self.staging / cand.id,
                                   os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                                   | getattr(os, "O_NOFOLLOW", 0))
            try:
                directory_info = os.fstat(directory_fd)
                if not stat.S_ISDIR(directory_info.st_mode):
                    return GateResult("P", False, "candidate directory is not a real directory")
                entry_fd = os.open(cand.entry, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                                   dir_fd=directory_fd)
                try:
                    info = os.fstat(entry_fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_SOURCE_BYTES:
                        return GateResult("P", False, "candidate entry is not a private bounded file")
                    with os.fdopen(entry_fd, "r", encoding="utf-8") as stream:
                        entry_fd = -1
                        source = stream.read(MAX_SOURCE_BYTES + 1)
                finally:
                    if entry_fd >= 0:
                        os.close(entry_fd)
            finally:
                os.close(directory_fd)
            if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
                return GateResult("P", False, "candidate source exceeds the probe limit")
            encoded_args = json.dumps(args or {}, ensure_ascii=False)
        except (OSError, UnicodeError, TypeError, ValueError) as exc:
            return GateResult("P", False, f"candidate unavailable ({type(exc).__name__})")
        try:
            from isycode.command_runner import CommandRunOwner, sandbox_executable
            from isycode.approvals import ActionApprovalStore
            from isycode.workspace_authority import WorkspaceAuthority
            sandbox = sandbox_executable()
            if sandbox is None:
                return GateResult("P", False, "verified Bubblewrap/seccomp sandbox is unavailable")
            with tempfile.TemporaryDirectory(prefix="isycode-l1-probe-") as temporary:
                root = Path(temporary)
                (root / "candidate.py").write_text(source, encoding="utf-8")
                code = (
                    "import json\n"
                    "source = open('/workspace/candidate.py', encoding='utf-8').read()\n"
                    "ns = {}\n"
                    "exec(compile(source, 'candidate.py', 'exec'), ns)\n"
                    "fn = ns.get('main') or ns.get('run')\n"
                    f"print(json.dumps(fn({encoded_args}), ensure_ascii=False))\n"
                )
                authority = WorkspaceAuthority(root, state_directory=root / ".authority")
                approvals = ActionApprovalStore()
                runner = CommandRunOwner(root, authority, approvals)
                preview = runner.prepare(["/usr/bin/python3", "-c", code], timeout_s=15)
                # The temp workspace contains only the candidate. The runner's
                # sandbox clears the environment, blocks sockets, limits resources
                # and caps output; no ambient project files or credentials are mounted.
                # Observe only. The temporary workspace is discarded, so there
                # is nothing to promote back into a project tree.
                result = asyncio.run(runner._execute(preview, promote=False))
            if result["exit_code"] != 0:
                return GateResult("P", False, "sandboxed candidate probe failed")
            json.loads(result["output"])
        except (OSError, RuntimeError, TypeError, ValueError, KeyError,
                asyncio.TimeoutError, json.JSONDecodeError) as exc:
            return GateResult("P", False, f"sandboxed probe failed ({type(exc).__name__})")
        cand.gates_passed.append("P")
        return GateResult("P", True, "sandboxed probe returned valid JSON")

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
