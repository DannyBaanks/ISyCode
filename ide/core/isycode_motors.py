"""OpenISy-style guided composite motors and model teaching helpers for ISyCode IDE.

These motors execute multi-step deterministic workflows *for* the model in a single
tool call so the model does not waste turns guessing CLI flags, Python signatures,
or MCP tool schemas.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path
from typing import Any

from core.isymcp_hub_client import ISyMCPHubClient
from core.resident import ResidentReader
from core.runtime.base import ExecutionResult

VALID_MOTORS = ("planner", "historian", "inspector", "hub_route")

_ENTRYPOINTS = (
    "README.md",
    "pyproject.toml",
    "build.zig",
    "Makefile",
    "package.json",
    "Cargo.toml",
    "CMakeLists.txt",
)


def detect_available_toolchains() -> list[str]:
    """Detect user and system toolchains accessible inside LinuxCommandRuntime."""
    user_local = Path("/home/danny/.local") if Path("/home/danny/.local").is_dir() else Path.home() / ".local"
    search_path = f"/usr/bin:/bin:/usr/local/bin:{user_local / 'bin'}"
    found: list[str] = []
    for name in ("python3", "pytest", "git", "zig", "ziggrep", "node", "npm", "cargo", "rustc", "make", "gcc"):
        if shutil.which(name, path=search_path):
            found.append(name)
    return found


def build_tool_guide(hub_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compact structured guide injected into ISYCODE CONTEXT to teach the model."""
    guide: dict[str, Any] = {
        "sandbox_toolchains": detect_available_toolchains(),
        "run_command_timeout_max_s": 120,
        "recommended_workflow": [
            "1. Antes de correr comandos o adivinar flags, llama isycode_motor(motor='planner') para obtener estructura, entrypoints y toolchains disponibles en 1 paso.",
            "2. Antes de importar o instanciar clases/funciones, llama isycode_motor(motor='inspector', target='<archivo_o_simbolo>') o read para ver firmas exactas.",
            "3. Para contexto histórico, reglas previas o memoria compartida ISyCo, llama isycode_motor(motor='historian', query='<tema>').",
            "4. Para herramientas MCP en ISyMCP Hub: NO adivines nombres de servidor (muchas tools como FlowSight/GitHub/media viven dentro de servidores existentes como 'isymcp'). Usa solo nombres exactos de tool_guide.isymcp_hub.servers o pide permiso al usuario para ejecutar una sola llamada acotada de isycode_mcp_discover(query='<palabra>', limit=10).",
        ],
    }
    if hub_summary is not None:
        guide["isymcp_hub"] = hub_summary
    return guide


def error_recovery_hint(tool_name: str, error_code: str, stderr: str) -> str:
    """Generate a concise actionable hint when a tool fails so the model self-corrects."""
    code = (error_code or "").upper()
    err = stderr or ""
    if code == "ISYMCP_HUB_ERROR" or tool_name == "isycode_mcp_discover":
        return (
            "Hint: no adivines el nombre de un servidor MCP ni afirmes que no existe sin buscar por query. "
            "Usa solo los nombres exactos listados en tool_guide.isymcp_hub.servers o haz una sola llamada con query='<palabra>' (sin server) pidiendo confirmación al usuario."
        )
    if code == "EXECUTABLE_MISSING":
        return (
            "Hint: binario no encontrado en /usr/bin, /bin, /usr/local/bin ni ~/.local/bin. "
            "Usa isycode_motor(motor='planner') para ver toolchains disponibles o isycode_motor(motor='hub_route') para delegar a ISyMCP Hub."
        )
    if code == "TIMEOUT_LIMIT":
        return "Hint: el timeout máximo de run_command es 120s; reduce el alcance del comando."
    if code == "PLAN_MODE_WRITE_DENIED":
        return "Hint: estás en modo PLAN (solo lectura). Usa isycode_motor(motor='planner') o indica al usuario cambiar a CODER."
    if code == "COMMAND_INTERRUPTED":
        return (
            "Hint: el comando excedió los límites del sandbox (1 GB RAM / 90s CPU) o falló antes de emitir recibo. "
            "Acota el comando (ej. un solo test o archivo) o usa isycode_motor(motor='inspector')."
        )
    if any(tok in err for tok in ("TypeError:", "AttributeError:", "ImportError:", "ModuleNotFoundError:")):
        return (
            "Hint: no adivines firmas ni imports. Llama isycode_motor(motor='inspector', target='<archivo>') "
            "o read para ver la definición exacta antes de reintentar."
        )
    if tool_name == "run_command" and ("--help" in err or "unrecognized" in err.lower() or "usage:" in err.lower()):
        return "Hint: lee el código fuente del script/binario con read o isycode_motor(motor='inspector') en vez de probar flags a ciegas."
    return ""


