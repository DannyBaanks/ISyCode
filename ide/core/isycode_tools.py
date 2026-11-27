"""Native ISyCode repo & ecosystem tools for the agent runtime.

All read-only tools are safe in PLAN and CODER modes.
Mutating file tools (mkdir, move_file, delete_file) enforce strict workspace
containment and require CODER mode + explicit operator approval.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
from pathlib import Path

from core.proposals import ProposalError
from core.runtime.base import ExecutionResult

READONLY_ISYCODE_TOOLS = {
    "isycode_git_status",
    "isycode_git_diff",
    "isycode_git_log",
    "isycode_worktrees",
    "isycode_isymem_recall",
    "isycode_mcp_servers",
    "isycode_mcp_discover",
    "isycode_mcp_describe",
    "isycode_motor",
    "isycode_attachment_inspect",
    "isycode_see_image",
}

MUTATING_ISYCODE_TOOLS = {
    "isycode_mkdir",
    "isycode_rmdir",
    "isycode_move_file",
    "isycode_delete_file",
    "isycode_mcp_execute",
}

ALL_ISYCODE_TOOLS = READONLY_ISYCODE_TOOLS | MUTATING_ISYCODE_TOOLS

MAX_OUTPUT_CHARS = 24_000


def _bounded(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncado a {limit} caracteres]"


def _safe_workspace_path(workspace: Path, raw: str, *, allow_root: bool = False) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ProposalError("PATH_REQUIRED: se requiere una ruta relativa no vacía.")
    root = workspace.resolve()
    cand = Path(raw)
    if not cand.is_absolute():
        cand = root / cand
    resolved = cand.resolve(strict=False)
    try:
        rel = resolved.relative_to(root)
    except ValueError as exc:
        raise ProposalError(f"PATH_OUTSIDE_WORKSPACE: '{raw}' sale del proyecto '{root}'.") from exc
    if any(part in {".git", ".isyvm", ".isycode-ide"} for part in rel.parts):
        raise ProposalError("HOST_STATE_PROTECTED: no se puede operar sobre metadatos protegidos del host.")
    if resolved == root and not allow_root:
        raise ProposalError("PATH_IS_WORKSPACE_ROOT: especifica un archivo o subcarpeta dentro del proyecto.")
    return resolved


async def _run_git(workspace: Path, args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(workspace), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", "git command timed out"
    return proc.returncode or 0, out_b.decode("utf-8", "replace"), err_b.decode("utf-8", "replace")


async def execute_isycode_readonly_tool(workspace: Path, name: str, arguments: dict) -> ExecutionResult:
    root = workspace.resolve()
    try:
        if name == "isycode_git_status":
            rc, out, err = await _run_git(root, ["status", "--porcelain=v1", "-b"])
            if rc != 0:
                return ExecutionResult(False, stderr=err.strip() or "No es un repositorio Git.", returncode=rc, error_code="GIT_ERROR")
            return ExecutionResult(True, stdout=_bounded(out.strip() or "(árbol limpio)"))

        if name == "isycode_git_diff":
            staged = bool(arguments.get("staged", False))
            path = arguments.get("path")
            cmd = ["diff", "--cached"] if staged else ["diff"]
            if isinstance(path, str) and path.strip():
                resolved = _safe_workspace_path(root, path, allow_root=True)
                cmd.extend(["--", str(resolved.relative_to(root))])
            rc, out, err = await _run_git(root, cmd)
            if rc != 0:
                return ExecutionResult(False, stderr=err.strip() or "Error ejecutando git diff.", returncode=rc, error_code="GIT_ERROR")
            return ExecutionResult(True, stdout=_bounded(out.strip() or "(sin diferencias)"))

        if name == "isycode_git_log":
            limit = arguments.get("limit", 15)
            try:
                limit = max(1, min(50, int(limit)))
            except (TypeError, ValueError):
                limit = 15
            rc, out, err = await _run_git(root, ["log", f"-n{limit}", "--oneline", "--decorate"])
            if rc != 0:
                return ExecutionResult(False, stderr=err.strip() or "Error ejecutando git log.", returncode=rc, error_code="GIT_ERROR")
            return ExecutionResult(True, stdout=_bounded(out.strip() or "(sin commits)"))

        if name == "isycode_worktrees":
            from core.worktrees import WorktreeManager
            wts = await WorktreeManager(root).list_worktrees()
            payload = [
                {
                    "path": str(w.path),
                    "branch": w.branch,
                    "head": w.head[:12] if w.head else "",
                    "bare": w.bare,
                    "locked": w.locked,
                    "prunable": w.prunable,
                }
                for w in wts
            ]
            return ExecutionResult(True, stdout=json.dumps({"worktrees": payload}, indent=2, ensure_ascii=False))

        if name == "isycode_isymem_recall":
            query = str(arguments.get("query", "")).strip().casefold()
            project = str(arguments.get("project", "")).strip().casefold()
            limit = max(1, min(15, int(arguments.get("limit", 6) or 6)))
            candidates = [
                root / "docs" / "agent" / "memory",
                Path.home() / "Development" / "ISyCo" / "docs" / "agent" / "memory",
                Path("/home/danny/Development/ISyCo/docs/agent/memory"),
            ]
            mem_dir = next((d for d in candidates if d.is_dir() and any(d.glob("*.md"))), None)
            if mem_dir is None:
                return ExecutionResult(True, stdout=json.dumps({"found": 0, "memories": [], "note": "Banco isymem no encontrado."}, ensure_ascii=False))
            hits = []
            for md in sorted(mem_dir.glob("*.md")):
                try:
                    txt = md.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                low = txt.casefold()
                if project and project not in md.stem.casefold() and f"project: {project}" not in low:
                    continue
                score = 0
                if query:
                    for token in query.split():
                        if token in md.stem.casefold():
                            score += 5
                        if token in low:
                            score += 2
                    if score == 0:
                        continue
                else:
                    score = 1
                hits.append((score, md.stem, txt[:450].strip()))
            hits.sort(key=lambda x: (-x[0], x[1]))
            top = [{"slug": slug, "score": sc, "excerpt": ex} for sc, slug, ex in hits[:limit]]
            return ExecutionResult(True, stdout=json.dumps({"bank": str(mem_dir), "found": len(top), "memories": top}, indent=2, ensure_ascii=False))

        if name == "isycode_mcp_servers":
            def _port_open(port: int) -> bool:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                        return True
                except OSError:
                    return False
            real_home = Path("/home/danny") if Path("/home/danny/.config/isycode/mcp.json").is_file() else Path.home()
            cfg = real_home / ".config" / "isycode" / "mcp.json"
            servers = {}
            if cfg.is_file():
                try:
                    data = json.loads(cfg.read_text(encoding="utf-8"))
                    raw = data.get("mcpServers") or data.get("servers") or {}
                    if isinstance(raw, dict):
                        for k, v in raw.items():
                            if isinstance(v, dict):
                                servers[k] = {
                                    "transport": "http" if v.get("url") else "stdio",
                                    "target": v.get("url") or v.get("command", ""),
                                    "disabled": bool(v.get("disabled", False)),
                                }
                except Exception:
                    servers = {"_error": "mcp.json inválido"}
            payload = {
                "hub_8798_active": _port_open(8798),
                "monitor_8799_active": _port_open(8799),
                "config_path": str(cfg),
                "servers": servers,
            }
            return ExecutionResult(True, stdout=json.dumps(payload, indent=2, ensure_ascii=False))

        if name == "isycode_mcp_discover":
            from core.isymcp_hub_client import ISyMCPHubClient
            client = ISyMCPHubClient()
            resp = await client.discover(
                server=arguments.get("server") or None,
                query=arguments.get("query") or None,
                include_idle=bool(arguments.get("include_idle", False)),
                limit=int(arguments.get("limit", 12) or 12),
            )
            if not resp.get("ok"):
                return ExecutionResult(False, stderr=resp.get("error", "Error consultando ISyMCP Hub."), returncode=1, error_code="ISYMCP_HUB_ERROR")
            return ExecutionResult(True, stdout=_bounded(resp.get("text", ""), limit=6_000))

        if name == "isycode_mcp_describe":
            from core.isymcp_hub_client import ISyMCPHubClient
            server = str(arguments.get("server", "")).strip()
            tool = str(arguments.get("tool", "")).strip()
            if not server or not tool:
                raise ProposalError("INVALID_ARGUMENTS: se requieren server y tool.")
            client = ISyMCPHubClient()
            resp = await client.describe(server, tool)
            if not resp.get("ok"):
                return ExecutionResult(False, stderr=resp.get("error", "Error obteniendo schema en ISyMCP Hub."), returncode=1, error_code="ISYMCP_HUB_ERROR")
            return ExecutionResult(True, stdout=_bounded(resp.get("text", "")))

        if name == "isycode_motor":
            from core.isycode_motors import run_isycode_motor
            res = await run_isycode_motor(root, arguments)
            if res.stdout:
                res.stdout = _bounded(res.stdout)
            return res

        if name == "isycode_attachment_inspect":
            from core.attachment_router import inspect_attachment
            res = inspect_attachment(root, str(arguments.get("path", "")))
            if res.stdout:
                res.stdout = _bounded(res.stdout)
            return res

        if name == "isycode_see_image":
            from core.attachment_router import see_image_with_flowsight
            res = await see_image_with_flowsight(
                root,
                token=str(arguments.get("token", "")),
                path=str(arguments.get("path", "")),
                split=str(arguments.get("split", "quarters")),
            )
            if res.stdout:
                res.stdout = _bounded(res.stdout)
            return res

        return ExecutionResult(False, stderr=f"Tool desconocida: {name}", returncode=1, error_code="INVALID_TOOL")
    except ValueError as exc:
        return ExecutionResult(False, stderr=str(exc), returncode=1, error_code=str(exc).split(":", 1)[0])
    except Exception as exc:
        return ExecutionResult(False, stderr=f"{type(exc).__name__}: {exc}", returncode=1, error_code="TOOL_ERROR")


def preview_isycode_mutating_tool(workspace: Path, name: str, arguments: dict) -> str:
    root = workspace.resolve()
    if name == "isycode_mcp_execute":
        server = str(arguments.get("server", "")).strip()
        tool = str(arguments.get("tool", "")).strip()
        if not server or not tool:
            raise ProposalError("INVALID_ARGUMENTS: se requieren server y tool para isycode_mcp_execute.")
        tool_args = arguments.get("arguments") or {}
        if not isinstance(tool_args, dict):
            raise ProposalError("INVALID_ARGUMENTS: arguments debe ser un objeto JSON.")
        return (
            f"Delegar ejecución a ISyMCP Hub:\n"
            f"  server: {server}\n"
            f"  tool:   {tool}\n"
            f"  args:   {json.dumps(tool_args, indent=2, ensure_ascii=False)[:1500]}"
        )
    if name == "isycode_mkdir":
        target = _safe_workspace_path(root, arguments.get("path", ""))
        return f"Crear carpeta:\n  + {target.relative_to(root)}/"
    if name == "isycode_rmdir":
        target = _safe_workspace_path(root, arguments.get("path", ""))
        if not target.exists():
            raise ProposalError(f"DIR_NOT_FOUND: no existe '{arguments.get('path')}'")
        if not target.is_dir() or target.is_symlink():
            raise ProposalError("NOT_A_DIR: isycode_rmdir solo elimina carpetas vacías (no archivos ni symlinks).")
        if any(target.iterdir()):
            raise ProposalError("DIR_NOT_EMPTY: la carpeta no está vacía; elimina sus archivos primero.")
        return f"Eliminar carpeta vacía:\n  - {target.relative_to(root)}/"
    if name == "isycode_move_file":
        src = _safe_workspace_path(root, arguments.get("src", ""))
        dst = _safe_workspace_path(root, arguments.get("dst", ""))
        if not src.exists():
            raise ProposalError(f"FILE_NOT_FOUND: no existe '{arguments.get('src')}'")
        return f"Mover / renombrar:\n  - {src.relative_to(root)}\n  + {dst.relative_to(root)}"
    if name == "isycode_delete_file":
        target = _safe_workspace_path(root, arguments.get("path", ""))
        if not target.exists():
            raise ProposalError(f"FILE_NOT_FOUND: no existe '{arguments.get('path')}'")
        if target.is_dir() or target.is_symlink():
            raise ProposalError("NOT_A_FILE: isycode_delete_file solo elimina archivos regulares (no carpetas ni symlinks).")
        return f"Eliminar archivo regular:\n  - {target.relative_to(root)} ({target.stat().st_size} bytes)"
    raise ProposalError(f"INVALID_TOOL: {name}")


def execute_isycode_mutating_tool(workspace: Path, name: str, arguments: dict) -> ExecutionResult:
    root = workspace.resolve()
    if name == "isycode_mkdir":
        target = _safe_workspace_path(root, arguments.get("path", ""))
        target.mkdir(parents=True, exist_ok=True)
        return ExecutionResult(True, stdout=f"Carpeta creada: {target.relative_to(root)}")
    if name == "isycode_rmdir":
        target = _safe_workspace_path(root, arguments.get("path", ""))
        if not target.exists():
            return ExecutionResult(False, stderr=f"DIR_NOT_FOUND: {target}", returncode=1, error_code="DIR_NOT_FOUND")
        if not target.is_dir() or target.is_symlink():
            return ExecutionResult(False, stderr="NOT_A_DIR: solo carpetas vacías.", returncode=1, error_code="NOT_A_DIR")
        if any(target.iterdir()):
            return ExecutionResult(False, stderr="DIR_NOT_EMPTY: la carpeta no está vacía.", returncode=1, error_code="DIR_NOT_EMPTY")
        target.rmdir()
        return ExecutionResult(True, stdout=f"Carpeta vacía eliminada: {target.relative_to(root)}")
    if name == "isycode_move_file":
        src = _safe_workspace_path(root, arguments.get("src", ""))
        dst = _safe_workspace_path(root, arguments.get("dst", ""))
        if not src.exists():
            return ExecutionResult(False, stderr=f"FILE_NOT_FOUND: {src}", returncode=1, error_code="FILE_NOT_FOUND")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return ExecutionResult(True, stdout=f"Movido: {src.relative_to(root)} → {dst.relative_to(root)}")
    if name == "isycode_delete_file":
        target = _safe_workspace_path(root, arguments.get("path", ""))
        if not target.exists():
            return ExecutionResult(False, stderr=f"FILE_NOT_FOUND: {target}", returncode=1, error_code="FILE_NOT_FOUND")
        if target.is_dir() or target.is_symlink():
            return ExecutionResult(False, stderr="NOT_A_FILE: solo archivos regulares.", returncode=1, error_code="NOT_A_FILE")
        target.unlink()
        return ExecutionResult(True, stdout=f"Archivo eliminado: {target.relative_to(root)}")
    return ExecutionResult(False, stderr=f"INVALID_TOOL: {name}", returncode=1, error_code="INVALID_TOOL")


async def execute_isycode_mcp_tool(workspace: Path, arguments: dict) -> ExecutionResult:
    from core.isymcp_hub_client import ISyMCPHubClient
    server = str(arguments.get("server", "")).strip()
    tool = str(arguments.get("tool", "")).strip()
    tool_args = arguments.get("arguments") or {}
    if not server or not tool or not isinstance(tool_args, dict):
        return ExecutionResult(False, stderr="INVALID_ARGUMENTS: server, tool y arguments dict son obligatorios.", returncode=1, error_code="INVALID_ARGUMENTS")
    client = ISyMCPHubClient()
    resp = await client.execute(server, tool, tool_args, timeout=60.0)
    if not resp.get("ok"):
        return ExecutionResult(
            False,
            stderr=_bounded(resp.get("error") or resp.get("text") or "Error ejecutando tool en ISyMCP Hub."),
            returncode=1,
            error_code="ISYMCP_HUB_ERROR",
            evidence={"mcp": {"server": server, "tool": tool}},
        )
    return ExecutionResult(
        True,
        stdout=_bounded(resp.get("text", "")),
        evidence={"mcp": {"server": server, "tool": tool}},
    )
