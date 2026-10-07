"""Gate documents are historical records, not release approvals."""
import hashlib
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _validator():
    spec = importlib.util.spec_from_file_location("validate_gates", ROOT / "scripts/validate_gates.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_gate(root: Path, *, sha="a" * 40, state="EN_REVISION", result="PASS",
                artifacts=True) -> Path:
    folder = root / "docs/evidence/classic-security-ux/M6" / sha
    folder.mkdir(parents=True, exist_ok=True)
    payload = b"real evidence\n"
    (folder / "output.txt").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    cases = "".join(
        f"  - id: G6-{i:02d}\n    resultado: {result}\n" +
        (f"    artefactos:\n      - output.txt\n        sha256: {digest}\n" if artifacts else "")
        for i in range(1, 6))
    path = folder / "gate.yaml"
    path.write_text(f"hito: M6\npuerta: G6\nestado: {state}\nsha_evaluado: {sha}\n"
                    f"revision: ausente\ncasos:\n{cases}", encoding="utf-8")
    return path


def test_self_test_rejects_bad_documents():
    assert _validator().self_test() == []


def test_historical_review_records_are_valid_but_do_not_approve_release():
    validator = _validator()
    assert validator.validate_tree(ROOT) == []
    errors = validator.validate_tree(ROOT, require_approved=True)
    assert errors and any("EN_REVISION" in error for error in errors)
    assert any("revision" in error.lower() for error in errors)


def test_artifact_missing_and_hash_mismatch_are_rejected(tmp_path):
    validator = _validator()
    gate = _write_gate(tmp_path)
    assert validator.validate_tree(tmp_path) == []
    artifact = gate.parent / "output.txt"
    artifact.rename(gate.parent / "saved.txt")
    assert any("missing" in error for error in validator.validate_tree(tmp_path))
    artifact.write_bytes(b"tampered\n")
    assert any("mismatch" in error for error in validator.validate_tree(tmp_path))


@pytest.mark.parametrize("result", ["FAIL", "UNKNOWN", "SKIP"])
def test_failed_required_case_is_not_a_green_gate(tmp_path, result):
    _write_gate(tmp_path, result=result)
    errors = _validator().validate_tree(tmp_path)
    assert any(result in error for error in errors)


def test_review_without_artifact_hash_cannot_release(tmp_path):
    validator = _validator()
    gate = _write_gate(tmp_path)
    text = gate.read_text().replace("resultado: PASS", "resultado: EN_REVISION")
    text = "\n".join(line for line in text.splitlines() if "sha256:" not in line) + "\n"
    gate.write_text(text)
    assert validator.validate_tree(tmp_path) == []
    errors = validator.validate_tree(tmp_path, require_approved=True)
    assert any("sha256" in error for error in errors)


def test_pass_case_needs_evidence(tmp_path):
    _write_gate(tmp_path, artifacts=False)
    assert any("artifact" in error for error in _validator().validate_tree(tmp_path))


@pytest.mark.parametrize("kind", ["escape", "symlink", "conflicting_hash"])
def test_artifacts_cannot_escape_or_hide_conflicting_digests(tmp_path, kind):
    gate = _write_gate(tmp_path)
    text = gate.read_text()
    if kind == "escape":
        text = text.replace("- output.txt", "- ../../../../../../../outside.txt")
    elif kind == "symlink":
        (gate.parent / "output.txt").rename(gate.parent / "saved.txt")
        (gate.parent / "output.txt").symlink_to(gate.parent / "saved.txt")
    else:
        digest = hashlib.sha256(b"real evidence\n").hexdigest()
        text = text.replace(digest, "b" * 64, 1)
    gate.write_text(text)
    assert _validator().validate_tree(tmp_path)


def test_full_but_nonexistent_commit_is_rejected_in_a_git_checkout(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _write_gate(tmp_path, sha="f" * 40)
    assert any("commit" in error for error in _validator().validate_tree(tmp_path))


def test_case_results_stay_bound_to_their_own_ids():
    with pytest.raises(ValueError):
        _validator().document_from_text(
            "hito: M6\ncasos:\n  - id: G6-01\n  - id: G6-02\n"
            "    resultado: PASS\n    resultado: FAIL\n")


def test_foreign_folder_sha_omitted_case_and_self_approval_are_rejected(tmp_path):
    gate = _write_gate(tmp_path)
    gate.write_text(gate.read_text().replace("sha_evaluado: " + "a" * 40,
                                          "sha_evaluado: " + "b" * 40))
    assert any("does not match" in error for error in _validator().validate_tree(tmp_path))
    gate = _write_gate(tmp_path)
    gate.write_text(gate.read_text().replace("id: G6-05", "id: G6-99"))
    assert any("omitted required tests" in error for error in _validator().validate_tree(tmp_path))
    _write_gate(tmp_path, state="APROBADO")
    assert any("revision: aceptada" in error for error in _validator().validate_tree(tmp_path))


def test_self_approval_is_rejected_and_independent_acceptance_passes(tmp_path):
    validator = _validator()
    gate = _write_gate(tmp_path, state="APROBADO")
    text = gate.read_text()
    acceptance = ("autor: agent session x\nrevision: aceptada\nrevisor: danny\n"
                  "revision_fecha_utc: 2026-10-05T00:00:00Z\n")
    gate.write_text(text.replace("revision: ausente\n", acceptance))
    assert validator.validate_tree(tmp_path) == []
    gate.write_text(gate.read_text().replace("revisor: danny", "revisor: agent session x"))
    assert any("revisor must be different" in error for error in validator.validate_tree(tmp_path))


def test_cli_accepts_the_explicit_release_check():
    assert _validator().main(["--root", str(ROOT), "--require-approved"]) == 1
