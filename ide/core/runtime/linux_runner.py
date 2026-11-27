"""Standalone broker mounted read-only INSIDE the command namespace.

Input/output are proposals from an untrusted namespace, never host authority.
The host independently checks paths, limits, original hashes and consent.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shutil
import signal
import stat
from pathlib import Path


async def command(argv, cwd, timeout):
    process = await asyncio.create_subprocess_exec(*argv, cwd=cwd, stdin=asyncio.subprocess.DEVNULL,
                                                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                  start_new_session=True)
    total = 0
    async def read(stream):
        nonlocal total
        chunks = []
        while chunk := await stream.read(16384):
            total += len(chunk)
            if total > 1_000_000:
                raise ValueError("COMMAND_OUTPUT_LIMIT")
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")
    tasks = [asyncio.create_task(read(process.stdout)), asyncio.create_task(read(process.stderr))]
    try:
        async with asyncio.timeout(timeout):
            out, err = await asyncio.gather(*tasks)
            code = await process.wait()
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await process.wait()
        raise
    return code, out, err


def export_changes(config):
    originals = config["files"]
    seen, changed, unsupported = set(), {}, []
    total = 0
    for directory, dirs, files, fd in os.fwalk("/work", follow_symlinks=False):
        dirs[:] = [name for name in dirs if name not in config["exclude"] and not name.startswith(".")]
        for name in dirs + files:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                unsupported.append(str(Path(directory, name).relative_to("/work")) + " (enlace)")
        for name in files:
            if name.startswith(".") or name in config["exclude"]:
                continue
            path = str(Path(directory, name).relative_to("/work"))
            seen.add(path)
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(handle, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    unsupported.append(path + " (tipo o enlace no soportado)")
                    continue
                digest_state = hashlib.sha256()
                chunks, length = [], 0
                for chunk in iter(lambda: stream.read(65536), b""):
                    length += len(chunk)
                    digest_state.update(chunk)
                    if length <= 2_000_000:
                        chunks.append(chunk)
                digest = digest_state.hexdigest()
                original = originals.get(path)
                if original and digest == original["sha256"]:
                    if stat.S_IMODE(info.st_mode) != original["mode"]:
                        unsupported.append(path + " (cambio de permisos)")
                    continue
                if length > 2_000_000:
                    unsupported.append(path + " (más de 2 MB)")
                    continue
                raw = b"".join(chunks)
                try:
                    raw.decode("utf-8")
                except UnicodeDecodeError:
                    unsupported.append(path + " (binario)")
                    continue
                total += len(raw)
                if len(changed) >= 100 or total > 10_000_000:
                    raise ValueError("CHANGESET_LIMIT")
                changed[path] = base64.b64encode(raw).decode("ascii")
    for path in originals.keys() - seen:
        unsupported.append(path + " (eliminado)")
    return changed, unsupported


async def main():
    config = json.loads(Path("/launch.json").read_text())
    # Only the host-owned filtered input is copied; no host checkout is writable.
    shutil.copytree("/input", "/work", dirs_exist_ok=True)
    try:
        code, out, err = await command(config["argv"], "/work/" + config["cwd"], config["timeout"])
        changes, unsupported = export_changes(config)
        report = {"request": config["request"], "returncode": code, "stdout": out, "stderr": err,
                  "changes": changes, "unsupported": unsupported}
    except (ValueError, OSError, TimeoutError):
        report = {"request": config["request"], "error": "El comando excedió límites o produjo cambios no soportados; la carpeta original se conserva."}
    print(json.dumps(report, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
