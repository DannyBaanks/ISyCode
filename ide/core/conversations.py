"""Durable conversations, separate from the structural resident's technical log."""

from __future__ import annotations

import json
import asyncio
import os
import sqlite3
import uuid
from contextlib import contextmanager, closing
from pathlib import Path

from core.agent.diagnostics import agent_failure
from core.ide_state import project_state
from core.resident.store import utc_now


class ConversationStore:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()
        self.path = project_state(self.workspace) / "conversations.sqlite3"

    @contextmanager
    def _connection(self):
        if self.path.is_symlink() or self.path.parent.resolve() != self.workspace / ".isycode-ide":
            raise ValueError("El historial no puede atravesar enlaces simbólicos.")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=5000;")
            db.execute("PRAGMA journal_mode=WAL;")
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL,
                    updated TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
                    protocol TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS messages (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL
                    REFERENCES sessions(id), role TEXT NOT NULL, content TEXT NOT NULL,
                    turn TEXT NOT NULL DEFAULT '', created TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY, session TEXT NOT NULL REFERENCES sessions(id),
                    status TEXT NOT NULL, pid INTEGER NOT NULL, process_start TEXT NOT NULL,
                    provider TEXT NOT NULL, model TEXT NOT NULL, created TEXT NOT NULL,
                    updated TEXT NOT NULL, protocol TEXT NOT NULL, wire TEXT NOT NULL DEFAULT '[]'
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_running_turn
                    ON turns(session) WHERE status='running';
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    session TEXT NOT NULL REFERENCES sessions(id),
                    turn TEXT NOT NULL REFERENCES turns(id),
                    kind TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL
                );
            """)
            os.chmod(self.path, 0o600)
            yield db

    @staticmethod
    def _process_start(pid: int) -> str:
        try:
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError):
            return ""

    def create(self, title="Nueva conversación", provider="", model="", protocol="") -> str:
        identifier, now = uuid.uuid4().hex, utc_now()
        with self._connection() as db:
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                       (identifier, title[:160], now, now, provider, model, protocol))
        return identifier

    def list(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self._connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM sessions ORDER BY updated DESC")]

    def transcript(self, session: str) -> list[dict]:
        with self._connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM messages WHERE session=? ORDER BY seq", (session,))]

    def wire_history(self, session: str, protocol: str, exclude_turn: str = "") -> list[dict]:
        with self._connection() as db:
            row = db.execute("SELECT id,wire,protocol FROM turns WHERE session=? AND status='completed' ORDER BY created DESC LIMIT 1", (session,)).fetchone()
            if row and row["protocol"] == protocol:
                history = json.loads(row["wire"])
                last = db.execute("SELECT MAX(seq) FROM messages WHERE turn=?", (row["id"],)).fetchone()[0] or 0
                history.extend({"role": item["role"], "content": item["content"]}
                               for item in db.execute("SELECT role,content FROM messages WHERE session=? AND seq>? AND turn!=? AND role IN ('user','assistant') ORDER BY seq", (session, last, exclude_turn)))
                return history
            # A different wire protocol cannot reuse the old provider's tool blocks.
            return [{"role": item["role"], "content": item["content"]}
                    for item in db.execute("SELECT role,content FROM messages WHERE session=? AND turn!=? AND role IN ('user','assistant') ORDER BY seq", (session, exclude_turn))]

    def begin(self, session: str, prompt: str, provider: str, model: str, protocol: str) -> str:
        identifier, now = uuid.uuid4().hex, utc_now()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT id FROM sessions WHERE id=?", (session,)).fetchone():
                raise ValueError("La conversación no existe.")
            active = db.execute("SELECT * FROM turns WHERE session=? AND status='running'", (session,)).fetchone()
            if active:
                if active["process_start"] and self._process_start(active["pid"]) == active["process_start"]:
                    raise ValueError("Esta conversación ya tiene un turno activo.")
                db.execute("UPDATE turns SET status='interrupted',updated=? WHERE id=?", (now, active["id"]))
            db.execute("INSERT INTO turns(id,session,status,pid,process_start,provider,model,created,updated,protocol) VALUES(?,?,'running',?,?,?,?,?,?,?)",
                       (identifier, session, os.getpid(), self._process_start(os.getpid()), provider, model, now, now, protocol))
            db.execute("INSERT INTO messages(session,role,content,turn,created) VALUES(?,?,?,?,?)", (session, "user", prompt, identifier, now))
            db.execute("UPDATE sessions SET title=CASE WHEN title='Nueva conversación' THEN ? ELSE title END,provider=?,model=?,protocol=?,updated=? WHERE id=?",
                       (prompt[:100], provider, model, protocol, now, session))
        return identifier

    def append_response(self, session: str, turn: str, text: str) -> None:
        if not text:
            return
        with self._connection() as db:
            if not db.execute("SELECT id FROM turns WHERE id=? AND session=? AND status='running'", (turn, session)).fetchone():
                raise ValueError("El turno ya terminó.")
            row = db.execute("SELECT seq FROM messages WHERE turn=? AND role='assistant'", (turn,)).fetchone()
            if row:
                db.execute("UPDATE messages SET content=content||? WHERE seq=?", (text, row["seq"]))
            else:
                db.execute("INSERT INTO messages(session,role,content,turn,created) VALUES(?,?,?,?,?)", (session, "assistant", text, turn, utc_now()))

    def finish(self, turn: str, status: str, wire: list[dict] | None = None) -> None:
        if status not in {"completed", "cancelled", "failed", "interrupted"}:
            raise ValueError("Estado de turno inválido.")
        # Current system context is rebuilt on every turn, never saved as history.
        wire = [message for message in (wire or []) if message.get("role") != "system"]
        with self._connection() as db:
            db.execute("UPDATE turns SET status=?,wire=?,updated=? WHERE id=? AND status='running'",
                       (status, json.dumps(wire, ensure_ascii=False), utc_now(), turn))

    def turn_status(self, session: str) -> str:
        with self._connection() as db:
            row = db.execute("SELECT status,pid,process_start FROM turns WHERE session=? ORDER BY created DESC LIMIT 1", (session,)).fetchone()
            if not row:
                return "empty"
            if row["status"] == "running" and self._process_start(row["pid"]) != row["process_start"]:
                return "interrupted"
            return row["status"]

    def append_event(self, session, turn, event):
        if not isinstance(event, dict) or event.get("type") not in {"tool_started", "tool_finished", "proposal_prepared", "proposal_decided", "command_decided", "provider_reasoning", "agent_failed"}:
            raise ValueError("Evento de conversación no válido.")
        payload = json.dumps(event, ensure_ascii=False)
        if len(payload.encode()) > 65536:
            raise ValueError("El evento supera el límite.")
        with self._connection() as db:
            if not db.execute("SELECT id FROM turns WHERE id=? AND session=? AND status='running'", (turn, session)).fetchone():
                raise ValueError("El turno ya terminó.")
            db.execute("INSERT INTO events(session,turn,kind,payload,created) VALUES(?,?,?,?,?)",
                       (session, turn, event["type"], payload, utc_now()))

    def events(self, session):
        with self._connection() as db:
            return [{**dict(row), "payload": json.loads(row["payload"])} for row in
                    db.execute("SELECT * FROM events WHERE session=? ORDER BY seq", (session,))]


class ConversationService:
    """Run one agent turn with durable messages and a cross-process turn lease."""

    def __init__(self, store: ConversationStore):
        self.store = store

    async def run_agent(self, agent, prompt: str):
        config = agent.ctx.provider_config or agent.provider_registry.get_config(agent.ctx.provider_name, agent.ctx.model or None)
        agent.ctx.provider_config = config
        turn = self.store.begin(agent.session_id, prompt, config.name, config.model, config.provider_type)
        status = "failed"
        stream = None
        reasoning, reasoning_size, reasoning_truncated = [], 0, False
        previous_reasoning = getattr(agent, "on_reasoning", None)

        def receive_reasoning(text):
            nonlocal reasoning_size, reasoning_truncated
            if previous_reasoning is not None:
                previous_reasoning(text)
            remaining = max(0, 32_000 - reasoning_size)
            encoded = text.encode("utf-8")
            part = encoded[:remaining].decode("utf-8", errors="ignore")
            if part:
                reasoning.append(part)
            reasoning_size += len(part.encode("utf-8"))
            reasoning_truncated = reasoning_truncated or len(encoded) > remaining

        agent.on_reasoning = receive_reasoning
        previous_callback = agent.tool_execution.on_event
        agent.tool_execution.on_event = lambda event: self.store.append_event(agent.session_id, turn, event)
        try:
            agent.ctx.history = self.store.wire_history(agent.session_id, config.provider_type, exclude_turn=turn)
            stream = agent.run(prompt)
            async for chunk in stream:
                self.store.append_response(agent.session_id, turn, chunk)
                yield chunk
            status = "completed"
        except (asyncio.CancelledError, GeneratorExit):
            status = "cancelled"
            raise
        except Exception as exc:
            try:
                self.store.append_event(agent.session_id, turn, agent_failure(exc, agent))
            except Exception:
                pass  # Preserve the original failure if diagnostic storage fails.
            raise
        finally:
            try:
                if stream is not None:
                    await stream.aclose()
            finally:
                agent.tool_execution.on_event = previous_callback
                agent.on_reasoning = previous_reasoning
                try:
                    if reasoning_size:
                        saved = {"type": "provider_reasoning", "text": "".join(reasoning),
                            "truncated": reasoning_truncated, "provider": config.name,
                            "model": config.model, "status": status}
                        # JSON escaping can expand control characters beyond the
                        # raw UTF-8 cap. Keep the complete event below storage cap.
                        while len(json.dumps(saved, ensure_ascii=False).encode()) > 64_000 and saved["text"]:
                            saved["text"] = saved["text"][:len(saved["text"]) // 2]
                            saved["truncated"] = True
                        try:
                            self.store.append_event(agent.session_id, turn, saved)
                        except Exception:
                            pass  # Optional display history cannot mask turn outcome.
                finally:
                    self.store.finish(turn, status, agent.messages)
