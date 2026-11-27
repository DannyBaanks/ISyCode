"""Runtime base classes."""

from __future__ import annotations
import asyncio
import fnmatch
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
import subprocess
import json
import tempfile
from pathlib import Path
from core.project_tree import ProjectView, visible_name


@dataclass
class ExecutionResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    evidence: dict = None
    error_code: str = ""


@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str


class BaseRuntime(ABC):
    """Base runtime for executing tool calls."""
    
    def __init__(self, working_dir: Path):
        self.working_dir = working_dir
    
    @abstractmethod
    async def execute(self, tool_call: ToolCall) -> ExecutionResult:
        pass
    
    @abstractmethod
    async def verify(self, result: ExecutionResult) -> dict:
        pass


class SandboxRuntime(BaseRuntime):
    """Layer A: Python sandbox (best effort, NO security boundary)."""
    
    def __init__(self, working_dir: Path):
        super().__init__(working_dir)
        self._interp = None
    
    def _get_interp(self):
        if self._interp is None:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from sandbox.interp import SandboxInterp
            self._interp = SandboxInterp()
        return self._interp

    def _root(self) -> Path:
        return self.working_dir.resolve()

    def _resolve_path(self, raw_path: Any, *, allow_root: bool = False) -> Path:
        """Resolve a path and enforce the runtime root boundary.

        ``Path.resolve`` handles ``..`` and existing symlinks. The final
        ``relative_to`` check is intentional: string-prefix checks are not a
        valid containment boundary (for example, ``root2`` is not ``root``).
        """
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("PATH_REQUIRED: path must be a non-empty string")
        root = self._root()
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve(strict=False)
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"PATH_OUTSIDE_WORKSPACE: la ruta '{raw_path}' ({resolved}) sale del proyecto '{root}'. "
                "Abre o vincula esa carpeta como proyecto, o usa una ruta relativa dentro del workspace."
            ) from exc
        if any(part in {".git", ".isyvm", ".isycode-ide"} for part in relative.parts):
            raise ValueError("HOST_STATE_PROTECTED: agent tools cannot access host metadata")
        if resolved == root and not allow_root:
            raise ValueError("PATH_IS_WORKSPACE_ROOT: file path required")
        return resolved

    def _resolve_pattern(self, raw_pattern: Any) -> str:
        """Validate a glob pattern before expanding it."""
        if not isinstance(raw_pattern, str) or not raw_pattern.strip():
            raise ValueError("PATTERN_REQUIRED: pattern must be a non-empty string")
        root = self._root()
        pattern_path = Path(raw_pattern)
        if not pattern_path.is_absolute():
            pattern_path = root / pattern_path

        wildcard_chars = "*?["
        static_parts = []
        for part in pattern_path.parts:
            if any(char in part for char in wildcard_chars):
                break
            static_parts.append(part)
        static_path = Path(*static_parts) if static_parts else root
        resolved_static = static_path.resolve(strict=False)
        try:
            resolved_static.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"PATH_OUTSIDE_WORKSPACE: el patrón '{raw_pattern}' ({resolved_static}) sale del proyecto '{root}'. "
                "Vincula esa carpeta o acota el patrón a una ruta relativa dentro del proyecto."
            ) from exc
        return str(pattern_path)

    def _failure(self, code: str, message: str) -> ExecutionResult:
        return ExecutionResult(False, stderr=message, returncode=1, error_code=code)
    
    async def execute(self, tool_call: ToolCall) -> ExecutionResult:
        name = tool_call.name
        args = tool_call.arguments
        
        try:
            if name == "read":
                return await self._read(args)
            elif name == "write":
                return await self._write(args)
            elif name == "edit":
                return await self._edit(args)
            elif name == "glob":
                return await self._glob(args)
            elif name == "project_tree":
                view = await ProjectView(self.working_dir).snapshot(args.get("path", "."),
                                    offset=args.get("offset", 0), limit=args.get("limit", 60))
                return ExecutionResult(True, stdout=json.dumps(view, ensure_ascii=False))
            elif name == "grep":
                return await self._grep(args)
            elif name == "python":
                return await self._python(args)
            elif name == "verify":
                return await self._verify(args)
            elif name == "bash":
                return self._failure("UNSUPPORTED_TOOL", "bash is disabled in the local agent runtime")
            else:
                return self._failure("INVALID_TOOL", f"Unknown tool: {name}")
        except Exception as e:
            return self._failure("RUNTIME_ERROR", str(e))
    
    async def _read(self, args: dict) -> ExecutionResult:
        try:
            path = self._resolve_path(args.get("path"))
        except ValueError as exc:
            return self._failure(str(exc).split(":", 1)[0], str(exc))
        if not path.exists():
            return self._failure("FILE_NOT_FOUND", f"File not found: {path}")
        if not path.is_file():
            return self._failure("NOT_A_FILE", f"Not a file: {path}")
        # Preserve line endings so the editor's base hash matches disk bytes.
        with path.open("r", encoding="utf-8", newline="") as stream:
            content = stream.read()
        return ExecutionResult(True, stdout=content)
    
    async def _write(self, args: dict) -> ExecutionResult:
        if not isinstance(args.get("content"), str):
            return self._failure("CONTENT_REQUIRED", "content must be a string")
        try:
            path = self._resolve_path(args.get("path"))
        except ValueError as exc:
            return self._failure(str(exc).split(":", 1)[0], str(exc))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return ExecutionResult(True, stdout=f"Written {len(args['content'])} bytes to {path}")
    
    async def _edit(self, args: dict) -> ExecutionResult:
        try:
            path = self._resolve_path(args.get("path"))
        except ValueError as exc:
            return self._failure(str(exc).split(":", 1)[0], str(exc))
        if not path.is_file():
            return self._failure("FILE_NOT_FOUND", f"File not found: {path}")
        content = path.read_text(encoding="utf-8")
        if args["old"] not in content:
            return self._failure("TEXT_NOT_FOUND", f"Text not found: {args['old'][:50]}...")
        content = content.replace(args["old"], args["new"], 1)
        path.write_text(content, encoding="utf-8")
        return ExecutionResult(True, stdout=f"Edited {path}")
    
    async def _glob(self, args: dict) -> ExecutionResult:
        try:
            pattern = self._resolve_pattern(args.get("pattern"))
            root = self._root()
            if args.get("pattern") in {"**/*", "**", "*", "./**/*", "./*"}:
                view = await ProjectView(root).snapshot()
                view["hint"] = "Broad glob converted to a project directory snapshot. Expand relevant folders with project_tree(path); this is not a recursive file listing."
                return ExecutionResult(True, stdout=json.dumps(view, ensure_ascii=False))
            parts = Path(pattern).relative_to(root).parts
            if not any(any(c in part for c in "*?[") for part in parts):
                path = self._resolve_path(str(Path(pattern)), allow_root=True)
                ProjectView(root).path(path.relative_to(root).as_posix())
                return ExecutionResult(True, stdout=str(path.relative_to(root)) if path.exists() else "")
            if any(part in {".", ".."} for part in parts):
                raise ValueError("INVALID_PATTERN: use a workspace-relative pattern without parent components")
            # Expand one directory at a time. Never materialize an unbounded
            # recursive glob (or follow directory symlinks) on the agent loop.
            def closure(states):
                states = set(states)
                for index in range(len(parts)):
                    if index in states and parts[index] == "**":
                        states.add(index + 1)
                return states

            stack = [(root, closure({0}))]
            files = []
            visited, output_bytes, started = 0, 0, time.monotonic()
            while stack:
                directory, states = stack.pop()
                await asyncio.sleep(0)
                with os.scandir(directory) as entries:
                    for entry in entries:
                        visited += 1
                        if visited % 64 == 0:
                            await asyncio.sleep(0)
                        if visited > 20_000 or time.monotonic() - started > 10:
                            return self._failure("SEARCH_LIMIT", "La búsqueda alcanzó su límite. Abre la carpeta del proyecto o usa un patrón más específico.")
                        if not visible_name(entry.name) or entry.is_symlink():
                            continue
                        next_states = set()
                        for index in states:
                            if index == len(parts):
                                continue
                            part = parts[index]
                            if entry.name.startswith(".") and not part.startswith("."):
                                continue
                            if part == "**":
                                next_states.add(index)
                            elif fnmatch.fnmatchcase(entry.name, part):
                                next_states.add(index + 1)
                        next_states = closure(next_states)
                        if not next_states:
                            continue
                        match = Path(entry.path)
                        if len(parts) in next_states:
                            # Revalidate containment before exporting the path.
                            self._resolve_path(str(match), allow_root=True)
                            relative = str(match.relative_to(root))
                            output_bytes += len(relative.encode("utf-8")) + 1
                            if len(files) >= 200 or output_bytes > 12_000:
                                return self._failure("SEARCH_LIMIT", "Demasiados resultados. Usa un patrón más específico; la lista no se considera completa.")
                            files.append(relative)
                        if entry.is_dir(follow_symlinks=False) and any(index < len(parts) for index in next_states):
                            stack.append((match, next_states))
            return ExecutionResult(True, stdout="\n".join(sorted(files)))
        except ValueError as exc:
            return self._failure(str(exc).split(":", 1)[0], str(exc))
    
    async def _grep(self, args: dict) -> ExecutionResult:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern or len(pattern) > 512:
            return self._failure("INVALID_PATTERN", "grep necesita texto literal no vacío, de hasta 512 caracteres.")
        results, skipped, scanned, limited, output_size = [], 0, 0, False, 0
        try:
            async for file in ProjectView(self.working_dir).files(args.get("path", ".")):
                await asyncio.sleep(0)
                if scanned >= 2_000:
                    limited = True
                    break
                scanned += 1
                try:
                    # Read a bounded amount, not an entire large source/binary.
                    with file.open("rb") as stream:
                        raw = stream.read(1_000_001)
                    if len(raw) > 1_000_000 or b"\0" in raw:
                        skipped += 1
                        continue
                    content = raw.decode("utf-8")
                except (OSError, UnicodeError):
                    skipped += 1
                    continue
                for i, line in enumerate(content.splitlines(), 1):
                    if i % 64 == 0:
                        await asyncio.sleep(0)
                    if pattern in line:
                        item = {"path": file.relative_to(self._root()).as_posix(), "line": i, "text": line[:300]}
                        output_size += len(json.dumps(item, ensure_ascii=False))
                        if output_size > 12_000:
                            limited = True
                            break
                        results.append(item)
                        if len(results) >= 30:
                            limited = True
                            break
                if limited:
                    break
        except ValueError as exc:
            if str(exc).startswith("SEARCH_LIMIT:"):
                limited = True
            else:
                return self._failure(str(exc).split(":", 1)[0], str(exc))
        return ExecutionResult(True, stdout=json.dumps({"matches": results, "truncated": limited,
                    "skipped_files": skipped, "scanned_files": scanned, "syntax": "literal",
                    "hint": "Narrow path if truncated or files were skipped; no matches only applies to scanned readable files."}, ensure_ascii=False))
    
    async def _bash(self, args: dict) -> ExecutionResult:
        return self._failure("UNSUPPORTED_TOOL", "bash is disabled in the local agent runtime")
    
    async def _python(self, args: dict) -> ExecutionResult:
        try:
            from sandbox.interp import run_program
            result = run_program(args["code"])
            return ExecutionResult(True, stdout=str(result))
        except Exception as e:
            return self._failure("PYTHON_RUNTIME_ERROR", str(e))
    
    async def _verify(self, args: dict) -> ExecutionResult:
        """Inspect built-in formal contracts; this does not run project tests."""
        target = args.get("target", "all")
        if target == ".":
            target = "all"
        if target not in {"all", "sandbox_interp", "cpu"}:
            return self._failure("UNSUPPORTED_TARGET", "verify solo inspecciona contratos internos: all, sandbox_interp o cpu. Pruebas del proyecto: pendientes del runtime aislado.")
        try:
            from verifier.contract_verifier import run_all_checks_for
            reports = run_all_checks_for(target)
            checks = {name: [{"law": c.law, "result": c.result, "detail": c.detail} for c in values]
                      for name, values in reports.items()}
            passed = all(c.result == "PASS" for values in reports.values() for c in values)
            return ExecutionResult(passed, stdout=json.dumps({"scope": "IDE built-in formal contracts; not project tests", "checks": checks}, indent=2),
                                   returncode=0 if passed else 1, error_code="" if passed else "CONTRACT_FAILED")
        except Exception:
            return self._failure("VERIFY_ERROR", "No se pudo inspeccionar el contrato interno.")

    async def verify(self, result: ExecutionResult) -> dict:
        return {"runtime": "layer_a", "verified": result.success, "evidence": result.evidence}


class WASMRuntime(BaseRuntime):
    """Layer B: WASM runtime (real boundary)."""
    
    async def execute(self, tool_call: ToolCall) -> ExecutionResult:
        # TODO: Implement WASM execution via wasmtime/wasmer
        return ExecutionResult(False, stderr="WASM runtime not implemented", returncode=1)
    
    async def verify(self, result: ExecutionResult) -> dict:
        return {"runtime": "layer_b", "verified": result.success}


class VMRuntime(BaseRuntime):
    """Layer C: Hyper-V VM runtime (real boundary)."""
    
    async def execute(self, tool_call: ToolCall) -> ExecutionResult:
        # TODO: Implement VM execution
        return ExecutionResult(False, stderr="VM runtime not implemented", returncode=1)
    
    async def verify(self, result: ExecutionResult) -> dict:
        return {"runtime": "layer_c", "verified": result.success}
