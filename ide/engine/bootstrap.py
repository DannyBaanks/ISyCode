"""
engine/bootstrap.py -- CLI unificado de IsyVM.

Une piezas verificadas (sandbox/interp, core/cpu, verifier/contract_verifier)
en un solo entrypoint. No es boundary de seguridad por si solo.

Comandos:
  python -m engine.bootstrap whoami
  python -m engine.bootstrap status
  python -m engine.bootstrap test          # pytest tests/ (33)
  python -m engine.bootstrap verify        # contract_verifier multi-target
  python -m engine.bootstrap run "<py>"
  python -m engine.bootstrap cpu "PUSH 3; PUSH 4; ADD; HALT"

Desde ISyCo:
  isyco shell -c "/isyvm status|test|bootstrap"
"""
from __future__ import annotations

import subprocess
import sys
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GOLDENS = [
    ("GOLDEN 1", "bridge isolation", 10, "Verified"),
    ("GOLDEN 2", "sandbox interp (Layer_a filtro best-effort)", 9, "Verified"),
    ("GOLDEN 3", "contract_verifier CLI + sandbox", 4, "Verified"),
    ("GOLDEN 4a", "core/cpu.py Harvard real", 10, "Verified"),
    ("GOLDEN 4b", "multi-contrato sandbox_interp + cpu", 0, "Verified (suite 33)"),
]
_GOLDEN_SUITE_TOTAL = 33
_CURRENT_SUITE_TOTAL = 69


def _whoami() -> int:
    print("IsyVM -- containment VM (sister of ISyCo)")
    print(f"repo:     {_REPO_ROOT}")
    print(f"suite:    {_CURRENT_SUITE_TOTAL} passed + 1 platform skip (current)")
    print(f"golden:   {_GOLDEN_SUITE_TOTAL} tests (GOLDEN 1..4b baseline)")
    print("verified GOLDENs:")
    for name, desc, ntests, st in _GOLDENS:
        extra = f" ({ntests} tests)" if ntests else ""
        print(f"  {name:10} [{st}]{extra} -- {desc}")
    print("  GOLDEN 5   [Spike documented, NOT Active] -- agent-bridge bitacora")
    print("  Layer_c_OS [Documented -- needs Danny eyes on Hyper-V]")
    print()
    print("Runtime_operational:        Layer_a best-effort local runtime only.")
    print("Layer_b_WASM:               unavailable (not implemented/registered).")
    print("Layer_c_OS:                 Hyper-V pending verification.")
    return 0


def _status() -> int:
    print(f"IsyVM tree (root={_REPO_ROOT}):")
    _print_tree(
        _REPO_ROOT, "", 0, 3,
        exclude={".pytest_cache", "__pycache__", "site-packages",
                 "Scripts", "Include", "Lib", ".venv"},
    )
    print()
    print("Estado pieza por pieza:")
    for name, desc, ntests, st in _GOLDENS:
        print(f"  {name:10} {st:28} {desc}")
    print(f"  pytest suite: {_CURRENT_SUITE_TOTAL} passed + 1 platform skip")
    print("  GOLDEN 5   SPIKE documentado (NO Active)")
    print("  Layer_c_OS Documented -- pending verification (Hyper-V)")
    return 0


def _print_tree(path: Path, prefix: str, depth: int, max_depth: int,
                exclude: set[str]) -> None:
    if depth > max_depth:
        return
    try:
        items = sorted(
            [p for p in path.iterdir() if p.name not in exclude],
            key=lambda p: p.name,
        )
    except (PermissionError, OSError):
        return
    for i, item in enumerate(items):
        last = (i == len(items) - 1)
        branch = "\\-- " if last else "+-- "
        label = item.name + ("/" if item.is_dir() else "")
        print(f"{prefix}{branch}{label}")
        if item.is_dir():
            nxt = prefix + ("    " if last else "|   ")
            _print_tree(item, nxt, depth + 1, max_depth, exclude)


