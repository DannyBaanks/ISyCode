import json
import os
import subprocess
import sys

import pytest

from isycode.chat_sessions import ChatSessionStore
from isycode.platform_storage import storage


def _private_session_store(tmp_path):
    root = tmp_path / "sessions"
    storage.ensure_directory(root, repair=True)
    return ChatSessionStore(root)


@pytest.mark.parametrize('content', [
    'Authorization: Bearer fixture-private-token-value',
    json.dumps({'password': 'fixture secret with spaces', 'access_token': 'fixture-token-value'}),
])
def test_export_redacts_quoted_json_credentials(tmp_path, content):
    store = _private_session_store(tmp_path)
    session = store.create()
    session.messages = [{'role': 'user', 'content': content}]
    store.save(session)
    exported = store.export_json(session.session_id)
    assert 'fixture-private-token-value' not in exported
    assert 'fixture secret with spaces' not in exported
    assert 'fixture-token-value' not in exported
    assert '[redacted]' in exported


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='POSIX FIFO fixture')
def test_session_listing_rejects_fifo_without_blocking(tmp_path):
    store = _private_session_store(tmp_path)
    os.mkfifo(store.root / ('a' * 32 + '.json'))
    script = ('from pathlib import Path; from isycode.chat_sessions import ChatSessionStore; '
              f'assert ChatSessionStore(Path({str(store.root)!r})).list_sessions() == []')
    try:
        env = dict(os.environ, PYTHONPATH=str(__import__('pathlib').Path(__file__).resolve().parents[1] / 'src'))
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=2, env=env)
    except subprocess.TimeoutExpired:
        pytest.fail('session listing blocks opening a FIFO before it checks the file type')
    assert result.returncode == 0, result.stderr.decode()
