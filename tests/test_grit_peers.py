"""grit peer claims: pinned parser, sandbox owner authorization, advisory semantics."""
import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

import isycode.grit as grit
from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import GritPeersOwner
from isycode.approvals import ActionApprovalStore
from isycode.workspace_authority import WorkspaceAuthority

REAL_STATUS = """\
* agent-1 -- add validation
  | src/auth.py::login (2026-10-09 09:35:33) [EXPIRED]
* agent-2 -- cleanup
  | src/auth.py::logout (read) (2026-10-09 09:35:33) [ttl=600s]

2/6 symbols locked
"""


def test_parse_status_accepts_the_pinned_grammar():
    claims = grit.parse_status(REAL_STATUS)
    assert claims == [
        {"agent": "agent-1", "intent": "add validation", "symbol": "src/auth.py::login",
         "mode": "write", "locked_at": "2026-10-09 09:35:33"},
        {"agent": "agent-2", "intent": "cleanup", "symbol": "src/auth.py::logout",
         "mode": "read", "locked_at": "2026-10-09 09:35:33"},
    ]


def test_parse_status_accepts_empty_registry_and_queued_totals():
    assert grit.parse_status("No active locks.\n") == []
    queued = REAL_STATUS.replace("2/6 symbols locked", "2/6 symbols locked, 1 queued")
    assert len(grit.parse_status(queued)) == 2


@pytest.mark.parametrize("text", [
    "* agent-1 -- intent\n  | src/x.py::login extra garbage here\n\n1/2 symbols locked",
    "random line\n",
    "* agent-1 -- intent\n1/2 symbols locked\n",
    "",
])
def test_parse_status_rejects_unknown_output(text):
    with pytest.raises(ValueError):
        grit.parse_status(text)


def test_claims_for_path_matches_only_that_file():
    claims = grit.parse_status(REAL_STATUS)
    assert [item["symbol"] for item in grit.claims_for_path(claims, "src/auth.py")] == \
        ["src/auth.py::login", "src/auth.py::logout"]
    assert grit.claims_for_path(claims, "auth.py") == []
    assert grit.claims_for_path(claims, "src/other.py") == []


def test_advisory_text_names_holder_and_stays_advisory():
    claims = grit.parse_status(REAL_STATUS)
    text = grit.advisory_text(claims)
    assert "login" in text and "agent-1" in text and "add validation" in text
    assert "advisory only" in text and "rtk-ai/grit" in text
    assert grit.advisory_text([]) is None


def test_discover_grit_pins_path_and_sha256(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "grit"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    (bin_dir / "bwrap").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "bwrap").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    info = grit.discover_grit()
    assert info is not None and info["state"] == "sandbox_ready"
    assert info["executable"] == str(fake.resolve())
    assert info["sha256"] == hashlib.sha256(fake.read_bytes()).hexdigest()
    assert info["repository"] == "https://github.com/rtk-ai/grit"


def test_discover_grit_without_binary_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert grit.discover_grit() is None


