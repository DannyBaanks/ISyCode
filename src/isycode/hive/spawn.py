"""External Hive launch is unavailable until an execution owner can enforce it.

Coordination hooks are not a sandbox or an Authority grant. TUI repair tasks use
ISyCode's normal conversation owner instead of starting detached external CLIs.
"""
from __future__ import annotations

from dataclasses import dataclass
from .manager import HiveManager
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
    hook_server: HookServer | None,
    provider: str,
    compose: str,
    workspace_root: str | None = None,
) -> SpawnResult:
    """Reject unowned external execution without initializing files or services."""
    return SpawnResult("", provider, None, str(manager.hive_root),
                       "External Hive launch requires a bounded execution owner; use an ISyCode repair conversation.")


def spawn_hive_agent_sync(
    manager: HiveManager,
    provider: str,
    compose: str,
    workspace_root: str | None = None,
) -> SpawnResult:
    """Same fail-closed result for synchronous callers."""
    return SpawnResult("", provider, None, str(manager.hive_root),
                       "External Hive launch requires a bounded execution owner; use an ISyCode repair conversation.")
