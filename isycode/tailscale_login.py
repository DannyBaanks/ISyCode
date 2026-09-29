"""Approved, short-lived interactive Tailscale login without saved credentials."""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from isycode.action_runtime import (
    ActionOutcome, ActionReceipt, ProductActionGate, TailscaleAuthorityFacts,
)
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.tailscale import TailscaleAdapter, TailscaleSnapshot
from isycode.workspace_authority import WorkspaceAuthority


LOGIN_TIMEOUT = 10 * 60.0
MAX_LOGIN_OUTPUT = 64 * 1024
LOGIN_URL_PREFIX = "https://login.tailscale.com/a/"


@dataclass(frozen=True)
class LoginStatus:
    attempt_id: str
    state: str
    reason: str
    login_url: str | None = field(default=None, repr=False)
    receipt: ActionReceipt | None = None


@dataclass
class _Attempt:
    attempt_id: str
    request: ActionRequest
    process: Any
    started_at: float
    output_bytes: int = 0
    url_candidate: str = ""
    login_url: str | None = None


def _snapshot(adapter: Any) -> TailscaleSnapshot:
    value = adapter.inspect()
    if not isinstance(value, TailscaleSnapshot):
        raise ValueError("Tailscale inventory is unavailable")
    return value


def _capture_login_url(attempt: _Attempt, text: str) -> None:
    """Retain only a recognized official login URL fragment, never CLI prose."""
    candidate = attempt.url_candidate
    if not candidate:
        start = text.rfind(LOGIN_URL_PREFIX)
        if start >= 0:
            candidate, text = text[start:], ""
        else:
            # A URL prefix may straddle reads. Keep only the longest matching
            # suffix of the fixed official prefix; discard all other output.
            candidate = next((LOGIN_URL_PREFIX[:size] for size in
                              range(len(LOGIN_URL_PREFIX) - 1, 0, -1)
                              if text.endswith(LOGIN_URL_PREFIX[:size])), "")
            return
    elif len(candidate) < len(LOGIN_URL_PREFIX):
        candidate += text
        text = ""
        if not LOGIN_URL_PREFIX.startswith(candidate):
            attempt.url_candidate = ""
            return
    else:
        candidate += text
        text = ""

    if candidate.startswith(LOGIN_URL_PREFIX):
        path = candidate[len(LOGIN_URL_PREFIX):]
        parsed_path = re.match(r"[A-Za-z0-9_-]{0,513}", path)
        if parsed_path is None:
            attempt.url_candidate = ""
            return
        path = parsed_path.group(0)
        candidate = LOGIN_URL_PREFIX + path
        if 8 <= len(path) <= 512:
            attempt.login_url = candidate
        if len(path) > 512:
            candidate = ""
    attempt.url_candidate = candidate


