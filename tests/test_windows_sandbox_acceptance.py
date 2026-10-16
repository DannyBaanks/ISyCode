"""Adversarial controls with OS witnesses; no product policy bypass."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='native Windows acceptance')


@pytest.fixture
def resources(tmp_path):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    source = tmp_path / 'source'
    source.mkdir()
    with WindowsSandboxResources.prepare(source, Path(sys.base_prefix), ()) as prepared:
        yield prepared


def test_owner_death_kills_job_without_cooperative_shutdown(resources):
    import json
    import win32api
    import win32con
    import win32event
    payload = {'exe': str(resources.runtime_root / 'python.exe'),
        'cwd': str(resources.stage_root), 'env': resources.environment,
        'sid': resources.profile_sid.hex(), 'caps': [sid.hex() for sid in resources.capability_sids]}
    code = '''import json,sys,os,time
from pathlib import Path
from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
p=json.load(sys.stdin); x=Path(p['exe'])
child=WindowsSandboxProcess.launch(x,(str(x),'-I','-c','import time;time.sleep(120)'),
    Path(p['cwd']),p['env'],bytes.fromhex(p['sid']),256,tuple(bytes.fromhex(v) for v in p['caps']))
print(child.pid,flush=True)
time.sleep(1)
os._exit(0)
'''
    owner = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        owner.stdin.write(json.dumps(payload))
        owner.stdin.close()
        pid = int(owner.stdout.readline().strip())
        child = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
        try:
            assert owner.wait(15) == 0
            assert win32event.WaitForSingleObject(child, 10000) == win32event.WAIT_OBJECT_0
        finally:
            child.Close()
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(10)
        owner.stdout.close()
        owner.stderr.close()


def test_junction_source_is_rejected_before_copy(tmp_path):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    outside = tmp_path / 'outside'
    outside.mkdir()
    source = tmp_path / 'source'
    source.mkdir()
    link = source / 'junction'
    command = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(outside)],
        capture_output=True, text=True)
    assert command.returncode == 0, command.stderr
    try:
        with pytest.raises(ValueError, match='reparse'):
            WindowsSandboxResources.prepare(source, Path(sys.base_prefix), ())
    finally:
        link.rmdir()


def test_runtime_digest_mismatch_refuses_execution(tmp_path):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    with pytest.raises(ValueError, match='runtime changed'):
        WindowsSandboxResources.prepare(tmp_path, Path(sys.base_prefix), (), '0' * 64)


@pytest.mark.parametrize('relative', ['../escape', 'C:/outside', 'file:stream', 'folder\\escape'])
def test_invalid_mask_cannot_escape_scratch(tmp_path, relative):
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    with pytest.raises(ValueError, match='mask'):
        WindowsSandboxResources.prepare(tmp_path, Path(sys.base_prefix), ((relative, False),))


@pytest.mark.xfail(strict=True, reason='Windows per-file execution limit is not implemented; native activation is blocked')
def test_execution_file_budget_blocks_513_mib(resources):
    import shutil
    from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
    if shutil.disk_usage(resources.scratch_root).free < (513 * 1024 ** 2 + 1024 ** 3):
        pytest.skip('bounded allocation control preserves 1 GiB free; NOT_DEMONSTRATED')
    exe = resources.runtime_root / 'python.exe'
    code = 'from pathlib import Path; f=Path("budget.bin").open("wb"); chunk=b"x"*1048576;\nfor _ in range(513): f.write(chunk)\nf.close()'
    with WindowsSandboxProcess.launch(exe, (str(exe), '-I', '-c', code),
            resources.stage_root, resources.environment, resources.profile_sid,
            256, resources.capability_sids) as process:
        status = process.wait(30)
    size = (resources.stage_root / 'budget.bin').stat().st_size
    print('budget-control', {'exit_code': status, 'file_bytes': size,
                             'limit_bytes': 512 * 1024 ** 2}, flush=True)
    assert status != 0 and size <= 512 * 1024 ** 2, (status, size)


def test_missing_budget_keeps_product_native_backend_unavailable():
    from isycode.platform_windows_sandbox import WindowsSandbox
    assert WindowsSandbox().executable() is None