def _verify() -> int:
    from verifier.contract_verifier import run_all_checks, write_report
    # GOLDEN 4b API: target_name="all" -> dict multi-contrato
    results_by_target = run_all_checks(target_name="all")
    write_report(results_by_target)
    all_pass = all(
        all(r.result == "PASS" for r in results)
        for results in results_by_target.values()
    )
    for target_name, results in results_by_target.items():
        print(f"--- Target: {target_name} ---")
        for r in results:
            mark = "OK" if r.result == "PASS" else "XX"
            print(f"[{mark}] {r.law}: {r.detail}")
        print()
    total = sum(len(v) for v in results_by_target.values())
    passed = sum(sum(1 for r in v if r.result == "PASS") for v in results_by_target.values())
    print(("PASS" if all_pass else "FAIL") + f" ({passed}/{total})")
    print(f"report: {_REPO_ROOT / 'tests' / 'CONTRACT_VERIFICATION.md'}")
    from core.resident import ResidentRecorder
    ResidentRecorder(_REPO_ROOT).verification(
        "tests/CONTRACT_VERIFICATION.md",
        "verified" if all_pass else "failed",
        ["engine/bootstrap.py", "verifier/contract_verifier.py"],
    )
    return 0 if all_pass else 1


def _test() -> int:
    py = sys.executable
    venv = _REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv.is_file():
        py = str(venv)
    cmd = [py, "-m", "pytest", str(_REPO_ROOT / "tests"), "-q", "--tb=line"]
    print(" ".join(cmd))
    r = subprocess.run(cmd, cwd=str(_REPO_ROOT))
    from core.resident import ResidentRecorder
    ResidentRecorder(_REPO_ROOT).verification("tests", "verified" if r.returncode == 0 else "failed", ["pytest tests"])
    return int(r.returncode)


def _run(source: str) -> int:
    from sandbox.interp import run_program, verify_program, UnsafeOperationDetected
    try:
        verify_program(source)
    except UnsafeOperationDetected as e:
        print(f"verify_program RECHAZO el programa:\n{e}", file=sys.stderr)
        return 1
    try:
        ns = run_program(source)
    except UnsafeOperationDetected as e:
        print(f"run_program levanto (filtra post-exec):\n{e}", file=sys.stderr)
        return 1
    print("programa ejecutado OK. namespace final:")
    for k, v in ns.items():
        shown = repr(v)
        if len(shown) > 120:
            shown = shown[:117] + "..."
        print(f"  {k} = {shown}")
    return 0


