"""Private provider metadata uses native storage rather than optional POSIX locks."""
import json,os,subprocess,sys
from pathlib import Path
import pytest
from isycode.platform_storage import storage


@pytest.fixture(autouse=True)
def hermetic_legacy_state(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME',str(tmp_path/'legacy-state'))


def test_observations_use_native_state_and_private_files(tmp_path,monkeypatch):
    from isycode import capability_observations as c
    root=tmp_path/'state';monkeypatch.setenv('ISYCODE_STATE_HOME',str(root))
    assert c.record('parity','modelo-ñ','images',True)
    assert c._path()==root/'model-capabilities.jsonl'
    assert storage.private(root) and storage.private(c._path())
    assert c.observed('parity','modelo-ñ','images') is True


def test_preferences_directory_and_file_are_private(tmp_path,monkeypatch):
    from isycode.providers import _write_preferences,_preferences_path
    monkeypatch.setenv('ISYCODE_STATE_HOME',str(tmp_path/'state'))
    _write_preferences({'version':1,'provider':'parity','models':{}})
    path=_preferences_path()
    assert storage.private(path.parent) and storage.private(path)


def test_observation_writers_do_not_interleave(tmp_path,monkeypatch):
    from isycode import capability_observations as c
    monkeypatch.setenv('ISYCODE_STATE_HOME',str(tmp_path/'state'))
    code="from isycode.capability_observations import record; import sys; assert all(record('parity',sys.argv[1]+str(i),'steer',True) for i in range(12))"
    jobs=[subprocess.Popen([sys.executable,'-c',code,str(i)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for i in range(3)]
    for job in jobs:
        out,err=job.communicate(timeout=40)
        assert job.returncode==0,err.decode(errors='replace')
    rows=[json.loads(line) for line in c._path().read_text(encoding='utf-8').splitlines()]
    assert len(rows)==36 and len({row['model'] for row in rows})==36


def test_onboarding_then_observation_reload_is_private(tmp_path,monkeypatch):
    from isycode.workspace_setup import WorkspaceSetupStore
    from isycode import capability_observations as c
    root=tmp_path/'onboarding';monkeypatch.setenv('ISYCODE_STATE_HOME',str(root))
    setup=WorkspaceSetupStore()
    assert c.record('parity','after-onboarding','steer',True)
    assert c.observed('parity','after-onboarding','steer') is True
    assert storage.private(setup.root)
