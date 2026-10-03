#!/usr/bin/env python3
"""Check historical gate documents without confusing review with approval.

The legacy gate files use a small YAML-like dialect (artifact path followed by
an indented sha256), not valid general YAML. Parse that dialect explicitly.
--require-approved is fail-closed: no independent approval mechanism has been
established yet, so this checker cannot authorize a product release.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
CASE_ID = re.compile(r"^G[0-9]+A?-[0-9]{2}$")
RESULTS = {"PASS", "FAIL", "UNKNOWN", "SKIP", "EN_REVISION"}
STATES = {"PENDIENTE", "EN_CURSO", "BLOQUEADO", "EN_REVISION", "APROBADO", "REABIERTO"}
REQUIRED = ("hito", "puerta", "estado", "sha_evaluado", "casos")
REQUIRED_BY_GATE = {
    gate: {f"{gate}-{number:02d}" for number in range(1, count + 1)}
    for gate, count in (("G0", 4), ("G1", 4), ("G2", 5), ("G3", 6),
                        ("G4", 5), ("G5", 5), ("G6", 5), ("G6A", 8),
                        ("G7", 5), ("G8", 5), ("G9", 6), ("G10", 4))
}


def document_from_text(text: str) -> dict:
    """Bind each result and artifact to its own case; reject duplicate fields."""
    document: dict = {}
    cases: list[dict] = []
    case = None
    artifact = None
    artifact_indent = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if indent == 0:
            case = artifact = artifact_indent = None
            if ":" not in line:
                raise ValueError("invalid root field")
            key, value = line.split(":", 1)
            if key in REQUIRED or key in {"revision", "dependencias"}:
                if key in document:
                    raise ValueError(f"duplicate field {key}")
                document[key] = value.strip()
            continue
        match = re.fullmatch(r"-\s+id:\s*(\S+)", line)
        if indent == 2 and match:
            case = {"id": match.group(1), "artefactos": []}
            cases.append(case)
            artifact = artifact_indent = None
            continue
        if case is None:
            continue
        if indent == 4 and line.startswith("resultado:"):
            if "resultado" in case:
                raise ValueError("duplicate case resultado")
            case["resultado"] = line.split(":", 1)[1].strip()
        if indent == 4 and line == "artefactos:":
            artifact_indent = indent
            artifact = None
            continue
        if artifact_indent is not None and indent <= artifact_indent:
            artifact_indent = None
            artifact = None
        if artifact_indent is not None:
            if line.startswith("- "):
                artifact = {"path": line[2:].strip()}
                case["artefactos"].append(artifact)
            elif artifact is not None and line.startswith("sha256:"):
                if "sha256" in artifact:
                    raise ValueError("duplicate artifact sha256")
                artifact["sha256"] = line.split(":", 1)[1].strip()
    if any("resultado" not in item for item in cases):
        raise ValueError("each case needs one resultado")
    document["casos"] = cases
    return document


def validate_document(document: dict, *, required_ids: set[str] | None = None,
                      dependency_states: dict[str, str] | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["document is not a mapping"]
    errors.extend(f"missing {key}" for key in REQUIRED if key not in document)
    state = document.get("estado")
    if state not in STATES:
        errors.append("estado is not a gate state")
    if not SHA.fullmatch(str(document.get("sha_evaluado", ""))):
        errors.append("sha_evaluado must be the full 40-character commit")
    cases = document.get("casos")
    if not isinstance(cases, list) or not cases:
        errors.append("casos must be a non-empty list")
        cases = []
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            errors.append("case is not a mapping")
            continue
        case_id = str(case.get("id", ""))
        if not CASE_ID.fullmatch(case_id):
            errors.append(f"bad case id {case_id!r}")
        if case_id in seen:
            errors.append(f"duplicate case id {case_id}")
        seen.add(case_id)
        result = case.get("resultado")
        if result not in RESULTS:
            errors.append(f"{case_id} result is missing or unknown")
        elif result in {"FAIL", "UNKNOWN", "SKIP"} or (state == "APROBADO" and result != "PASS"):
            errors.append(f"{case_id} blocks the gate because its result is {result}")
    if required_ids and required_ids - seen:
        errors.append("omitted required tests: " + ", ".join(sorted(required_ids - seen)))
    if state == "APROBADO":
        for name, claimed in (document.get("dependencias_estado") or {}).items():
            if (dependency_states or {}).get(name, claimed) != "APROBADO":
                errors.append(f"false dependency approval: {name}")
    return errors


def _artifact_errors(root: Path, folder: Path, case: dict, *, strict: bool) -> list[str]:
    artifacts = case.get("artefactos") or []
    if not artifacts:
        return [f"{case['id']} has no artifact evidence"] if strict else []
    errors = []
    for artifact in artifacts:
        name = artifact["path"]
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            errors.append("artifact path escapes the repository")
            continue
        path = root / relative if relative.parts[0] in {"docs", "scripts", "tests", "src"} else folder / relative
        try:
            walked = root
            for part in path.relative_to(root).parts:
                walked /= part
                if walked.is_symlink():
                    raise ValueError("symlink artifact")
            if not path.is_file():
                raise ValueError("missing artifact")
            expected = artifact.get("sha256")
            if expected is None and not strict:
                continue  # Historical reference on a case still EN_REVISION.
            if not re.fullmatch(r"[0-9a-f]{64}", str(expected or "")):
                errors.append(f"artifact {name!r} has no valid sha256")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                errors.append(f"artifact {name!r} sha256 mismatch")
        except (OSError, ValueError) as exc:
            errors.append(f"artifact {name!r}: {exc}")
    return errors


def validate_tree(root: Path, *, require_approved: bool = False) -> list[str]:
    root = root.resolve()
    evidence = root / "docs/evidence/classic-security-ux"
    files = sorted(evidence.glob("M*/**/gate.yaml"))
    if not files:
        return ["missing gate.yaml evidence files"]
    errors = []
    for path in files:
        try:
            document = document_from_text(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        found = validate_document(document, required_ids=REQUIRED_BY_GATE.get(str(document.get("puerta", ""))))
        if document.get("puerta") not in REQUIRED_BY_GATE:
            found.append("unknown gate")
        if document.get("sha_evaluado") != path.parent.name:
            found.append("folder sha does not match sha_evaluado")
        if document.get("hito") != path.parent.parent.name:
            found.append("hito does not match milestone folder")
        sha = str(document.get("sha_evaluado", ""))
        if SHA.fullmatch(sha) and (root / ".git").exists():
            result = subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=root,
                                    capture_output=True, timeout=10)
            if result.returncode:
                found.append("evaluated commit is absent from this checkout; fetch its history")
        for case in document.get("casos", []):
            found.extend(_artifact_errors(root, path.parent, case,
                         strict=require_approved or case.get("resultado") == "PASS"))
        if document.get("estado") == "APROBADO":
            found.append("APROBADO is rejected until independent reviewer acceptance is implemented")
        if require_approved:
            if document.get("estado") != "APROBADO":
                found.append(f"release blocked: gate is {document.get('estado')}, not APROBADO")
            found.append("release blocked: independent revision acceptance is not established")
        errors.extend(f"{path}: {error}" for error in found)
    return errors


def self_test() -> list[str]:
    base = {"hito": "M1", "puerta": "G1", "estado": "EN_REVISION",
            "sha_evaluado": "a" * 40, "casos": [{"id": "G1-01", "resultado": "PASS"}]}
    fixtures = [{}, {**base, "sha_evaluado": "bad"},
                *[{**base, "casos": [{"id": "G1-01", "resultado": result}]}
                  for result in ("FAIL", "UNKNOWN", "SKIP")]]
    failures = ["invalid fixture accepted" for fixture in fixtures if not validate_document(fixture)]
    if not validate_document(base, required_ids={"G1-01", "G1-04"}):
        failures.append("omitted required test accepted")
    if validate_document(base):
        failures.append("review record rejected")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args(argv)
    errors = self_test() if args.self_test else validate_tree(Path(args.root), require_approved=args.require_approved)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("gate validator self-test passed" if args.self_test else "historical gate evidence checked; no gate approved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
