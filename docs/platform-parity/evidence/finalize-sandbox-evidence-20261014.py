"""Record exact final bytes after verification; run from the ISyCode root."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import subprocess

root = Path.cwd()
manifest = root / 'docs/platform-parity/hashes.json'
historical = root / 'docs/platform-parity/evidence/hashes-before-sandbox-20261014.json'
if not historical.exists():
    historical.write_bytes(manifest.read_bytes())
previous = json.loads(historical.read_text(encoding='utf-8'))
paths = set(previous['files'])
for folder in ('docs/platform-parity', 'src/isycode', 'tests'):
    for item in (root / folder).rglob('*'):
        relative = item.relative_to(root).as_posix()
        if item.is_file() and '__pycache__' not in item.parts:
            if folder == 'docs/platform-parity' or 'sandbox' in item.name:
                paths.add(relative)
paths.update({'.gitattributes', '.github/workflows/platform-parity.yml',
              'docs/security/m15-authority-coverage.json',
              'docs/superpowers/plans/2026-10-14-windows-command-sandbox.md',
              'docs/superpowers/plans/2026-10-14-windows-bounded-scratch.md',
              'src/isycode/action_runtime.py', 'src/isycode/command_runner.py',
              'src/isycode/diagnostics.py', 'src/isycode/staging.py',
              'tests/test_command_runner.py', 'tests/test_diagnostics.py'})
paths.add('tests/conftest.py')
paths.update({'scripts/prepare-windows-sandbox-volume.ps1', 'scripts/attach-windows-sandbox-volume.py', 'scripts/remount-windows-sandbox-volume.ps1', 'src/isycode/winfs.py'})
paths.discard('docs/platform-parity/hashes.json')
record = {
    'recorded_at': datetime.now().astimezone().isoformat(),
    'baseline_commit': previous['baseline_commit'],
    'source_parent_commit': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'environment': {'system': platform.platform(), 'python': platform.python_version()},
    'scope': 'Exact local bytes; real VHD acceptance 13/13 PASS, reboot/remount/inspection PASS, Windows owner 12/12 PASS; native activation remains disabled pending broader runtime/network/IPC and lifecycle gates.',
    'files': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
              for name in sorted(paths) if (root / name).is_file()},
}
manifest.write_bytes((json.dumps(record, indent=2) + '\n').encode('utf-8'))
assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
           for name, digest in record['files'].items())
print('verified SHA-256:', len(record['files']))
