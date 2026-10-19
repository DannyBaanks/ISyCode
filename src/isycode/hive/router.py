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
from typing import Any, Callable

from .types import HiveMessage, MessageAct, Registry, validate_identifier
from .safe_io import checked_path, read_message, create_message


class Router:
    """Periodically routes messages from outbox/ to inbox/."""

    HOP_CAP = 12
    SCAN_INTERVAL = 1.0  # seconds

    def __init__(
        self,
        hive_root: Path,
        registry: Registry | Callable[[], Registry],
        on_message_delivered: Callable[[str, HiveMessage], Any] | None = None,
    ) -> None:
        self.hive_root = hive_root
        self._registry_source = registry
        self.on_message_delivered = on_message_delivered
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_route_at = 0.0

    @property
    def registry(self) -> Registry:
        source = self._registry_source
        return source() if callable(source) else source

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
        checked_path(self.hive_root, agents_dir)
        if not agents_dir.exists():
            return

        for agent_dir in agents_dir.iterdir():
            if agent_dir.is_symlink() or not agent_dir.is_dir():
                continue
            agent_id = agent_dir.name
            if agent_id not in self.registry.agents or self.registry.agents[agent_id].archived:
                continue
            outbox = agent_dir / "outbox"
            if outbox.is_symlink():
                continue
            if not outbox.exists():
                continue

            for msg_file in sorted(outbox.glob("*.json")):
                if msg_file.name.startswith("."):
                    continue
                try:
                    await self._deliver_message(agent_id, msg_file)
                except (ValueError, OSError):
                    # Unsafe recipient paths stay pending, without touching the target.
                    continue

        self._last_route_at = time.time()

    async def _deliver_message(self, from_agent_id: str, msg_file: Path) -> None:
        try:
            validate_identifier(from_agent_id)
            text = read_message(self.hive_root, msg_file)
            msg = HiveMessage.from_jsonl(text)
            if msg.from_agent != from_agent_id or from_agent_id not in self.registry.agents:
                raise ValueError("Hive sender does not match outbox owner")
            if msg_file.name != f"{msg.id}.json":
                raise ValueError("Hive envelope ID does not match filename")
        except (ValueError, TypeError, KeyError, OSError):
            # Keep the source intact for diagnosis; never follow an untrusted path
            # while trying to quarantine it. It cannot be delivered.
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
            if to_agent.archived:
                continue
            validate_identifier(to_agent_id)
            inbox = self.hive_root / "agents" / to_agent_id / "inbox"
            checked_path(self.hive_root, inbox)
            inbox.mkdir(parents=True, exist_ok=True)
            checked_path(self.hive_root, inbox / ".done")
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
            if not (inbox / ".done" / dest.name).exists():
                if create_message(self.hive_root, dest, delivered.to_jsonl() + "\n"):
                    if self.on_message_delivered:
                        try:
                            res = self.on_message_delivered(to_agent_id, delivered)
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception:
                            pass

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
        checked_path(self.hive_root, sent_dir)
        checked_path(self.hive_root, msg_file)
        checked_path(self.hive_root, sent_dir / msg_file.name)
        sent_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(msg_file), str(sent_dir / msg_file.name))
        except Exception:
            pass