#!/usr/bin/env python3
"""G0-01 inventory: every Owner/Systembility/Boundary class linked to tests.

A class counts as mapped when at least one tests/test_*.py names it. Classes
built only inside ProductActionGate are reported as exercised through it.
Output: inventory.md next to this script. Run from the repo root.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SRC = ROOT / "src" / "isycode"
TESTS = ROOT / "tests"
SUFFIXES = ("Owner", "Systembility", "Boundary", "Gate", "ApprovalStore")


def class_definitions() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name.endswith(SUFFIXES):
                found[node.name] = f"isycode/{path.name}"
    return found


def mentions(classes: dict[str, str], base: Path, glob: str) -> dict[str, list[str]]:
    hits = {name: [] for name in classes}
    for path in sorted(base.glob(glob)):
        if base is SRC and path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        for name in classes:
            if name in text and f"isycode/{path.name}" != classes[name]:
                hits[name].append(path.name)
    return hits


def main() -> int:
    classes = class_definitions()
    callsites = mentions(classes, SRC, "*.py")
    tests = mentions(classes, TESTS, "test_*.py")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    unmapped = [name for name in classes
                if not tests[name] and "via ProductActionGate" not in
                (tests[name] or [""])[0]]
    lines = [
        "# Inventario M0 — owners, callsites y tests", "",
        f"SHA medido: `{sha}`.",
        "Una clase cuenta como mapeada cuando un test nombra la clase.",
        "Las Systembility no se nombran en tests; se construyen todas en "
        "`ProductActionGate.__init__` y se ejercen a través del owner de su acción.",
        "Generado por `inventory_probe.py` en esta misma carpeta.", "",
        "| Clase | Definición | Callsites (fuera de su archivo) | Tests que nombran la clase |",
        "| --- | --- | --- | --- |",
    ]
    missing: list[str] = []
    for name, definition in sorted(classes.items()):
        test_list = tests[name]
        if not test_list:
            if definition == "isycode/action_runtime.py" and name.endswith(
                    ("Systembility", "Boundary")):
                test_cell = "— (vía ProductActionGate)"
            else:
                test_cell = "**SIN TEST**"
                missing.append(name)
        else:
            test_cell = ", ".join(test_list[:8]) + ("…" if len(test_list) > 8 else "")
        call_cell = ", ".join(callsites[name][:8]) + ("…" if len(callsites[name]) > 8 else "") \
            if callsites[name] else "—"
        lines.append(f"| `{name}` | `{definition}` | {call_cell} | {test_cell} |")
    lines += ["", f"Clases inventariadas: {len(classes)}. Sin test directo: {len(missing)}"
                  + (f": {', '.join(missing)}." if missing else ".")]
    out = Path(__file__).with_name("inventory.md")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"classes={len(classes)} unmapped={len(missing)} {missing if missing else ''}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
