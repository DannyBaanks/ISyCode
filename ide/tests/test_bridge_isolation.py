"""
GOLDEN 1 — bridge isolation.

4 PASS positivos (lecturas legitimas funcionan) +
6 PELIGROSAS (intentos de fuga detectados y rechazados).

Si algun PASS verde falla -> el bridge no leee lo que deberia.
Si algun PELIGROSA no levanta IsolationViolation -> HAY FUGA, GOLDEN roto.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bridge.isyco_reader import (
    IsolationViolation,
    _ISYCO_ROOT,
    list_contracts,
    read_contract,
    read_capability_contract,
)

_needs_isyco = pytest.mark.skipif(
    not _ISYCO_ROOT.is_dir(),
    reason="External ISyCo monorepo not present on this runner",
)


# === PASS positivos (4) ===

@_needs_isyco
def test_pass1_read_existing_bootstrap_contract():
    txt = read_contract("bootstrap/bootstrap.iesy")
    assert "Identity:" in txt
    assert "Version:" in txt

@_needs_isyco
def test_pass2_list_contracts_nonempty_and_all_iesy():
    names = list_contracts()
    assert len(names) > 0
    assert all(n.endswith(".iesy") for n in names)

@_needs_isyco
def test_pass3_read_capability_contract_runtime_exe():
    txt = read_capability_contract("cap.runtime.exe")
    assert "Identity:" in txt
    assert ".iesy" in txt or "iesy" in txt.lower()

@_needs_isyco
def test_pass4_list_contracts_atoms_subdir():
    names = list_contracts("bridge_core/contracts/bootstrap/atoms")
    # debe contener al menos compare.iesy y return.iesy si existen
    assert isinstance(names, list)
    # no debe haber nada que no sea .iesy
    assert all(n.endswith(".iesy") for n in names)


# === PELIGROSAS (6) — intentos de fuga DEBEN ser rechazados ===

def test_peligrosa_1a_path_escape_system32():
    # Intento leer fuera del root via ..
    with pytest.raises(IsolationViolation):
        read_contract("../../../../Windows/System32/cmd.exe")

def test_peligrosa_1b_denied_segment_git():
    # Intento leer bajo .git (denied)
    with pytest.raises(IsolationViolation):
        read_contract("../.git/config")

def test_peligrosa_1c_subdir_no_autorizado():
    # cli existe bajo ISyCo pero no esta en ALLOWED_SUBDIRS
    with pytest.raises(IsolationViolation):
        list_contracts("bridge_core/cli")

def test_peligrosa_1d_extension_no_iesy():
    # Bootstrap_Law.md existe pero no es .iesy
    with pytest.raises(IsolationViolation):
        read_contract("bootstrap/Bootstrap_Law.md")

def test_peligrosa_1e_capability_inexistente():
    with pytest.raises(IsolationViolation):
        read_capability_contract("cap.inexistente.xxx")

def test_peligrosa_1f_invariante_no_compile_call():
    # Invariante de auditoria: el modulo bridge NO debe usar compile()
    # ni eval() ni exec() en su codigo fuente — son canales de fuga.
    import bridge.isyco_reader as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    # no debe contener llamadas a compile/eval/exec como instrucciones
    for forbidden in ("compile(", "eval(", "exec(", "import os",
                      "import subprocess", "__import__"):
        assert forbidden not in src, (
            f"bridge/isyco_reader.py contiene '{forbidden}' — "
            f"viola invariante de no-fuga"
        )
