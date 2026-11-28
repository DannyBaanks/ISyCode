"""Verified-tail cache and the optional Zig fast path of the action journal.

The cache must never let an append trust bytes that changed since this handle
verified them, a segment must never be sealed on the cache alone, and the
native verifier must agree with the Python one on everything it accepts.
"""
import hashlib
import json
import os
import secrets
from pathlib import Path

import pytest

from isycode import native_journal
from isycode.action_audit import ActionAuditError, ActionAuditJournal
from isycode.action_runtime import ActionReceipt, ProductActionGate
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


@pytest.fixture(params=["native", "python"])
def mode(request, monkeypatch):
    native_journal._reset_for_tests()
    if request.param == "native":
        if native_journal.load() is None:
            pytest.skip("libisyjournal is not built (python -m isycode.native_journal build)")
    else:
        monkeypatch.setenv("ISYCODE_NATIVE_JOURNAL", "0")
    yield request.param
    native_journal._reset_for_tests()


@pytest.fixture
def env(tmp_path: Path, monkeypatch, mode):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    authority.set_grant("provider.request", enabled=True, network_hosts=["api.example.com"])
    gate = ProductActionGate(root, authority, owner_id="provider_network")
    return root, gate


def _effect(root, gate, n):
    request = ActionRequest("provider.request", root, "api.example.com",
                            {"url": "https://api.example.com/v1", "n": n},
                            execution_owner="provider_network")
    _, decision = gate.authorize(request)
    receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id, request.digest,
                            "ALLOW", "SUCCESS", hashlib.sha256(str(n).encode()).hexdigest())
    return decision.allowed and gate.persist_receipt(request, receipt)


def _count_full_reads(monkeypatch, journal):
    calls = []
    original = journal._read_verified

    def counting(fd):
        calls.append(fd)
        return original(fd)

    monkeypatch.setattr(journal, "_read_verified", counting)
    return calls


def test_appends_after_the_first_reuse_the_verified_tail(env, monkeypatch):
    root, gate = env
    assert _effect(root, gate, 0)
    reads = _count_full_reads(monkeypatch, gate.audit)
    for n in range(1, 6):
        assert _effect(root, gate, n)
    assert reads == []  # ten appends, no re-read of the active file
    report = ActionAuditJournal(root).verify()
    assert report.status == "PASS" and report.decisions == 6 and report.receipts == 6


def test_an_append_by_another_handle_forces_full_verification(env, monkeypatch):
    root, gate = env
    assert _effect(root, gate, 0)
    other = ProductActionGate(root, gate.authority, owner_id="provider_network")
    assert _effect(root, other, 1)  # a second writer (another ISyCode window)
    reads = _count_full_reads(monkeypatch, gate.audit)
    assert _effect(root, gate, 2)
    assert len(reads) == 1
    assert ActionAuditJournal(root).verify().status == "PASS"


def test_same_size_tampering_with_restored_mtime_is_still_caught(env):
    root, gate = env
    for n in range(3):
        assert _effect(root, gate, n)
    path = gate.audit.path
    before = path.stat()
    data = path.read_bytes()
    index = data.index(b'"time":') + len(b'"time":')
    tampered = data[:index] + (b"9" if data[index:index + 1] != b"9" else b"8") + data[index + 1:]
    path.write_bytes(tampered)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))  # forge mtime; ctime moves
    assert path.stat().st_size == before.st_size
    with pytest.raises(ActionAuditError):
        gate.audit._append({"kind": "probe"})
    assert ActionAuditJournal(root).verify().status == "JOURNAL_INVALID"