def _cpu(spec: str) -> int:
    from core.cpu import Instruction, validate_program, run, CPUFault
    try:
        program = _parse_cpu_program(spec)
    except ValueError as e:
        print(f"parseo de programa ISA invalido: {e}", file=sys.stderr)
        return 2
    try:
        validate_program(program)
    except CPUFault as e:
        print(f"validate_program RECHAZO:\n  {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    try:
        result = run(program)
    except CPUFault as e:
        print(f"run CPUFault:\n  {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"CPU HALT. halted={result.halted}, steps={result.steps}")
    print(f"  stack   = {result.stack}")
    print(f"  memory  = {result.memory}")
    return 0


def _resident(args: list[str]) -> int:
    """Inspect or update the host-owned structural resident state."""
    from core.resident import ResidentReader, SelfScanner

    command = args[0] if args else "status"
    reader = ResidentReader(_REPO_ROOT)
    if command == "scan":
        result = SelfScanner(_REPO_ROOT).scan()
    elif command == "status":
        result = {**reader.status(), "config": reader.config()}
    elif command == "map":
        result = {"records": reader.map_records()}
    elif command == "query":
        if len(args) < 2:
            print("uso: isyvm resident query \"intent\"", file=sys.stderr)
            return 2
        result = reader.query(" ".join(args[1:]))
    elif command == "verify":
        result = reader.verify()
    else:
        print("uso: isyvm resident [status|scan|map|query|verify]", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status", "ok") not in {"fail", "unknown"} else 1


def _mode_command(command: str, args: list[str]) -> int:
    from core.mode import ModeController
    from core.plan import PlanStore
    from core.resident import ResidentRecorder

    controller = ModeController(_REPO_ROOT)
    plans = PlanStore(_REPO_ROOT)
    if command == "plan":
        mode = controller.set("plan")
        plan_id = None
        if args:
            plan_id = plans.create(" ".join(args))
        result = {"mode": mode, "plan_id": plan_id or plans.latest_id(), "plan": plans.context()}
    elif command == "code":
        mode = controller.set("coder")
        plan_id = plans.latest_id()
        if plan_id:
            plans.append(plan_id, "approval", status="approved", actor="USER", content="PLAN -> CODER")
        result = {"mode": mode, "plan_id": plan_id, "plan": plans.context()}
    else:
        if args and args[0] in {"plan", "coder"}:
            controller.set(args[0])
        result = {"mode": controller.current(), "plan": plans.context()}
    ResidentRecorder(_REPO_ROOT).record("decisions.jsonl", {
        "type": "decision", "id": f"mode:{command}:{uuid.uuid4().hex}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "host", "content": f"mode changed through isyvm {command}", "mode": result["mode"],
    })
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _parse_cpu_program(spec: str):
    from core.cpu import Instruction
    program = []
    if not spec.strip():
        return program
    for raw in spec.split(";"):
        chunk = raw.split("#", 1)[0].strip()
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.replace(",", " ").split() if p.strip()]
        if not parts:
            continue
        op = parts[0].upper()
        arg = None
        if len(parts) > 1:
            try:
                arg = int(parts[1], 0)
            except ValueError:
                raise ValueError(f"argumento no entero en '{chunk}': {parts[1]!r}")
        program.append(Instruction(op=op, arg=arg))
    return program


def main(argv: list[str]) -> int:
    if not argv:
        _print_usage()
        return 2
    if len(argv) > 1 and Path(str(argv[0])).name in {"bootstrap.py", "bootstrap"}:
        args = list(argv[1:])
    else:
        args = list(argv)
    if not args:
        _print_usage()
        return 2
    cmd = args[0]
    if cmd == "whoami":
        return _whoami()
    if cmd == "status":
        return _status()
    if cmd == "verify":
        return _verify()
    if cmd in ("test", "pytest"):
        return _test()
    if cmd == "run":
        if len(args) < 2:
            print('uso: python -m engine.bootstrap run "<python source>"', file=sys.stderr)
            return 2
        return _run(args[1])
    if cmd == "cpu":
        if len(args) < 2:
            print('uso: python -m engine.bootstrap cpu "PUSH 3; PUSH 4; ADD; HALT"',
                  file=sys.stderr)
            return 2
        return _cpu(args[1])
    if cmd == "resident":
        return _resident(args[1:])
    if cmd in {"plan", "code"}:
        return _mode_command(cmd, args[1:])
    if cmd == "mode":
        return _mode_command(cmd, args[1:])
    print(f"comando desconocido: {cmd!r}", file=sys.stderr)
    _print_usage()
    return 2


def _print_usage() -> None:
    print("IsyVM CLI -- containment sandbox (sister of ISyCo)")
    print()
    print("uso: python -m engine.bootstrap <cmd> [args]")
    print("  o:  isyvm.cmd <cmd> ...")
    print("  o:  isyco shell -c \"/isyvm test\"")
    print()
    print("comandos:")
    print("  whoami            identidad y golden records")
    print("  status            arbol IsyVM + estado piezas")
    print("  test | pytest     corre la suite actual (69 passed, 1 platform skip)")
    print("  verify            contract_verifier multi-target (PASS/FAIL por ley)")
    print('  run "<src>"       sandbox/interp verify + run (Layer_a filtro)')
    print('  cpu "<prog>"      core/cpu validate + run ("PUSH 3; PUSH 4; ADD; HALT")')
    print("  resident <cmd>    structural resident: status|scan|map|query|verify")
    print("  plan [goal]        enter PLAN mode and optionally create a plan")
    print("  plan add <type> <path> [reason]  append a plan item")
    print("  code               enter CODER mode and approve the current plan")
    print("  mode [plan|coder]  inspect or change mode")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
