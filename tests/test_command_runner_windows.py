"""Native approved-command flow through the shared owner and effect ledger."""
import asyncio
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='native Windows owner')


@pytest.fixture
def owner(tmp_path, monkeypatch, synthetic_windows_storage):
    import isycode.platform_windows_sandbox as native
    monkeypatch.setattr(native, 'NATIVE_ACCEPTED', True)
    from isycode.command_runner import CommandRunOwner
    from isycode.approvals import ActionApprovalStore
    from isycode.workspace_authority import WorkspaceAuthority
    (tmp_path / '.isyroot').write_text('')
    authority = WorkspaceAuthority(tmp_path)
    approvals = ActionApprovalStore()
    authority.set_mode('classic')
    return CommandRunOwner(tmp_path, authority, approvals)


def test_native_owner_keeps_approval_and_promotes_accounted_diff(owner):
    preview = owner.prepare(['python', '-c',
        'from pathlib import Path; Path("result.txt").write_text("native-owned"); print("finished")'])
    assert asyncio.run(owner.run(preview, None)).decision == 'DENY'
    outcome = asyncio.run(owner.run(preview, owner.approvals.issue(preview.request)))
    assert outcome.decision == 'ALLOW', outcome.reason
    result = json.loads(outcome.text)
    assert result['exit_code'] == 0, result['output']
    assert (owner.root / 'result.txt').read_text() == 'native-owned'
    assert result['staging']['promotion']['state'] == 'committed'
    assert outcome.receipt is not None


def test_volume_change_prevents_promotion(owner, synthetic_windows_storage, monkeypatch):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    prepared = []
    prepare = WindowsSandboxResources.prepare
    def capture(*args, **kwargs):
        resource = prepare(*args, **kwargs)
        prepared.append(resource)
        return resource
    monkeypatch.setattr(WindowsSandboxResources, 'prepare', capture)
    preview = owner.prepare(['python', '-c',
        'from pathlib import Path; Path("untrusted.txt").write_text("stage"); print("changed",flush=True)'])
    def change(_):
        for lease in synthetic_windows_storage:
            if not lease.closed:
                lease.changed = True
    try:
        outcome = asyncio.run(owner.run(preview, owner.approvals.issue(preview.request), on_output=change))
        assert outcome.receipt is None
        assert not (owner.root / 'untrusted.txt').exists()
    finally:
        # Restore only this synthetic lease so this test can erase its own
        # retained scratch. Product cleanup remains fail closed.
        for resource in prepared:
            lease = resource.storage_lease
            lease.closed = lease.changed = False
            resource.close()
            lease.close()


def test_native_owner_timeout_kills_tree_and_reports(owner):
    preview = owner.prepare(['python', '-c', 'import time; time.sleep(120)'], timeout_s=1)
    outcome = asyncio.run(owner.run(preview, owner.approvals.issue(preview.request)))
    assert outcome.decision == 'ALLOW', outcome.reason
    assert json.loads(outcome.text)['timed_out'] is True


def test_native_owner_cancellation_never_promotes(owner):
    async def execute():
        preview = owner.prepare(['python', '-c',
            'from pathlib import Path; import time; Path("cancelled.txt").write_text("stage"); print("started",flush=True); time.sleep(120)'])
        event = asyncio.Event()
        def output(_):
            event.set()
        task = asyncio.create_task(owner.run(preview, owner.approvals.issue(preview.request), on_output=output))
        await asyncio.wait_for(event.wait(), 45)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not (owner.root / 'cancelled.txt').exists()
    asyncio.run(execute())


def test_native_owner_never_copies_junction_target(owner):
    import subprocess
    import shutil
    outside = owner.root.parent / ('outside-' + owner.root.name)
    outside.mkdir()
    (outside / 'seed.txt').write_text('seeded-external-control')
    link = owner.root / 'junction'
    command = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(outside)],
        capture_output=True, text=True)
    assert command.returncode == 0, command.stderr
    try:
        preview = owner.prepare(['python', '-c', 'from pathlib import Path; print(Path("junction/seed.txt").read_text())'])
        outcome = asyncio.run(owner.run(preview, owner.approvals.issue(preview.request)))
        assert outcome.decision in {'DENY', 'ERROR'}, outcome.text
        assert (outside / 'seed.txt').read_text() == 'seeded-external-control'
    finally:
        link.rmdir()
        shutil.rmtree(outside)


@pytest.mark.parametrize('cwd', ['C:/Windows', 'C:relative', 'file:stream', 'con', 'folder/NUL.txt', 'LPT1'])
def test_native_owner_rejects_drive_ads_and_device_cwd(owner, cwd):
    with pytest.raises(ValueError, match='cwd'):
        owner.prepare(['python', '-c', 'print(1)'], cwd=cwd)


def test_cleanup_failure_reports_committed_effect_not_start_failure(owner, monkeypatch):
    from isycode.platform_sandbox import sandbox_backend
    real_close = sandbox_backend.close
    async def failed_cleanup(process):
        await real_close(process)
        raise OSError('cleanup control')
    monkeypatch.setattr(sandbox_backend, 'close', failed_cleanup)
    preview = owner.prepare(['python', '-c', 'from pathlib import Path; Path("committed.txt").write_text("committed")'])
    outcome = asyncio.run(owner.run(preview, owner.approvals.issue(preview.request)))
    assert (owner.root / 'committed.txt').read_text() == 'committed'
    assert outcome.decision == 'NOT_VERIFIABLE'
    assert outcome.receipt is None
    result = json.loads(outcome.text)
    assert result['staging']['promotion']['state'] == 'committed'
    assert result['sandbox_cleanup']['state'] == 'uncertain'
