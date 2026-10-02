"""G1-04 local half: bad gate documents fail, and the checked-in tree does not."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _validator():
    path = ROOT / "scripts" / "validate_gates.py"
    spec = importlib.util.spec_from_file_location("validate_gates", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_self_test_rejects_missing_foreign_omitted_false_and_bypass_documents():
    assert _validator().self_test() == []


def test_checked_in_evidence_matches_its_folder_sha():
    errors = _validator().validate_tree(ROOT)
    assert errors == []


def test_foreign_sha_omitted_case_and_approval_are_rejected(tmp_path: Path):
    validator = _validator()
    folder = tmp_path / "docs" / "evidence" / "classic-security-ux" / "M1" / ("b" * 40)
    folder.mkdir(parents=True)
    (folder / "gate.yaml").write_text(
        "hito: M1\n"
        "puerta: G1\n"
        "estado: EN_REVISION\n"
        f"sha_evaluado: {'a' * 40}\n"
        "casos:\n"
        "  - id: G1-01\n"
        "    resultado: PASS\n",
        encoding="utf-8",
    )
    errors = validator.validate_tree(tmp_path)
    assert any("does not match" in item for item in errors)
    assert any("omitted required tests" in item for item in errors)

    approved = tmp_path / "docs" / "evidence" / "classic-security-ux" / "M9" / ("c" * 40)
    approved.mkdir(parents=True)
    cases = "\n".join(
        f"  - id: G9-{number:02d}\n    resultado: PASS" for number in range(1, 7))
    (approved / "gate.yaml").write_text(
        "hito: M9\n"
        "puerta: G9\n"
        "estado: APROBADO\n"
        f"sha_evaluado: {'c' * 40}\n"
        "dependencias: ninguna\n"
        "casos:\n"
        f"{cases}\n",
        encoding="utf-8",
    )
    approved_errors = validator.validate_tree(tmp_path)
    assert any("APROBADO is rejected" in item for item in approved_errors)
