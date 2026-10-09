"""Native RTK is optional, keeps original execution and preserves evidence."""
import asyncio
import dataclasses
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest


def test_native_adapter_exists():
    assert importlib.util.find_spec('isycode.rtk_integration'), 'native RTK adapter is missing'


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    from isycode import rtk_integration as rtk
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    binary = tmp_path / 'rtk'
    binary.write_bytes(b'fixture RTK binary')
    binary.chmod(0o755)
    monkeypatch.setattr(rtk, 'discover', lambda: str(binary))
    def cli(identity, args, raw=b''):
        if args == ('--version',):
            return 0, b'rtk 0.51.0\n'
        if args[0] == 'rewrite':
            return 3, b'rtk grep -n needle notes.txt'
        if args[0] == 'pipe':
            return 0, b'notes.txt:1:needle\n'
        raise AssertionError(args)
    monkeypatch.setattr(rtk, '_cli', cli)
    return rtk, binary


def test_off_does_not_detect_or_execute_rtk(adapter, monkeypatch):
    rtk, _ = adapter
    monkeypatch.setattr(rtk, 'discover', lambda: pytest.fail('off must not discover binaries'))
    assert rtk.plan(('grep', '-n', 'needle', 'notes.txt'), '/usr/bin/grep') is None


def test_opt_in_binds_path_hash_version_and_advisory(adapter):
    rtk, binary = adapter
    identity = rtk.Settings().enable()
    plan = rtk.plan(('grep', '-n', 'needle', 'notes.txt'), '/usr/bin/grep')
    assert identity['path'] == str(binary)
    assert identity['sha256'] == hashlib.sha256(binary.read_bytes()).hexdigest()
    assert plan['version'] == 'rtk 0.51.0'
    assert plan['decision'] == 'ask'
    assert plan['strategy'] == 'pipe'
    assert plan['rewrite_argv'] == ('rtk', 'grep', '-n', 'needle', 'notes.txt')


def test_swapped_binary_does_not_inherit_opt_in(adapter):
    rtk, binary = adapter
    rtk.Settings().enable()
    binary.write_bytes(b'another executable')
    with pytest.raises(ValueError, match='changed'):
        rtk.plan(('grep', 'x', 'file'), '/usr/bin/grep')


def test_workspace_program_cannot_become_rtk_authorized(adapter):
    rtk, _ = adapter
    rtk.Settings().enable()
    assert rtk.plan(('./grep', 'x', 'file'), '/workspace/grep') is None


def test_unsupported_command_keeps_native_execution(adapter, monkeypatch):
    rtk, _ = adapter
    rtk.Settings().enable()
    monkeypatch.setattr(rtk, '_cli', lambda *args: (1, b''))
    assert rtk.plan(('echo', 'hello'), '/usr/bin/echo') is None


def test_rewrite_is_data_never_shell_code(adapter, monkeypatch):
    rtk, _ = adapter
    rtk.Settings().enable()
    monkeypatch.setattr(rtk, '_cli', lambda *args: (3, b'rtk grep x file && touch /tmp/escape'))
    with pytest.raises(ValueError, match='rewrite'):
        rtk.plan(('grep', 'x', 'file'), '/usr/bin/grep')


def test_compression_fallback_keeps_original_output_and_exit(adapter, monkeypatch):
    rtk, _ = adapter
    rtk.Settings().enable()
    plan = rtk.plan(('grep', 'needle', 'notes.txt'), '/usr/bin/grep')
    monkeypatch.setattr(rtk, '_cli', lambda *args: (1, b'filter failure'))
    result = {'output': 'original failure', 'exit_code': 7, 'timed_out': False,
              'output_bytes': 16, 'output_truncated': False}
    asyncio.run(rtk.finish(plan, result, b'original failure'))
    assert result['output'] == 'original failure'
    assert result['exit_code'] == 7
    assert result['rtk']['applied'] is False


def test_raw_output_and_result_have_verifiable_private_artifacts(adapter):
    rtk, _ = adapter
    rtk.Settings().enable()
    plan = rtk.plan(('grep', 'needle', 'notes.txt'), '/usr/bin/grep')
    raw = b'notes.txt:1:needle\n' * 10
    result = {'output': raw.decode(), 'exit_code': 1, 'timed_out': False,
              'output_bytes': len(raw), 'output_truncated': False}
    asyncio.run(rtk.finish(plan, result, raw))
    assert len(result['output'].encode()) < len(raw)
    assert result['exit_code'] == 1
    assert result['rtk']['raw_sha256'] == hashlib.sha256(raw).hexdigest()
    evidence = rtk.archive_result(result)
    assert evidence.read_bytes() == json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
    raw_path = evidence.parent / (result['rtk']['raw_sha256'] + '.bin')
    assert raw_path.read_bytes() == raw
    assert raw_path.stat().st_mode & 0o077 == 0


def test_filter_cannot_expand_output(adapter, monkeypatch):
    rtk, _ = adapter
    rtk.Settings().enable()
    plan = rtk.plan(('grep', 'x', 'file'), '/usr/bin/grep')
    monkeypatch.setattr(rtk, '_cli', lambda *args: (0, b'bigger output than original'))
    result = {'output': 'small', 'exit_code': 0, 'timed_out': False,
              'output_bytes': 5, 'output_truncated': False}
    asyncio.run(rtk.finish(plan, result, b'small'))
    assert result['output'] == 'small'
    assert result['rtk']['saved_bytes'] == 0


