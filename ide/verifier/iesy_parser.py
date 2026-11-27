"""
verifier/iesy_parser.py -- parser minimo y especifico (NO generico)
para archivos .iesy. Su unico trabajo: extraer los nombres de las
leyes declaradas bajo 'Laws:' en el orden en que aparecen. No
interpreta 'Regla:' ni ningun otro campo -- esa semantica sigue
viviendo en los checkers escritos a mano.
"""
from __future__ import annotations

import re
from pathlib import Path

LAW_NAME_RE = re.compile(r"^\s*-\s*Nombre:\s*(\S+)\s*$")


def extract_law_names(iesy_path: Path) -> list[str]:
    text = iesy_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        laws_idx = next(i for i, l in enumerate(lines) if l.strip() == "Laws:")
    except StopIteration:
        raise ValueError(f"{iesy_path}: no se encontro seccion 'Laws:'")

    names: list[str] = []
    for line in lines[laws_idx + 1:]:
        m = LAW_NAME_RE.match(line)
        if m:
            names.append(m.group(1))

    if not names:
        raise ValueError(f"{iesy_path}: seccion 'Laws:' vacia o formato no reconocido")
    return names
