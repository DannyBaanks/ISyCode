"""Durable effect ledger: finite caps, crash recovery, and no model-owned reset."""
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from isycode.actions import ACTION_BY_ID
from isycode.approvals import ActionApprovalStore
from isycode.command_runner import CommandRunOwner, sandbox_command, sandbox_executable
from isycode.effect_ledger import (
    MAX_CHURN_BYTES, MAX_DELETE_OPS, MAX_UNIQUE_PATHS, RESET_PHRASE, CrashInjected, EffectCost,
    EffectLedger, LedgerDenied, workspace_identity,
)
from isycode.safety import Budget
from isycode.staging import cleanup_staging, measure_changes, prepare_staging, promote_accounted
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the effect ledger uses POSIX locks")

_PHASES = ["before-reserve", "after-reserve", "after-backup", "after-plan", "before-commit", "after-commit"]
for _index in range(3):
    _PHASES.extend([
        f"before-apply:{_index}", f"after-mark-applying:{_index}",
        f"after-apply:{_index}", f"after-mark-applied:{_index}",
    ])


def _ledger(root: Path, state: Path) -> EffectLedger:
    return EffectLedger(root, state_directory=state)


def _snap(root: Path) -> dict[str, bytes | None]:
    found = {}
    for name in ("a.txt", "b.txt", "c.txt"):
        path = root / name
        found[name] = path.read_bytes() if path.is_file() and not path.is_symlink() else None
    return found


def _commit_one(ledger: EffectLedger, path: str, *, deletes: int = 1, churn: int = 1) -> None:
    reservation = ledger.reserve(EffectCost((path,), deletes, churn))
    ledger.commit(reservation, applied_paths=(path,), deletes=deletes, churn_bytes=churn)


def test_limits_are_finite_and_are_not_safety_budget():
    assert Budget().max_files is None
    assert all(isinstance(value, int) and value > 0 for value in (
        MAX_UNIQUE_PATHS, MAX_DELETE_OPS, MAX_CHURN_BYTES))
    with pytest.raises(LedgerDenied):
        EffectCost(("/etc/passwd",), 0, 1)
    with pytest.raises(LedgerDenied):
        EffectCost(("../outside.txt",), 0, 1)
    with pytest.raises(LedgerDenied):
        EffectCost(("a.txt",), -1, 1)


def test_one_oversized_call_charges_nothing_and_split_calls_stop_at_the_cap(tmp_path, monkeypatch):
    import isycode.effect_ledger as module
    monkeypatch.setattr(module, "MAX_DELETE_OPS", 40)
    monkeypatch.setattr(module, "MAX_DELETES_PER_OPERATION", 100)
    state = tmp_path / "ledger"
    wide = tmp_path / "wide"
    wide.mkdir()
    denied = _ledger(wide, state)
    with pytest.raises(LedgerDenied) as oversized:
        denied.reserve(EffectCost(tuple(f"f{i}.txt" for i in range(41)), 41, 41))
    assert denied.status()["delete_ops"] == 0
    assert "41" not in str(oversized.value) or "0 deletes" in str(oversized.value)
    assert "0 deletes" in str(oversized.value) and "0 paths" in str(oversized.value)

    split = tmp_path / "split"
    split.mkdir()
    ledger = _ledger(split, state)
    accepted = 0
    for index in range(1000):
        try:
            _commit_one(ledger, f"s{index}.txt")
        except LedgerDenied as exc:
            assert "ledger has" in str(exc)
            assert "deletes" in str(exc) and "churn bytes" in str(exc)
            break
        accepted += 1
    assert accepted == 40
    assert ledger.status()["delete_ops"] == 40
    for _restart in range(3):
        again = _ledger(split, state)
        assert again.status()["delete_ops"] == 40
        with pytest.raises(LedgerDenied):
            again.reserve(EffectCost(("extra.txt",), 1, 1))


