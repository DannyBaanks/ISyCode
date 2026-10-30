"""ISyCode's L0 for GUS (ADR 0013, MK5): an explicit manifest, its rule and its fingerprint."""
import hashlib
import os
import re
import shutil
from pathlib import Path

import pytest

from isycode.gus_l0 import (
    L0_DIRECTORIES, L0_FILES, L0_RULE, fingerprint, manifest_text, repository_path, touches_l0)

REPO = Path(__file__).resolve().parents[1]
OWNER_CLASS = re.compile(r"^class \w+Owner\b", re.MULTILINE)
# Changing what L0 is goes through this pin. Both files are L0 themselves, so
# GUS can neither shrink the list nor update the pin.
PINNED_MANIFEST = "659f57bb201161f2ef4e1427a8c3eb0cbce17ece914e1a7f50e27161fde12181"


def _manifest_digest() -> str:
    return hashlib.sha256("\n".join(L0_FILES + L0_DIRECTORIES).encode("utf-8")).hexdigest()


def test_the_manifest_is_pinned():
    assert _manifest_digest() == PINNED_MANIFEST, (
        "L0 changed: review the change with Danny, then update PINNED_MANIFEST")


def test_every_l0_entry_exists_and_is_listed_once():
    assert len(set(L0_FILES)) == len(L0_FILES)
    for path in L0_FILES:
        assert (REPO / path).is_file(), path
    for path in L0_DIRECTORIES:
        assert (REPO / path).is_dir(), path


def test_every_module_with_an_execution_owner_is_l0():
    owners = sorted(path.relative_to(REPO).as_posix() for path in (REPO / "src" / "isycode").glob("*.py")
                    if OWNER_CLASS.search(path.read_text(encoding="utf-8")))
    assert owners and [path for path in owners if path not in L0_FILES] == []


@pytest.mark.parametrize("path", [
    "src/isycode/security.py",
    "SRC/IsyCode/Security.PY",                 # a case-insensitive filesystem
    "src\\isycode\\workspace_authority.py",     # Windows separators
    "./src/isycode/gus_role.py",
    "src/isycode/../isycode/action_audit.py",
    "src/isycode/security.py.",                 # NTFS drops trailing dots
    "src/isycode/security.py..",
    "src/isycode/security.py .",                # and trailing spaces
    "src/isycode./security.py",                 # a folder alias, not just the leaf
    "src/isycode/security.py:stream",           # an NTFS stream of the L0 file
    "src/isycode/security.py::$DATA",           # the default stream is the file itself
    "src/isycode/security.py.:stream",          # both aliases on the same component
    "src/isycode./security.py:stream",          # a folder alias plus a stream
    "src/isycode/.../security.py",              # not a real Windows name: refuse it
    "src/isycode/agents/gus.md",
    "docs/decisions/0013-gus-l1-l0.md",
    "docs/decisions/9999-new.md",               # a new file inside an L0 folder
    ".github/workflows/ci.yml",
    "AGENTS.md",
    "src", "src/isycode", "docs", ".", "",      # folders holding L0: a move or delete touches it
])
def test_l0_paths_and_their_folders_are_l0(path):
    assert touches_l0(path) or path == ""
    assert touches_l0(path or ".")


@pytest.mark.parametrize("path", [
    "src/isycode/tui.py",
    "src/isycode/work_list.py",
    "tests/test_work_list.py",
    "docs/roadmap-gus.md",
    "docs/decisions-notes.md",                  # a name that only starts like an L0 folder
    "src/isycode/security.py.bak",
    "src/isycode/tui.py.",                      # an L1 file with a Windows alias stays L1
    "src/isycode/notes:2026.md",                # a POSIX name whose stream base is not L0
    "../ISyCode/src/isycode/security.py",       # outside the repository: Authority refuses it
    "/etc/passwd",
    "C:/Windows/system.ini",
])
def test_l1_and_outside_paths_are_not_l0(path):
    assert not touches_l0(path)


def test_repository_path_normalizes_or_refuses():
    assert repository_path("a\\b/../c.py") == "a/c.py"
    assert repository_path("../x") is None and repository_path("/x") is None
    assert repository_path("C:\\x") is None


@pytest.fixture
def copy(tmp_path):
    root = tmp_path / "repo"
    for path in L0_FILES + ("src/isycode/tui.py",):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / path, root / path)
    for path in L0_DIRECTORIES:
        shutil.copytree(REPO / path, root / path)
    return root


def test_the_fingerprint_sees_every_l0_change_and_no_l1_change(copy):
    before = fingerprint(copy)
    assert before == fingerprint(copy)

    (copy / "src/isycode/tui.py").write_text("# an L1 change\n", encoding="utf-8")
    assert fingerprint(copy).changed(before) == []

    with (copy / "src/isycode/security.py").open("a", encoding="utf-8") as handle:
        handle.write("\n# weakened\n")
    (copy / "docs/decisions/9999-new.md").write_text("# new\n", encoding="utf-8")
    (copy / "AGENTS.md").unlink()
    after = fingerprint(copy)
    assert after.changed(before) == ["AGENTS.md", "docs/decisions/9999-new.md", "src/isycode/security.py"]
    assert after.digest != before.digest


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows runners")
def test_swapping_an_l0_file_for_a_link_is_a_change(copy):
    before = fingerprint(copy)
    target = copy / "elsewhere.py"
    shutil.copyfile(copy / "src/isycode/approvals.py", target)
    (copy / "src/isycode/approvals.py").unlink()
    (copy / "src/isycode/approvals.py").symlink_to(target)
    assert fingerprint(copy).changed(before) == ["src/isycode/approvals.py"]


def test_the_manifest_text_carries_the_rule_every_path_and_the_fingerprint(copy):
    current = fingerprint(copy)
    text = manifest_text(current)
    assert L0_RULE in text and current.digest[:16] in text
    assert all(f"- {path}\n" in text + "\n" for path in L0_FILES)
    assert all(f"- {path}/" in text for path in L0_DIRECTORIES)


def test_the_fingerprint_is_the_same_with_crlf_line_endings(copy):
    before = fingerprint(copy)
    for path in ("AGENTS.md", "src/isycode/security.py"):
        target = copy / path
        target.write_bytes(target.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert fingerprint(copy) == before
