"""ISyCode Hive — on-disk multi-agent coordination layer.

A git-backed mailbox system where agents exchange messages via inbox/outbox,
coordinated by a single-committer router. Human-in-the-loop approval surfaces
in the agent's own terminal (ISyCode lane) and can be approved remotely.

Design mirrors isyco-worlds/src/main/hive.ts but in Python, integrated with
ISyCode's lanes, Sentinel, and the harness compose pipeline.
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