"""CLI pipes use an explicit UTF-8 contract, including legacy Windows locales."""
import os,subprocess,sys


def test_launcher_reconfigures_legacy_redirected_output(tmp_path):
    env=dict(os.environ,ISYCODE_STATE_HOME=str(tmp_path/'state'),XDG_CONFIG_HOME=str(tmp_path/'config'))
    script="import sys;sys.stdout.reconfigure(encoding='cp1252');from isycode.launcher import main;raise SystemExit(main(['--help']))"
    result=subprocess.run([sys.executable,'-c',script],capture_output=True,env=env,timeout=20)
    assert result.returncode==0,result.stderr
    text=result.stdout.decode('utf-8')
    assert 'ISyCode ·' in text
