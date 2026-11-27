"""
isyco_reader.py — puente SOLO LECTURA entre IsyVM e ISyCo.

Rigor COBOL: cada entrada al mundo exterior esta en ALLOWED_READS.
Nada implicito. Nada se adivina. Nada se ejecuta.

vm.isolation Law no_hosts_builtins: este modulo NO importa os,
subprocess, importlib. Solo `pathlib.Path` y `json` (este ultimo acotado
a un archivo fijo: routes.json de ISyCo, lectura unica).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import FrozenSet

from .exceptions import IsolationViolation


# === Ley 2: raiz canonica, igual que IRS.md ===
_LINUX_ROOT = Path("/home/danny/Development/ISyCo")
_ISYCO_ROOT = _LINUX_ROOT if _LINUX_ROOT.is_dir() else Path(r"C:\Development\ISyCo")

# === Ley 3: allowlist de directorios legibles (COBOL rigor) ===
_ALLOWED_SUBDIR_RELS: FrozenSet[str] = frozenset({
    "bridge_core/contracts",
    "bridge_core/contracts/bootstrap",
    "bridge_core/contracts/bootstrap/atoms",
    "bridge_core/capabilities/runtime_exe",
    "bridge_core/runtimes/windows/python",
    r"bridge_core\contracts",
    r"bridge_core\contracts\bootstrap",
    r"bridge_core\contracts\bootstrap\atoms",
    r"bridge_core\capabilities\runtime_exe",
    r"bridge_core\runtimes\windows\python",
})
_DENY_SEGMENTS: FrozenSet[str] = frozenset({
    ".git",
    "__pycache__",
    "_backups",
    ".pytest_cache",
    ".aider.tags.cache.v4",
    ".claude",
})


def _vet(p: Path) -> Path:
    """Normaliza + verifica que p este bajo ISYCO_ROOT, no en zona
    negada, y cae bajo un directorio explicitamente autorizado."""
    if not p.exists():
        raise IsolationViolation(f"Ruta inexistente: {p}")
    rp = p.resolve()
    root_resolved = _ISYCO_ROOT.resolve()
    try:
        rp.relative_to(root_resolved)
    except ValueError:
        raise IsolationViolation(
            f"Ruta fuera de ISYCO_ROOT: {rp} -- vm.isolation Law no_path_escape"
        )
    for seg in rp.parts:
        if seg in _DENY_SEGMENTS:
            raise IsolationViolation(
                f"Ruta en zona negada ({seg}): {rp} -- vm.isolation Law no_path_escape"
            )
    # debe caer bajo algun directorio explicitamente autorizado
    authorized = False
    for sub_rel in _ALLOWED_SUBDIR_RELS:
        allowed_dir = (root_resolved / Path(sub_rel.replace("\\", "/"))).resolve()
        try:
            rp.relative_to(allowed_dir)
            authorized = True
            break
        except ValueError:
            continue
    if not authorized:
        raise IsolationViolation(
            f"Path no cae bajo ningun directorio autorizado: {rp} "
            f"-- vm.isolation Law explicit_allowlist / vm.bridge_isyco Law read_only"
        )
    return rp


# === ALLOWED_READS explicito (Ley explicit_allowlist) ===
ALLOWED_READS = frozenset({
    "read_contract",
    "list_contracts",
    "read_capability_contract",
})


def list_contracts(root_subdir: str = "bridge_core/contracts") -> list[str]:
    """Lista nombres de .iesy bajo root_subdir. Solo lectura."""
    base = _vet(_ISYCO_ROOT / root_subdir)
    if not base.is_dir():
        raise IsolationViolation(f"No es directorio: {base}")
    return sorted(p.name for p in base.rglob("*.iesy"))


def read_contract(name: str, root_subdir: str = "bridge_core/contracts") -> str:
    """Lee el contenido raw de un .iesy. NUNCA lo parsea, NUNCA lo ejecuta."""
    base = _vet(_ISYCO_ROOT / root_subdir)
    target_path = base / name
    target = _vet(target_path)
    if not target.is_file() or target.suffix != ".iesy":
        raise IsolationViolation(f"No es .iesy: {target}")
    return target.read_text(encoding="utf-8")


def read_capability_contract(cap_identity: str) -> str:
    """
    Lee el .iesy de una capability via routes.json.
    vm.isolation Law no_capability_invocation: NO devuelve el execute.py
    ni ningun codigo. Solo el contract .iesy (pura observacion).
    """
    routes_path = _ISYCO_ROOT / "bridge_core" / "runtimes" / "windows" / "python" / "routes.json"
    routes_path = _vet(routes_path)
    routes = json.loads(routes_path.read_text(encoding="utf-8"))
    if cap_identity not in routes:
        raise IsolationViolation(f"Capability desconocida: {cap_identity}")
    contract_str = routes[cap_identity]["contract"]
    contract_path = Path(contract_str)
    contract_path = _vet(contract_path)
    if not contract_path.is_file() or contract_path.suffix != ".iesy":
        raise IsolationViolation(f"No es .iesy: {contract_path}")
    return contract_path.read_text(encoding="utf-8")
