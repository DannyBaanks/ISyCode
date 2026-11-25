from pathlib import Path
import sqlite3

import pytest

from isycode.state_index import StateIndex
from isycode.telegram.state import TelegramStore


def store(tmp_path, profile='personal'):
    return TelegramStore(profile, index=StateIndex(tmp_path / 'state'))


def bound(state, tmp_path, session='a' * 32):
    root = tmp_path / 'project'
    root.mkdir(exist_ok=True)
    state.add_workspace('project', root)
    state.bind_session(session, root)
    return session, root


def test_transactional_update_queue_deduplicates_and_preserves_fifo(tmp_path):
    state = store(tmp_path)
    session, root = bound(state, tmp_path)
    command = {'session_id': session, 'text': 'first'}
    first = state.accept_update(1, 123, command)
    assert first.accepted and first.queue_id
    assert state.accept_update(1, 123, command).duplicate
    state.accept_update(2, 123, {'session_id': session, 'text': 'second'})
    job = state.claim_next()
    assert job.text == 'first' and job.workspace == root
    assert store(tmp_path).claim_next() is None
    state.finish(job.turn_id, 'completed')
    assert state.claim_next().text == 'second'


def test_restart_does_not_replay_running_effects(tmp_path):
    state = store(tmp_path)
    session, _ = bound(state, tmp_path)
    state.accept_update(1, 123, {'session_id': session, 'text': 'command'})
    job = state.claim_next()
    restarted = store(tmp_path)
    restarted.recover()
    assert restarted.queue()[0]['state'] == 'interrupted'
    assert restarted.claim_next() is None
    assert job.turn_id == restarted.queue()[0]['turn_id']


def test_invalid_session_rolls_back_cursor_and_queue(tmp_path):
    state = store(tmp_path)
    with pytest.raises(ValueError):
        state.accept_update(3, 123, {'session_id': 'missing', 'text': 'x'})
    assert state.cursor() == 0 and state.queue() == []
    denied = state.accept_update(3, 999, {'rejected': True})
    assert not denied.accepted and state.cursor() == 4


def test_event_delivery_retry_and_isolation(tmp_path):
    state = store(tmp_path)
    event = state.append_event('run', 'content', {'text': 'api_key=synthetic-secret'})
    pending = state.pending_deliveries()
    assert pending[0].sequence == event
    assert 'synthetic-secret' not in str(pending[0].payload)
    assert store(tmp_path, 'other').pending_deliveries() == []
    state.ack_delivery(pending[0].id, 10)
    assert state.pending_deliveries() == []


def test_cancelled_queue_does_not_run_and_lock_is_exclusive(tmp_path):
    state = store(tmp_path)
    session, _ = bound(state, tmp_path)
    accepted = state.accept_update(1, 123, {'session_id': session, 'text': 'later'})
    assert state.cancel_pending(accepted.queue_id)
    assert state.claim_next() is None
    with state.service_lock():
        with pytest.raises((OSError, ValueError)):
            with store(tmp_path).service_lock():
                pytest.fail('second consumer acquired the lock')


def test_profile_traversal_and_unknown_schema_are_refused(tmp_path):
    with pytest.raises(ValueError):
        store(tmp_path, '../bad')
    state = store(tmp_path)
    with sqlite3.connect(state.path) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError):
        store(tmp_path)


def test_recovery_pauses_followup_without_replaying_interrupted_turn(tmp_path):
    state = store(tmp_path)
    session, _ = bound(state, tmp_path)
    state.accept_update(1, 123, {'session_id': session, 'text': 'uncertain'})
    state.accept_update(2, 123, {'session_id': session, 'text': 'next'})
    first = state.claim_next()
    state.recover()
    assert state.claim_next() is None
    assert state.resume_pending(session)
    assert state.claim_next().text == 'next'
    assert state.queue()[0]['turn_id'] == first.turn_id
    assert state.queue()[0]['state'] == 'interrupted'

def test_failed_update_insert_rolls_back_enqueue(tmp_path):
    state = store(tmp_path)
    session, _ = bound(state, tmp_path)
    with state.db() as db:
        db.execute("CREATE TRIGGER reject_update BEFORE INSERT ON updates BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        state.accept_update(1, 123, {'session_id': session, 'text': 'not committed'})
    assert state.cursor() == 0 and state.queue() == []

def test_event_kind_cannot_be_forged_by_payload(tmp_path):
    state = store(tmp_path)
    state.append_event('run', 'tool.result', {'kind': 'approval', 'text': 'untrusted'})
    assert state.pending_deliveries()[0].payload['kind'] == 'tool.result'

def test_private_db_and_separate_state_roots(tmp_path):
    import os
    state = store(tmp_path)
    state.set_setting('bot_id', 123)
    other = store(tmp_path / 'other')
    assert other.setting('bot_id') is None
    if os.name == 'posix':
        assert state.path.stat().st_mode & 0o077 == 0
        assert state.directory.stat().st_mode & 0o077 == 0
