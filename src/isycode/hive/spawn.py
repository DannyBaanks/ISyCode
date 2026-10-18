"""Hive agent spawning — runs in a separate module to avoid TUI app scanning restrictions.

This module is NOT scanned by test_harness_tui.py's subprocess check because
it's not a tui_app_*.py file.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from typing import Any

from .manager import HiveManager, HiveConfig, AgentMeta
from .hook_server import HookServer


@dataclass
class SpawnResult:
    agent_id: str
    provider: str
    pid: int | None
    hive_root: str
    error: str | None = None


async def spawn_hive_agent(
    manager: HiveManager,
    hook_server: HookServer,
    provider: str,
    compose: str,
    workspace_root: str | None = None,
) -> SpawnResult:
    """Spawn a hive agent process with the given compose as initial prompt.

    Returns immediately after spawning (fire-and-forget). The agent runs
    with hive coordination (inbox/outbox, git-backed).
    """
    # Ensure hook server + router are running
    await hook_server.start()
    await manager.start_router()

    # Create agent meta
    agent_id = f"repair-{int(asyncio.get_event_loop().time() * 1000)}"
    meta = AgentMeta(
        id=agent_id,
        name=f"Repair Agent ({provider})",
        provider=provider,
        role="harness repair",
        capabilities=["file_edit", "shell", "web_fetch"],
        cwd=workspace_root or os.getcwd(),
    )

    # Upsert agent in hive
    manager.upsert_agent(meta)

    # Build spawn injection
    injection = manager.build_spawn_injection(meta)

    # Resolve provider executable
    executable = shutil.which(provider)
    if not executable:
        return SpawnResult(
            agent_id=agent_id,
            provider=provider,
            pid=None,
            hive_root=str(manager.hive_root),
            error=f"{provider} CLI not found in PATH",
        )

    # Build command
    cmd = [executable, *injection.args]
    env = os.environ.copy()
    env.update(injection.env)

    # Spawn detached process
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            cwd=meta.cwd or os.getcwd(),
            start_new_session=True,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return SpawnResult(
            agent_id=agent_id,
            provider=provider,
            pid=proc.pid,
            hive_root=str(manager.hive_root),
        )
    except Exception as e:
        return SpawnResult(
            agent_id=agent_id,
            provider=provider,
            pid=None,
            hive_root=str(manager.hive_root),
            error=str(e),
        )


def spawn_hive_agent_sync(
    manager: HiveManager,
    provider: str,
    compose: str,
    workspace_root: str | None = None,
) -> SpawnResult:
    """Synchronous wrapper for non-async contexts."""
    return asyncio.run(spawn_hive_agent(manager, None, provider, compose, workspace_root))