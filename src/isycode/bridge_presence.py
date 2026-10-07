"""Typed, opt-in bridge presence; never connect, claim, send or wake."""
from __future__ import annotations
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.bridge import find_handshake
from isycode.security import ActionRequest


def parse_agents(output: str, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows = []
    for line in output.splitlines():
        match = re.fullmatch(r"\s+([A-Za-z0-9_.-]{1,128})\s+caps=\[.*\]\s+last_hb=(\S+)\s+status=(.*)", line)
        if not match:
            continue
        name, heartbeat, status = match.groups()
        try:
            stamp = datetime.fromisoformat(heartbeat.replace('Z', '+00:00'))
            # Legacy handshake dates without an offset are UTC per its producer.
            if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
            age = (now - stamp).total_seconds()
        except ValueError:
            continue
        # Keep a quiet agent. The registry still says alive long after one
        # heartbeat interval; drop only clock skew and day-old rows.
        if age < -60 or age > 24 * 60 * 60 or status.lower().startswith(('gone', 'stale', 'archived')):
            continue
        # Never render arbitrary progress text or secret-bearing status fields.
        public = status if status in {'alive','working','idle','waiting','busy'} else 'active'
        rows.append({'name':name, 'status':public, 'heartbeat':heartbeat})
    return sorted(rows, key=lambda row: row['name'])


_NAME_PREFIXES = (
    ("copilot_audit", "Copilot audit"),
    ("copilot", "Copilot"),
    ("claude_code", "Claude"),
    ("claude", "Claude"),
    ("chatgpt", "ChatGPT"),
    ("codex", "Codex"),
    ("opencode", "OpenCode"),
    ("grok", "Grok"),
)


def display_name(name: str) -> str:
    """A short name for the sessions line. Machine ids stay off the screen."""
    folded = name.casefold()
    for prefix, label in _NAME_PREFIXES:
        if folded == prefix or folded.startswith(prefix + "_") or folded.startswith(prefix + "-"):
            return label
    if re.search(r"(?:^|[_-])(?:[0-9a-f]{8,}|20\d{6})", name, re.IGNORECASE):
        stem = re.split(r"[_-](?:[0-9a-f]{8,}|20\d{6})", name, maxsplit=1, flags=re.IGNORECASE)[0]
        stem = stem.replace("_", " ").replace("-", " ").strip()
        return stem or "agent"
    return name


def _clip_line(text: str, width: int) -> str:
    from rich.cells import cell_len
    if width <= 0 or cell_len(text) <= width:
        return text
    if width == 1:
        return text[:1]
    cut = text
    while cut and cell_len(cut) > width - 1:
        cut = cut[:-1]
    return cut.rstrip(" ·") + "…"


def presence_line(rows: list[dict], width: int = 0) -> str:
    """One clipped line: how many are online, then readable names."""
    if not rows:
        return "No recent agents"
    parts = []
    seen = set()
    for row in rows:
        label = display_name(str(row.get("name") or "agent"))
        status = str(row.get("status") or "active")
        piece = f"{label} {status}"
        if piece in seen:
            continue
        seen.add(piece)
        parts.append(piece)
    text = " · ".join(parts)
    if len(rows) > 1:
        text = f"Bridge · {len(rows)} online · {text}"
    limit = width if width > 0 else 72
    return _clip_line(text, limit)


class BridgePresenceOwner:
    def __init__(self, root, authority, approvals):
        self.root = Path(root).resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id='bridge_presence')

    def prepare(self):
        script = find_handshake().resolve(strict=True)
        executable = str(Path(sys.executable).resolve(strict=True))
        return ActionRequest('bridge.agents', self.root, 'agents',
            {'executable':executable, 'handshake':str(script),
             'sha256':hashlib.sha256(script.read_bytes()).hexdigest(), 'operation':'agents'},
            execution_owner='bridge_presence')

    def read(self, request, approval):
        if self.prepare() != request:
            return ActionOutcome('Presence unavailable.', 'DENY', None, 'handshake changed after review'), []
        _, decision = self.gate.authorize(request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            return ActionOutcome('Presence unavailable.', 'DENY', None, 'bridge.agents needs its own grant and approval'), []
        try:
            result = subprocess.run([request.parameters['executable'], request.parameters['handshake'], 'agents'],
                capture_output=True, text=True, timeout=10,
                env={'PATH':'/usr/bin:/bin', 'HOME':str(Path.home()), 'LANG':'C.UTF-8'})
            if result.returncode or len(result.stdout) > 512*1024:
                raise ValueError('bounded handshake failed')
            rows = parse_agents(result.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return ActionOutcome('Presence unavailable.', 'ERROR', None, 'no verified handshake response'), []
        text = json.dumps(rows, ensure_ascii=False)
        receipt = ActionReceipt('rcpt_'+secrets.token_hex(8), request.action_id, request.digest,
                                'ALLOW', 'SUCCESS', hashlib.sha256(text.encode()).hexdigest())
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome('Presence unavailable.', 'NOT_VERIFIABLE', None, 'journal unavailable'), []
        return ActionOutcome(text, 'ALLOW', receipt, 'presence snapshot; not authority'), rows