class TailscaleLoginOwner:
    """Launch only `tailscale login`; keep the attempt and auth URL in memory."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore, *, adapter: object | None = None,
                 popen: Callable = subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.adapter = adapter or TailscaleAdapter()
        self._popen = popen
        self._clock = clock
        self._attempts: dict[str, _Attempt] = {}

    @staticmethod
    def _executable(snapshot: TailscaleSnapshot) -> str:
        executable = snapshot.executable
        if (not isinstance(executable, str) or not Path(executable).is_absolute()
                or Path(executable).name != "tailscale"):
            raise ValueError("canonical Tailscale executable is unavailable")
        resolved = Path(executable).resolve(strict=True)
        if str(resolved) != executable or not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ValueError("canonical Tailscale executable is unavailable")
        return executable

    def login_request(self) -> ActionRequest:
        """Build the exact request that Settings can preview before confirmation."""
        snapshot = _snapshot(self.adapter)
        if snapshot.state != "signed_out":
            raise ValueError("Tailscale must be installed, running, and signed out")
        executable = self._executable(snapshot)
        return ActionRequest("tailscale.login", self.root, "tailscale",
                             {"executable": executable, "operation": "login"},
                             execution_owner="tailscale_login")

    def preview(self, request: ActionRequest) -> str:
        expected = self.login_request()
        if request != expected:
            raise ValueError("login request no longer matches the local Tailscale inventory")
        executable = request.parameters["executable"]
        return (f"Run exactly: {executable} login\n"
                "Tailscale may open its official login page at login.tailscale.com. "
                "You will authorize this device in your browser. ISyCode will not ask "
                "for or save a password, auth key, or OAuth token.\n"
                "This adds the local device to your Tailscale network; it does not "
                "enable Serve or expose the Gateway.\n")

    @staticmethod
    def _gate(root: Path, authority: WorkspaceAuthority,
              executable: str) -> ProductActionGate:
        facts = TailscaleAuthorityFacts(cli_executable=executable)
        return ProductActionGate(root, authority, owner_id="tailscale_login",
                                 tailscale_facts=facts)

    def _receipt(self, gate: ProductActionGate, request: ActionRequest,
                 outcome: str, event: str) -> ActionReceipt | None:
        # Receipt input is deliberately a fixed local event label; never hash or
        # persist raw CLI output, login URLs, or status JSON.
        result_digest = hashlib.sha256(f"{outcome}:{event}".encode()).hexdigest()
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id,
                                request.digest, "ALLOW", outcome, result_digest)
        return receipt if gate.persist_receipt(request, receipt) else None

    def begin_login(self, request: ActionRequest,
                    approval: ActionApproval | None) -> ActionOutcome:
        try:
            snapshot = _snapshot(self.adapter)
            executable = self._executable(snapshot)
            expected = ActionRequest("tailscale.login", self.root, "tailscale",
                                     {"executable": executable, "operation": "login"},
                                     execution_owner="tailscale_login")
            if snapshot.state != "signed_out" or request != expected:
                return ActionOutcome("Tailscale login denied.", "DENY", None,
                                     "fresh signed-out inventory and exact login request required")
            gate = self._gate(self.root, self.authority, executable)
            _, decision = gate.authorize(request, approvals=self.approvals,
                                         approval=approval)
            if not decision.allowed:
                return ActionOutcome("Tailscale login denied.", "DENY", None,
                                     "Workspace Authority, IsySentinel, approval, or journal denied")
        except (OSError, RuntimeError, TypeError, ValueError):
            return ActionOutcome("Tailscale login denied.", "DENY", None,
                                 "Tailscale executable or fresh inventory is unavailable")

        try:
            process = self._popen(
                [executable, "login"], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
                cwd=str(self.root), shell=False, close_fds=True, start_new_session=True,
            )
            for pipe in (getattr(process, "stdout", None), getattr(process, "stderr", None)):
                if pipe is not None and hasattr(pipe, "fileno"):
                    os.set_blocking(pipe.fileno(), False)
        except (OSError, ValueError, TypeError):
            receipt = self._receipt(gate, request, "FAILURE", "launch_failed")
            if receipt is None:
                return ActionOutcome("Tailscale login status is not verifiable.",
                                     "NOT_VERIFIABLE", None, "durable receipt unavailable")
            return ActionOutcome("Tailscale login could not start.", "ERROR", receipt,
                                 "fixed Tailscale login process failed to launch")

        attempt_id = "login_" + secrets.token_urlsafe(18)
        self._attempts[attempt_id] = _Attempt(attempt_id, request, process,
                                               self._clock())
        receipt = self._receipt(gate, request, "SUCCESS", "login_process_started")
        if receipt is None:
            self._terminate(process)
            self._attempts.pop(attempt_id, None)
            return ActionOutcome("Tailscale login status is not verifiable.",
                                 "NOT_VERIFIABLE", None, "durable receipt unavailable")
        return ActionOutcome(f"Login attempt started: {attempt_id}", "ALLOW", receipt,
                             "approved local Tailscale login process started")

    @staticmethod
    def _terminate(process: Any) -> None:
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2.0)
        except (OSError, subprocess.TimeoutExpired, AttributeError):
            pass
        for name in ("stdout", "stderr"):
            pipe = getattr(process, name, None)
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass

    @staticmethod
    def _read_available(pipe: Any, limit: int) -> bytes:
        if pipe is None or limit <= 0:
            return b""
        custom = getattr(pipe, "read_available", None)
        if callable(custom):
            data = custom(limit)
            return data if isinstance(data, bytes) else b""
        try:
            return os.read(pipe.fileno(), limit)
        except (BlockingIOError, InterruptedError):
            return b""

    def _drain(self, attempt: _Attempt) -> bool:
        for name in ("stdout", "stderr"):
            pipe = getattr(attempt.process, name, None)
            try:
                chunk = self._read_available(pipe, min(4096, MAX_LOGIN_OUTPUT + 1 - attempt.output_bytes))
            except (OSError, ValueError, AttributeError):
                chunk = b""
            attempt.output_bytes += len(chunk)
            if attempt.output_bytes > MAX_LOGIN_OUTPUT:
                return False
            if chunk:
                _capture_login_url(attempt, chunk.decode("utf-8", "replace"))
        return True

    def _finish(self, attempt: _Attempt, state: str, reason: str,
                outcome: str) -> LoginStatus:
        self._attempts.pop(attempt.attempt_id, None)
        gate = self._gate(self.root, self.authority,
                          str(attempt.request.parameters["executable"]))
        receipt = self._receipt(gate, attempt.request, outcome, state)
        self._terminate(attempt.process)
        if receipt is None:
            return LoginStatus(attempt.attempt_id, "verification_unavailable",
                               "durable action receipt could not be written")
        return LoginStatus(attempt.attempt_id, state, reason,
                           attempt.login_url if state == "pending" else None, receipt)

    def poll(self, attempt_id: str) -> LoginStatus:
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            return LoginStatus(str(attempt_id)[:128], "unknown",
                               "login attempt is not active in this process")
        if self._clock() - attempt.started_at >= LOGIN_TIMEOUT:
            self._terminate(attempt.process)
            return self._finish(attempt, "timed_out", "login attempt exceeded its time limit",
                                "FAILURE")
        if not self._drain(attempt):
            return self._finish(attempt, "failed", "login process output exceeded its limit",
                                "FAILURE")
        try:
            snapshot = _snapshot(self.adapter)
        except (OSError, RuntimeError, TypeError, ValueError):
            snapshot = None
        returncode = attempt.process.poll()
        if snapshot is not None and snapshot.state == "signed_in":
            return self._finish(attempt, "signed_in", "Tailscale reports this device signed in",
                                "SUCCESS")
        if returncode is not None and returncode != 0:
            return self._finish(attempt, "failed", "Tailscale login process failed",
                                "FAILURE")
        if snapshot is None or snapshot.state not in {"signed_out", "signed_in"}:
            return LoginStatus(attempt_id, "verification_unavailable",
                               "Tailscale status is temporarily unavailable",
                               attempt.login_url)
        return LoginStatus(attempt_id, "pending", "complete sign-in in the official browser",
                           attempt.login_url)

    def cancel(self, attempt_id: str) -> LoginStatus:
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            return LoginStatus(str(attempt_id)[:128], "unknown",
                               "login attempt is not active in this process")
        return self._finish(attempt, "cancelled", "local login process stopped; tailnet state unchanged",
                            "FAILURE")


__all__ = ["LoginStatus", "TailscaleLoginOwner"]
