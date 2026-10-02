#!/usr/bin/env python3
"""Validate Classic/Security gate evidence. A bad manifest is a failure.

The script checks documents. It does not grant product authority and it does
not treat EN_REVISION as approved. Remote branch protection is recorded by the
operator; this script cannot see GitHub settings unless --require-approved
is passed for a release check.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # The evidence files are a small YAML subset written by hand.
    yaml = None

SHA = re.compile(r"^[0-9a-f]{40}$")
CASE_ID = re.compile(r"^G[0-9]+A?-[0-9]{2}$")
RESULTS = {"PASS", "FAIL", "UNKNOWN", "SKIP", "EN_REVISION"}
STATES = {"PENDIENTE", "EN_CURSO", "BLOQUEADO", "EN_REVISION", "APROBADO", "REABIERTO"}
REQUIRED = ("hito", "puerta", "estado", "sha_evaluado", "casos")
REQUIRED_BY_GATE = {
    "G0": {f"G0-{number:02d}" for number in range(1, 5)},
    "G1": {f"G1-{number:02d}" for number in range(1, 5)},
    "G2": {f"G2-{number:02d}" for number in range(1, 6)},
    "G3": {f"G3-{number:02d}" for number in range(1, 7)},
    "G4": {f"G4-{number:02d}" for number in range(1, 6)},
    "G5": {f"G5-{number:02d}" for number in range(1, 6)},
    "G6": {f"G6-{number:02d}" for number in range(1, 6)},
    "G6A": {f"G6A-{number:02d}" for number in range(1, 9)},
    "G7": {f"G7-{number:02d}" for number in range(1, 6)},
    "G8": {f"G8-{number:02d}" for number in range(1, 6)},
    "G9": {f"G9-{number:02d}" for number in range(1, 7)},
    "G10": {f"G10-{number:02d}" for number in range(1, 5)},
}


def _parse(text: str) -> dict:
    if yaml is not None:
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, dict):
            raise ValueError("gate document must be a mapping")
        return loaded
    return _tiny_yaml(text)


def _tiny_yaml(text: str) -> dict:
    """Parse the gate documents this repo writes. Not a general YAML parser."""
    root: dict = {}
    stack: list[tuple[int, object]] = [(-1, root)]
    current_case: dict | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            item = line[2:].strip()
            if isinstance(parent, dict) and "casos" in parent and parent.get("_open_list") == "casos":
                current_case = {}
                parent["casos"].append(current_case)
                if ":" in item:
                    key, value = item.split(":", 1)
                    current_case[key.strip()] = _scalar(value.strip())
                stack.append((indent, current_case))
                continue
            if isinstance(parent, dict):
                raise ValueError(f"list item without a list: {line}")
            parent.append(_scalar(item) if ":" not in item else item)
            continue
        if ":" not in line:
            raise ValueError(f"expected key: {line}")
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if value == "":
            container: object = [] if key in {"casos", "artefactos", "skips", "deselected_integration", "sin_evidencia_real"} else {}
            if isinstance(parent, dict):
                parent[key] = container
                if key == "casos":
                    parent["_open_list"] = "casos"
            stack.append((indent, container if not isinstance(container, dict) else parent))
            if isinstance(container, dict):
                stack[-1] = (indent, container)
                parent[key] = container
            continue
        if isinstance(parent, dict):
            parent[key] = _scalar(value)
        elif isinstance(parent, list) and current_case is not None and parent and parent[-1] is current_case:
            current_case[key] = _scalar(value)
        else:
            raise ValueError(f"cannot place {key}")
    root.pop("_open_list", None)
    return root


def _scalar(value: str):
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith(">") or value.startswith("|"):
        return value
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def validate_document(document: dict, *, required_ids: set[str] | None = None,
                      dependency_states: dict[str, str] | None = None) -> list[str]:
    """Return human-readable errors. An empty list means the document is usable."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["document is not a mapping"]
    for key in REQUIRED:
        if key not in document:
            errors.append(f"missing {key}")
    state = str(document.get("estado", ""))
    if state not in STATES:
        errors.append(f"estado {state!r} is not a gate state")
    sha = str(document.get("sha_evaluado", ""))
    if not SHA.fullmatch(sha):
        errors.append("sha_evaluado must be the full 40-character commit")
    cases = document.get("casos")
    if not isinstance(cases, list) or not cases:
        errors.append("casos must be a non-empty list")
        cases = []
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            errors.append("case is not a mapping")
            continue
        case_id = str(case.get("id", ""))
        if not CASE_ID.fullmatch(case_id):
            errors.append(f"bad case id {case_id!r}")
        elif case_id in seen:
            errors.append(f"duplicate case id {case_id}")
        seen.add(case_id)
        result = str(case.get("resultado", ""))
        if result not in RESULTS:
            errors.append(f"{case_id or '?'} resultado {result!r} is missing or unknown")
        if state == "APROBADO" and result != "PASS":
            errors.append(f"{case_id} blocks approval because its result is {result or 'missing'}")
    if required_ids:
        missing = sorted(required_ids - seen)
        if missing:
            errors.append("omitted required tests: " + ", ".join(missing))
    if state == "APROBADO":
        deps = document.get("dependencias_estado")
        if not isinstance(deps, dict) or not deps:
            if document.get("dependencias") not in (None, "ninguna", "Ninguna"):
                errors.append("approved gate needs dependencias_estado for every dependency")
        else:
            for name, dep_state in deps.items():
                observed = (dependency_states or {}).get(str(name), str(dep_state))
                if observed != "APROBADO":
                    errors.append(f"dependency {name} is {observed}, not APROBADO")
        if dependency_states is not None:
            for name, dep_state in (document.get("dependencias_estado") or {}).items():
                if dependency_states.get(str(name), dep_state) != "APROBADO":
                    errors.append(f"false dependency approval: {name}")
    return errors


