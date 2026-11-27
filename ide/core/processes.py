"""Bounded, cancellable CLI capture. Callers own argv and safe public errors."""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass


class ProcessFailure(ValueError):
    pass


@dataclass(frozen=True)
class ProcessOutput:
    returncode: int
    stdout: bytes
    stderr: bytes


async def capture_process(argv, *, cwd=None, env=None, timeout=30, limit=2_000_000, input_data=None):
    """No shell. Kill the process group on cancellation, timeout or overflow."""
    startup = asyncio.create_task(asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    ))
    try:
        process = await asyncio.shield(startup)
    except asyncio.CancelledError:
        # Cancellation can arrive while asyncio is still creating the child.
        # Recover its handle before leaving; otherwise the child can be orphaned.
        process = await startup
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.communicate()
        raise
    total = 0

    async def read(stream):
        nonlocal total
        chunks = []
        while chunk := await stream.read(16_384):
            total += len(chunk)
            if total > limit:
                raise ProcessFailure("OUTPUT_LIMIT: la salida supera el límite del IDE")
            chunks.append(chunk)
        return b"".join(chunks)

    tasks = [asyncio.create_task(read(process.stdout)), asyncio.create_task(read(process.stderr))]
    if input_data is not None:
        async def write_input():
            process.stdin.write(input_data)
            await process.stdin.drain()
            process.stdin.close()
        tasks.append(asyncio.create_task(write_input()))
    try:
        async with asyncio.timeout(timeout):
            captured = await asyncio.gather(*tasks)
            stdout, stderr = captured[:2]
            returncode = await process.wait()
            return ProcessOutput(returncode, stdout, stderr)
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
