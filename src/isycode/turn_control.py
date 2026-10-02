"""Durable operation identity and bounded transport retry.

A rendered token and a tool note are not an effect. An operation is recorded
before the effect and becomes a receipt only after the result is durable.
Reopening a receipt returns that result and does not run the effect again.
Reopening an effect that has no receipt is UNCERTAIN: the effect is not
repeated, because a lost response is not proof that nothing happened.

This is not an agent supervisor. It does not send provider traffic, change
grants, or replay a chat turn.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from dataclasses import dataclass
from pathlib import Path

from isycode.effect_ledger import workspace_identity
from isycode.workspace_setup import state_root

JOURNAL_VERSION = 1
MAX_OPERATIONS = 500
_RETRYABLE = (ConnectionRefusedError, ConnectionAbortedError, TimeoutError, asyncio.TimeoutError, OSError)


class OperationError(Exception):
    """The operation journal cannot be trusted. Do not repeat the effect."""


class RetryCancelled(Exception):
    """A connect retry stopped before another attempt. No request was sent."""


@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    phase: str
    kind: str
    result: str
    applied: tuple[str, ...]
    refused: tuple[str, ...]
    reason: str


def tool_arguments_complete(raw: object) -> bool:
    """True only for one complete JSON object. A truncated stream is not a call."""
    if not isinstance(raw, str) or not raw or len(raw) > 64 * 1024:
        return False
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(value, dict)


class OperationJournal:
    """One file per workspace identity, outside the workspace."""

    def __init__(self, root: Path, *, state_directory: Path | None = None):
        self.root = root.resolve(strict=True)
        self.identity = workspace_identity(self.root)
        base = Path(state_directory) if state_directory is not None else state_root() / "operations"
        self.directory = base
        self.path = base / f"{self.identity}.json"
        self.lock_path = base / f"{self.identity}.lock"
        self._depth = 0
        self._descriptor: int | None = None

    def lookup(self, operation_id: str) -> OperationRecord | None:
        _operation_id(operation_id)

        def op(state: dict) -> OperationRecord | None:
            current = state["operations"].get(operation_id)
            if current is None:
                return None
            return _view(operation_id, current)
        return self._locked(op)

    def claim_effect(self, operation_id: str, *, kind: str,
                     applied: list[str] | None = None,
                     refused: list[str] | None = None) -> tuple[OperationRecord, bool]:
        """Mark the effect as started, once. False means this caller must not run it."""
        _operation_id(operation_id)
        if kind not in {"publish", "promote"}:
            raise OperationError("unknown operation kind")

        def op(state: dict) -> tuple[OperationRecord, bool]:
            current = state["operations"].get(operation_id)
            if current is None:
                if len(state["operations"]) >= MAX_OPERATIONS:
                    raise OperationError("operation journal is full; reconcile before another effect")
                current = {
                    "phase": "effected", "kind": kind, "result": "",
                    "applied": list(applied or []), "refused": list(refused or []),
                    "reason": "",
                }
                state["operations"][operation_id] = current
                return _view(operation_id, current), True
            return _view(operation_id, current), False
        return self._locked(op)

    def mark_receipt(self, operation_id: str, *, result: str,
                     applied: list[str] | tuple[str, ...] = (),
                     refused: list[str] | tuple[str, ...] = ()) -> OperationRecord:
        _operation_id(operation_id)

        def op(state: dict) -> OperationRecord:
            current = state["operations"].get(operation_id)
            if current is None or current.get("phase") not in {"effected", "receipt"}:
                raise OperationError("a receipt needs an effect that already started")
            if current["phase"] != "receipt":
                current["phase"] = "receipt"
                current["result"] = result[:4000]
                current["applied"] = list(applied)
                current["refused"] = list(refused)
                current["reason"] = ""
            return _view(operation_id, current)
        return self._locked(op)

    def mark_uncertain(self, operation_id: str, reason: str) -> OperationRecord:
        """A receipt stays a receipt. Anything else must not be run again."""
        _operation_id(operation_id)

        def op(state: dict) -> OperationRecord:
            current = state["operations"].get(operation_id)
            if current is None:
                raise OperationError("operation is not open")
            if current.get("phase") != "receipt":
                current["phase"] = "uncertain"
                current["reason"] = reason[:300]
            return _view(operation_id, current)
        return self._locked(op)

    def _fresh(self) -> dict:
        return {"version": JOURNAL_VERSION, "identity": self.identity, "operations": {}}

    def _acquire(self) -> None:
        if self._depth:
            self._depth += 1
            return
        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover - POSIX only
            raise OperationError("operation journal lock is unavailable") from exc
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.is_symlink():
            raise OperationError("operation journal directory is a symlink")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.lock_path, flags, 0o600)
        try:
            if os.name == "posix":
                os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except Exception:
            os.close(descriptor)
            raise
        self._descriptor = descriptor
        self._depth = 1

    def _release(self) -> None:
        if self._depth == 0:
            return
        self._depth -= 1
        if self._depth:
            return
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is None:
            return
        try:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def _locked(self, function):
        self._acquire()
        try:
            state = self._read()
            error: Exception | None = None
            result = None
            try:
                result = function(state)
            except Exception as exc:
                error = exc
            try:
                self._write(state)
            except Exception as exc:
                if error is not None:
                    raise exc from error
                raise
            if error is not None:
                raise error
            return result
        finally:
            self._release()

    def _read(self) -> dict:
        if not self.path.exists():
            return self._fresh()
        if self.path.is_symlink() or not self.path.is_file():
            raise OperationError("operation journal is not a regular file")
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperationError("operation journal is unreadable") from exc
        if not isinstance(loaded, dict) or loaded.get("version") != JOURNAL_VERSION:
            raise OperationError("operation journal version is unusable")
        if loaded.get("identity") != self.identity or not isinstance(loaded.get("operations"), dict):
            raise OperationError("operation journal does not match this workspace")
        return loaded

    def _write(self, state: dict) -> None:
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8")
        temporary = self.path.with_name(self.path.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, self.path)
        if os.name == "posix":
            os.chmod(self.path, 0o600)
        directory = os.open(self.directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


class TransportRetry:
    """Retry a connect that has not sent request bytes.

    At most four attempts. The wait is capped and jittered. Cancellation stops
    the next attempt. This does not retry an HTTP status, a redirect, an
    egress denial, a tool, or a chat turn.
    """

    def __init__(self, *, max_attempts: int = 3, base_delay_s: float = 0.05,
                 max_delay_s: float = 0.2, sleeper=None, rng: random.Random | None = None):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 4:
            raise ValueError("transport retries are bounded to 4 attempts")
        if base_delay_s < 0 or max_delay_s < base_delay_s:
            raise ValueError("transport retry delay is invalid")
        self.max_attempts = max_attempts
        self.base_delay_s = base_delay_s
        self.max_delay_s = max_delay_s
        self.sleeper = sleeper
        self.rng = rng or random.Random()

    def delay_for(self, retry_index: int) -> float:
        growth = self.base_delay_s * (2 ** retry_index)
        capped = min(self.max_delay_s, growth)
        return capped * (0.5 + 0.5 * self.rng.random())

    async def attempt(self, connect, *, cancelled: asyncio.Event | None = None):
        last: BaseException | None = None
        for number in range(self.max_attempts):
            self._raise_if_cancelled(cancelled)
            try:
                return await connect()
            except asyncio.CancelledError:
                raise
            except RetryCancelled:
                raise
            except _RETRYABLE as exc:
                last = exc
                if number + 1 >= self.max_attempts:
                    break
                await self._wait(self.delay_for(number), cancelled)
        if last is None:
            raise OperationError("transport retry made no attempt")
        raise last

    async def _wait(self, delay: float, cancelled: asyncio.Event | None) -> None:
        if self.sleeper is not None:
            await self.sleeper(delay)
            self._raise_if_cancelled(cancelled)
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + delay
        while True:
            self._raise_if_cancelled(cancelled)
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            try:
                if cancelled is None:
                    await asyncio.sleep(min(0.05, remaining))
                else:
                    await asyncio.wait_for(cancelled.wait(), timeout=min(0.05, remaining))
                    raise RetryCancelled("transport retry cancelled")
            except asyncio.TimeoutError:
                continue

    @staticmethod
    def _raise_if_cancelled(cancelled: asyncio.Event | None) -> None:
        task = asyncio.current_task()
        # Task.cancelling() is Python 3.11+. The Linux CI job is 3.10, where
        # the next await raises CancelledError before another connect starts.
        cancelling = getattr(task, "cancelling", None) if task is not None else None
        if cancelling is not None and cancelling():
            raise asyncio.CancelledError()
        if cancelled is not None and cancelled.is_set():
            raise RetryCancelled("transport retry cancelled")


def _operation_id(value: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise OperationError("operation id must be a 64 character hex digest")


def _view(operation_id: str, current: dict) -> OperationRecord:
    applied = current.get("applied") or []
    refused = current.get("refused") or []
    return OperationRecord(
        operation_id, str(current.get("phase") or ""), str(current.get("kind") or ""),
        str(current.get("result") or ""), tuple(applied), tuple(refused),
        str(current.get("reason") or ""))


__all__ = [
    "OperationError", "OperationJournal", "OperationRecord", "RetryCancelled",
    "TransportRetry", "tool_arguments_complete",
]
