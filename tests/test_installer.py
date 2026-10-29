"""Tests for ISyCode's universal install scripts (install.sh and install.ps1)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
posix_installer = pytest.mark.skipif(
    os.name != "posix",
    reason="install.sh requires a POSIX environment",
)


@posix_installer
def test_install_sh_syntax():
    """install.sh passes bash syntax validation."""
    script = ROOT / "install.sh"
    assert script.is_file(), "install.sh must exist at repo root"
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, f"Syntax error in install.sh: {result.stderr}"


@posix_installer
def test_install_sh_help():
    """install.sh --help displays usage and available options."""
    script = ROOT / "install.sh"
    result = subprocess.run([str(script), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "ISyCode — Instalador Universal" in result.stdout
    assert "-d, --dir" in result.stdout
    assert "-b, --branch" in result.stdout
    assert "--bin-dir" in result.stdout
    assert "--uninstall" in result.stdout


@posix_installer
def test_install_sh_unknown_flag():
    """install.sh fails with code 1 and error message on unknown flags."""
    script = ROOT / "install.sh"
    result = subprocess.run([str(script), "--unknown-flag-xyz"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Opción no reconocida" in result.stderr


@posix_installer
def test_install_sh_uninstall_workflow(tmp_path: Path):
    """--uninstall cleanly removes the launcher executable symlink."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    target_cmd = bin_dir / "isycode"

    script = ROOT / "install.sh"
    env = dict(os.environ, ISYCODE_BIN_DIR=str(bin_dir), HOME=str(tmp_path))

    # Case 1: uninstall when command does not exist
    res1 = subprocess.run([str(script), "--uninstall"], env=env, capture_output=True, text=True)
    assert res1.returncode == 0
    assert "No se encontró ningún enlace" in res1.stdout

    # Case 2: uninstall when symlink exists
    target_cmd.symlink_to(ROOT / "scripts" / "isycode")
    assert target_cmd.is_symlink()
    res2 = subprocess.run([str(script), "--uninstall"], env=env, capture_output=True, text=True)
    assert res2.returncode == 0
    assert "Se eliminó el enlace ejecutable" in res2.stdout
    assert not target_cmd.exists()


@posix_installer
def test_install_sh_local_repo_execution(tmp_path: Path):
    """Running install.sh inside the repository links the launcher without cloning."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Create a mock target repo structure
    repo_copy = tmp_path / "mock-repo"
    repo_copy.mkdir()
    (repo_copy / ".git").mkdir()
    (repo_copy / "pyproject.toml").write_text('name = "isycode"\nversion = "1.0.0"\n', encoding="utf-8")
    scripts_dir = repo_copy / "scripts"
    scripts_dir.mkdir()
    isycode_script = scripts_dir / "isycode"
    isycode_script.write_text("#!/bin/sh\necho isycode-mock\n", encoding="utf-8")
    isycode_script.chmod(0o755)

    # Fake venv python
    venv_bin = repo_copy / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    python_bin = venv_bin / "python"
    python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python_bin.chmod(0o755)

    script = ROOT / "install.sh"
    env = dict(os.environ, ISYCODE_BIN_DIR=str(bin_dir), HOME=str(tmp_path), NO_COLOR="1")

    # Run installer pointing to the mock repo as --dir and --bin-dir
    result = subprocess.run(
        [str(script), "--dir", str(repo_copy), "--bin-dir", str(bin_dir), "--no-modify-path"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Installer failed: {result.stderr}\n{result.stdout}"
    assert "Entorno virtual y dependencias listas" in result.stdout
    assert "Comando enlazado en:" in result.stdout
    assert (bin_dir / "isycode").exists()


def test_install_ps1_content():
    """install.ps1 exists and defines expected PowerShell parameters and commands."""
    ps1 = ROOT / "install.ps1"
    assert ps1.is_file(), "install.ps1 must exist at repo root"
    content = ps1.read_text(encoding="utf-8")
    assert "param(" in content
    assert "$Dir" in content
    assert "$Branch" in content
    assert "$Uninstall" in content
    assert "ISyCode" in content
