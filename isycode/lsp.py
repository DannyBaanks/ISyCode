"""Read-only LSP adapter for installed servers with syscall-level network denial."""
from __future__ import annotations

import asyncio
import ctypes.util
import json
import os
import shutil
from pathlib import Path
from typing import Any

try:
    import resource
except ModuleNotFoundError:  # pragma: no cover - no resource limits outside POSIX
    resource = None

MAX_FRAME_BYTES = 2_000_000
MAX_SYMBOLS = 500

# This host denies creating a network namespace, and Bubblewrap's --seccomp FD
# path cannot install a filter through the outer container's prctl policy.
# Load libseccomp through its seccomp(2) API in a tiny trusted bootstrap after
# Bubblewrap has finished constructing namespaces/mounts and before exec'ing
# the language server. The filter is inherited across exec and child processes.
_SECCOMP_BOOTSTRAP = r'''import ctypes, os, resource, sys
# Apply process-count limits only after Bubblewrap has created its namespaces.
# Applying RLIMIT_NPROC to the launcher can make namespace setup fail with
# EAGAIN when the host user already owns more than this many processes.
resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
lib = ctypes.CDLL("libseccomp.so.2")
lib.seccomp_init.argtypes = [ctypes.c_uint32]
lib.seccomp_init.restype = ctypes.c_void_p
lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
lib.seccomp_rule_add.restype = ctypes.c_int
lib.seccomp_load.argtypes = [ctypes.c_void_p]
lib.seccomp_load.restype = ctypes.c_int
lib.seccomp_release.argtypes = [ctypes.c_void_p]
ctx = lib.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
if not ctx:
    raise SystemExit("seccomp policy unavailable")
try:
    denied = ("socket socketpair connect bind listen accept accept4 sendto recvfrom "
                "sendmsg recvmsg sendmmsg recvmmsg shutdown setsockopt getsockopt "
              "getsockname getpeername io_uring_setup io_uring_enter io_uring_register "
              "socketcall unshare setns").split()
    for name in denied:
        number = lib.seccomp_syscall_resolve_name(name.encode())
        if number >= 0 and lib.seccomp_rule_add(ctx, 0x00050000 | 1, number, 0):
            raise SystemExit("could not compile network-deny policy")
    if lib.seccomp_load(ctx):
        raise SystemExit("could not install network-deny policy")
finally:
    lib.seccomp_release(ctx)
os.execv(sys.argv[1], sys.argv[1:])
'''


def discover_servers() -> list[dict[str, Any]]:
    """Inspect known LSP executables without starting them."""
    found: list[dict[str, Any]] = []
    bwrap = shutil.which("bwrap")
    node = shutil.which("node")
    pyright = shutil.which("pyright-langserver")
    if pyright:
        script = Path(pyright).resolve(strict=True)
        node_path = Path(node).resolve(strict=True) if node else None
        sandbox = Path(bwrap).resolve(strict=True) if bwrap else None
        package_root = script.parent
        ready = bool(node_path and sandbox and ctypes.util.find_library("seccomp")
                     and resource is not None
                     and hasattr(resource, "prlimit") and script.is_file()
                     and (package_root / "dist" / "pyright-langserver.js").is_file())
        found.append({
            "id": "pyright",
            "label": "Pyright Language Server",
            "state": "sandbox_ready" if ready else "installed_unavailable",
            "command": pyright,
            "server_executable": str(script),
            "node_executable": str(node_path) if node_path else "",
            "sandbox_executable": str(sandbox) if sandbox else "",
            "capability": "workspace/symbol",
        })
    rust_analyzer = shutil.which("rust-analyzer")
    if rust_analyzer:
        found.append({
            "id": "rust-analyzer",
            "label": "rust-analyzer",
            "state": "installed_unsupported",
            "command": rust_analyzer,
            "capability": "",
        })
    for server_id, label, command in (
        ("typescript", "TypeScript Language Server", "typescript-language-server"),
        ("gopls", "gopls", "gopls"),
        ("clangd", "clangd", "clangd"),
        ("jdtls", "Eclipse JDT Language Server", "jdtls"),
        ("pylsp", "Python LSP Server", "pylsp"),
    ):
        executable = shutil.which(command)
        if executable:
            found.append({"id": server_id, "label": label,
                          "state": "installed_unsupported", "command": executable,
                          "capability": ""})
    return found


