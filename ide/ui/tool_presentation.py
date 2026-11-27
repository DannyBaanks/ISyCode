"""Deterministic presentation hook over real tool arguments/results.

This only formats native UI. It never changes model output, wire results,
policy, approval or evidence. Unknown/malformed payloads stay unknown.
"""
from __future__ import annotations

import json
import shlex

BROAD_GLOBS = {"**/*", "**", "*", "./**/*", "./*"}
TITLES = {"project_tree": "Árbol del proyecto", "read": "Leer archivo",
          "write": "Crear archivo", "edit": "Editar archivo", "glob": "Buscar archivos",
          "grep": "Buscar texto", "resident_query": "Consultar residente",
          "resident_scan": "Escaneo estructural", "run_command": "Ejecutar comando",
          "verify": "Verificar contratos internos",
          "isycode_git_status": "Git status",
          "isycode_git_diff": "Git diff",
          "isycode_git_log": "Historial Git",
          "isycode_worktrees": "Git worktrees",
          "isycode_isymem_recall": "Memoria isymem",
          "isycode_mcp_servers": "ISyMCP Hub / MCP",
          "isycode_mkdir": "Crear carpeta",
          "isycode_move_file": "Mover archivo",
          "isycode_delete_file": "Eliminar archivo"}
ERRORS = {"FILE_NOT_FOUND": "no encontrado", "PROJECT_PATH_NOT_FOUND": "no encontrada",
          "PATH_NOT_FOUND": "no encontrada", "NOT_A_DIRECTORY": "no es una carpeta",
          "NOT_A_FILE": "no es un archivo", "PROJECT_PATH_EXCLUDED": "excluida de la vista",
          "PROJECT_SYMLINK_EXCLUDED": "enlace excluido", "PATH_OUTSIDE_WORKSPACE": "fuera del proyecto",
          "INVALID_PAGE": "paginación inválida", "PLAN_MODE_WRITE_DENIED": "bloqueado en PLAN",
          "USER_REJECTED": "rechazado por ti", "CANCELLED": "detenida",
          "TOOL_DISABLED": "herramienta desactivada", "POLICY_DENIED": "bloqueado por la política",
          "APPROVAL_REQUIRED": "requiere aprobación", "SEARCH_LIMIT": "límite de búsqueda alcanzado"}


def compact(value, limit=180):
    if isinstance(value, (dict, list, tuple)):
        return "valor estructurado · ver Detalles"
    text = " ".join(str(value).split())
    return text[:limit] + ("…" if len(text) > limit else "")


def _payload(stdout):
    if not isinstance(stdout, str) or len(stdout) > 1_000_000:
        return None
    try:
        value = json.loads(stdout)
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError):
        return None


def _count(data, field):
    value = data.get(field)
    return len(value) if isinstance(value, list) else None


