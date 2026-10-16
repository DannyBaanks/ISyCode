"""Native controls, using only an ephemeral profile and copied test runtime."""
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='native Windows LPAC')


@pytest.fixture
def resources(tmp_path):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    stage = tmp_path / 'stage with spaces'
    stage.mkdir()
    with WindowsSandboxResources.prepare(stage, Path(sys.base_prefix), ()) as prepared:
        yield prepared, prepared.stage_root


def launch(resources, code):
    from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
    prepared, stage = resources
    executable = prepared.runtime_root / 'python.exe'
    return WindowsSandboxProcess.launch(executable, (str(executable), '-I', '-c', code),
        stage, prepared.environment, prepared.profile_sid, 256, prepared.capability_sids)


def test_native_lpac_runs_private_runtime(resources):
    with launch(resources, 'print("native-lpac")') as process:
        assert process.wait(15) == 0
        assert b'native-lpac' in process.read(8192)


def test_native_lpac_preserves_argv(resources):
    from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
    prepared, stage = resources
    exe = prepared.runtime_root / 'python.exe'
    args = ('', 'hola ñ', 'space and trailing\\', 'quote"inside')
    with WindowsSandboxProcess.launch(exe, (str(exe), '-I', '-c',
            'import sys,json; print(json.dumps(sys.argv[1:]))', *args),
            stage, prepared.environment, prepared.profile_sid, 256, prepared.capability_sids) as process:
        assert process.wait(15) == 0
        import json
        assert json.loads(process.read(8192)) == list(args)


def test_native_lpac_loads_standard_native_extensions(resources):
    with launch(resources, 'import ctypes,socket,ssl; print("extensions-loaded")') as process:
        status = process.wait(15)
        output = process.read(8192)
        assert status == 0, output.decode(errors='replace')
        assert b'extensions-loaded' in output


def test_native_lpac_blocks_original_file(resources, tmp_path):
    original = tmp_path / 'outside-secret.txt'
    original.write_text('seeded-secret')
    code = f'from pathlib import Path; p=Path({str(original)!r});\ntry: p.read_text()\nexcept PermissionError: print("denied")\nelse: raise RuntimeError("escaped")'
    with launch(resources, code) as process:
        assert process.wait(15) == 0
        assert b'denied' in process.read(8192)
    assert original.read_text() == 'seeded-secret'


def test_job_terminates_tree(resources):
    import time
    import win32api
    import win32con
    prepared, stage = resources
    # PID communicated through stdout rather than a file open in staging.
    code = 'import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-I","-c","import time; time.sleep(120)"]); print(p.pid,flush=True); time.sleep(120)'
    with launch(resources, code) as process:
        child_pid = int(process.read(128).strip())
        child = win32api.OpenProcess(win32con.SYNCHRONIZE, False, child_pid)
        try:
            process.terminate_tree()
            process.wait(10)
            import win32event
            assert win32event.WaitForSingleObject(child, 10000) == win32event.WAIT_OBJECT_0
        finally:
            child.Close()


def test_job_assignment_failure_never_resumes(resources, monkeypatch):
    import isycode.platform_windows_sandbox_process as native
    import time
    _, stage = resources
    original_update = native._update
    def refuse(*args):
        if args[2] == 0x2000D:
            raise OSError('assignment control')
        return original_update(*args)
    monkeypatch.setattr(native, '_update', refuse)
    with pytest.raises(OSError, match='assignment control'):
        launch(resources, 'from pathlib import Path; Path("escaped.txt").write_text("ran")')
    time.sleep(0.2)
    assert not (stage / 'escaped.txt').exists()


def test_breakaway_refused(resources):
    code = 'import subprocess,sys;\ntry: subprocess.Popen([sys.executable,"-I","-c","print(1)"],creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB)\nexcept PermissionError: print("breakaway-denied")\nelse: raise RuntimeError("escaped job")'
    with launch(resources, code) as process:
        status = process.wait(15)
        output = process.read(8192)
        assert status == 0, output
        assert b'breakaway-denied' in output


def test_process_is_in_job_at_creation_before_resume(resources, monkeypatch):
    import isycode.platform_windows_sandbox_process as native
    import win32job
    captured = {}
    original_job = win32job.CreateJobObject
    original_create = native._create
    def job(*args):
        handle = original_job(*args)
        captured['job'] = handle
        return handle
    def create(*args):
        result = original_create(*args)
        if result:
            pi = args[-1]._obj
            captured['assigned_before_return'] = win32job.IsProcessInJob(pi.hProcess, captured['job'])
        return result
    monkeypatch.setattr(win32job, 'CreateJobObject', job)
    monkeypatch.setattr(native, '_create', create)
    with launch(resources, 'print("atomic-job")') as process:
        assert process.wait(15) == 0
    assert captured['assigned_before_return'] is True


def test_registry_protection_failure_never_resumes(resources, monkeypatch):
    import isycode.platform_windows_sandbox_process as native
    def refuse(*args):
        raise OSError('registry protection control')
    def resumed(*args):
        raise AssertionError('child resumed before registry protection')
    monkeypatch.setattr(native, 'restrict_profile_registry', refuse)
    monkeypatch.setattr(native, '_resume', resumed)
    with pytest.raises(OSError, match='registry protection control'):
        launch(resources, 'from pathlib import Path; Path("registry-failure.txt").write_text("ran")')
    assert not (resources[1] / 'registry-failure.txt').exists()


def test_protected_profile_can_be_reused_without_leaking_thread_identity(resources):
    import win32security as security
    import win32api
    import win32con
    import pywintypes
    for _ in range(2):
        with launch(resources, 'print("repeat-profile")') as process:
            assert process.wait(15) == 0
            assert b'repeat-profile' in process.read(8192)
        with pytest.raises(pywintypes.error) as failure:
            security.OpenThreadToken(win32api.GetCurrentThread(), win32con.TOKEN_QUERY, True)
        assert failure.value.winerror == 1008