def _effect_worker(root: str, state: str, barrier, queue, index: int) -> None:
    barrier.wait()
    ledger = EffectLedger(Path(root), state_directory=Path(state))
    with ledger.exclusive():
        try:
            reservation = ledger.reserve(EffectCost((f"w{index}.txt",), 1, 1))
            ledger.commit(reservation, applied_paths=(f"w{index}.txt",), deletes=1, churn_bytes=1)
        except LedgerDenied:
            queue.put("deny")
            return
    queue.put("ok")


def test_eight_workers_share_one_cap(tmp_path, monkeypatch):
    import multiprocessing
    import isycode.effect_ledger as module
    monkeypatch.setattr(module, "MAX_DELETE_OPS", 3)
    monkeypatch.setattr(module, "MAX_DELETES_PER_OPERATION", 1)
    root = tmp_path / "shared"
    root.mkdir()
    state = tmp_path / "ledger"
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(8)
    queue = context.Queue()
    processes = [context.Process(target=_effect_worker, args=(str(root), str(state), barrier, queue, index))
                 for index in range(8)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    results = [queue.get(timeout=5) for _ in processes]
    assert results.count("ok") == 3
    assert results.count("deny") == 5
    assert _ledger(root, state).status()["delete_ops"] == 3


def test_rename_alias_clock_and_corruption_do_not_open_a_fresh_budget(tmp_path):
    state = tmp_path / "ledger"
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    ledger = _ledger(root, state)
    _commit_one(ledger, "a.txt", deletes=0, churn=4)
    renamed = tmp_path / "renamed"
    root.rename(renamed)
    alias = tmp_path / "alias"
    alias.symlink_to(renamed)
    for opened in (renamed, alias):
        again = _ledger(opened, state)
        assert again.identity == workspace_identity(renamed)
        assert again.status()["churn_bytes"] == 4
        assert again.status()["unique_paths"] == 1
    fresh = tmp_path / "other"
    fresh.mkdir()
    assert _ledger(fresh, state).identity != ledger.identity
    assert _ledger(fresh, state).status()["churn_bytes"] == 0

    stored = json.loads(again.path.read_text(encoding="utf-8"))
    stored["touched_at"] = 2**31 - 1
    again.path.write_text(json.dumps(stored), encoding="utf-8")
    os.utime(again.path, (10, 10))
    clocked = _ledger(renamed, state)
    assert clocked.status()["churn_bytes"] == 4
    with pytest.raises(LedgerDenied):
        clocked.reserve(EffectCost(("b.txt",), 0, MAX_CHURN_BYTES))

    original = clocked.path.read_bytes()
    clocked.path.write_bytes(b"")
    with pytest.raises(LedgerDenied):
        _ledger(renamed, state).reserve(EffectCost(("b.txt",), 0, 1))
    assert clocked.path.read_bytes() == b""
    clocked.path.write_bytes(b"{")
    with pytest.raises(LedgerDenied):
        _ledger(renamed, state).reserve(EffectCost(("b.txt",), 0, 1))
    assert clocked.path.read_bytes() == b"{"
    clocked.path.write_bytes(original)
    swapped = json.loads(original)
    swapped["identity"] = "not-this-directory"
    clocked.path.write_text(json.dumps(swapped), encoding="utf-8")
    with pytest.raises(LedgerDenied):
        _ledger(renamed, state).status()
    assert json.loads(clocked.path.read_text(encoding="utf-8"))["churn_bytes"] == 4
    link = clocked.path
    payload = link.read_bytes()
    link.unlink()
    other = state / "elsewhere.json"
    other.write_bytes(payload)
    link.symlink_to(other)
    with pytest.raises(LedgerDenied):
        _ledger(renamed, state).reserve(EffectCost(("b.txt",), 0, 1))
    assert other.read_bytes() == payload


def test_registered_crash_seeds_settle_once(tmp_path):
    """100 registered seeds. Each clean crash ends as the old tree or the new tree, once."""
    state = tmp_path / "ledger"
    seen = []
    for seed in range(100):
        root = tmp_path / f"seed-{seed}"
        root.mkdir()
        (root / "a.txt").write_bytes(b"a\n")
        (root / "b.txt").write_bytes(b"b\n")
        (root / "c.txt").write_bytes(b"c\n")
        original = _snap(root)
        staging = prepare_staging(root)
        try:
            (staging.root / "a.txt").write_bytes(b"A\n")
            (staging.root / "b.txt").write_bytes(b"B\n")
            (staging.root / "c.txt").unlink()
            target = _snap(staging.root)
            phase = _PHASES[seed % len(_PHASES)]
            book = _ledger(root, state / str(seed))
            try:
                promote_accounted(staging, measure_changes(staging), ledger=book, crash_at=phase)
            except CrashInjected as exc:
                assert str(exc) == phase
            first = book.reconcile()
            status = book.status()
            second = book.reconcile()
        finally:
            cleanup_staging(staging)
        assert second == "IDLE"
        assert first in {"COMMITTED", "ROLLED_BACK", "IDLE"}
        assert status["uncertain"] is None
        now = _snap(root)
        assert now == original or now == target
        if now == target:
            assert status["delete_ops"] == 1 and status["churn_bytes"] > 0
        else:
            assert status["delete_ops"] == 0 and status["churn_bytes"] == 0
        assert book.reconcile() == "IDLE"
        assert book.status()["churn_bytes"] == status["churn_bytes"]
        seen.append((seed, phase, first, now == target))
    assert [item[0] for item in seen] == list(range(100))
    assert {item[1] for item in seen} == set(_PHASES)


def test_rollback_keeps_human_bytes_and_git_state(tmp_path):
    state = tmp_path / "ledger"
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "tracked.txt").write_text("v1\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt", ".gitignore"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)
    (root / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    (root / "staged.txt").write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "add", "staged.txt"], cwd=root, check=True)
    (root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    (root / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    (root / "target.txt").write_text("old\n", encoding="utf-8")

    def porcelain() -> bytes:
        return subprocess.check_output(["git", "status", "--porcelain=v1", "-uall"], cwd=root)

    def index_bytes(path: str) -> bytes:
        return subprocess.check_output(["git", "show", f":{path}"], cwd=root)

    before_status = porcelain()
    before_index = index_bytes("staged.txt")
    before_tracked = (root / "tracked.txt").read_bytes()
    staging = prepare_staging(root)
    try:
        (staging.root / "target.txt").write_text("new\n", encoding="utf-8")
        book = _ledger(root, state)
        with pytest.raises(CrashInjected):
            promote_accounted(staging, measure_changes(staging), ledger=book, crash_at="after-apply:0")
        (root / "target.txt").write_text("human\n", encoding="utf-8")
        assert book.reconcile() == "UNCERTAIN"
        assert (root / "target.txt").read_text(encoding="utf-8") == "human\n"
        with pytest.raises(LedgerDenied) as blocked:
            book.reserve(EffectCost(("other.txt",), 0, 1))
        assert "uncertain" in str(blocked.value)
        assert book.reconcile() == "UNCERTAIN"
        assert (root / "target.txt").read_text(encoding="utf-8") == "human\n"
    finally:
        cleanup_staging(staging)
    assert porcelain() == before_status
    assert index_bytes("staged.txt") == before_index
    assert (root / "tracked.txt").read_bytes() == before_tracked
    assert (root / "untracked.txt").read_text(encoding="utf-8") == "untracked\n"
    assert (root / "ignored.txt").read_text(encoding="utf-8") == "ignored\n"
    with pytest.raises(LedgerDenied):
        book.user_reset("please")
    assert book.status()["uncertain"]
    book.user_reset(RESET_PHRASE)
    assert book.status()["uncertain"] is None
    assert book.status()["churn_bytes"] == 0


def test_a_failed_backup_does_not_mutate_and_a_bad_backup_blocks(tmp_path, monkeypatch):
    state = tmp_path / "ledger"
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    staging = prepare_staging(root)
    try:
        (staging.root / "a.txt").write_text("b\n", encoding="utf-8")
        book = _ledger(root, state)
        book.backup_root.mkdir(parents=True)
        book.backup_root.chmod(0o500)
        with pytest.raises(LedgerDenied):
            promote_accounted(staging, measure_changes(staging), ledger=book)
        assert (root / "a.txt").read_text(encoding="utf-8") == "a\n"
        assert book.status()["open"] is False
        assert book.status()["churn_bytes"] == 0
    finally:
        book.backup_root.chmod(0o700)
        cleanup_staging(staging)

    root2 = tmp_path / "restore"
    root2.mkdir()
    (root2 / "a.txt").write_text("a\n", encoding="utf-8")
    (root2 / "b.txt").write_text("b\n", encoding="utf-8")
    staging = prepare_staging(root2)
    try:
        (staging.root / "a.txt").write_text("A\n", encoding="utf-8")
        (staging.root / "b.txt").write_text("B\n", encoding="utf-8")
        book = _ledger(root2, state / "two")
        with pytest.raises(CrashInjected):
            promote_accounted(staging, measure_changes(staging), ledger=book,
                              crash_at="after-mark-applied:0")
        backup = next(book.backup_root.rglob("a.txt"))
        backup.write_bytes(b"tampered\n")
        assert book.reconcile() == "UNCERTAIN"
        assert (root2 / "a.txt").read_text(encoding="utf-8") == "A\n"
        assert (root2 / "b.txt").read_text(encoding="utf-8") == "b\n"
        with pytest.raises(LedgerDenied):
            book.reserve(EffectCost(("a.txt",), 0, 1))
    finally:
        cleanup_staging(staging)

    root3 = tmp_path / "missing"
    root3.mkdir()
    (root3 / "a.txt").write_text("a\n", encoding="utf-8")
    (root3 / "b.txt").write_text("b\n", encoding="utf-8")
    staging = prepare_staging(root3)
    try:
        (staging.root / "a.txt").write_text("A\n", encoding="utf-8")
        (staging.root / "b.txt").write_text("B\n", encoding="utf-8")
        book = _ledger(root3, state / "three")
        with pytest.raises(CrashInjected):
            promote_accounted(staging, measure_changes(staging), ledger=book,
                              crash_at="after-mark-applied:0")
        next(book.backup_root.rglob("a.txt")).unlink()
        assert book.reconcile() == "UNCERTAIN"
        assert (root3 / "a.txt").read_text(encoding="utf-8") == "A\n"
        with pytest.raises(LedgerDenied):
            book.reserve(EffectCost(("c.txt",), 0, 1))
    finally:
        cleanup_staging(staging)


def _namespace_works() -> bool:
    sandbox = sandbox_executable()
    if sandbox is None:
        return False
    args = [sandbox, "--die-with-parent", "--unshare-all", "--share-net", "--ro-bind", "/usr", "/usr"]
    for source, destination, alias in (("/bin", "/bin", "/usr/bin"), ("/lib", "/lib", "/usr/lib"),
                                       ("/lib64", "/lib64", "/usr/lib64")):
        if Path(source).is_symlink():
            args.extend(["--symlink", alias, destination])
        elif Path(source).exists():
            args.extend(["--ro-bind", source, destination])
    args.extend(["--proc", "/proc", "--dev", "/dev", "--", "/usr/bin/true"])
    try:
        completed = subprocess.run(args, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


@pytest.mark.skipif(not _namespace_works(), reason="bubblewrap cannot create a namespace here")
def test_sandbox_cannot_remove_the_ledger(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    state = tmp_path / "state"
    ledger = _ledger(root, state)
    _commit_one(ledger, "a.txt", deletes=0, churn=2)
    payload = ledger.path.read_bytes()
    script = root / "poke.sh"
    script.write_text("#!/bin/sh\nrm -f \"$1\"\necho done\n", encoding="utf-8")
    script.chmod(0o755)
    sandbox = sandbox_executable()
    assert sandbox is not None
    args = sandbox_command(sandbox, root, "/workspace/poke.sh", ("./poke.sh", str(ledger.path)), ".", ())
    mounted = args[:args.index("--")]
    assert str(state) not in mounted
    assert str(ledger.path) not in mounted
    completed = subprocess.run(args, capture_output=True, timeout=20, check=False)
    assert completed.returncode == 0
    assert ledger.path.read_bytes() == payload


def test_over_limit_keeps_the_approval_and_the_model_cannot_reset(tmp_path, monkeypatch):
    import isycode.effect_ledger as module
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(module, "MAX_CHURN_PER_OPERATION", 4)
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("hi\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    owner = WorkspaceWriteOwner(root, authority, approvals)
    authority.set_grant("workspace.files.write", enabled=True, path_prefixes=[root])
    preview = owner.preview("src/app.py", "hello\n")
    approval = approvals.issue(preview.request)
    denied = owner.apply(preview, approval)
    assert denied.decision == "DENY"
    assert "ledger has" in denied.reason
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "hi\n"
    monkeypatch.setattr(module, "MAX_CHURN_PER_OPERATION", 32 * 1024 * 1024)
    allowed = owner.apply(preview, approval)
    assert allowed.decision == "ALLOW", allowed.reason
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "hello\n"
    book = EffectLedger(root)
    assert book.status()["churn_bytes"] > 0

    authority.set_grant("workspace.files.delete", enabled=True, path_prefixes=[root])
    monkeypatch.setattr(module, "MAX_DELETE_OPS", 1)
    deletion = owner.preview_delete("src/app.py")
    assert owner.apply(deletion, approvals.issue(deletion.request)).decision == "ALLOW"
    (root / "src" / "other.py").write_text("x\n", encoding="utf-8")
    again = owner.preview_delete("src/other.py")
    blocked = owner.apply(again, approvals.issue(again.request))
    assert blocked.decision == "DENY" and "ledger has" in blocked.reason
    assert (root / "src" / "other.py").read_text(encoding="utf-8") == "x\n"
    assert book.status()["delete_ops"] == 1

    catalog = " ".join(ACTION_BY_ID)
    assert "effect" not in catalog or "reset" not in catalog
    assert not any("reset" in action_id for action_id in ACTION_BY_ID)
    tui = Path(importlib.util.find_spec("isycode.tui").origin).read_text(encoding="utf-8")
    assert "user_reset" not in tui and "effect_ledger" not in tui
    assert not hasattr(module.EffectLedger, "set_limits")


def test_a_command_over_the_cap_is_not_promoted(tmp_path, monkeypatch):
    import isycode.effect_ledger as module
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(module, "MAX_CHURN_PER_OPERATION", 1)
    spec = importlib.util.spec_from_file_location(
        "isycode_fake_bwrap", Path(__file__).with_name("test_command_runner.py"))
    fake_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fake_module)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "bwrap"
    fake.write_text(fake_module.FAKE_BWRAP.format(python=Path(sys.executable).resolve()), encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_BWRAP_LOG", str(tmp_path / "bwrap.json"))
    root = tmp_path / "project"
    root.mkdir()
    (root / ".isyroot").write_text("id\n", encoding="utf-8")
    (root / "app.py").write_text("keep\n", encoding="utf-8")
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    approvals = ActionApprovalStore()
    owner = CommandRunOwner(root, authority, approvals)
    sandbox = sandbox_executable()
    authority.set_grant("workspace.command.run", enabled=True, executables=[sandbox])
    preview = owner.prepare(["python3", "-c", "open('app.py','w').write('changed\\n')"])
    outcome = asyncio.run(owner.run(preview, approvals.issue(preview.request)))
    assert outcome.decision == "ALLOW", outcome.reason
    body = json.loads(outcome.text)
    assert body["exit_code"] == 0
    assert body["staging"]["promotion"]["state"] == "denied"
    assert "ledger has" in body["staging"]["promotion"]["reason"]
    assert body["staging"]["promoted_count"] == 0
    assert (root / "app.py").read_text(encoding="utf-8") == "keep\n"
    assert "not promoted" in outcome.reason
