"""Hive router — drains each agent's outbox into recipients' inboxes.

Runs as a background task. Single-writer: only the router commits to the hive git repo.
Agents just write files to their outbox/.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from .types import HiveMessage, MessageAct, Registry


class Router:
    """Periodically routes messages from outbox/ to inbox/."""

    HOP_CAP = 12
    SCAN_INTERVAL = 1.0  # seconds

    def __init__(self, hive_root: Path, registry: Registry) -> None:
        self.hive_root = hive_root
        self.registry = registry
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_route_at = 0.0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def last_route_at(self) -> float:
        return self._last_route_at

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._route_once()
            except Exception as e:
                # Log but don't crash the router
                print(f"[hive router] error: {e}")
            await asyncio.sleep(self.SCAN_INTERVAL)

    async def _route_once(self) -> None:
        """Scan all agents' outbox/ and deliver messages."""
        agents_dir = self.hive_root / "agents"
        if not agents_dir.exists():
            return

        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            agent_id = agent_dir.name
            outbox = agent_dir / "outbox"
            if not outbox.exists():
                continue

            for msg_file in sorted(outbox.glob("*.json")):
                if msg_file.name.startswith("."):
                    continue
                await self._deliver_message(agent_id, msg_file)

            # Also check .sent for any strays
            sent = outbox / ".sent"
            if sent.exists():
                for msg_file in sorted(sent.glob("*.json")):
                    await self._deliver_message(agent_id, msg_file)

        self._last_route_at = time.time()

    async def _deliver_message(self, from_agent_id: str, msg_file: Path) -> None:
        try:
            text = msg_file.read_text(encoding="utf-8")
            msg = HiveMessage.from_jsonl(text)
        except Exception:
            # Malformed → quarantine
            quarantine = self.hive_root / "quarantine"
            quarantine.mkdir(exist_ok=True)
            shutil.move(str(msg_file), str(quarantine / msg_file.name))
            return

        # Check hop limit
        if msg.hops >= self.HOP_CAP:
            self._archive_sent(from_agent_id, msg_file, "hop_limit")
            return

        # Determine recipients
        recipients = self._resolve_recipients(msg)
        if not recipients:
            self._archive_sent(from_agent_id, msg_file, "no_recipient")
            return

        # Deliver to each recipient's inbox
        for to_agent_id in recipients:
            if to_agent_id not in self.registry.agents:
                continue
            to_agent = self.registry.agents[to_agent_id]
            inbox = self.hive_root / "agents" / to_agent_id / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            (inbox / ".done").mkdir(exist_ok=True)

            # Increment hops and write
            delivered = HiveMessage(
                id=msg.id,
                conversation=msg.conversation,
                in_reply_to=msg.in_reply_to,
                from_agent=msg.from_agent,
                to_agent=to_agent_id,
                act=msg.act,
                subject=msg.subject,
                body=msg.body,
                hops=msg.hops + 1,
                requires_reply=msg.requires_reply,
                needs_human=msg.needs_human,
                created_at=msg.created_at,
            )
            dest = inbox / f"{msg.id}.json"
            dest.write_text(delivered.to_jsonl() + "\n", encoding="utf-8")

        # Archive from sender's outbox
        self._archive_sent(from_agent_id, msg_file, "delivered")

    def _resolve_recipients(self, msg: HiveMessage) -> list[str]:
        """Return list of agent_ids that should receive this message."""
        to = msg.to_agent
        if to == "broadcast":
            # All active agents except sender and assistants
            return [
                aid for aid, a in self.registry.agents.items()
                if aid != msg.from_agent and not a.is_assistant and not a.archived
            ]
        if to == "god":
            if self.registry.god_id:
                return [self.registry.god_id]
            return []
        # Direct message
        if to in self.registry.agents:
            return [to]
        return []

    def _archive_sent(self, agent_id: str, msg_file: Path, reason: str) -> None:
        """Move message from outbox/ to outbox/.sent/."""
        agent_dir = self.hive_root / "agents" / agent_id
        sent_dir = agent_dir / "outbox" / ".sent"
        sent_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(msg_file), str(sent_dir / msg_file.name))
        except Exception:
            pass