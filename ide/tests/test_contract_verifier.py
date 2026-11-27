"""
Tests para verifier/contract_verifier.

GOLDEN 3 (sandbox_interp) + GOLDEN 4b (cpu multi-contrato).

Cobertura:
  - parser: 4 leyes vm.sandbox_interp.iesy, 5 leyes vm.cpu.iesy
  - holds: 4/4 sandbox_interp (regresion GOLDEN 3)
  - holds: 5/5 cpu (GOLDEN 4b)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Hacer importable el paquete verifier desde tests
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from verifier.contract_verifier import run_all_checks, run_all_checks_for
from verifier.iesy_parser import extract_law_names

_SANDBOX_CONTRACT = _ROOT / "contracts" / "vm.sandbox_interp.iesy"
_CPU_CONTRACT = _ROOT / "contracts" / "vm.cpu.iesy"


def test_parser_extracts_4_law_names_sandbox():
    names = extract_law_names(_SANDBOX_CONTRACT)
    assert names == [
        "static_verify_before_exec",
        "explicit_deny_lists",
        "restricted_builtins_only",
        "no_boundary_claim",
    ]


def test_parser_extracts_5_law_names_cpu():
    names = extract_law_names(_CPU_CONTRACT)
    assert names == [
        "harvard_separation",
        "fixed_instruction_set",
        "bounded_execution",
        "no_host_capability",
        "deterministic_halt",
    ]


def test_contract_holds_sandbox_interp():
    results = run_all_checks()  # retrocompat: lista plana
    failed = [r for r in results if r.result != "PASS"]
    assert not failed, "violaciones vm.sandbox_interp: " + "; ".join(
        f"{r.law}: {r.detail}" for r in failed)


def test_contract_holds_cpu():
    results_by = run_all_checks_for("cpu")
    results = results_by.get("cpu", [])
    failed = [r for r in results if r.result != "PASS"]
    assert not failed, "violaciones vm.cpu: " + "; ".join(
        f"{r.law}: {r.detail}" for r in failed)

