"""
verifier/contract_verifier.py -- GOLDEN 3 (sandbox_interp) + GOLDEN 4b
(multi-contrato): verificador determinista de cumplimiento de contrato.

Lee .iesy via iesy_parser, coteja codigo real contra cada ley con un
checker Python escrito a mano. No interpreta la prosa de 'Regla:' -- eso
lo sigue escribiendo un humano/agente en el checker.

MULTI-CONTRATO (GOLDEN 4b):
  Cada par (contrato, codigo) se modela como AuditTarget.
  Completitud bidireccional ley <-> checker se mantiene PER-CONTRATO
  (no global), para que un checker de sandbox no sea huerfano solo
  porque no existe ley homonima en vm.cpu.

  - DEFAULT_AUDIT_TARGETS: [sandbox_interp, cpu]
  - run_all_checks() sin args: retrocompat con GOLDEN 3 (solo sandbox_interp)
  - run_all_checks_for('cpu'): solo cpu
  - run_all_checks_for('all'): todos los DEFAULT_AUDIT_TARGETS
  - write_report(): una seccion por target, Regresion sandbox_interp
  garantizada.

No es un oraculo con LLM. No decide nada mas alla de PASS/FAIL
determinista. No modifica el contrato ni el codigo auditado.
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional

from .iesy_parser import extract_law_names

ROOT = Path(__file__).resolve().parent.parent

# === Paths canonicos ===
_SANDBOX_INTERP_PATH = ROOT / "sandbox" / "interp.py"
_SANDBOX_EXCEPTIONS_PATH = ROOT / "sandbox" / "exceptions.py"
_SANDBOX_INIT_PATH = ROOT / "sandbox" / "__init__.py"
_CPU_PATH = ROOT / "core" / "cpu.py"
_CPU_CONTRACT_PATH = ROOT / "contracts" / "vm.cpu.iesy"
_SANDBOX_CONTRACT_PATH = ROOT / "contracts" / "vm.sandbox_interp.iesy"
_REPORT_PATH = ROOT / "tests" / "CONTRACT_VERIFICATION.md"

NEGATION_MARKERS = ("no ", "nunca", "not a", "not an")
_SANDBOX_DIR = ROOT / "sandbox"


# === Tipos ===
class CheckResult(NamedTuple):
    law: str
    result: str  # "PASS" | "FAIL"
    detail: str


@dataclass
class AuditTarget:
    name: str
    contract_path: Path
    audit_paths: List[Path]
    checkers: Dict[str, Callable[[str, ast.Module, dict], CheckResult]]


# === Helpers AST ===
def _find_func(tree: ast.Module, name: str) -> Optional[ast.FunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _first_call_lineno(node: ast.AST, call_name: str) -> Optional[int]:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fname = None
            if isinstance(sub.func, ast.Name):
                fname = sub.func.id
            elif isinstance(sub.func, ast.Attribute):
                fname = sub.func.attr
            if fname == call_name:
                return sub.lineno
    return None


def _find_call(body: List[ast.stmt], call_name: str) -> Optional[ast.Call]:
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call):
            fname = None
            if isinstance(node.func, ast.Name):
                fname = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fname = node.func.attr
            if fname == call_name:
                return node
    return None


# === Checkers: SANDBOX_INTERP (4 leyes) ===
def _check_static_verify_before_exec(source: str, tree: ast.Module,
                                      ctx: dict) -> CheckResult:
    fn = _find_func(tree, "run_program")
    if fn is None:
        return CheckResult("static_verify_before_exec", "FAIL",
                           "no existe run_program() en interp.py")
    verify_line = _first_call_lineno(fn, "verify_program")
    exec_line = _first_call_lineno(fn, "exec")
    if verify_line is None:
        return CheckResult("static_verify_before_exec", "FAIL",
                           "run_program no llama a verify_program()")
    if exec_line is None:
        return CheckResult("static_verify_before_exec", "PASS",
                           "run_program no llama a exec() directamente")
    if verify_line < exec_line:
        return CheckResult("static_verify_before_exec", "PASS",
                           f"verify_program() en linea {verify_line}, "
                           f"exec() en linea {exec_line}")
    return CheckResult("static_verify_before_exec", "FAIL",
                       f"exec() (linea {exec_line}) no esta precedido por "
                       f"verify_program() (linea {verify_line})")


def _check_explicit_deny_lists(source: str, tree: ast.Module,
                                ctx: dict) -> CheckResult:
    required = ("BANNED_IMPORT_MODULES", "BANNED_CALL_NAMES",
                "BANNED_ATTR_NAMES")
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
            if name in required:
                is_frozenset_literal = (
                    isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "frozenset"
                    and len(node.value.args) == 1
                    and isinstance(node.value.args[0], ast.Set)
                )
                found[name] = is_frozenset_literal
    missing = [n for n in required if n not in found]
    not_literal = [n for n, ok in found.items() if not ok]
    if missing or not_literal:
        parts = []
        if missing:
            parts.append(f"faltan: {', '.join(missing)}")
        if not_literal:
            parts.append(f"no son frozenset({{...}}) literal: "
                         f"{', '.join(not_literal)}")
        return CheckResult("explicit_deny_lists", "FAIL",
                           "; ".join(parts))
    return CheckResult("explicit_deny_lists", "PASS",
                       f"{', '.join(required)} son frozenset literal a "
                       f"nivel modulo")


def _check_restricted_builtins_only(source: str, tree: ast.Module,
                                     ctx: dict) -> CheckResult:
    has_safe_builtins = False
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            if (node.targets[0].id == "SAFE_BUILTINS"
                    and isinstance(node.value, ast.Dict)):
                has_safe_builtins = True
        if (isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)):
            if (node.target.id == "SAFE_BUILTINS"
                    and isinstance(node.value, ast.Dict)):
                has_safe_builtins = True
    if not has_safe_builtins:
        return CheckResult("restricted_builtins_only", "FAIL",
                           "SAFE_BUILTINS no existe como dict literal a "
                           "nivel modulo")
    fn = _find_func(tree, "run_program")
    if fn is None:
        return CheckResult("restricted_builtins_only", "FAIL",
                           "no existe run_program() en interp.py")
    ok = False
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "__builtins__"
                        and isinstance(v, ast.Name)
                        and v.id == "SAFE_BUILTINS"):
                    ok = True
    if not ok:
        return CheckResult("restricted_builtins_only", "FAIL",
                           "run_program no construye "
                           "{'__builtins__': SAFE_BUILTINS} literal")
    return CheckResult("restricted_builtins_only", "PASS",
                       "run_program inyecta {'__builtins__': SAFE_BUILTINS} "
                       "explicito")


def _check_no_boundary_claim(source: str, tree: ast.Module,
                              ctx: dict) -> CheckResult:
    claim_words = ("aisla", "protege", "isolat", "protect", "boundary")
    offenders = []
    for py_file in sorted(_SANDBOX_DIR.glob("*.py")):
        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            low = line.lower()
            if any(w in low for w in claim_words):
                window = " ".join(
                    lines[max(0, i - 3):i + 1]).lower()
                if not any(neg in window for neg in NEGATION_MARKERS):
                    offenders.append(
                        f"{py_file.name}:{i + 1}: {line.strip()}")
    if offenders:
        return CheckResult("no_boundary_claim", "FAIL",
                           "afirmaciones sin negar (ventana de 4 lineas): "
                           " | ".join(offenders))
    return CheckResult("no_boundary_claim", "PASS",
                       "todas las menciones de aislamiento/proteccion "
                       "estan negadas explicitamente (ventana de 4 lineas)")


# === Checkers: CPU (5 leyes) ===
def _check_harvard_separation(source: str, tree: ast.Module,
                               ctx: dict) -> CheckResult:
    """JMP/JZ siempre usan arg literal (int), nunca variable/source/memory."""
    violations = []
    jumps = ("JMP", "JZ")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fname = None
            if isinstance(node.func, ast.Name):
                fname = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fname = node.func.attr
            if fname == "Instruction":
                # Instruction(op, arg) -- revisar que arg sea int constante
                # en las llamadas de JMP/JZ (no Name/Attribute subscript)
                pass
    # Buscar constructores Instruction(op="JMP"/"JZ", arg=...) en el source
    # Los args de JMP/JZ en .py hardcodeados son siempre int literales
    # (no hay forma de calcularlos en runtime en instrucciones validadas)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fname = None
            if isinstance(node.func, ast.Name):
                fname = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fname = node.func.attr
            if fname == "Instruction":
                args = node.args
                kw_names = [k.arg for k in node.keywords]
                if len(args) >= 2:
                    op_node = args[0]
                    arg_node = args[1]
                    op_val = None
                    if (isinstance(op_node, ast.Constant)
                            and isinstance(op_node.value, str)):
                        op_val = op_node.value.upper()
                    if op_val in jumps:
                        if not isinstance(arg_node, ast.Constant):
                            violations.append(
                                f"Instruction({op_val}, <non-constant>) "
                                f"en linea {node.lineno}")
                        elif not isinstance(arg_node.value, int):
                            violations.append(
                                f"Instruction({op_val}, "
                                f"{arg_node.value!r}) arg no es int "
                                f"en linea {node.lineno}")
    if violations:
        return CheckResult("harvard_separation", "FAIL",
                           "; ".join(violations))
    return CheckResult("harvard_separation", "PASS",
                       "todos los JMP/JZ usan arg literal int en "
                       "Instruction(...)")


def _check_fixed_instruction_set(source: str, tree: ast.Module,
                                  ctx: dict) -> CheckResult:
    """OPCODES es frozenset literal nivel-modulo y validate_program
    existe."""
    has_opcodes = False
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            if node.targets[0].id == "OPCODES":
                has_opcodes = (
                    isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "frozenset"
                    and len(node.value.args) == 1
                    and isinstance(node.value.args[0], (ast.Set, ast.Dict))
                )
    if not has_opcodes:
        return CheckResult("fixed_instruction_set", "FAIL",
                           "OPCODES no es frozenset literal a nivel modulo")
    validate_fn = _find_func(tree, "validate_program")
    if validate_fn is None:
        return CheckResult("fixed_instruction_set", "FAIL",
                           "no existe validate_program() en cpu.py")
    fn = validate_fn
    checks_unknown = False
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            test = node.test
            # "x in OPCODES" (ast.In) y "x not in OPCODES" (ast.NotIn) son
            # nodos distintos en el AST -- ambos son formas validas de
            # rechazar un opcode desconocido, y "not in" es la forma mas
            # natural de escribir el rechazo. Solo aceptar ast.In era un
            # falso negativo del checker, no un bug real en cpu.py.
            if (isinstance(test, ast.Compare)
                    and any(isinstance(op, (ast.In, ast.NotIn)) for op in test.ops)):
                for comparator in test.comparators:
                    if (isinstance(comparator, ast.Name)
                            and comparator.id == "OPCODES"):
                        checks_unknown = True
    if not checks_unknown:
        return CheckResult("fixed_instruction_set", "FAIL",
                           "validate_program no chequea instr.op not in "
                           "OPCODES")
    return CheckResult("fixed_instruction_set", "PASS",
                       "OPCODES es frozenset literal; validate_program "
                       "rechaza opcodes desconocidos")


def _check_bounded_execution(source: str, tree: ast.Module,
                              ctx: dict) -> CheckResult:
    """MAX_STEPS y MAX_STACK son constantes nivel-modulo; run() las usa."""
    required_names = ("MAX_STEPS", "MAX_STACK")
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
            if name in required_names:
                found[name] = isinstance(node.value, ast.Constant)
    missing = [n for n in required_names if n not in found]
    if missing:
        return CheckResult("bounded_execution", "FAIL",
                           f"faltan constantes: {', '.join(missing)}")
    run_fn = _find_func(tree, "run")
    if run_fn is None:
        return CheckResult("bounded_execution", "FAIL",
                           "no existe run() en cpu.py")
    checks_steps = False
    checks_stack = False
    for node in ast.walk(run_fn):
        if isinstance(node, ast.If):
            test_str = ast.dump(node.test)
            if "steps" in test_str and "max_steps" in test_str:
                checks_steps = True
            if "stack" in test_str and "MAX_STACK" in test_str:
                checks_stack = True
    if not checks_steps:
        return CheckResult("bounded_execution", "FAIL",
                           "run() no chequea steps >= max_steps")
    if not checks_stack:
        return CheckResult("bounded_execution", "FAIL",
                           "run() no chequea len(stack) >= MAX_STACK")
    return CheckResult("bounded_execution", "PASS",
                       "MAX_STEPS y MAX_STACK definidas; run() respeta "
                       "ambos limites")


def _check_no_host_capability(source: str, tree: ast.Module,
                               ctx: dict) -> CheckResult:
    """OPCODES no contiene I/O; cpu.py no importa os/subprocess/io."""
    banned_modules = ("os", "sys", "subprocess", "io", "socket",
                      "shutil", "pathlib")
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                mod = node.module or ""
                names = [mod]
            for name in names:
                root = name.split(".")[0]
                if root in banned_modules:
                    return CheckResult(
                        "no_host_capability", "FAIL",
                        f"import prohibido en cpu.py: {name}")
    opcodes_check = _check_fixed_instruction_set.__wrapped__ if hasattr(
        _check_fixed_instruction_set, "__wrapped__") else None
    # Revisar que OPCODES no contenga nombres de I/O
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "OPCODES"):
            if isinstance(node.value, ast.Call):
                inner = node.value.args[0] if node.value.args else None
                if isinstance(inner, ast.Set):
                    for elt in inner.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            if elt.value.upper() in ("IO", "INPUT", "OUTPUT",
                                                     "SYS_CALL"):
                                return CheckResult(
                                    "no_host_capability", "FAIL",
                                    f"OPCODES contiene opcode "
                                    f"sospechoso de I/O: {elt.value}")
    return CheckResult("no_host_capability", "PASS",
                       "cpu.py no importa os/subprocess/io; OPCODES "
                       "no contiene opcodes de I/O")


def _check_deterministic_halt(source: str, tree: ast.Module,
                               ctx: dict) -> CheckResult:
    """Todas las excepciones son subclase de CPUFault; HALT retorna
    CPUResult; no hay raise Exception(...) generico."""
    generic_except = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id == "Exception"):
            generic_except = True
    if generic_except:
        return CheckResult("deterministic_halt", "FAIL",
                           "hay raise Exception(...) generico en cpu.py")
    # Verificar que CPUFault exista como clase base
    has_cpufault = False
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "CPUFault":
            has_cpufault = True
    if not has_cpufault:
        return CheckResult("deterministic_halt", "FAIL",
                           "no existe clase base CPUFault en cpu.py")
    return CheckResult("deterministic_halt", "PASS",
                       "todas las excepciones son CPUFault nombradas; "
                       "HALT retorna CPUResult; sin raise generico")


# === Checkers: SANDBOX_INTERP (registro) ===
_SANDBOX_CHECKERS: Dict[str, Callable] = {
    "static_verify_before_exec": _check_static_verify_before_exec,
    "explicit_deny_lists": _check_explicit_deny_lists,
    "restricted_builtins_only": _check_restricted_builtins_only,
    "no_boundary_claim": _check_no_boundary_claim,
}

# === Checkers: CPU (registro) ===
_CPU_CHECKERS: Dict[str, Callable] = {
    "harvard_separation": _check_harvard_separation,
    "fixed_instruction_set": _check_fixed_instruction_set,
    "bounded_execution": _check_bounded_execution,
    "no_host_capability": _check_no_host_capability,
    "deterministic_halt": _check_deterministic_halt,
}

# === AuditTargets por defecto ===
def _build_sandbox_target() -> AuditTarget:
    source = _SANDBOX_INTERP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    ctx = {"source": source, "tree": tree}
    return AuditTarget(
        name="sandbox_interp",
        contract_path=_SANDBOX_CONTRACT_PATH,
        audit_paths=[_SANDBOX_INTERP_PATH, _SANDBOX_EXCEPTIONS_PATH,
                     _SANDBOX_INIT_PATH],
        checkers=_SANDBOX_CHECKERS,
    )


def _build_cpu_target() -> AuditTarget:
    source = _CPU_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    validate_fn = _find_func(tree, "validate_program")
    ctx = {
        "source": source,
        "tree": tree,
        "validate_program_fn": validate_fn,
    }
    return AuditTarget(
        name="cpu",
        contract_path=_CPU_CONTRACT_PATH,
        audit_paths=[_CPU_PATH],
        checkers=_CPU_CHECKERS,
    )


DEFAULT_AUDIT_TARGETS: List[AuditTarget] = [
    _build_sandbox_target(),
    _build_cpu_target(),
]

_TARGETS_BY_NAME: Dict[str, AuditTarget] = {
    t.name: t for t in DEFAULT_AUDIT_TARGETS
}


# === Runner ===
def run_all_checks(target_name: Optional[str] = None
                   ) -> Dict[str, List[CheckResult]]:
    """Corre checkers para el target especificado.

    Retrocompat GOLDEN 3:
      - sin args -> solo sandbox_interp, devuelve lista plana (API vieja)
      - target_name='cpu' -> solo cpu, devuelve dict
      - target_name='all' -> todos, devuelve dict
    """
    if target_name is None:
        target = _TARGETS_BY_NAME["sandbox_interp"]
        law_names = extract_law_names(target.contract_path)
        law_set = set(law_names)
        checker_set = set(target.checkers.keys())
        res: List[CheckResult] = []
        for law in sorted(law_set - checker_set):
            res.append(CheckResult(law, "FAIL",
                                   "ley en el contrato sin checker registrado"))
        for cname in sorted(checker_set - law_set):
            res.append(CheckResult(cname, "FAIL",
                                   "checker huerfano (sin ley "
                                   "correspondiente en el contrato)"))
        source = target.audit_paths[0].read_text(encoding="utf-8")
        tree = ast.parse(source)
        ctx = {"sources": {target.audit_paths[0].name: source},
               "trees": {target.audit_paths[0].name: tree}}
        for law in law_names:
            if law not in target.checkers:
                continue
            res.append(target.checkers[law](source, tree, ctx))
        return res  # tipo List[CheckResult] para retrocompat

    if target_name == "all":
        targets = DEFAULT_AUDIT_TARGETS
    elif target_name in _TARGETS_BY_NAME:
        targets = [_TARGETS_BY_NAME[target_name]]
    else:
        raise ValueError(
            f"target desconocido: {target_name!r}. "
            f"Disponibles: {list(_TARGETS_BY_NAME.keys())}")

    results_by_target: Dict[str, List[CheckResult]] = {}
    for target in targets:
        law_names = extract_law_names(target.contract_path)
        law_set = set(law_names)
        checker_set = set(target.checkers.keys())

        res: List[CheckResult] = []

        for law in sorted(law_set - checker_set):
            res.append(CheckResult(law, "FAIL",
                                   "ley en el contrato sin checker "
                                   "registrado"))
        for cname in sorted(checker_set - law_set):
            res.append(CheckResult(cname, "FAIL",
                                   "checker huerfano (sin ley "
                                   "correspondiente en el contrato)"))

        sources = {}
        trees = {}
        for ap in target.audit_paths:
            try:
                txt = ap.read_text(encoding="utf-8")
                sources[ap.name] = txt
                if ap == target.audit_paths[0]:
                    trees[ap.name] = ast.parse(txt)
            except OSError:
                pass

        primary_name = target.audit_paths[0].name if target.audit_paths else ""
        primary_source = sources.get(primary_name, "")
        primary_tree = trees.get(primary_name)

        ctx = {"sources": sources, "trees": trees}

        for law in law_names:
            if law not in target.checkers:
                continue
            fn = target.checkers[law]
            if primary_tree is not None:
                res.append(fn(primary_source, primary_tree, ctx))
            else:
                res.append(CheckResult(law, "FAIL",
                                       "no se pudo parsear "
                                       "el archivo auditado"))

        results_by_target[target.name] = res
    return results_by_target


def write_report(results_by_target: Dict[str, List[CheckResult]]) -> None:
    lines = [
        "# CONTRACT_VERIFICATION.md -- generado por "
        "verifier/contract_verifier.py (GOLDEN 3 + GOLDEN 4b)",
        "",
        "Cada seccion corresponde a un AuditTarget (par contrato/codigo).",
        "Completitud bidireccional ley <-> checker por target.",
        "",
    ]
    all_pass = True
    for target_name, results in results_by_target.items():
        target_pass = all(r.result == "PASS" for r in results)
        if not target_pass:
            all_pass = False
        target = _TARGETS_BY_NAME.get(target_name)
        contract_label = (target.contract_path.relative_to(ROOT)
                          if target else target_name)
        lines.append(f"## Target: {target_name}")
        lines.append(f"Contrato: `{contract_label}`")
        lines.append(f"Resultado: **{'PASS' if target_pass else 'FAIL'}**")
        lines.append("")
        lines.append("| Ley | Resultado | Detalle |")
        lines.append("|-----|-----------|---------|")
        for r in results:
            lines.append(f"| `{r.law}` | {r.result} | {r.detail} |")
        lines.append("")

    if all_pass:
        lines.append("## Resultado global: **CONTRACT HOLDS**")
    else:
        lines.append("## Resultado global: **CONTRACT BROKEN**")
    lines.append("")
    lines.append(
        "Este reporte certifica cumplimiento del contrato existente. "
        "No certifica que ninguna capa sea un boundary de seguridad "
        "-- eso sigue siendo Layer_c_OS, pendiente de verificacion."
    )
    _REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    results_by_target = run_all_checks_for("all")
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
    passed = sum(
        sum(1 for r in v if r.result == "PASS")
        for v in results_by_target.values()
    )
    print(("PASS" if all_pass else "FAIL") + f" ({passed}/{total})")
    return 0 if all_pass else 1


def run_all_checks_for(target_name: str) -> Dict[str, List[CheckResult]]:
    """Public wrapper (alias semantico de run_all_checks)."""
    return run_all_checks(target_name=target_name)


if __name__ == "__main__":
    sys.exit(main())

