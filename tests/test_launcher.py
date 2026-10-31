"""The installed launcher resolves ISyCode from any working directory."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
posix_installer = pytest.mark.skipif(
    os.name != "posix",
    reason="these installer tests exercise the POSIX shell launcher; Windows uses install-windows.ps1",
)


@posix_installer
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
    assert str(ROOT / "src") in pythonpath.split(os.pathsep)


@posix_installer
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


@posix_installer
def test_installer_explicitly_migrates_only_its_legacy_symlink_and_keeps_backup(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command = bin_dir / "isycode"
    legacy = ROOT / ".venv" / "bin" / "isycode"
    command.symlink_to(legacy)
    env = dict(os.environ, ISYCODE_BIN_DIR=str(bin_dir))
    result = subprocess.run([str(ROOT / "scripts/install-path"), "--replace-owned"],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert command.resolve() == (ROOT / "scripts/isycode").resolve()
    backups = list(bin_dir.glob("isycode.backup.*"))
    assert len(backups) == 1 and os.readlink(backups[0]) == str(legacy)
    again = subprocess.run([str(ROOT / "scripts/install-path"), "--replace-owned"],
                           env=env, capture_output=True, text=True)
    assert again.returncode == 0 and list(bin_dir.glob("isycode.backup.*")) == backups


@posix_installer
def test_installer_migration_keeps_unknown_symlinks_and_regular_files(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command = bin_dir / "isycode"
    command.symlink_to(tmp_path / "someone-elses-tool")
    env = dict(os.environ, ISYCODE_BIN_DIR=str(bin_dir))
    result = subprocess.run([str(ROOT / "scripts/install-path"), "--replace-owned"],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert os.readlink(command) == str(tmp_path / "someone-elses-tool")
    assert not list(bin_dir.glob("isycode.backup.*"))
    # The refusal has to say what it compared, or the human cannot tell a foreign
    # tool from a checkout that only looks different because of a symlink.
    assert f"found target: {tmp_path / 'someone-elses-tool'}" in result.stderr
    assert "it resolves to: " in result.stderr
    assert "this checkout resolves to: " in result.stderr


def _checkout(tmp_path: Path, *, with_virtualenv: bool) -> Path:
    """A stand-in repository, so the installer compares files this test owns.

    The real checkout has no ``.venv`` on a CI runner: pointing the tests at it
    made every resolution fail, and on Linux the two empty answers compared
    equal, which read as "this launcher is ours".
    """
    repository = tmp_path / "repo"
    (repository / "scripts").mkdir(parents=True)
    for name in ("install-path", "isycode"):
        script = repository / "scripts" / name
        script.write_bytes((ROOT / "scripts" / name).read_bytes())
        script.chmod(0o755)
    if with_virtualenv:
        owned = repository / ".venv" / "bin" / "isycode"
        owned.parent.mkdir(parents=True)
        owned.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        owned.chmod(0o755)
    return repository


def _mainline_alias(task_home: Path, venv_target: Path | None) -> tuple[Path, Path]:
    """The retired mainline command name, with or without a runtime behind it."""
    legacy_dir = task_home / ".local/share/isycode-mainline"
    legacy_dir.mkdir(parents=True)
    if venv_target is not None:
        (legacy_dir / ".venv").symlink_to(venv_target, target_is_directory=True)
    bin_dir = task_home / ".local/bin"
    bin_dir.mkdir(parents=True)
    command = bin_dir / "isycode"
    command.symlink_to(legacy_dir / ".venv/bin/isycode")
    return bin_dir, command


@posix_installer
def test_installer_migrates_mainline_alias_only_when_it_shares_this_virtualenv(tmp_path: Path):
    repository = _checkout(tmp_path, with_virtualenv=True)
    task_home = tmp_path / "home"
    bin_dir, command = _mainline_alias(task_home, repository / ".venv")
    env = dict(os.environ, HOME=str(task_home), ISYCODE_BIN_DIR=str(bin_dir))
    result = subprocess.run([str(repository / "scripts/install-path"), "--replace-owned"],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert command.resolve() == (repository / "scripts/isycode").resolve()
    backups = list(bin_dir.glob("isycode.backup.*"))
    assert len(backups) == 1 and os.readlink(backups[0]) == str(
        task_home / ".local/share/isycode-mainline/.venv/bin/isycode")


@posix_installer
def test_installer_refuses_an_alias_it_cannot_resolve(tmp_path: Path):
    """Two unreadable names are not one fact about one file."""
    repository = _checkout(tmp_path, with_virtualenv=False)
    task_home = tmp_path / "home"
    bin_dir, command = _mainline_alias(task_home, None)
    env = dict(os.environ, HOME=str(task_home), ISYCODE_BIN_DIR=str(bin_dir))
    result = subprocess.run([str(repository / "scripts/install-path"), "--replace-owned"],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert os.readlink(command) == str(
        task_home / ".local/share/isycode-mainline/.venv/bin/isycode")
    assert "it resolves to: unreadable" in result.stderr
    assert not list(bin_dir.glob("isycode.backup.*"))


@posix_installer
def test_launcher_prefers_repository_virtualenv(tmp_path: Path):
    repository = tmp_path / "repo"
    launcher = repository / "scripts" / "isycode"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes((ROOT / "scripts" / "isycode").read_bytes())
    launcher.chmod(0o755)
    python = repository / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    capture = tmp_path / "python-invocation.txt"
    python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$CAPTURE\"\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    env = os.environ.copy()
    env.pop("ISYCODE_PYTHON", None)
    env["CAPTURE"] = str(capture)

    subprocess.run([str(launcher), "--probe"], cwd=tmp_path, env=env,
                   check=True, capture_output=True, text=True)

    assert capture.read_text(encoding="utf-8").strip() == "-m isycode --probe"


def test_help_lists_spanish_self_update_commands(capsys):
    from isycode.launcher import main

    assert main(["--help"]) == 0
    help_text = capsys.readouterr().out
    assert "isycode actualizar" in help_text
    assert "isycode update" in help_text
    assert "--check" in help_text


def test_update_command_dispatches_check_and_exit_code(monkeypatch, capsys):
    import isycode.updater
    from isycode.launcher import main

    calls = []

    class FakeUpdater:
        def __init__(self, confirm=None):
            self.confirm = confirm

        def run(self, check_only=False):
            calls.append(check_only)
            return isycode.updater.UpdateReport("available", ("Hay una actualización.",))

    monkeypatch.setattr(isycode.updater, "SelfUpdater", FakeUpdater)

    assert main(["actualizar", "--check"]) == 0
    assert calls == [True]
    assert "actualización" in capsys.readouterr().out
    assert main(["update", "--check"]) == 0
    assert calls == [True, True]
    assert main(["actualizar"]) == 0
    assert calls == [True, True, False]
    assert main(["update"]) == 0
    assert calls == [True, True, False, False]


def test_update_command_returns_failure_when_local_changes_need_resolution(monkeypatch, capsys):
    import isycode.updater
    from isycode.launcher import main

    class FakeUpdater:
        def __init__(self, confirm=None):
            self.confirm = confirm

        def run(self, check_only=False):
            return isycode.updater.UpdateReport(
                "updated-conflicts", ("Se requiere resolver un cambio local.",))

    monkeypatch.setattr(isycode.updater, "SelfUpdater", FakeUpdater)

    assert main(["actualizar"]) == 1
    assert "resolver" in capsys.readouterr().out


def test_update_asks_only_when_someone_can_answer(monkeypatch):
    import isycode.updater
    from isycode.launcher import main

    seen = []

    class FakeUpdater:
        def __init__(self, confirm=None):
            seen.append(confirm)

        def run(self, check_only=False):
            return isycode.updater.UpdateReport("current", ())

    monkeypatch.setattr(isycode.updater, "SelfUpdater", FakeUpdater)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    main(["actualizar"])
    assert seen[-1] is None
    main(["actualizar", "--yes"])
    assert seen[-1]("¿merge?", ()) is True


def test_update_command_rejects_unknown_flags(capsys):
    from isycode.launcher import main

    assert main(["actualizar", "--force"]) == 2
    assert "Uso:" in capsys.readouterr().err
