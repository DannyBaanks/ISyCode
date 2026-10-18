"""HiveManager — the main coordination layer for ISyCode Hive.

Manages the on-disk hive structure (git repo), agent registry, inbox/outbox,
router, and spawn injection for hive-aware agents.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import shlex
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .guard import hive_write_decision, HiveWriteInput
from .router import Router
from .safe_io import checked_path, read_message, create_message
from .types import (
    AgentMeta,
    HiveMessage,
    HiveTask,
    MessageAct,
    Registry,
    RegistryAgent,
    SpawnInjection,
    validate_identifier,
)


# Provider constants
HIVE_AWARE_PROVIDERS = frozenset({"claude"})
HOOK_PROVIDERS = frozenset({"codex", "opencode", "gemini", "pi", "grok", "crush"})
PROXY_PROVIDERS = frozenset({"qwen"})


@dataclass
class HiveConfig:
    """Configuration for the hive."""
    harness_home: Path
    git_user_name: str = "isyco-hive"
    git_user_email: str = "hive@isyco.local"
    auto_commit: bool = True
    router_interval: float = 1.0


class HiveManager:
    """Main hive coordination manager."""

    def __init__(self, config: HiveConfig) -> None:
        self.config = config
        self.hive_root = config.harness_home / "hive"
        self._registry: Registry = Registry()
        self._router: Router | None = None
        self._router_task: asyncio.Task | None = None
        self._git_lock = asyncio.Lock()
        self._started = False

    # ─── Paths ───

    def agent_dir(self, agent_id: str) -> Path:
        validate_identifier(agent_id)
        path = self.hive_root / "agents" / agent_id
        return checked_path(self.hive_root, path)

    def registry_path(self) -> Path:
        return self.hive_root / "registry.json"

    def tasks_path(self) -> Path:
        return self.hive_root / "tasks.json"

    def board_path(self) -> Path:
        return self.hive_root / "board.md"

    def log_path(self) -> Path:
        return self.hive_root / "log.jsonl"

    def sock_path(self) -> str | None:
        """Unix domain socket path for hook bridge."""
        root = self.hive_root
        if not root.exists():
            return None
        if os.name == "nt":
            import hashlib
            id_hash = hashlib.sha1(str(root).encode()).hexdigest()[:12]
            return f"\\\\.\\pipe\\isyco-hive-{id_hash}"
        return str(root / "hooks.sock")

    # ─── Bootstrap ───

    def ensure_hive(self) -> None:
        """Create hive skeleton + git repo if missing. Idempotent."""
        self.hive_root.mkdir(parents=True, exist_ok=True)
        (self.hive_root / "agents").mkdir(exist_ok=True)

        # PROTOCOL.md (authority doc)
        protocol = self.hive_root / "PROTOCOL.md"
        if not protocol.exists():
            protocol.write_text(PROTOCOL_MD, encoding="utf-8")

        # registry.json
        reg_path = self.registry_path()
        if not reg_path.exists():
            self._atomic_write_json(reg_path, {"godId": None, "agents": {}})

        # board.md
        board = self.board_path()
        if not board.exists():
            board.write_text("# Hive Board\n\n_Shared plans live here. The god agent is the scribe._\n", encoding="utf-8")

        # tasks.json
        tasks = self.tasks_path()
        if not tasks.exists():
            self._atomic_write_json(tasks, {"tasks": []})

        # log.jsonl
        log = self.log_path()
        if not log.exists():
            log.write_text("", encoding="utf-8")

        # .gitignore
        gitignore = self.hive_root / ".gitignore"
        want = ["fleet.json", "hooks.sock", "cost-ledger.jsonl", "crashes/", ".DS_Store"]
        lines = []
        if gitignore.exists():
            lines = gitignore.read_text().splitlines()
        missing = [w for w in want if w not in lines]
        if missing:
            gitignore.write_text("\n".join([l for l in lines if l] + missing) + "\n", encoding="utf-8")

        # git repo
        git_dir = self.hive_root / ".git"
        if not git_dir.exists():
            self._git(["init", "-q"])
            self._git_config()
            self._commit("hive: init")

        # Load registry
        self._load_registry()

    def _load_registry(self) -> None:
        try:
            data = json.loads(self.registry_path().read_text(encoding="utf-8"))
            self._registry = Registry.from_dict(data)
        except Exception:
            self._registry = Registry()

    def _save_registry(self) -> None:
        self._atomic_write_json(self.registry_path(), self._registry.to_dict())
        if self.config.auto_commit:
            self._commit("hive: registry update")

    # ─── Registry ───

    @property
    def registry(self) -> Registry:
        return self._registry

    def upsert_agent(self, meta: AgentMeta) -> RegistryAgent:
        """Ensure agent workspace + registry entry. Returns the full RegistryAgent."""
        self.ensure_hive()
        agent_dir = self.agent_dir(meta.id)
        agent_dir.mkdir(parents=True, exist_ok=True)
        checked_path(self.hive_root, agent_dir / "inbox" / ".done")
        checked_path(self.hive_root, agent_dir / "outbox" / ".sent")
        (agent_dir / "inbox" / ".done").mkdir(parents=True, exist_ok=True)
        (agent_dir / "outbox" / ".sent").mkdir(parents=True, exist_ok=True)

        prev = self._registry.agents.get(meta.id)

        # Resolve role
        role = meta.role or prev.role if prev else meta.role
        if meta.is_god:
            role = "god"

        # Write identity.md (refreshed on each spawn)
        for relative in ("identity.md", "memory.md", "cursor.json", "inbox", "inbox/.done", "outbox", "outbox/.sent"):
            checked_path(self.hive_root, agent_dir / relative)
        identity = agent_dir / "identity.md"
        identity.write_text(self._identity_text(meta, role or ""), encoding="utf-8")

        # memory.md
        memory = agent_dir / "memory.md"
        if not memory.exists():
            memory.write_text(
                f"# Memory — {meta.name} ({meta.id})\n\n_Append durable facts, decisions, and context below._\n",
                encoding="utf-8",
            )

        # cursor.json
        cursor = agent_dir / "cursor.json"
        if not cursor.exists():
            self._atomic_write_json(cursor, {"lastProcessed": None})

        # Validate cwd
        cwd_valid = False
        cwd_issue = None
        if meta.cwd:
            try:
                p = Path(meta.cwd).expanduser().resolve(strict=True)
                cwd_valid = p.is_dir()
                cwd_issue = None if cwd_valid else "not-a-directory"
            except Exception:
                cwd_valid = False
                cwd_issue = "missing-dir"

        agent = RegistryAgent(
            id=meta.id,
            name=meta.name,
            provider=meta.provider,
            role=role,
            capabilities=meta.capabilities,
            cwd=str(Path(meta.cwd).expanduser().resolve()) if meta.cwd and cwd_valid else meta.cwd,
            is_god=meta.is_god,
            is_assistant=meta.is_assistant,
            status="idle",
            last_seen=time.time(),
            archived=False,
            on_hold=False,
            session_id=prev.session_id if prev else None,
            cwd_valid=cwd_valid,
        )

        self._registry.agents[meta.id] = agent
        if meta.is_god:
            self._registry = Registry(god_id=meta.id, agents=self._registry.agents)
        self._save_registry()

        self._append_log({"kind": "spawn", "agentId": meta.id, "name": meta.name, "isGod": meta.is_god})
        if not cwd_valid:
            self._append_log({"kind": "cwd_invalid", "agentId": meta.id, "cwd": meta.cwd, "issue": cwd_issue})

        return agent

    def patch_agent_role(self, agent_id: str, role: str) -> dict[str, Any]:
        """Update the durable job string (hire role) without respawning."""
        role = role.strip()
        if not role:
            return {"ok": False, "error": "empty role"}
        agent = self._registry.agents.get(agent_id)
        if not agent:
            return {"ok": False, "error": "unknown agent"}
        # Immutable dataclass → recreate
        new_agent = RegistryAgent(
            **{**agent.__dict__, "role": role}
        )
        self._registry.agents[agent_id] = new_agent
        # Update identity.md
        identity = self.agent_dir(agent_id) / "identity.md"
        identity.write_text(self._identity_text(new_agent, role), encoding="utf-8")
        self._save_registry()
        return {"ok": True}

    def set_agent_status(self, agent_id: str, status: str) -> None:
        agent = self._registry.agents.get(agent_id)
        if agent:
            new_agent = RegistryAgent(**{**agent.__dict__, "status": status, "last_seen": time.time()})
            self._registry.agents[agent_id] = new_agent
            self._save_registry()

    def set_agent_session(self, agent_id: str, session_id: str) -> None:
        agent = self._registry.agents.get(agent_id)
        if agent:
            new_agent = RegistryAgent(**{**agent.__dict__, "session_id": session_id})
            self._registry.agents[agent_id] = new_agent
            self._save_registry()

    def archive_agent(self, agent_id: str) -> None:
        agent = self._registry.agents.get(agent_id)
        if agent:
            new_agent = RegistryAgent(**{**agent.__dict__, "archived": True})
            self._registry.agents[agent_id] = new_agent
            self._save_registry()

    # ─── Router ───

    async def start_router(self) -> None:
        if self._router is None:
            self._router = Router(self.hive_root, lambda: self._registry)
            self._router_task = asyncio.create_task(self._router.start())
        elif self._router_task is None or self._router_task.done():
            self._router_task = asyncio.create_task(self._router.start())

    async def stop_router(self) -> None:
        if self._router:
            await self._router.stop()
            self._router = None
        if self._router_task:
            self._router_task.cancel()
            try:
                await self._router_task
            except asyncio.CancelledError:
                pass
            self._router_task = None

    def last_route_at(self) -> float:
        return self._router.last_route_at() if self._router else 0.0

    # ─── Messaging ───

    def send_message(
        self,
        from_agent: str,
        to_agent: str,
        act: MessageAct,
        subject: str,
        body: str,
        conversation: str | None = None,
        in_reply_to: str | None = None,
        requires_reply: bool = False,
        needs_human: bool = False,
    ) -> HiveMessage:
        """Write a message to the sender's outbox. Router will deliver."""
        self.ensure_hive()
        if from_agent not in self._registry.agents:
            raise ValueError(f"Unknown sender: {from_agent}")

        conv = conversation or f"conv-{uuid.uuid4().hex[:8]}"
        msg = HiveMessage(
            id=f"msg-{uuid.uuid4().hex[:12]}",
            conversation=conv,
            in_reply_to=in_reply_to,
            from_agent=from_agent,
            to_agent=to_agent,
            act=act,
            subject=subject,
            body=body,
            requires_reply=requires_reply,
            needs_human=needs_human,
        )

        outbox = self.agent_dir(from_agent) / "outbox"
        checked_path(self.hive_root, outbox / ".sent")
        outbox.mkdir(parents=True, exist_ok=True)
        (outbox / ".sent").mkdir(exist_ok=True)

        msg_file = outbox / f"{msg.id}.json"
        create_message(self.hive_root, msg_file, msg.to_jsonl() + "\n")

        self._append_log({
            "kind": "message_sent",
            "id": msg.id,
            "from": from_agent,
            "to": to_agent,
            "act": act.value,
            "subject": subject,
        })
        return msg

    def read_inbox(self, agent_id: str, include_done: bool = False) -> list[HiveMessage]:
        """Read all messages in agent's inbox."""
        inbox = self.agent_dir(agent_id) / "inbox"
        if not inbox.exists():
            return []
        msgs = []
        for msg_file in sorted(inbox.glob("*.json")):
            if msg_file.name.startswith("."):
                continue
            try:
                msgs.append(HiveMessage.from_jsonl(read_message(self.hive_root, msg_file)))
            except Exception:
                pass
        if include_done:
            done = inbox / ".done"
            if done.exists():
                for msg_file in sorted(done.glob("*.json")):
                    try:
                        msgs.append(HiveMessage.from_jsonl(read_message(self.hive_root, msg_file)))
                    except Exception:
                        pass
        return msgs

    def read_outbox(self, agent_id: str, include_sent: bool = False) -> list[HiveMessage]:
        """Read all messages in agent's outbox."""
        outbox = self.agent_dir(agent_id) / "outbox"
        if not outbox.exists():
            return []
        msgs = []
        for msg_file in sorted(outbox.glob("*.json")):
            if msg_file.name.startswith("."):
                continue
            try:
                msgs.append(HiveMessage.from_jsonl(read_message(self.hive_root, msg_file)))
            except Exception:
                pass
        if include_sent:
            sent = outbox / ".sent"
            if sent.exists():
                for msg_file in sorted(sent.glob("*.json")):
                    try:
                        msgs.append(HiveMessage.from_jsonl(read_message(self.hive_root, msg_file)))
                    except Exception:
                        pass
        return msgs

    def mark_inbox_read(self, agent_id: str, msg_ids: list[str]) -> None:
        """Move messages from inbox/ to inbox/.done/."""
        inbox = self.agent_dir(agent_id) / "inbox"
        done = inbox / ".done"
        done.mkdir(exist_ok=True)
        for msg_id in msg_ids:
            validate_identifier(msg_id)
            src = checked_path(self.hive_root, inbox / f"{msg_id}.json")
            checked_path(self.hive_root, done)
            if src.exists():
                try:
                    src.rename(done / src.name)
                except Exception:
                    pass

    # ─── Tasks ───

    def create_task(
        self,
        title: str,
        description: str | None = None,
        assignee: str | None = None,
        priority: int = 0,
        depends_on: list[str] | None = None,
    ) -> HiveTask:
        self.ensure_hive()
        task = HiveTask(
            id=f"task-{uuid.uuid4().hex[:12]}",
            title=title,
            description=description,
            assignee=assignee,
            priority=priority,
            depends_on=depends_on or [],
        )
        tasks_data = {"tasks": []}
        try:
            tasks_data = json.loads(self.tasks_path().read_text(encoding="utf-8"))
        except Exception:
            pass
        tasks_data["tasks"].append(task.to_dict())
        self._atomic_write_json(self.tasks_path(), tasks_data)
        if self.config.auto_commit:
            self._commit(f"hive: task {task.id}")
        self._append_log({"kind": "task_created", "taskId": task.id, "title": title})
        return task

    def update_task(self, task_id: str, **kwargs) -> HiveTask | None:
        tasks_data = {"tasks": []}
        try:
            tasks_data = json.loads(self.tasks_path().read_text(encoding="utf-8"))
        except Exception:
            return None
        for i, t in enumerate(tasks_data["tasks"]):
            if t["id"] == task_id:
                for k, v in kwargs.items():
                    if k in t:
                        t[k] = v
                tasks_data["tasks"][i] = t
                break
        else:
            return None
        self._atomic_write_json(self.tasks_path(), tasks_data)
        if self.config.auto_commit:
            self._commit(f"hive: task {task_id}")
        return HiveTask.from_dict(t)

    def list_tasks(self) -> list[HiveTask]:
        try:
            data = json.loads(self.tasks_path().read_text(encoding="utf-8"))
            return [HiveTask.from_dict(t) for t in data.get("tasks", [])]
        except Exception:
            return []

    # ─── Spawn Injection ───

    def build_spawn_injection(self, meta: AgentMeta, extra_writable: list[str] | None = None) -> SpawnInjection:
        """Build provider-specific args + env that make the process hive-aware."""
        provider = (meta.provider or "claude").lower()
        if provider != "claude":
            raise ValueError(f"Hive hooks for {provider} are not supported")
        self.ensure_hive()
        if meta.id not in self.registry.agents:
            raise ValueError("Register the Hive agent before building hook settings")
        agent_dir = self.agent_dir(meta.id)
        settings_path = checked_path(self.hive_root, agent_dir / "settings.json")
        settings_path.write_text(json.dumps(self._hook_settings(meta, str(agent_dir), extra_writable)), encoding="utf-8")
        return SpawnInjection(
            args=["--append-system-prompt", self._injected_prompt(meta, str(agent_dir), str(self.hive_root)),
                  "--settings", str(settings_path)],
            env={"AGENT_ID": meta.id, "AGENT_NAME": meta.name,
                 "HIVE_ROOT": str(self.hive_root), "AGENT_DIR": str(agent_dir),
                 "HIVE_SOCK": self.sock_path() or ""},
            degraded="Coordination hooks only; not an ISyCode execution owner or sandbox.",
        )

    # ─── Hook Settings / Prompts ───

    def _hook_settings(
        self,
        meta: AgentMeta,
        agent_dir: str,
        extra_writable: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate settings.json for Claude Code hooks."""
        sock = self.sock_path()
        shim = self._hook_shim_path()
        writable = self._sandbox_writable_dirs(meta, agent_dir, str(self.hive_root), extra_writable)
        return {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
                        "hooks": [{"type": "command", "command": f"{shim} pre-tool-use"}],
                    }
                ],
                "PostToolUse": [
                    {
                        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
                        "hooks": [{"type": "command", "command": f"{shim} post-tool-use"}],
                    }
                ],
                "Stop": [
                    {
                        "matcher": "",
                        "hooks": [{"type": "command", "command": f"{shim} stop"}],
                    }
                ],
            },
            "permissions": {
                "allow": writable,
                "deny": [str(self.hive_root)],
            },
        }

    def _hook_shim_path(self) -> str:
        """Invoke the installed Python source, with platform-correct shell quoting."""
        args = [sys.executable, str(Path(__file__).with_name("hook_shim.py").resolve())]
        return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)

    def _injected_prompt(self, meta: AgentMeta, agent_dir: str, root: str) -> str:
        """The system prompt injected into the agent at spawn."""
        return f"""# ISyCode Hive Agent Identity

You are **{meta.name}** (id: `{meta.id}`), role: `{meta.role or 'worker'}`.
Provider: `{meta.provider or 'claude'}`.

## Hive Protocol

You are a citizen of the ISyCode Hive. Coordination happens through the
filesystem under `{root}/`:

- **Your workspace**: `{agent_dir}/`
  - `identity.md` — this document (refresh on each spawn)
  - `memory.md` — append durable facts, decisions, context
  - `inbox/` — incoming messages (read + move to `.done/`)
  - `outbox/` — outgoing messages (router delivers to recipients' inbox/)
  - `cursor.json` — tracks last processed message

- **Shared** (read-only for workers, god writes):
  - `board.md` — shared plans (god is sole scribe)
  - `tasks.json` — task ledger (all agents update their own task status)
  - `log.jsonl` — append-only event log
  - `PROTOCOL.md` — full protocol spec (authoritative)

## Communication

**Send a message**: write JSON to `outbox/<msg-id>.json`:
```json
{{
  "id": "msg-<uuid>",
  "conversation": "conv-<uuid>",
  "in_reply_to": null,
  "from": "{meta.id}",
  "to": "<target-agent-id|god|broadcast>",
  "act": "request|inform|propose|query|agree|refuse|done",
  "subject": "Brief subject",
  "body": "Message body",
  "hops": 0,
  "requires_reply": false,
  "needs_human": false,
  "created_at": "ISO8601"
}}
```

**Receive**: read `inbox/*.json`, process, then move to `inbox/.done/`.

**Router** runs every ~1s, drains outbox → recipients' inbox, increments `hops`.

## Human-in-the-loop

- Permission prompts surface in YOUR terminal (ISyCode lane).
- A Hive message or god role cannot approve an ISyCode action.
- `needs_human: true` routes to god for explicit approval.

## Guardrails

- You may ONLY write to: your `memory.md`, `inbox/`, `outbox/`, `tasks.json`.
- God may also write `board.md` and `spawn-requests/`.
- The coordination file guard rejects other Hive paths; it does not sandbox shell commands.
- To reach another agent, write a message to your outbox.

## Your Mission

{meta.role or "Assist with the hive's objectives. Coordinate via messages."}

---
*Generated by ISyCode Hive at {time.time()}*
"""

    def _identity_text(self, meta: AgentMeta, role: str) -> str:
        return f"""# Agent Identity

**Name**: {meta.name}
**ID**: {meta.id}
**Role**: {role or meta.role or 'worker'}
**Provider**: {meta.provider or 'claude'}
**Capabilities**: {', '.join(meta.capabilities) if meta.capabilities else 'none'}
**CWD**: {meta.cwd or 'not set'}
**God**: {'yes' if meta.is_god else 'no'}
**Assistant**: {'yes' if meta.is_assistant else 'no'}

---
*This file is refreshed on every spawn by the hive manager.*
"""

    def _sandbox_writable_dirs(
        self,
        meta: AgentMeta,
        agent_dir: str,
        root: str,
        extra_writable: list[str] | None,
    ) -> list[str]:
        dirs = [agent_dir, root]
        if meta.cwd:
            try:
                p = Path(meta.cwd).expanduser().resolve()
                if p.is_dir():
                    dirs.append(str(p))
            except Exception:
                pass
        if extra_writable:
            dirs.extend(extra_writable)
        return dirs

    # ─── Git ───

    def _git(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.hive_root)] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def _git_config(self) -> None:
        self._git(["config", "user.name", self.config.git_user_name])
        self._git(["config", "user.email", self.config.git_user_email])

    def _commit(self, message: str) -> None:
        try:
            self._git(["add", "-A"])
            self._git(["commit", "-q", "-m", message])
        except Exception:
            pass

    def _atomic_write_json(self, path: Path, data: Any) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _append_log(self, entry: dict[str, Any]) -> None:
        entry["ts"] = time.time()
        self.log_path().write_text(
            self.log_path().read_text(encoding="utf-8") + json.dumps(entry, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # ─── Guard ───

    def check_write(self, tool: str, tool_input: dict[str, Any], cwd: str, agent_id: str) -> dict[str, Any]:
        """Check if a file write is allowed in the hive."""
        agent = self._registry.agents.get(agent_id)
        if agent is None or agent.archived:
            return {"deny": True, "reason": "Unknown or archived Hive agent."}
        inp: HiveWriteInput = {
            "tool": tool,
            "toolInput": tool_input,
            "cwd": cwd,
            "agentId": agent_id,
            "isGod": agent.is_god,
            "hiveRoot": str(self.hive_root),
            "caseInsensitive": os.name == "nt",
        }
        return hive_write_decision(inp)


# ─── Constants ───

PROTOCOL_MD = """# ISyCode Hive Protocol

## Overview

The hive is a git-backed multi-agent coordination layer. Agents communicate
by writing JSON messages to their `outbox/`; a router drains them into
recipients' `inbox/`. All coordination state lives in the hive root.

## Agent Workspace

Each agent has a directory under `agents/<id>/`:

```
agents/<id>/
├── identity.md       # This document (refreshed on spawn)
├── memory.md         # Durable facts/decisions (append only)
├── inbox/            # Incoming messages (read → move to .done/)
│   └── .done/        # Processed messages
├── outbox/           # Outgoing messages (router delivers)
│   └── .sent/        # Delivered messages
├── cursor.json       # {{ "lastProcessed": "<msg-id>" }}
└── settings.json     # Hook config (Claude Code)
```

## Message Format

```json
{{
  "id": "msg-<uuid>",
  "conversation": "conv-<uuid>",
  "in_reply_to": null,
  "from": "<agent-id>",
  "to": "<agent-id|god|broadcast>",
  "act": "request|inform|propose|query|agree|refuse|done",
  "subject": "Brief subject",
  "body": "Message body",
  "hops": 0,
  "requires_reply": false,
  "needs_human": false,
  "created_at": "ISO8601"
}}
```

## Acts

- `request` — needs action from recipient
- `inform` — FYI, no reply needed
- `propose` — suggests a plan, wants agreement
- `query` — asks a question
- `agree` / `refuse` — response to propose
- `done` — task completed

## Router

Runs every ~1 second. For each message in `outbox/`:
1. If `hops >= 12` → archive to `.sent/` with reason "hop_limit"
2. Resolve recipients:
   - `to: "broadcast"` → all active non-assistant agents except sender
   - `to: "god"` → god agent
   - `to: "<id>"` → that agent if exists
3. Write copy to each recipient's `inbox/` with `hops + 1`
4. Archive original to sender's `outbox/.sent/`

## Human-in-the-Loop

- `needs_human: true` → routes to god for explicit approval
- Permission prompts surface in the agent's own ISyCode lane
- Remote approval via `/remote-control` (future)

## Guardrails

File-write tools (Write, Edit, MultiEdit, NotebookEdit) are checked:
- Only allowed targets: own `memory.md`, `inbox/`, `outbox/`, `tasks.json`
- God: also `board.md`, `spawn-requests/`
- Everything else in hive root → DENY with explanatory message

## Tasks

`tasks.json` holds the shared task ledger. Each task:
```json
{{
  "id": "task-<uuid>",
  "title": "...",
  "description": "...",
  "assignee": "<agent-id>",
  "status": "todo|doing|blocked|done",
  "dependsOn": ["task-..."],
  "priority": 0,
  "createdAt": "ISO8601",
  "humanQA": [{{"q": "...", "a": "...", "askedAt": "...", "answeredAt": "..."}}],
  "result": "..."
}}
```

Agents update their own task status. God adds humanQA when a task is blocked.

## Spawn Injection

On spawn, the hive injects:
- `AGENT_ID`, `AGENT_NAME`, `HIVE_ROOT`, `AGENT_DIR`
- `HIVE_SOCK` (Unix socket for hooks)
- Provider-specific args/env:
  - **Claude**: `--append-system-prompt <identity+protocol>` + `--settings <agent-dir/settings.json>`
  - Other CLIs are unsupported; no trust-bypass flags or fake hook configs are emitted.

External process launch is disabled. A coordination hook is not a sandbox,
Workspace Authority grant, Sentinel decision or approval channel. Repairs run
in an ordinary ISyCode conversation using its selected model and execution owners.
"""