def document_from_text(text: str) -> dict:
    """Read the fields this repository's gate files actually use."""
    estado = re.search(r"(?m)^estado:\s*([A-Z_]+)\s*$", text)
    sha = re.search(r"(?m)^sha_evaluado:\s*([0-9a-fA-F]+)\s*$", text)
    hito = re.search(r"(?m)^hito:\s*(\S+)\s*$", text)
    puerta = re.search(r"(?m)^puerta:\s*(\S+)\s*$", text)
    ids = re.findall(r"(?m)^[ \t]*(?:-[ \t]*)?id:\s*(\S+)\s*$", text)
    results = re.findall(r"(?m)^[ \t]*(?:-[ \t]*)?resultado:\s*(\S+)\s*$", text)
    if len(ids) != len(results):
        raise ValueError("each case needs one resultado")
    return {
        "hito": hito.group(1) if hito else "",
        "puerta": puerta.group(1) if puerta else "",
        "estado": estado.group(1) if estado else "",
        "sha_evaluado": sha.group(1).lower() if sha else "",
        "casos": [{"id": case_id, "resultado": result} for case_id, result in zip(ids, results)],
        "dependencias": "ninguna" if re.search(r"(?m)^dependencias:\s*ninguna\s*$", text) else None,
    }


def validate_tree(root: Path) -> list[str]:
    errors: list[str] = []
    evidence = root / "docs" / "evidence" / "classic-security-ux"
    if not evidence.is_dir():
        return ["missing docs/evidence/classic-security-ux"]
    files = sorted(evidence.glob("M*/**/gate.yaml"))
    if not files:
        return ["no gate.yaml evidence files"]
    for path in files:
        try:
            document = document_from_text(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        folder_sha = path.parent.name
        if document.get("sha_evaluado") != folder_sha:
            errors.append(f"{path}: folder sha {folder_sha} does not match sha_evaluado")
        puerta = str(document.get("puerta", ""))
        required_ids = REQUIRED_BY_GATE.get(puerta)
        if required_ids is None:
            errors.append(f"{path}: unknown gate {puerta!r}")
        errors.extend(
            f"{path}: {item}" for item in validate_document(document, required_ids=required_ids))
        if document.get("estado") == "APROBADO":
            errors.append(f"{path}: APROBADO is rejected until a second reviewer records it")
    return errors


def self_test() -> list[str]:
    """Negative documents that must be rejected. Returns failures of the checker."""
    failures: list[str] = []

    def expect_reject(label: str, document: dict, **kwargs) -> None:
        found = validate_document(document, **kwargs)
        if not found:
            failures.append(f"{label} was accepted")

    base = {
        "hito": "M1", "puerta": "G1", "estado": "EN_REVISION",
        "sha_evaluado": "a" * 40,
        "casos": [{"id": "G1-01", "resultado": "PASS"}],
    }
    expect_reject("missing manifest fields", {})
    expect_reject("foreign sha", {**base, "sha_evaluado": "deadbeef"})
    expect_reject("omitted test", base, required_ids={"G1-01", "G1-04"})
    expect_reject("false dependency", {
        **base, "estado": "APROBADO",
        "casos": [{"id": "G1-01", "resultado": "PASS"}],
        "dependencias_estado": {"G0": "APROBADO"},
    }, dependency_states={"G0": "EN_REVISION"})
    expect_reject("bypass with failing case", {
        **base, "estado": "APROBADO",
        "casos": [{"id": "G1-01", "resultado": "FAIL"}],
        "dependencias": "ninguna",
    })
    good = validate_document(base)
    if good:
        failures.append("valid review document was rejected: " + "; ".join(good))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        failures = self_test()
        if failures:
            print("\n".join(failures), file=sys.stderr)
            return 1
        print("gate validator self-test passed")
        return 0
    errors = validate_tree(Path(args.root))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    digest = hashlib.sha256(Path(args.root, "scripts/validate_gates.py").read_bytes()).hexdigest()
    print(f"gate evidence checked; validator sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