def _frame(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError("LSP request exceeds the frame limit")
    return f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload


async def _read_message(reader: asyncio.StreamReader) -> dict[str, Any]:
    content_length: int | None = None
    header_size = 0
    while True:
        line = await reader.readline()
        header_size += len(line)
        if not line or header_size > 8192:
            raise RuntimeError("LSP server returned invalid headers")
        if line in {b"\r\n", b"\n"}:
            break
        key, sep, value = line.partition(b":")
        if sep and key.strip().lower() == b"content-length":
            try:
                content_length = int(value.strip())
            except ValueError as exc:
                raise RuntimeError("LSP server returned an invalid frame length") from exc
    if content_length is None or not 0 <= content_length <= MAX_FRAME_BYTES:
        raise RuntimeError("LSP server frame is missing or exceeds 2 MB")
    payload = await reader.readexactly(content_length)
    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise RuntimeError("LSP server returned a non-object message")
    return message


def _server_request_response(message: dict[str, Any]) -> dict[str, Any] | None:
    """Answer the small, read-only set of client requests Pyright may send.

    Requests that would mutate the editor/workspace are explicitly rejected.
    A ``None`` return means the message was a notification and needs no reply.
    """
    if "method" not in message or "id" not in message:
        return None
    method = message.get("method")
    request_id = message.get("id")
    if method == "workspace/configuration":
        params = message.get("params")
        items = params.get("items", []) if isinstance(params, dict) else []
        result: Any = [None for _ in items] if isinstance(items, list) else []
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    if method in {"window/workDoneProgress/create", "client/registerCapability",
                  "client/unregisterCapability", "window/showMessageRequest"}:
        return {"jsonrpc": "2.0", "id": request_id, "result": None}
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32601, "message": "Client request is not supported"}}


async def _response(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                    request_id: int, timeout_s: float,
                    expected: type = dict) -> dict[str, Any]:
    async def receive() -> dict[str, Any]:
        while True:
            message = await _read_message(reader)
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError("LSP server rejected the request")
                result = message.get("result")
                if not isinstance(result, expected):
                    raise RuntimeError("LSP server returned an invalid result")
                return {"result": result}
            response = _server_request_response(message)
            if response is not None:
                writer.write(_frame(response))
                await writer.drain()
    return await asyncio.wait_for(receive(), timeout=timeout_s)


def _sandbox_command(root: Path, server: dict[str, Any]) -> list[str]:
    sandbox = str(Path(server["sandbox_executable"]).resolve(strict=True))
    script = Path(server["server_executable"]).resolve(strict=True)
    node = Path(server["node_executable"]).resolve(strict=True)
    if not script.is_file() or not node.is_file() or not os.access(node, os.X_OK):
        raise RuntimeError("Pyright runtime files are unavailable")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError("Workspace root is unavailable")
    # Only the selected workspace and read-only OS/runtime files are visible.
    # This host denies a network namespace. Keep the network namespace shared,
    # then install a fail-closed seccomp deny-list before the untrusted server
    # starts. No home directory or credentials are mounted.
    args = [sandbox, "--die-with-parent", "--unshare-all", "--share-net", "--clearenv",
            "--ro-bind", "/usr", "/usr"]
    for source, destination, alias in (("/bin", "/bin", "/usr/bin"),
                                       ("/lib", "/lib", "/usr/lib"),
                                       ("/lib64", "/lib64", "/usr/lib64")):
        if Path(source).is_symlink():
            args.extend(["--symlink", alias, destination])
        elif Path(source).exists():
            args.extend(["--ro-bind", source, destination])
    args.extend(["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                 "--dir", "/runtime", "--dir", "/runtime/pyright", "--dir", "/workspace",
                 "--ro-bind", str(script.parent), "/runtime/pyright",
                 "--ro-bind", str(node), "/runtime/node",
                 "--ro-bind", str(root), "/workspace",
                 "--chdir", "/workspace",
                 "--setenv", "HOME", "/tmp",
                 "--setenv", "XDG_CONFIG_HOME", "/tmp/config",
                 "--setenv", "PATH", "/usr/bin:/bin:/runtime",
                 "--", "/usr/bin/python3", "-c", _SECCOMP_BOOTSTRAP,
                 "/runtime/node", "/runtime/pyright/langserver.index.js", "--stdio"])
    return args