def test_settings_symlink_is_rejected(adapter, tmp_path):
    rtk, _ = adapter
    settings = rtk.Settings()
    target = tmp_path / 'untrusted.json'
    target.write_text('{"enabled": true}')
    settings.path.symlink_to(target)
    with pytest.raises((ValueError, OSError)):
        settings.load()


@pytest.mark.skipif(shutil.which('bwrap') is None or not Path('/usr/local/bin/rtk').is_file(),
                    reason='real native RTK and bubblewrap are required')
def test_real_owner_filters_once_keeps_exit_and_journal(tmp_path, monkeypatch):
    from isycode import rtk_integration as rtk
    from isycode.approvals import ActionApprovalStore
    from isycode.command_runner import CommandRunOwner, sandbox_executable
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.action_audit import ActionAuditJournal
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    root = tmp_path / 'project'
    root.mkdir()
    (root / '.isyroot').write_text('')
    (root / 'notes.txt').write_text(''.join('needle_' + str(i) + '\n' for i in range(300)))
    authority = WorkspaceAuthority(root)
    authority.set_mode('classic')
    approvals = ActionApprovalStore()
    owner = CommandRunOwner(root, authority, approvals)
    rtk.Settings().enable()
    preview = owner.prepare(['grep', '-H', '-n', 'needle', 'notes.txt'])
    assert preview.request.target == '/usr/bin/grep'
    assert preview.argv == ('grep', '-H', '-n', 'needle', 'notes.txt')
    assert 'rtk' in preview.request.parameters
    result = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert result.decision == 'ALLOW', result.reason
    data = json.loads(result.text)
    assert data['exit_code'] == 0
    assert data['rtk']['saved_bytes'] > 0
    assert ActionAuditJournal(root).verify().status == 'PASS'
    # The requested program's error code survives even though RTK pipe exits 0.
    preview = owner.prepare(['grep', '-n', 'needle', 'missing.txt'])
    result = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert result.decision == 'ALLOW', result.reason
    assert json.loads(result.text)['exit_code'] == 2


def test_raw_artifact_failure_prevents_promotion(tmp_path, monkeypatch):
    from isycode import rtk_integration as rtk
    from isycode.approvals import ActionApprovalStore
    from isycode.command_runner import CommandRunOwner
    from isycode.workspace_authority import WorkspaceAuthority
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    root = tmp_path / 'project'
    root.mkdir()
    (root / '.isyroot').write_text('')
    (root / 'input.txt').write_text('original')
    authority = WorkspaceAuthority(root)
    authority.set_mode('classic')
    approvals = ActionApprovalStore()
    owner = CommandRunOwner(root, authority, approvals)
    # Exercise the real command owner/staging; only RTK's probe is a fixture.
    identity = {'path': '/usr/local/bin/rtk', 'sha256': 'a'*64, 'version': 'rtk 0.51.0',
                'strategy': 'pipe', 'decision': 'ask', 'rewrite_argv': ('rtk', 'proxy', 'python3')}
    monkeypatch.setattr(rtk, 'plan', lambda *args: identity)
    monkeypatch.setattr(rtk, '_artifact', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    preview = owner.prepare(['python3', '-c', "from pathlib import Path; Path('input.txt').write_text('changed')"])
    result = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert result.decision == 'ERROR'
    assert (root / 'input.txt').read_text() == 'original'


def test_enable_rejects_identity_changed_after_display(adapter):
    rtk, binary = adapter
    shown = rtk.Settings().inspect()
    binary.write_bytes(b'replaced after display')
    with pytest.raises(ValueError, match='changed'):
        rtk.Settings().enable(expected=shown)


def test_private_artifacts_reject_hardlinks(adapter, tmp_path):
    rtk, _ = adapter
    raw = b'private output'
    artifact = rtk._artifact(raw, '.bin')
    os.link(artifact, tmp_path / 'alias')
    with pytest.raises(ValueError):
        rtk._artifact(raw, '.bin')


def test_evidence_links_receipt_hash_to_original_bytes(tmp_path, monkeypatch):
    from isycode import rtk_integration as rtk
    from isycode.approvals import ActionApprovalStore
    from isycode.command_runner import CommandRunOwner
    from isycode.workspace_authority import WorkspaceAuthority
    monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'project'; root.mkdir(); (root / '.isyroot').write_text('')
    (root / 'notes.txt').write_text('needle\n' * 80)
    authority = WorkspaceAuthority(root); authority.set_mode('classic')
    approvals = ActionApprovalStore(); owner = CommandRunOwner(root, authority, approvals)
    rtk.Settings().enable()
    preview = owner.prepare(['grep', '-H', '-n', 'needle', 'notes.txt'])
    outcome = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert outcome.decision == 'ALLOW', outcome.reason
    result = json.loads(outcome.text)
    directory = rtk._directory('outputs')
    archived = directory / (outcome.receipt.result_digest + '.json')
    assert archived.read_text() == outcome.text
    raw = directory / (result['rtk']['raw_sha256'] + '.bin')
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == result['rtk']['raw_sha256']
    assert len(raw.read_bytes()) == result['rtk']['captured_bytes']
