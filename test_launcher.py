"""The installed launcher resolves ISyCode from any working directory."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_installer_links_launcher_and_preserves_invocation_directory(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launch_dir = tmp_path / "arbitrary" / "project"
    launch_dir.mkdir(parents=True)
    capture = tmp_path / "python-invocation.txt"
    fake_python = tmp_path / "python-capture"
    fake_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$PWD\" \"$*\" \"$PYTHONPATH\" > \"$CAPTURE\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = os.environ.copy()
    env.update({"ISYCODE_BIN_DIR": str(bin_dir), "ISYCODE_PYTHON": str(fake_python),
                "CAPTURE": str(capture)})

    installed = bin_dir / "isycode"
    subprocess.run([str(ROOT / "scripts" / "install-path")], cwd=tmp_path,
                   env=env, check=True, capture_output=True, text=True)
    subprocess.run([str(installed), "--probe"], cwd=launch_dir, env=env,
                   check=True, capture_output=True, text=True)

    cwd, argv, pythonpath = capture.read_text(encoding="utf-8").splitlines()
    assert cwd == str(launch_dir)
    assert argv == "-m isycode --probe"
    assert str(ROOT) in pythonpath.split(os.pathsep)


def test_installer_refuses_to_replace_an_existing_command(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command = bin_dir / "isycode"
    command.write_text("user-owned", encoding="utf-8")
    env = os.environ.copy()
    env["ISYCODE_BIN_DIR"] = str(bin_dir)

    result = subprocess.run([str(ROOT / "scripts" / "install-path")], cwd=tmp_path,
                            env=env, capture_output=True, text=True)

    assert result.returncode != 0
    assert command.read_text(encoding="utf-8") == "user-owned"