def test_sandbox_command_mounts_workspace_ro_and_only_grit_rw(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_grit = bin_dir / "grit"
    fake_grit.write_text("#!/bin/sh\nexit 0\n")
    fake_grit.chmod(0o755)
    fake_bwrap = bin_dir / "bwrap"
    fake_bwrap.write_text("#!/bin/sh\nexit 1\n")
    fake_bwrap.chmod(0o755)
    root = tmp_path / "project"
    (root / ".grit").mkdir(parents=True)
    info = {"executable": str(fake_grit.resolve()), "sandbox_executable": str(fake_bwrap.resolve())}
    command = grit._sandbox_command(root, info)
    joined = " ".join(command)
    assert f"--ro-bind {root.resolve()} /workspace" in joined
    assert f"--bind {(root / '.grit').resolve()} /workspace/.grit" in joined
    assert f"--ro-bind {fake_grit.resolve()} /runtime/grit" in joined
    assert "--setenv NO_COLOR 1" in joined and "--unshare-all" in command
    assert command[-1] == "status"


@pytest.fixture
def peers(tmp_path: Path, monkeypatch):
    if os.name != "posix":
        pytest.skip("POSIX sandbox only")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_bwrap = bin_dir / "bwrap"
    fake_bwrap.write_text("#!/bin/sh\nexit 1\n")
    fake_bwrap.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    fake_grit = bin_dir / "grit"
    fake_grit.write_text("#!/bin/sh\nexit 0\n")
    fake_grit.chmod(0o755)
    root = tmp_path / "project"
    root.mkdir()
    (root / ".grit").mkdir()
    (root / "app.py").write_text("x = 1\n")
    info = {"id": "grit", "label": "grit peer claims", "state": "sandbox_ready",
            "executable": str(fake_grit.resolve()),
            "sha256": hashlib.sha256(fake_grit.read_bytes()).hexdigest(),
            "sandbox_executable": str(fake_bwrap.resolve())}
    monkeypatch.setattr(grit, "discover_grit", lambda: dict(info))
    calls = []

    async def fake_read(root, item, timeout_s=grit.STATUS_TIMEOUT_S):
        calls.append(root)
        return {"claims": grit.parse_status(REAL_STATUS),
                "raw_sha256": "0" * 64,
                "grit_executable": item["executable"], "grit_sha256": item["sha256"]}

    monkeypatch.setattr(grit, "read_peer_claims", fake_read)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    owner = GritPeersOwner(root, authority, ActionApprovalStore())
    return owner, authority, info, calls


def _run(owner, path="src/auth.py"):
    return asyncio.run(owner.claims(path))


def test_claims_need_grit_grant_and_read_grant(peers):
    owner, authority, info, calls = peers
    assert _run(owner).decision == "DENY"
    authority.set_grant("grit.claims.read", enabled=True, executables=[info["sandbox_executable"]])
    denied = _run(owner)
    assert denied.decision == "DENY" and "workspace.files.read" in denied.reason
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[owner.root])
    outcome = _run(owner)
    assert outcome.decision == "ALLOW"
    payload = json.loads(outcome.text)
    assert payload["path"] == "src/auth.py"
    assert [claim["symbol"] for claim in payload["claims"]] == \
        ["src/auth.py::login", "src/auth.py::logout"]
    assert "advisory only" in payload["advisory"]
    assert ActionAuditJournal(owner.root).verify().receipts == 1


def test_claims_stay_off_without_a_grit_registry(peers, monkeypatch):
    owner, authority, info, calls = peers
    authority.set_grant("grit.claims.read", enabled=True, executables=[info["sandbox_executable"]])
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[owner.root])
    no_registry = owner.root / ".grit"
    no_registry.rmdir()
    outcome = _run(owner)
    assert outcome.decision == "DENY" and "no grit registry" in outcome.reason
    assert calls == []


def test_classic_does_not_imply_claims(peers):
    owner, authority, info, _ = peers
    authority.set_mode("classic")
    assert _run(owner).decision == "DENY"


def test_failed_grit_exit_is_unavailable_not_empty(peers, monkeypatch):
    owner, authority, info, _ = peers
    authority.set_grant("grit.claims.read", enabled=True, executables=[info["sandbox_executable"]])
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[owner.root])

    async def failing(root, item, timeout_s=grit.STATUS_TIMEOUT_S):
        raise RuntimeError("grit status exited with 1")

    monkeypatch.setattr(grit, "read_peer_claims", failing)
    outcome = _run(owner)
    assert outcome.decision == "ERROR" and "unavailable" in outcome.text.lower()


def test_unparseable_output_is_unavailable_not_empty(peers, monkeypatch):
    owner, authority, info, _ = peers
    authority.set_grant("grit.claims.read", enabled=True, executables=[info["sandbox_executable"]])
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[owner.root])

    async def garbage(root, item, timeout_s=grit.STATUS_TIMEOUT_S):
        raise ValueError("unrecognized line in grit status output")

    monkeypatch.setattr(grit, "read_peer_claims", garbage)
    assert _run(owner).decision == "ERROR"
