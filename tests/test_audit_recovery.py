"""Crash and rollback regressions from the repository audit."""
import json
import os
import subprocess
import sys

import pytest

from isycode.effect_ledger import CrashInjected, EffectLedger
from isycode.staging import cleanup_staging, measure_changes, prepare_staging, promote_accounted


def test_rollback_keeps_the_original_file_mode(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_bytes(b"old\n")
    (root / "a.txt").chmod(0o751)
    (root / "b.txt").write_bytes(b"b\n")
    stage = prepare_staging(root)
    try:
        (stage.root / "a.txt").write_bytes(b"new\n")
        (stage.root / "b.txt").write_bytes(b"B\n")
        book = EffectLedger(root, state_directory=tmp_path / "ledger")
        with pytest.raises(CrashInjected):
            promote_accounted(stage, measure_changes(stage), ledger=book, crash_at="before-apply:1")
        assert book.reconcile() == "ROLLED_BACK"
        assert (root / "a.txt").read_bytes() == b"old\n"
        assert (root / "a.txt").stat().st_mode & 0o777 == 0o751
    finally:
        cleanup_staging(stage)


def test_typed_delete_crash_never_reports_a_free_rollback(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "victim.txt").write_bytes(b"keep\n")
    script = """
import os,sys
from pathlib import Path
from isycode.approvals import ActionApprovalStore
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_write import WorkspaceWriteOwner
root=Path(sys.argv[1])
authority=WorkspaceAuthority(root)
authority.set_mode('classic')
approvals=ActionApprovalStore()
owner=WorkspaceWriteOwner(root,authority,approvals)
preview=owner.preview_delete('victim.txt')
remove=owner._remove
def crash(*args,**kwargs):
 remove(*args,**kwargs)
 os._exit(86)
owner._remove=crash
owner.apply(preview,approvals.issue(preview.request))
"""
    env = {**os.environ, "ISYCODE_STATE_HOME": str(tmp_path / "state"),
           "PYTHONPATH": str(__import__('pathlib').Path(__file__).resolve().parents[1] / "src")}
    child = subprocess.run([sys.executable, "-B", "-c", script, str(root)], env=env, timeout=15)
    assert child.returncode == 86
    book = EffectLedger(root, state_directory=tmp_path / "state/effect-ledger")
    outcome = book.reconcile()
    assert outcome in {"COMMITTED", "ROLLED_BACK", "UNCERTAIN"}
    status = book.status()
    assert (root / "victim.txt").exists() or status["delete_ops"] == 1 or status["uncertain"]
