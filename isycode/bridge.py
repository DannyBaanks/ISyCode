"""Opt-in ISyCo Bridge coordination adapter for the ISyCode TUI."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isycode.config import PROJECT_ROOT


class BridgeError(RuntimeError):
    """The Bridge handshake could not complete."""


def find_handshake() -> Path:
    configured = os.environ.get("ISYCO_ROOT", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.append(PROJECT_ROOT.parent.parent / "ISyCo")
    candidates.append(Path.home() / "Development" / "ISyCo")
    for candidate in candidates:
        root = candidate.resolve()
        script = root / "bridge_core" / "capabilities" / "cap.agent_bridge" / "handshake.py"
        if (root / ".iesyroot").is_file() and script.is_file():
            return script
    checked = ", ".join(str(path) for path in candidates)
    raise BridgeError(f"Bridge handshake not found; configure ISYCO_ROOT. Checked: {checked}")


def _settings_path() -> Path:
    state_root = os.environ.get("XDG_STATE_HOME", "").strip()
    root = Path(state_root).expanduser() if state_root else Path.home() / ".local" / "state"
    return root / "isycode" / "settings.json"


def bridge_enabled() -> bool:
    """Read the user's opt-in setting. Missing/invalid settings mean disabled."""
    path = _settings_path()
    if path.is_symlink():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("bridge_enabled") is True


def save_bridge_enabled(enabled: bool) -> None:
    """Persist only the toggle; identity and handshake tokens remain in memory."""
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise BridgeError("Refusing to write settings through a symbolic link")
    if os.name != "nt":
        path.parent.chmod(0o700)
    data: dict[str, Any] = {}
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(current, dict):
            data = current
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError("Could not read ISyCode settings") from exc
    data["bridge_enabled"] = bool(enabled)
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, path)
        if os.name != "nt":
            path.chmod(0o600)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise BridgeError("Could not save ISyCode settings") from exc


@dataclass
class BridgeStatus:
    sequence: int
    leases: dict[str, dict[str, Any]]
    agents: dict[str, dict[str, Any]]
    pending_messages: int


class BridgeClient:
    """Thin subprocess adapter. Tokens are kept only in this process memory."""

    def __init__(self, identity: str, caps: str = "isycode", python: str | None = None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", identity):
            raise ValueError("Bridge identity must be 1-64 simple identifier characters")
        self.identity = identity
        self.caps = caps
        self.python = python or sys.executable
        self.handshake = find_handshake()
        self.token: str | None = None
        self.lease_tokens: dict[str, str] = {}

    def _run(self, *args: str, timeout_s: float = 20.0) -> str:
        try:
            out = subprocess.run(
                [self.python, str(self.handshake), *args],
                capture_output=True, text=True, timeout=timeout_s, check=False,
                cwd=self.handshake.parents[3],
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise BridgeError(f"Bridge handshake unavailable ({type(exc).__name__})") from exc
        if out.returncode != 0:
            detail = (out.stderr or out.stdout).strip().splitlines()
            message = detail[-1] if detail else "handshake failed"
            message = re.sub(r"(?:IDENTITY|LEASE)_TOKEN=\S+", "TOKEN=[redacted]", message)
            if self.token:
                message = message.replace(self.token, "[redacted]")
            raise BridgeError(message[:240])
        return out.stdout.strip()

    def hello(self) -> str:
        args = ["hello", self.identity, "--caps", self.caps, "--pid", str(os.getpid())]
        if self.token:
            args += ["--token", self.token]
        output = self._run(*args)
        for line in output.splitlines():
            if line.startswith("IDENTITY_TOKEN="):
                self.token = line.split("=", 1)[1].split()[0].strip()
        return output

    def heartbeat(self, status: str = "isycode") -> str:
        args = ["heartbeat", self.identity, "--status", status, "--pid", str(os.getpid())]
        if self.token:
            args += ["--token", self.token]
        return self._run(*args)

    def peek(self) -> list[dict[str, Any]]:
        output = self._run("peek", self.identity)
        messages: list[dict[str, Any]] = []
        for line in output.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and isinstance(item.get("seq"), int):
                messages.append(item)
        return messages

    def goodbye(self) -> str:
        args = ["goodbye", self.identity]
        if self.token:
            args += ["--token", self.token]
        output = self._run(*args)
        self.lease_tokens.clear()
        self.token = None
        return output

    def status(self) -> BridgeStatus:
        try:
            data = json.loads(self._run("status", "--json", timeout_s=10.0))
        except json.JSONDecodeError as exc:
            raise BridgeError("Bridge returned invalid status data") from exc
        if not isinstance(data, dict):
            raise BridgeError("Bridge returned invalid status data")
        leases = data.get("leases", {})
        if not isinstance(leases, dict):
            leases = {}
        return BridgeStatus(
            sequence=int(data.get("seq") or 0),
            leases={str(key): value for key, value in leases.items() if isinstance(value, dict)},
            agents=self.agents(),
            pending_messages=len(self.peek()),
        )

    def agents(self) -> dict[str, dict[str, Any]]:
        registry = self.handshake.parents[3] / "workspace" / "agents" / "bridge" / "agents.json"
        if registry.is_symlink():
            raise BridgeError("Bridge agent registry is a symbolic link")
        try:
            data = json.loads(registry.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise BridgeError("Could not read Bridge agent registry") from exc
        if not isinstance(data, dict):
            return {}
        result = {}
        for name, item in data.items():
            if not isinstance(name, str) or not isinstance(item, dict):
                continue
            capabilities = item.get("capabilities", [])
            result[name] = {
                "status": str(item.get("status", "unknown"))[:32],
                "last_heartbeat": str(item.get("last_heartbeat", ""))[:32],
                "capabilities": [str(value)[:64] for value in capabilities[:16]
                                 if isinstance(value, str)] if isinstance(capabilities, list) else [],
            }
        return result

    def claim(self, topic: str, ttl: int = 300, path: str = ".") -> str:
        args = ["claim", topic, self.identity, "--ttl", str(ttl), "--path", path]
        if self.token:
            args += ["--token", self.token]
        output = self._run(*args)
        for line in output.splitlines():
            if line.startswith("LEASE_TOKEN="):
                self.lease_tokens[topic] = line.split("=", 1)[1].split()[0]
        return output

    def release(self, topic: str) -> str:
        args = ["release", topic, self.identity]
        token = self.lease_tokens.get(topic)
        if token:
            args += ["--token", token]
        output = self._run(*args)
        self.lease_tokens.pop(topic, None)
        return output

    def send(self, to: str, kind: str, topic: str, payload: str = "") -> str:
        return self._run("send", self.identity, to, kind, topic, payload)
