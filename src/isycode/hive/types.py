"""Core types for the ISyCode Hive."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, TypedDict


class MessageAct(str, Enum):
    REQUEST = "request"
    INFORM = "inform"
    PROPOSE = "propose"
    QUERY = "query"
    AGREE = "agree"
    REFUSE = "refuse"
    DONE = "done"


@dataclass(frozen=True)
class HiveMessage:
    id: str
    conversation: str
    in_reply_to: str | None
    from_agent: str
    to_agent: str  # agent_id, 'god', or 'broadcast'
    act: MessageAct
    subject: str
    body: str
    hops: int = 0
    requires_reply: bool = False
    needs_human: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["act"] = self.act.value
        d["from"] = d.pop("from_agent")
        d["to"] = d.pop("to_agent")
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HiveMessage:
        d = dict(d)
        d["act"] = MessageAct(d["act"])
        d["from_agent"] = d.pop("from")
        d["to_agent"] = d.pop("to")
        return cls(**d)

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> HiveMessage:
        return cls.from_dict(json.loads(line))


@dataclass(frozen=True)
class HumanQA:
    q: str
    a: str | None = None
    asked_at: str | None = None
    answered_at: str | None = None
    dismissed_at: str | None = None


@dataclass(frozen=True)
class HiveTask:
    id: str
    title: str
    description: str | None = None
    assignee: str | None = None
    status: Literal["todo", "doing", "blocked", "done"] = "todo"
    depends_on: list[str] = field(default_factory=list)
    priority: int = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    human_qa: list[HumanQA] = field(default_factory=list)
    result: str | None = None
    slack: dict[str, str] | None = None
    webhook: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "assignee": self.assignee,
            "status": self.status,
            "dependsOn": self.depends_on,
            "priority": self.priority,
            "createdAt": self.created_at,
            "humanQA": [asdict(q) for q in self.human_qa],
            "result": self.result,
            "slack": self.slack,
            "webhook": self.webhook,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HiveTask:
        d = dict(d)
        d["depends_on"] = d.pop("dependsOn", [])
        d["created_at"] = d.pop("createdAt", d.get("created_at"))
        human_qa_raw = d.pop("humanQA", d.pop("human_qa", []))
        d["human_qa"] = [HumanQA(**q) for q in human_qa_raw]
        d["slack"] = d.get("slack")
        d["webhook"] = d.get("webhook")
        return cls(**d)


@dataclass(frozen=True)
class AgentMeta:
    id: str
    name: str
    provider: str | None = None  # 'claude', 'codex', 'crush', 'qwen', 'grok', 'opencode', 'pi', 'gemini'
    role: str | None = None
    capabilities: list[str] = field(default_factory=list)
    cwd: str = ""
    is_god: bool = False
    is_assistant: bool = False  # prep assistant — send-only, excluded from broadcast


@dataclass(frozen=True)
class RegistryAgent(AgentMeta):
    status: Literal["idle", "working", "blocked", "gone"] = "idle"
    last_seen: float = 0.0
    archived: bool = False
    on_hold: bool = False
    session_id: str | None = None
    cwd_valid: bool = False


@dataclass(frozen=True)
class Registry:
    god_id: str | None = None
    agents: dict[str, RegistryAgent] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "godId": self.god_id,
            "agents": {k: v.__dict__ for k, v in self.agents.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Registry:
        agents = {
            k: RegistryAgent(**v) for k, v in d.get("agents", {}).items()
        }
        return cls(god_id=d.get("godId"), agents=agents)


@dataclass(frozen=True)
class SpawnInjection:
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    seed_prompt: str | None = None
    degraded: str | None = None


class HiveWriteInput(TypedDict):
    tool: str
    toolInput: dict[str, Any]
    cwd: str
    agentId: str
    isGod: bool
    hiveRoot: str
    caseInsensitive: bool


class HiveWriteDecision(TypedDict):
    deny: bool
    reason: str | None