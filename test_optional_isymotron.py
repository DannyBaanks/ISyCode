import os
import subprocess
import sys
from pathlib import Path


def test_tui_module_import_does_not_require_isymotron_checkout(tmp_path):
    repository = Path(__file__).parent.resolve()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repository)
    script = (
        "import isycode.config as config; "
        "config.find_isymotron_root = lambda: (_ for _ in ()).throw("
        "config.ConfigurationError('not installed')); "
        "import isycode.tui"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
