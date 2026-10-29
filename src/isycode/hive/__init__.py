"""ISyCode Hive — on-disk multi-agent coordination layer.

A git-backed mailbox system where agents exchange messages via inbox/outbox,
coordinated by a router. This experimental mailbox is not an execution owner
or an approval channel. Detached external launch is disabled; repair tasks use
normal ISyCode conversation lanes with their existing Authority/Sentinel gates.
"""
from __future__ import annotations

from .manager import HiveManager, HiveConfig
from .types import (
    HiveMessage,
    HiveTask,
    AgentMeta,
    Registry,
    RegistryAgent,
    MessageAct,
    SpawnInjection,
)
from .router import Router
from .guard import hive_write_decision, HiveWriteInput
from .spawn import spawn_hive_agent, SpawnResult

__all__ = [
    "HiveManager",
    "HiveConfig",
    "HiveMessage",
    "HiveTask",
    "AgentMeta",
    "Registry",
    "RegistryAgent",
    "MessageAct",
    "SpawnInjection",
    "Router",
    "hive_write_decision",
    "HiveWriteInput",
    "spawn_hive_agent",
    "SpawnResult",
]