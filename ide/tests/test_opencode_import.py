"""Test importing API keys from opencode auth.json."""

import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.secret_broker import SecretBroker


def test_import_opencode():
    print("=== Import keys from opencode auth.json ===")
    tmp = Path(tempfile.mkdtemp())
    auth = {
        "openai": "sk-proj-opencode-key",
        "anthropic": "sk-ant-opencode-key",
        "nvidia": "nvapi-opencode-key",
    }
    auth_file = tmp / "auth.json"
    import json
    auth_file.write_text(json.dumps(auth), encoding="utf-8")

    broker = SecretBroker()
    imported = broker.import_from_opencode(auth_file)

    assert set(imported) == {"openai", "anthropic", "nvidia"}, imported
    assert broker.get("openai") == "sk-proj-opencode-key"
    assert broker.get("anthropic") == "sk-ant-opencode-key"
    assert broker.get("nvidia") == "nvapi-opencode-key"

    print(f"  Imported: {', '.join(imported)}")
    print(f"  Keys verified in broker (never printed): OK")

    # Path resolution test (default location)
    opts = {"XDG_DATA_HOME": str(tmp)}
    import os
    old = os.environ.get("XDG_DATA_HOME")
    os.environ["XDG_DATA_HOME"] = str(tmp)
    try:
        (tmp / "opencode").mkdir(exist_ok=True)
        (tmp / "opencode" / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
        imported2 = SecretBroker().import_from_opencode()
        assert "openai" in imported2
        print(f"  Default path (~/.local/share/opencode/auth.json) found: OK")
    finally:
        if old is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = old

    # Cleanup
    for p in ("openai", "anthropic", "nvidia"):
        broker.remove(p)
        SecretBroker().remove(p)
    print("  Cleaned up test keys")
    print("  OK")


if __name__ == "__main__":
    test_import_opencode()
    print("\nALL OPENCODE IMPORT TESTS PASSED")