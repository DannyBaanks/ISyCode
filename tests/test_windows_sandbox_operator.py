"""Check operator command generation without elevation or disk mutations."""
import os
from pathlib import Path
import subprocess
import importlib.util
import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='PowerShell operator parser')


def test_attach_parameters_match_sdk_union_alignment():
    import ctypes
    script=Path(__file__).resolve().parents[1]/'scripts/attach-windows-sandbox-volume.py'
    spec=importlib.util.spec_from_file_location('operator_attach',script)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.AttachParameters.data.offset==8
    assert ctypes.sizeof(module.AttachParameters)==24


def test_operator_attach_refuses_unelevated_before_image_access(tmp_path):
    import sys
    script=Path(__file__).resolve().parents[1]/'scripts/attach-windows-sandbox-volume.py'
    image=tmp_path/'never-created.vhd'
    result=subprocess.run([sys.executable,str(script),'--image',str(image),
                           '--expected-image-id','synthetic'],capture_output=True,text=True,timeout=20)
    assert result.returncode!=0
    assert 'Administrative operator required' in result.stderr
    assert not image.exists()


def test_powershell_operator_scripts_parse_without_execution():
    root=Path(__file__).resolve().parents[1]
    for name in ('prepare-windows-sandbox-volume.ps1','remount-windows-sandbox-volume.ps1'):
        script=root/'scripts'/name
        # Use an explicit script block so script paths remain data, never source.
        escaped=str(script).replace("'","''")
        result=subprocess.run(['powershell.exe','-NoProfile','-Command',
            "$errors=$null; [System.Management.Automation.Language.Parser]::ParseFile('"+escaped+"',[ref]$null,[ref]$errors)|Out-Null; if($errors){$errors|Out-String;exit 1}"],
            capture_output=True,text=True,timeout=20)
        assert result.returncode==0,result.stdout+result.stderr