async def pyright_workspace_symbols(root: Path, query: str,
                                    server: dict[str, Any],
                                    timeout_s: float = 25.0) -> dict[str, Any]:
    """Perform initialize + workspace/symbol in a bubblewrap, read-only sandbox."""
    if not isinstance(query, str) or not query.strip() or len(query) > 256:
        raise ValueError("Symbol query must contain 1–256 characters")
    root = root.resolve(strict=True)
    command = _sandbox_command(root, server)
    proc = await asyncio.create_subprocess_exec(
        *command, cwd="/", stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        limit=MAX_FRAME_BYTES + 8192,
    )
    deadline = asyncio.get_running_loop().time() + timeout_s
    try:
        if resource is None:
            raise RuntimeError("OS process limits are unavailable")
        resource.prlimit(proc.pid, resource.RLIMIT_CPU, (30, 30))
        resource.prlimit(proc.pid, resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        resource.prlimit(proc.pid, resource.RLIMIT_NOFILE, (128, 128))
        resource.prlimit(proc.pid, resource.RLIMIT_FSIZE, (4 * 1024**2, 4 * 1024**2))
    except (AttributeError, OSError, ValueError) as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError("LSP process resource limits could not be applied") from exc
    try:
        initialize = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "processId": None,
                "rootUri": "file:///workspace",
                "workspaceFolders": [{"uri": "file:///workspace", "name": root.name}],
                "capabilities": {}, "trace": "off",
                "clientInfo": {"name": "isycode", "version": "0.1.0"},
            },
        }
        proc.stdin.write(_frame(initialize))
        await proc.stdin.drain()
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError("Pyright initialize exceeded its deadline")
        initialized = await _response(proc.stdout, proc.stdin, 1, remaining)
        capabilities = initialized["result"].get("capabilities", {})
        if not isinstance(capabilities, dict) or not capabilities.get("workspaceSymbolProvider"):
            raise RuntimeError("Pyright did not advertise workspace symbol search")
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
        symbols: list[Any] = []
        request_id = 1
        for delay in (0.0, 0.2, 0.5, 0.8):
            if delay:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError("Pyright workspace indexing exceeded its deadline")
                await asyncio.sleep(min(delay, remaining))
            request_id += 1
            proc.stdin.write(_frame({"jsonrpc": "2.0", "id": request_id,
                                     "method": "workspace/symbol",
                                     "params": {"query": query.strip()}}))
            await proc.stdin.drain()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError("Pyright workspace search exceeded its deadline")
            response = await _response(proc.stdout, proc.stdin, request_id, remaining, list)
            symbols = response["result"]
            if symbols:
                break
        if not isinstance(symbols, list):
            raise RuntimeError("Pyright returned malformed workspace symbols")
        clipped = symbols[:MAX_SYMBOLS]
        clean = []
        for item in clipped:
            if not isinstance(item, dict):
                continue
            location = item.get("location", {})
            uri = location.get("uri", "") if isinstance(location, dict) else ""
            if uri and uri != "file:///workspace" and not uri.startswith("file:///workspace/"):
                continue
            clean.append(item)
        shutdown_id = request_id + 1
        proc.stdin.write(_frame({"jsonrpc": "2.0", "id": shutdown_id,
                                 "method": "shutdown", "params": None}))
        await proc.stdin.drain()
        try:
            await _response(proc.stdout, proc.stdin, shutdown_id, 2.0)
        except (asyncio.TimeoutError, RuntimeError):
            pass
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "exit", "params": None}))
        await proc.stdin.drain()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        return {
            "server": "pyright",
            "protocol": "LSP",
            "operation": "workspace/symbol",
            "query": query.strip(),
            "workspace_root": str(root),
            "symbols": clean,
            "truncated": len(symbols) > MAX_SYMBOLS,
            "sandbox": {"read_only_workspace": True,
                        "network": "socket syscalls denied by seccomp; host namespace shared"},
        }
    except (asyncio.CancelledError, Exception):
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise


__all__ = ["discover_servers", "pyright_workspace_symbols"]
