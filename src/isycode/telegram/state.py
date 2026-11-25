"""Private transactional intake, session bindings, events and delivery receipts."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import uuid

from isycode.chat_sessions import ChatSessionStore
from isycode.platform_storage import storage
from isycode.state_index import get_state_index

ID = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
BOT_TOKEN = re.compile(r'\b[0-9]{5,16}:[A-Za-z0-9_-]{20,}\b')


def clean(value):
    if isinstance(value, str):
        return BOT_TOKEN.sub('[REDACTED BOT TOKEN]', ChatSessionStore._sanitize_text(value))
    if isinstance(value, dict):
        return {str(key): '[REDACTED]' if str(key).lower() in {
            'token', 'bot_token', 'api_key', 'password', 'secret', 'authorization'} else clean(item)
                for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(item) for item in value]
    return value


@dataclass(frozen=True)
class AcceptResult:
    accepted: bool
    duplicate: bool
    cursor: int
    queue_id: str | None = None


@dataclass(frozen=True)
class QueueItem:
    id: str
    session_id: str
    workspace: Path
    turn_id: str
    text: str
    update_id: int
    state: str


@dataclass(frozen=True)
class Delivery:
    id: str
    turn_id: str
    sequence: int
    payload: dict
    attempts: int


class TelegramStore:
    def __init__(self, profile: str, *, index=None):
        if not isinstance(profile, str) or not ID.fullmatch(profile):
            raise ValueError('invalid profile name')
        self.profile = profile
        self.directory = (index or get_state_index()).telegram_path(profile)
        storage.ensure_directory(self.directory)
        self.path = self.directory / 'state.sqlite3'
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR |
                         getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
            storage.protect(self.path)
        with self.db() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in {0, 1}:
                raise ValueError('unsupported Telegram state version')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workspaces (alias TEXT PRIMARY KEY, root TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, root TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS updates (id INTEGER PRIMARY KEY, user INTEGER, disposition TEXT);
                CREATE TABLE IF NOT EXISTS paused_sessions (session TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS queue (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    session TEXT NOT NULL, root TEXT NOT NULL, turn TEXT UNIQUE NOT NULL,
                    text TEXT NOT NULL, update_id INTEGER UNIQUE, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, turn TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    delivered INTEGER NOT NULL DEFAULT 0, message_id INTEGER, retry_at REAL NOT NULL DEFAULT 0);
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def db(self):
        info = self.path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not storage.private(self.directory) or not storage.private(self.path)):
            raise ValueError('unsafe Telegram state file')
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA journal_mode=WAL')
        try:
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def setting(self, key, default=None):
        with self.db() as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        if clean(value) != value or key.lower() in {'token', 'secret', 'password', 'api_key'}:
            raise ValueError('secret material does not belong in Telegram state')
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))

    def add_workspace(self, alias, root):
        if not isinstance(alias, str) or not ID.fullmatch(alias):
            raise ValueError('invalid workspace alias')
        root = Path(root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError('workspace must be a directory')
        with self.db() as db:
            db.execute('INSERT INTO workspaces VALUES (?,?)', (alias, str(root)))

    def workspaces(self):
        with self.db() as db:
            return {row['alias']: Path(row['root']) for row in db.execute('SELECT * FROM workspaces')}

    def bind_session(self, session_id, root):
        if not isinstance(session_id, str) or not re.fullmatch('[a-f0-9]{32}', session_id):
            raise ValueError('invalid native session id')
        root = Path(root).resolve(strict=True)
        with self.db() as db:
            if not db.execute('SELECT 1 FROM workspaces WHERE root=?', (str(root),)).fetchone():
                raise ValueError('workspace is not registered')
            existing = db.execute('SELECT root FROM sessions WHERE id=?', (session_id,)).fetchone()
            if existing and existing[0] != str(root):
                raise ValueError('session is already bound to another workspace')
            db.execute('INSERT OR IGNORE INTO sessions VALUES (?,?)', (session_id, str(root)))

    def sessions(self):
        with self.db() as db:
            return {row['id']: Path(row['root']) for row in db.execute('SELECT * FROM sessions')}

    def cursor(self):
        with self.db() as db:
            return db.execute('SELECT coalesce(max(id)+1,0) FROM updates').fetchone()[0]

    def accept_update(self, update_id, user_id, command):
        if type(update_id) is not int or update_id < 0 or type(user_id) is not int:
            raise ValueError('invalid update identity')
        with self.db() as db:
            if db.execute('SELECT 1 FROM updates WHERE id=?', (update_id,)).fetchone():
                return AcceptResult(False, True, db.execute('SELECT max(id)+1 FROM updates').fetchone()[0])
            accepted = not command.get('rejected', False)
            queue_id = None
            if accepted and command.get('session_id') and 'text' in command:
                session = db.execute('SELECT root FROM sessions WHERE id=?', (command['session_id'],)).fetchone()
                if not session or not isinstance(command['text'], str) or not 0 < len(command['text']) <= 262144:
                    raise ValueError('invalid queue instruction/session')
                queue_id, turn = uuid.uuid4().hex, uuid.uuid4().hex
                db.execute('INSERT INTO queue(id,session,root,turn,text,update_id,state) VALUES(?,?,?,?,?,?,?)',
                           (queue_id, command['session_id'], session[0], turn, clean(command['text']), update_id, 'queued'))
            db.execute('INSERT INTO updates VALUES (?,?,?)', (update_id, user_id, 'accepted' if accepted else 'rejected'))
            return AcceptResult(accepted, False, db.execute('SELECT max(id)+1 FROM updates').fetchone()[0], queue_id)

    def enqueue(self, session_id, text, update_id):
        self.accept_update(update_id, 0, {'session_id': session_id, 'text': text})
        with self.db() as db:
            row = db.execute('SELECT * FROM queue WHERE update_id=?', (update_id,)).fetchone()
            if not row:
                raise ValueError('update did not enqueue a turn')
            return QueueItem(row['id'], row['session'], Path(row['root']), row['turn'], row['text'], row['update_id'], row['state'])

    def queue(self):
        with self.db() as db:
            return [{**dict(row), 'turn_id': row['turn'], 'session_id': row['session'], 'workspace': row['root']}
                    for row in db.execute('SELECT * FROM queue ORDER BY seq')]

    def claim_next(self):
        with self.db() as db:
            row = db.execute("""SELECT * FROM queue q WHERE state='queued' AND NOT EXISTS
                (SELECT 1 FROM queue active WHERE active.root=q.root AND active.state='running')
                AND NOT EXISTS (SELECT 1 FROM paused_sessions p WHERE p.session=q.session)
                ORDER BY seq LIMIT 1""").fetchone()
            if not row:
                return None
            db.execute("UPDATE queue SET state='running' WHERE id=?", (row['id'],))
            return QueueItem(row['id'], row['session'], Path(row['root']), row['turn'], row['text'], row['update_id'], 'running')

    def finish(self, turn_id, state):
        if state not in {'completed', 'failed', 'cancelled', 'interrupted'}:
            raise ValueError('invalid terminal state')
        with self.db() as db:
            if state in {'interrupted', 'cancelled'}:
                db.execute("INSERT OR IGNORE INTO paused_sessions SELECT session FROM queue WHERE turn=? AND state='running'", (turn_id,))
            db.execute('UPDATE queue SET state=? WHERE turn=? AND state=\'running\'', (state, turn_id))

    def recover(self):
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO paused_sessions SELECT session FROM queue WHERE state='running'")
            db.execute("UPDATE queue SET state='interrupted' WHERE state='running'")

    def resume_pending(self, session_id):
        """Explicit continuation only; never requeue an interrupted turn."""
        with self.db() as db:
            return db.execute('DELETE FROM paused_sessions WHERE session=?', (session_id,)).rowcount == 1

    def cancel_pending(self, queue_id):
        with self.db() as db:
            return db.execute("UPDATE queue SET state='cancelled' WHERE id=? AND state='queued'", (queue_id,)).rowcount == 1

    def append_event(self, turn_id, kind, payload):
        if not isinstance(payload, dict) or not isinstance(kind, str) or not ID.fullmatch(kind.replace('.', '_')):
            raise ValueError('invalid event')
        material = json.dumps(clean(payload), ensure_ascii=False, allow_nan=False)
        if len(material.encode()) > 4 * 1024 * 1024:
            raise ValueError('event exceeds the detail budget')
        with self.db() as db:
            return db.execute('INSERT INTO events(turn,kind,payload) VALUES (?,?,?)',
                              (turn_id, kind, material)).lastrowid

    def events(self, turn_id):
        with self.db() as db:
            return [{'sequence': row['id'], 'kind': row['kind'], 'payload': json.loads(row['payload'])}
                    for row in db.execute('SELECT * FROM events WHERE turn=? ORDER BY id', (turn_id,))]

    def pending_deliveries(self):
        with self.db() as db:
            return [Delivery(str(row['id']), row['turn'], row['id'],
                    {**json.loads(row['payload']), 'kind': row['kind']}, row['attempts'])
                    for row in db.execute('SELECT * FROM events WHERE delivered=0 AND retry_at<=? ORDER BY id LIMIT 100', (time.time(),))]

    def ack_delivery(self, identity, telegram_message_id):
        with self.db() as db:
            db.execute('UPDATE events SET delivered=1,message_id=? WHERE id=?', (telegram_message_id, int(identity)))

    def retry_delivery(self, identity, delay):
        with self.db() as db:
            db.execute('UPDATE events SET attempts=attempts+1,retry_at=? WHERE id=?', (time.time() + max(1, delay), int(identity)))

    @contextmanager
    def service_lock(self):
        path = self.directory / 'service.lock'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            if not storage.private(path, fd=fd) or os.fstat(fd).st_nlink != 1:
                raise ValueError('unsafe service lock')
            storage.lock(fd, blocking=False)
            yield
        finally:
            os.close(fd)