def present_tool(name, arguments, result=None):
    """Return bounded plain-text title/summary/status from an actual result."""
    args = arguments if isinstance(arguments, dict) else {}
    directory = name == "project_tree" or (name == "glob" and isinstance(args.get("pattern"), str) and args["pattern"] in BROAD_GLOBS)
    title = "Árbol del proyecto" if directory else TITLES.get(name, compact(name, 60))
    path = compact(args.get("path", "."))
    if directory:
        subject = "Carpeta: " + ("raíz del proyecto" if path in {".", ""} else path)
    elif name in {"read", "write", "edit"}:
        subject = "Archivo: " + compact(args.get("path", "sin ruta"))
    elif name == "resident_query":
        subject = "Residente · categoría: " + compact(args.get("category", "general"), 50)
    elif name == "resident_scan":
        subject = "Escaneo de referencias y cambios del proyecto"
    elif name == "glob":
        subject = "Archivos: " + compact(args.get("pattern", "sin patrón"))
    elif name == "grep":
        subject = "Texto: " + compact(args.get("pattern", ""), 100) + " · carpeta: " + path
    elif name == "run_command":
        argv = args.get("argv")
        command = shlex.join(argv) if isinstance(argv, list) and all(isinstance(x, str) for x in argv) else "argumentos recibidos en formato no válido"
        subject = "Comando: " + compact(command)
    else:
        subject = title + (" · " + compact(args.get("target")) if args.get("target") else "")
    if result is None:
        return {"title": title, "summary": subject + " · ejecutando…", "status": "ejecutando…"}
    if not result.get("success"):
        code = result.get("error_code", "")
        prefix = str(result.get("stderr") or "").split(":", 1)[0]
        # Runtime discovery currently returns a generic code with a typed prefix.
        if code == "RUNTIME_ERROR" and prefix in ERRORS:
            code = prefix
        description = ERRORS.get(code, "falló · consulta Detalles")
        return {"title": title, "summary": subject + " · " + description,
                "status": "■ detenida" if code == "CANCELLED" else "✗ " + description}
    data = _payload(result.get("stdout", "")) if name in {"project_tree", "glob", "grep", "resident_query", "resident_scan"} else None
    status, summary = "✓ completada", subject + " · completado"
    if directory and data is not None and isinstance(data.get("entries"), list):
        count = len(data["entries"])
        partial = bool(data.get("truncated"))
        status = f"✓ {count} elementos" + (" · vista parcial" if partial else "")
        summary = subject + (" · sin entradas visibles" if count == 0 and not partial else f" · {count} elementos en esta página")
        if partial:
            summary += " · vista parcial"
        names = [compact(item.get("path", ""), 65) for item in data["entries"][:4] if isinstance(item, dict)]
        if names:
            summary += "\n" + " · ".join(names) + (" · …" if count > 4 else "")
    elif name == "resident_query" and data is not None:
        references = _count(data, "relevant")
        restrictions = _count(data, "constraints")
        summary = "Residente: " + (f"{references} referencias registradas" if references is not None else "consulta recibida")
        if restrictions is not None:
            summary += f" · {restrictions} restricciones"
        summary += "\nExistencia de archivos en disco no comprobada por esta consulta."
        status = "✓ consulta recibida" + (" · hechos desconocidos" if data.get("status") == "unknown" else "")
    elif name == "resident_scan" and data is not None:
        changes = [(label, _count(data, key)) for label, key in (("añadidos", "files_added"), ("modificados", "files_modified"), ("eliminados", "files_deleted"))]
        summary = "Escaneo estructural: " + " · ".join(f"{n} {label}" for label, n in changes if n is not None)
        if not any(n is not None for _, n in changes):
            summary = "Escaneo estructural recibido · consulta Detalles"
    elif name == "grep" and data is not None and isinstance(data.get("matches"), list):
        count = len(data["matches"])
        summary = subject + f" · {count} coincidencias recibidas"
        if data.get("truncated"):
            summary += " · resultado parcial"
        skipped = data.get("skipped_files")
        if type(skipped) is int and skipped > 0:
            summary += f" · {skipped} archivos omitidos"
    elif name == "read":
        content = result.get("stdout") or ""
        summary = subject + (" · archivo vacío" if not content else f" · lectura recibida ({len(content.splitlines())} líneas)")
    elif name in {"write", "edit"}:
        summary = subject + " · cambio aplicado"
    elif name == "run_command":
        code = result.get("returncode")
        summary = subject + (f" · código de salida: {code}" if code is not None else " · resultado recibido")
    elif name == "glob":
        content = result.get("stdout") or ""
        if content.lstrip().startswith(("{", "[")):
            summary = subject + " · salida estructurada recibida · consulta Detalles"
        else:
            summary = subject + (f" · {len(content.splitlines())} rutas recibidas" if content else " · sin rutas coincidentes")
    elif name not in TITLES:
        summary = subject + " · salida disponible en Detalles"
    return {"title": title, "summary": summary[:650], "status": status}