def test_a_segment_is_never_sealed_on_the_cache_alone(env, monkeypatch):
    root, gate = env
    monkeypatch.setattr(ActionAuditJournal, "SEGMENT_BYTES", 4096)
    assert _effect(root, gate, 0)
    journal = gate.audit
    path = journal.path
    data = path.read_bytes()
    index = data.index(b'"time":') + len(b'"time":')
    path.write_bytes(data[:index] + (b"9" if data[index:index + 1] != b"9" else b"8")
                     + data[index + 1:])
    # Simulate a writer that could also forge ctime: point the cache at the
    # tampered file so only seal-time verification stands in the way.
    info = os.stat(path)
    journal._verified_tail = journal._stat_key(info) + (journal._verified_tail[5],)
    sealed_before = len(journal._sealed_segments())
    for n in range(1, 40):
        if not _effect(root, gate, n):
            break
    else:
        pytest.fail("tampered journal was sealed and kept accepting decisions")
    assert len(journal._sealed_segments()) == sealed_before


def test_rotation_with_the_cache_keeps_a_valid_chain(env, monkeypatch):
    root, gate = env
    monkeypatch.setattr(ActionAuditJournal, "SEGMENT_BYTES", 4096)
    for n in range(40):
        assert _effect(root, gate, n)
    journal = ActionAuditJournal(root)
    assert len(journal._sealed_segments()) >= 3
    report = journal.verify()
    assert report.status == "PASS" and report.decisions == 40 and report.receipts == 40


# ── native verifier parity ───────────────────────────────────────────────

def _python_chain(raw: bytes, previous: str):
    for line in raw.decode("utf-8").splitlines():
        record = json.loads(line)
        digest = record.pop("digest")
        if record.get("previous") != previous:
            return None
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256((previous + canonical).encode()).hexdigest() != digest:
            return None
        previous = digest
    return previous


def _chain(values) -> bytes:
    previous, out = "0" * 64, b""
    for value in values:
        record = {"kind": "decision", "previous": previous, "time": 1.5, "value": value,
                  "nested": {"b": [1, -2.25e-07, None, True], "a": {"z": "", "y": "\\"}}}
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        record["digest"] = hashlib.sha256((previous + canonical).encode()).hexdigest()
        out += (json.dumps(record, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")) + "\n").encode()
        previous = record["digest"]
    return out


STRINGS = ["plain", "ñandú 漢字 🙂", 'q"uote', "back\\slash", "tab\tnl\ncr\r",
           "\x00\x01\x1f\x7f", "​‮", "", "x" * 3000]


def _native():
    native_journal._reset_for_tests()
    native = native_journal.load()
    if native is None:
        pytest.skip("libisyjournal is not built")
    return native


def test_native_chain_matches_python_on_hostile_strings():
    native = _native()
    raw = _chain(STRINGS)
    status, tail, records, _ = native.verify_chain(raw, "0" * 64)
    assert status == native_journal.OK and records == len(STRINGS)
    assert tail == _python_chain(raw, "0" * 64)


@pytest.mark.parametrize("separator", [" ", " ", "\u0085"])
def test_native_defers_lines_python_splitlines_would_break(separator):
    native = _native()
    raw = _chain(["a" + separator + "b"])
    status, _, _, bad = native.verify_chain(raw, "0" * 64)
    assert status == native_journal.NOT_CANONICAL and bad == 1


def test_native_never_accepts_what_python_rejects():
    native = _native()
    raw = _chain(STRINGS)
    for offset in range(0, len(raw) - 1, 97):  # flip bytes all over the chain
        if raw[offset:offset + 1] == b"\n":
            continue
        broken = raw[:offset] + bytes([raw[offset] ^ 0x01]) + raw[offset + 1:]
        status, tail, _, _ = native.verify_chain(broken, "0" * 64)
        if status == native_journal.OK:
            assert tail == _python_chain(broken, "0" * 64)


def test_native_write_reports_errno():
    native = _native()
    with pytest.raises(OSError):
        native.write_fsync(-1, b"x")


def test_kill_switch_disables_the_library(monkeypatch):
    native_journal._reset_for_tests()
    monkeypatch.setenv("ISYCODE_NATIVE_JOURNAL", "0")
    assert native_journal.load() is None
