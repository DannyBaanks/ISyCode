"""Continue the broad native suite after the verified first module batch."""
from pathlib import Path
import pytest
already_verified={
 'test_windows_sandbox_process.py','test_windows_sandbox_resources.py',
 'test_windows_sandbox_registry.py','test_windows_sandbox_recovery.py',
 'test_windows_sandbox_acceptance.py','test_windows_sandbox_volume_acceptance.py',
 'test_windows_sandbox_volume_lifecycle.py','test_command_runner_windows.py'}
files=[str(p) for p in sorted(Path('tests').glob('test_*.py'))
       if p.name>'test_bridge_presence_owner.py' and p.name not in already_verified]
raise SystemExit(pytest.main(['-q','-m','not integration','--maxfail=12','--tb=short','--show-capture=no',*files]))