def _inspect_python_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {"path": str(path), "parse_error": str(exc), "head": text[:1200]}
    classes: list[dict[str, Any]] = []
    functions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods: list[str] = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [a.arg for a in item.args.args]
                    methods.append(f"{item.name}({', '.join(args)})")
            classes.append({"name": node.name, "line": node.lineno, "methods": methods[:20]})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            functions.append(f"{node.name}({', '.join(args)}) [L{node.lineno}]")
    return {
        "kind": "python_ast",
        "classes": classes[:25],
        "functions": functions[:35],
        "lines": text.count("\n") + 1,
    }


def _inspect_generic_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    defs = [
        f"L{idx}: {line.strip()[:120]}"
        for idx, line in enumerate(lines, 1)
        if re.match(r"^(pub\s+)?(fn|const|struct|enum|class|def|async\s+def|export\s+function|function)\b", line.strip())
    ]
    return {
        "kind": "generic_signatures",
        "lines": len(lines),
        "definitions": defs[:40],
        "head": "\n".join(lines[:30]),
    }


async def run_isycode_motor(workspace: Path, arguments: dict[str, Any]) -> ExecutionResult:
    """Execute one of the composite OpenISy-style motors in a single call."""
    from core.isycode_tools import execute_isycode_readonly_tool

    motor = str(arguments.get("motor", "")).strip().lower()
    query = str(arguments.get("query", "")).strip()
    target = str(arguments.get("target", "")).strip()
    root = workspace.resolve()

    if motor not in VALID_MOTORS:
        return ExecutionResult(
            False,
            stderr=f"INVALID_MOTOR: usa uno de {', '.join(VALID_MOTORS)}.",
            returncode=1,
            error_code="INVALID_MOTOR",
        )

    if motor == "historian":
        mem = await execute_isycode_readonly_tool(root, "isycode_isymem_recall", {"query": query or root.name, "limit": 6})
        log = await execute_isycode_readonly_tool(root, "isycode_git_log", {"limit": 12})
        status = await execute_isycode_readonly_tool(root, "isycode_git_status", {})
        resident = ResidentReader(root).context_pack()
        payload = {
            "motor": "historian",
            "workspace": str(root),
            "query": query or root.name,
            "git_status": status.stdout if status.success else status.stderr,
            "recent_commits": log.stdout if log.success else log.stderr,
            "isymem": json.loads(mem.stdout) if mem.success else {"error": mem.stderr},
            "resident_summary": resident,
        }
        return ExecutionResult(True, stdout=json.dumps(payload, indent=2, ensure_ascii=False))

    if motor == "planner":
        status = await execute_isycode_readonly_tool(root, "isycode_git_status", {})
        worktrees = await execute_isycode_readonly_tool(root, "isycode_worktrees", {})
        top_entries = sorted(
            p.name + ("/" if p.is_dir() else "")
            for p in root.iterdir()
            if not p.name.startswith(".") and p.name not in {"__pycache__", "node_modules", ".venv"}
        )[:60]
        entrypoints: dict[str, str] = {}
        for name in _ENTRYPOINTS:
            fp = root / name
            if fp.is_file():
                try:
                    entrypoints[name] = fp.read_text(encoding="utf-8", errors="replace")[:900]
                except OSError:
                    pass
        payload = {
            "motor": "planner",
            "workspace": str(root),
            "goal": query,
            "top_entries": top_entries,
            "entrypoints_found": list(entrypoints.keys()),
            "entrypoints_preview": entrypoints,
            "sandbox_toolchains": detect_available_toolchains(),
            "git_status": status.stdout if status.success else status.stderr,
            "worktrees": json.loads(worktrees.stdout) if worktrees.success else [],
            "next_step_guidance": (
                "Usa estos entrypoints y toolchains verificados. "
                "Antes de llamar clases/funciones por python3 -c, inspecciona el archivo con isycode_motor(motor='inspector', target='...')."
            ),
        }
        return ExecutionResult(True, stdout=json.dumps(payload, indent=2, ensure_ascii=False))

    if motor == "inspector":
        raw_target = target or query
        if not raw_target:
            return ExecutionResult(
                False,
                stderr="TARGET_REQUIRED: indica target (ruta relativa de archivo o símbolo a buscar).",
                returncode=1,
                error_code="TARGET_REQUIRED",
            )
        candidate = (root / raw_target).resolve()
        try:
            candidate.relative_to(root)
            in_workspace = True
        except ValueError:
            in_workspace = False
        if in_workspace and candidate.is_file():
            info = _inspect_python_file(candidate) if candidate.suffix == ".py" else _inspect_generic_file(candidate)
            return ExecutionResult(True, stdout=json.dumps({"motor": "inspector", "target": raw_target, **info}, indent=2, ensure_ascii=False))
        # Symbol search across workspace source files
        matches: list[dict[str, Any]] = []
        pattern = re.compile(re.escape(raw_target))
        for ext in ("*.py", "*.zig", "*.ts", "*.tsx", "*.js", "*.rs", "*.go"):
            for fp in root.rglob(ext):
                if any(part.startswith(".") or part in {"node_modules", ".venv", "venv", "target", "zig-out", "__pycache__"} for part in fp.parts):
                    continue
                try:
                    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                for idx, line in enumerate(lines, 1):
                    if pattern.search(line):
                        matches.append({"file": str(fp.relative_to(root)), "line": idx, "text": line.strip()[:160]})
                        if len(matches) >= 30:
                            break
                if len(matches) >= 30:
                    break
            if len(matches) >= 30:
                break
        return ExecutionResult(
            True,
            stdout=json.dumps({"motor": "inspector", "symbol": raw_target, "matches": matches}, indent=2, ensure_ascii=False),
        )

    # motor == "hub_route"
    client = ISyMCPHubClient()
    if not client.available:
        return ExecutionResult(
            False,
            stderr="ISYMCP_HUB_UNAVAILABLE: no se encontró isymcp-hub para enrutar la tarea.",
            returncode=1,
            error_code="ISYMCP_HUB_UNAVAILABLE",
        )
    disc = await client.discover(query=query or None, limit=12)
    if not disc.get("ok"):
        return ExecutionResult(False, stderr=disc.get("error", "Error en hub_discover"), returncode=1, error_code="ISYMCP_HUB_ERROR")
    described: list[dict[str, Any]] = []
    try:
        parsed = json.loads(disc.get("text", "{}"))
        candidates = parsed.get("matches") or parsed.get("tools") or []
        for item in candidates[:3]:
            if isinstance(item, dict) and item.get("server") and item.get("name"):
                desc = await client.describe(str(item["server"]), str(item["name"]))
                if desc.get("ok"):
                    described.append({
                        "server": item["server"],
                        "tool": item["name"],
                        "schema": desc.get("text", "")[:2500],
                    })
    except Exception:
        pass
    payload = {
        "motor": "hub_route",
        "query": query,
        "discovery": disc.get("text", "")[:4000],
        "ready_to_execute_schemas": described,
        "how_to_run": "Llama isycode_mcp_execute(server=..., tool=..., arguments={...}) respetando el schema exacto.",
    }
    return ExecutionResult(True, stdout=json.dumps(payload, indent=2, ensure_ascii=False))
