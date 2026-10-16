"""Suite-wide hermetic defaults."""
import os
import subprocess

import pytest
from pathlib import Path


@pytest.fixture
def synthetic_windows_storage(tmp_path, monkeypatch):
    """Native process controls only; this fake certifies NO physical quota."""
    if os.name != 'nt':
        pytest.skip('native Windows fixture')
    from isycode.platform_windows_sandbox_volume import StorageIdentity, StorageUnavailableError
    from isycode.platform_windows_sandbox import WindowsSandbox
    identity = StorageIdentity('synthetic-test-volume', 1, 'synthetic-image',
                               'synthetic-file', 536870912, 536870912)
    leases = []
    class Lease:
        root = Path(tmp_path.anchor)
        closed = False
        changed = False
        def assert_unchanged(self):
            if self.closed or self.changed:
                raise StorageUnavailableError('synthetic changed storage')
        def assert_directory(self, path):
            self.assert_unchanged()
            if path.parent != self.root:
                raise StorageUnavailableError('synthetic wrong root')
        def close(self): self.closed = True
        def __enter__(self): return self
        def __exit__(self, *_): self.close()
    class Provider:
        def open(self, expected=None):
            if expected is not None and expected != identity:
                raise StorageUnavailableError('synthetic identity changed')
            lease = Lease()
            lease.identity = identity
            leases.append(lease)
            return lease
    monkeypatch.setattr(WindowsSandbox, '_provider', lambda _: Provider())
    return leases


@pytest.fixture(autouse=True)
def _hermetic_native_state(tmp_path, monkeypatch):
    # Windows state_root uses LOCALAPPDATA rather than XDG_STATE_HOME.
    # Existing POSIX fixtures must never write into the Windows user's state.
    if os.name == 'nt':
        monkeypatch.setenv('ISYCODE_STATE_HOME', str(tmp_path / 'native-state'))


@pytest.fixture(autouse=True)
def _hermetic_isyco_checkout(request, tmp_path_factory, monkeypatch):
    """Point Bridge discovery at a stand-in ISyCo checkout.

    Unit tests must not depend on whether the machine has a real ISyCo checkout
    (CI runners do not; a developer's real one must not decide results). Tests
    that run the handshake patch subprocess.run. Integration tests, an explicit
    ISYCO_ROOT, or a test's own monkeypatch.setenv still win.
    """
    if request.node.get_closest_marker("integration") or os.environ.get("ISYCO_ROOT"):
        return
    root = tmp_path_factory.getbasetemp() / "isyco-stand-in"
    script = root / "bridge_core" / "capabilities" / "cap.agent_bridge" / "handshake.py"
    if not script.is_file():
        script.parent.mkdir(parents=True, exist_ok=True)
        (root / ".iesyroot").write_text("", encoding="utf-8")
        script.write_text('raise SystemExit("test stand-in: subprocess.run is patched")\n',
                          encoding="utf-8")
    monkeypatch.setenv("ISYCO_ROOT", str(root))


def pytest_make_parametrize_id(config, val, argname):
    """Keep case names bounded for OS environment limits and readable evidence."""
    if isinstance(val, (str, bytes)) and len(val)>128:
        import hashlib
        raw=val.encode('utf-8',errors='surrogatepass') if isinstance(val,str) else val
        return f'{argname}-{len(val)}bytes-{hashlib.sha256(raw).hexdigest()[:12]}'
    return None


@pytest.fixture
def make_directory_link():
    """Create a directory symlink on POSIX or an unprivileged junction on Windows."""
    def create(link: Path, target: Path) -> Path:
        if os.name != 'nt':
            link.symlink_to(target, target_is_directory=True)
            return link
        command = f'mklink /J "{link}" "{target}"'
        result = subprocess.run(
            ['cmd.exe', '/d', '/c', command], capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=10)
        if result.returncode:
            pytest.skip('NOT_DEMONSTRATED: Windows could not create a directory junction')
        return link
    return create
