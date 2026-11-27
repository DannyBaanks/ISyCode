"""
sandbox/interp.py -- Layer (a): filtro best-effort pre-ejecucion, NO
boundary de seguridad (vm.isolation.iesy v0.2.0, ley
layer_a_best_effort_only; vm.sandbox_interp.iesy, ley no_boundary_claim).
El boundary real es Layer_c_OS.

Dos pasos obligatorios, en este orden, sin excepcion:
  1. verify_program(source) -- analisis estatico via ast, ANTES de
     ejecutar nada. Rechaza imports prohibidos, llamadas prohibidas, y
     acceso a atributos dunder de introspeccion (el vector real que
     rompio rexec/Bastion: ().__class__.__bases__[0].__subclasses__()).
  2. run_program(source) -- solo si (1) paso, ejecuta con exec() sobre
     un __builtins__ restringido explicito (SAFE_BUILTINS), nunca los
     builtins completos del host.

Aviso honesto: esto NO es un sandbox real. Un interprete Python en el
mismo proceso que el host siempre tiene superficie de ataque residual.
Es un filtro barato que atrapa lo obvio y el escape historico conocido,
no una promesa de aislamiento.
"""
from __future__ import annotations

import ast
from typing import Any

from .exceptions import UnsafeOperationDetected

BANNED_IMPORT_MODULES = frozenset({
    "os", "sys", "subprocess", "importlib", "ctypes", "pickle",
    "marshal", "socket", "shutil", "shelve", "code", "codeop",
    "pty", "builtins", "multiprocessing",
})

BANNED_CALL_NAMES = frozenset({
    "open", "eval", "exec", "compile", "__import__", "input",
    "getattr", "setattr", "delattr", "vars", "dir", "globals",
    "locals", "breakpoint", "help",
})

# Vector real que rompio rexec/Bastion: caminar el grafo de objetos
# vivos via dunders en vez de importar directamente.
BANNED_ATTR_NAMES = frozenset({
    "__class__", "__bases__", "__subclasses__", "__globals__",
    "__builtins__", "__code__", "__mro__", "__init_subclass__",
    "__reduce__", "__reduce_ex__", "__getattribute__", "__dict__",
    "__closure__", "__func__", "__self__",
})

SAFE_BUILTINS: dict[str, Any] = {
    "print": print, "len": len, "range": range, "int": int,
    "float": float, "str": str, "bool": bool, "list": list,
    "dict": dict, "tuple": tuple, "set": set, "abs": abs,
    "min": min, "max": max, "sum": sum, "sorted": sorted,
    "enumerate": enumerate, "zip": zip, "True": True,
    "False": False, "None": None,
}


class _Verifier(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in BANNED_IMPORT_MODULES or alias.name in BANNED_IMPORT_MODULES:
                self.violations.append(f"import prohibido: {alias.name} (linea {node.lineno})")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        root = mod.split(".")[0]
        if root in BANNED_IMPORT_MODULES or mod in BANNED_IMPORT_MODULES:
            self.violations.append(f"from-import prohibido: {mod} (linea {node.lineno})")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name in BANNED_CALL_NAMES:
            self.violations.append(f"llamada prohibida: {name}() (linea {node.lineno})")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in BANNED_ATTR_NAMES:
            self.violations.append(f"atributo prohibido: .{node.attr} (linea {node.lineno})")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in BANNED_CALL_NAMES:
            self.violations.append(f"nombre prohibido referenciado: {node.id} (linea {node.lineno})")
        self.generic_visit(node)


def verify_program(source: str) -> None:
    """cobol_rigor_static_first: analiza TODO antes de ejecutar UNA
    linea. Levanta con TODAS las violaciones encontradas, no solo la
    primera."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise UnsafeOperationDetected(f"programa no parsea: {e}") from e

    verifier = _Verifier()
    verifier.visit(tree)
    if verifier.violations:
        raise UnsafeOperationDetected(
            "verify_program rechazo el programa:\n  - " + "\n  - ".join(verifier.violations)
        )


def run_program(source: str) -> dict[str, Any]:
    """Ejecuta SOLO si verify_program no levanto excepcion. Devuelve el
    namespace final (variables definidas), sin __builtins__."""
    verify_program(source)
    restricted_globals: dict[str, Any] = {"__builtins__": SAFE_BUILTINS}
    exec(compile(source, "<isyvm-sandboxed>", "exec"), restricted_globals)
    return {k: v for k, v in restricted_globals.items() if k != "__builtins__"}
