import asyncio
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='native Windows backend')
def test_storage_config_required_even_with_acceptance_flag(monkeypatch):
    import isycode.platform_windows_sandbox as native
    monkeypatch.setattr(native, 'NATIVE_ACCEPTED', True)
    monkeypatch.delenv('ISYCODE_WINDOWS_SANDBOX_STORAGE_CONFIG', raising=False)
    assert native.WindowsSandbox().executable() is None


@pytest.mark.skipif(os.name != 'nt', reason='native Windows backend')
def test_approved_storage_identity_change_never_launches(tmp_path, monkeypatch, synthetic_windows_storage):
    from isycode.platform_windows_sandbox import WindowsSandbox, WindowsSandboxProcess
    backend = WindowsSandbox()
    identity = backend.identity()
    identity['storage']['backing_file_id'] = 'substituted'
    def forbidden(*args, **kwargs): raise AssertionError('must never launch')
    monkeypatch.setattr(WindowsSandboxProcess, 'launch', forbidden)
    with pytest.raises(OSError, match='identity changed'):
        asyncio.run(backend.start(tmp_path, 'runtime/python.exe', ('python', '-c', 'pass'),
                                  '.', (), 10, identity=identity))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != 'nt', reason='native Windows backend')
def test_storage_close_failure_attempts_all_cleanup(monkeypatch):
    from types import SimpleNamespace
    from isycode.platform_windows_sandbox import WindowsSandbox
    backend = WindowsSandbox()
    calls = []
    async def fail_finish(_):
        calls.append('finish')
        raise OSError('changed volume')
    monkeypatch.setattr(backend, 'finish', fail_finish)
    process = SimpleNamespace(raw=SimpleNamespace(close=lambda: calls.append('raw')),
        resources=SimpleNamespace(close=lambda: calls.append('resources')),
        storage_lease=SimpleNamespace(close=lambda: calls.append('lease')))
    with pytest.raises(OSError, match='changed volume'):
        asyncio.run(backend.close(process))
    assert calls == ['finish', 'raw', 'resources', 'lease']


@pytest.mark.skipif(os.name != 'nt', reason='native Windows backend')
def test_native_backend_returns_isolated_stage(tmp_path, monkeypatch, synthetic_windows_storage):
    from isycode.platform_windows_sandbox import WindowsSandbox
    backend = WindowsSandbox()
    (tmp_path / 'input.txt').write_text('original')
    async def execute():
        process = await backend.start(tmp_path, 'runtime/python.exe',
            ('python', '-c', 'from pathlib import Path; Path("output.txt").write_text("isolated")'),
            '.', (), 10, identity=backend.identity())
        try:
            output = bytearray()
            while chunk := await process.stdout.read(8192):
                output.extend(chunk)
            assert await process.wait() == 0, output
            assert (process.staged_root / 'output.txt').read_text() == 'isolated'
            assert not (tmp_path / 'output.txt').exists()
        finally:
            await backend.close(process)
    asyncio.run(execute())


@pytest.mark.skipif(os.name != 'nt', reason='native Windows backend')
def test_native_program_discovery_ignores_path(tmp_path, monkeypatch):
    import shutil
    from isycode.platform_windows_sandbox import WindowsSandbox
    backend = WindowsSandbox()
    installed_non_cpython = [shutil.which(name) for name in ('node', 'bun')]
    monkeypatch.setenv('PATH', str(tmp_path))
    assert backend.resolve_program(tmp_path, 'python') == 'runtime/python.exe'
    for unsupported in ('cmd.exe', 'node', 'bun', *filter(None, installed_non_cpython)):
        with pytest.raises(ValueError, match='explicit CPython runtime only'):
            backend.resolve_program(tmp_path, unsupported)


@pytest.mark.skipif(os.name != 'nt', reason='native Windows backend')
def test_native_exit_259_is_finished_not_still_active(tmp_path, synthetic_windows_storage):
    from isycode.platform_windows_sandbox import WindowsSandbox
    backend = WindowsSandbox()
    async def execute():
        process = await backend.start(tmp_path, 'runtime/python.exe',
            ('python', '-c', 'raise SystemExit(259)'), '.', (), 10, identity=backend.identity())
        try:
            assert process.raw.wait(15) == 259
            assert process.returncode == 259
        finally:
            await backend.close(process)
    asyncio.run(execute())
