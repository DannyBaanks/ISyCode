"""Run the same native storage contract on each host."""
import os
import subprocess
import sys
import time
import threading

import pytest


def backend():
    from isycode.platform_storage import storage
    return storage


def test_private_directory_and_file_roundtrip(tmp_path):
    store = backend()
    root = tmp_path / 'private'
    store.ensure_directory(root)
    assert store.private(root)
    path = root / 'ñ.txt'
    path.write_bytes('hello ñ\n'.encode())
    store.protect(path)
    assert store.private(path)
    fd = os.open(path, os.O_RDWR | getattr(os, 'O_BINARY', 0))
    try:
        store.lock(fd)
        assert store.private(path, fd=fd)
        assert os.read(fd, 100) == 'hello ñ\n'.encode()
        store.unlock(fd)
    finally:
        os.close(fd)


def test_cross_process_lock_refuses_contender_and_recovers_after_death(tmp_path):
    store = backend()
    root = tmp_path / 'state'
    store.ensure_directory(root)
    path = root / 'lock'
    path.write_bytes(b'')
    code = '''import os, sys, time
from isycode.platform_storage import storage
fd = os.open(sys.argv[1], os.O_RDWR | getattr(os, "O_BINARY", 0))
storage.lock(fd)
print("LOCKED", flush=True)
time.sleep(60)
'''
    # Windows venv python.exe is a redirector: killing it leaves its child alive.
    code = 'import sys; sys.path = ' + repr(sys.path) + '\n' + code
    executable = getattr(sys, '_base_executable', sys.executable)
    holder = subprocess.Popen([executable, '-u', '-c', code, str(path)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    fd = os.open(path, os.O_RDWR | getattr(os, 'O_BINARY', 0))
    try:
        assert holder.stdout.readline().strip() == 'LOCKED'
        with pytest.raises(BlockingIOError):
            store.lock(fd, blocking=False)
        holder.kill()
        holder.wait(timeout=10)
        store.lock(fd, blocking=False)
        store.unlock(fd)
    finally:
        os.close(fd)
        if holder.poll() is None:
            holder.kill()
        holder.communicate(timeout=10)


def test_existing_nonprivate_state_is_rejected(tmp_path):
    store = backend()
    path = tmp_path / 'private'
    store.ensure_directory(path)
    if os.name == 'posix':
        path.chmod(0o755)
    else:
        import win32security as security
        everyone = security.CreateWellKnownSid(security.WinWorldSid, None)
        acl = security.ACL()
        acl.AddAccessAllowedAce(security.ACL_REVISION, 0x1F01FF, everyone)
        security.SetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT,
            security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)
    assert not store.private(path)
    with pytest.raises(ValueError):
        store.ensure_directory(path)


def test_native_effect_and_operation_journals_persist_unicode(tmp_path):
    from isycode.effect_ledger import EffectLedger, EffectCost
    from isycode.turn_control import OperationJournal
    root = tmp_path / 'project'
    root.mkdir()
    ledger = EffectLedger(root, state_directory=tmp_path / 'ledger')
    reservation = ledger.reserve(EffectCost(('ñ.txt',), 0, 9))
    ledger.commit(reservation, applied_paths=('ñ.txt',), deletes=0, churn_bytes=9)
    assert EffectLedger(root, state_directory=tmp_path / 'ledger').status()['churn_bytes'] == 9
    journal = OperationJournal(root, state_directory=tmp_path / 'operations')
    assert journal.lookup('ab' * 32) is None
    assert journal.path.exists()


def test_private_delete_refuses_active_writer_then_deletes_only_target(tmp_path):
    store = backend()
    root = tmp_path / 'state'
    store.ensure_directory(root)
    path, kept = root / 'one', root / 'two'
    path.write_bytes(b'one')
    kept.write_bytes(b'two')
    store.protect(path)
    store.protect(kept)
    fd = os.open(path, os.O_RDWR | getattr(os, 'O_BINARY', 0))
    try:
        store.lock(fd)
        with pytest.raises((BlockingIOError, PermissionError)):
            store.delete_private(path)
    finally:
        store.unlock(fd)
        os.close(fd)
    store.delete_private(path)
    assert not path.exists()
    assert kept.read_bytes() == b'two'


def test_effect_ledger_reentry_does_not_admit_another_thread(tmp_path):
    from isycode.effect_ledger import EffectLedger
    root = tmp_path / 'root'
    root.mkdir()
    book = EffectLedger(root, state_directory=tmp_path / 'ledger')
    started, entered = threading.Event(), threading.Event()
    def contender():
        started.set()
        with book.exclusive():
            entered.set()
    with book.exclusive():
        thread = threading.Thread(target=contender)
        thread.start()
        assert started.wait(2)
        admitted = entered.wait(0.15)
    thread.join(timeout=5)
    assert not admitted
    assert entered.is_set()


def test_private_state_rejects_linked_parent_before_creating_children(tmp_path):
    store = backend()
    outside, link = tmp_path / 'outside', tmp_path / 'link'
    store.ensure_directory(outside)
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                capture_output=True, timeout=10)
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(ValueError):
            store.ensure_directory(link / 'inside')
        assert not (outside / 'inside').exists()
    finally:
        if os.name == 'nt':
            os.rmdir(link)
        else:
            link.unlink()


def test_failed_effect_flush_leaves_no_target_or_temporary(tmp_path, monkeypatch):
    from isycode.effect_fs import apply_file
    def fail_flush(fd):
        raise OSError('injected flush failure')
    monkeypatch.setattr(os, 'fsync', fail_flush)
    with pytest.raises(OSError, match='flush failure'):
        apply_file(tmp_path, 'new.txt', b'new\n', expected=None)
    assert list(tmp_path.iterdir()) == []


def test_edit_during_flush_is_preserved(tmp_path, monkeypatch):
    import hashlib
    from isycode.effect_fs import apply_file
    target = tmp_path / 'user.txt'
    target.write_bytes(b'before')
    flush = os.fsync
    changed = False
    def edit_during_flush(fd):
        nonlocal changed
        if not changed:
            changed = True
            target.write_bytes(b'user edit')
        flush(fd)
    monkeypatch.setattr(os, 'fsync', edit_during_flush)
    with pytest.raises((OSError, ValueError), match='changed'):
        apply_file(tmp_path, 'user.txt', b'after', expected=hashlib.sha256(b'before').hexdigest())
    assert target.read_bytes() == b'user edit'


def test_git_boundary_denies_unavailable_executable(tmp_path, monkeypatch):
    from isycode.action_runtime import GitSystembility
    from isycode.platform_git import git_platform
    from isycode.security import ActionRequest, AuthorityDecision
    monkeypatch.setattr(git_platform, 'discover', lambda directories: None)
    request = ActionRequest('git.status', tmp_path, str(tmp_path),
        {'git': None, 'workspace_root': str(tmp_path), 'repo_path': '.'}, execution_owner='git')
    decision = GitSystembility().evaluate(request, AuthorityDecision(True, 'test', 'test', request.digest))
    assert not decision.passed


def test_legacy_private_child_remains_readable_without_changing_bytes(tmp_path):
    store = backend()
    root = tmp_path / 'sessions'
    store.ensure_directory(root)
    path = root / 'old.json'
    content = b'{"version":1}\n'
    path.write_bytes(content)
    path.chmod(0o644)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    try:
        assert store.private_child(path, fd=fd)
        assert path.read_bytes() == content
    finally:
        os.close(fd)
