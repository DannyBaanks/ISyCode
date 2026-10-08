import hashlib
import subprocess

from test_gate_validator import _validator, _write_gate


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def test_historical_source_is_verified_at_evaluated_commit_without_releasing_current_code(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
    git(tmp_path, 'config', 'user.name', 'Synthetic fixture')
    (tmp_path / 'scripts').mkdir()
    source = tmp_path / 'scripts/fixture.py'
    source.write_text('original source\n')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    git(tmp_path, 'add', '--', 'scripts/fixture.py')
    git(tmp_path, 'commit', '-qm', 'fixture source', '--', 'scripts/fixture.py')
    sha = git(tmp_path, 'rev-parse', 'HEAD')
    gate = _write_gate(tmp_path, sha=sha)
    gate.write_text(gate.read_text() + f'      - scripts/fixture.py\n        sha256: {digest}\n')
    source.write_text('changed current source\n')
    validator = _validator()
    assert validator.validate_tree(tmp_path) == []
    assert any('sha256 mismatch' in e for e in validator.validate_tree(tmp_path, require_approved=True))
    # Raw evidence is always checked on disk, never excused by historical source.
    (gate.parent / 'output.txt').write_text('tampered evidence\n')
    assert any('sha256 mismatch' in e for e in validator.validate_tree(tmp_path))
