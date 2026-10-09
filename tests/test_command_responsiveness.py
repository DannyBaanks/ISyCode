"""Slow command preparation must leave the TUI event loop responsive."""
import asyncio
import threading
from test_command_runner import sandbox


def test_revalidation_does_not_block_event_loop(sandbox, monkeypatch):
    owner, authority, approvals, _, _ = sandbox
    authority.set_mode('classic')
    preview = owner.prepare(['echo', 'hello'])
    ui_thread = threading.get_ident()
    original = owner.prepare
    def prepare(*args, **kwargs):
        assert threading.get_ident() != ui_thread, 'revalidation blocks the TUI thread'
        return original(*args, **kwargs)
    monkeypatch.setattr(owner, 'prepare', prepare)
    result = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert result.decision == 'ALLOW'


def test_staging_does_not_block_event_loop(sandbox, monkeypatch):
    from isycode import command_runner
    owner, authority, approvals, _, _ = sandbox
    authority.set_mode('classic')
    preview = owner.prepare(['echo', 'hello'])
    ui_thread = threading.get_ident()
    original = command_runner.prepare_staging
    def prepare(*args, **kwargs):
        assert threading.get_ident() != ui_thread, 'staging blocks the TUI thread'
        return original(*args, **kwargs)
    monkeypatch.setattr(command_runner, 'prepare_staging', prepare)
    result = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert result.decision == 'ALLOW'


def test_cancelled_copy_finishes_then_cleans_staging(sandbox, monkeypatch):
    from isycode import command_runner
    owner, authority, approvals, _, _ = sandbox
    authority.set_mode('classic')
    preview = owner.prepare(['echo', 'hello'])
    started = threading.Event()
    release = threading.Event()
    copies = []
    original = command_runner.prepare_staging
    def prepare(*args, **kwargs):
        started.set()
        assert release.wait(3)
        result = original(*args, **kwargs)
        copies.append(result.root)
        return result
    monkeypatch.setattr(command_runner, 'prepare_staging', prepare)
    async def check():
        task = asyncio.create_task(owner.run(preview, approvals.issue(preview.request)))
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done()
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('cancelled command proceeded')
    asyncio.run(check())
    assert copies and all(not path.exists() for path in copies)
