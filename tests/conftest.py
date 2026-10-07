"""Suite-wide hermetic defaults."""
import os

import pytest


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
