#!/usr/bin/env python3
"""ISyCode Bridge Client — multi-agent coordination via OpenISy handshake.

Wraps bridge_core/capabilities/cap.agent_bridge/handshake.py:
hello / peek / send / claim / release / heartbeat.

Leases are traffic lights, not locks. Two ISyCode agents coordinate
on a shared task without stepping on each other.
"""
from __future__ import annotations

import os
import sys
import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any

HANDSHAKE = ("/home/danny/Development/ISyCo/bridge_core/capabilities"
             "/cap.agent_bridge/handshake.py")


@dataclass
class BridgeMessage:
    seq: int
    frm: str
    to: str
    kind: str
    topic: str
    payload: Any


class BridgeError(Exception):
    pass


class BridgeClient:
    """Thin wrapper over the handshake CLI."""

    # (__init__ moved below with lease_tokens)

    def _run(self, *args: str, timeout_s: float = 30.0) -> str:
        cmd = [self.python, HANDSHAKE, *args]
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_s)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise BridgeError(f"handshake unreachable: {e}")
        if out.returncode != 0:
            raise BridgeError(f"handshake failed: {out.stderr.strip()[:200]}")
        return out.stdout.strip()

    def hello(self) -> str:
        """Announce presence. Returns (and stores) the identity token."""
        out = self._run("hello", self.identity,
                        "--caps", self.caps, "--pid", str(os.getpid()))
        # Token is printed to stdout, never in chat.jsonl
        for line in out.splitlines():
            if line.startswith("IDENTITY_TOKEN="):
                # Token is the first whitespace-separated field after '=';
                # the rest of the line is a human comment.
                self.token = line.split("=", 1)[1].split()[0].strip()
                break
        return out

    def _tok(self) -> list[str]:
        return ["--token", self.token] if self.token else []

    def peek(self) -> str:
        return self._run("peek", self.identity)

    def send(self, to: str, kind: str, topic: str, payload: str = "") -> str:
        return self._run("send", self.identity, to, kind, topic, payload)

    def __init__(self, identity: str, caps: str = "isycode",
                 python: str = "python3"):
        self.identity = identity
        self.caps = caps
        self.python = python
        self.token: str | None = None
        self.lease_tokens: dict[str, str] = {}

    def claim(self, topic: str, ttl: int = 300, path: str = ".") -> str:
        args = ["claim", topic, self.identity, "--ttl", str(ttl),
                "--path", path]
        if self.token:
            args += ["--token", self.token]
        out = self._run(*args)
        # Capture the LEASE_TOKEN — required for release/renew (RFC-0002 #18)
        for line in out.splitlines():
            if line.startswith("LEASE_TOKEN="):
                self.lease_tokens[topic] = line.split("=", 1)[1].split()[0]
                break
        return out

    def release(self, topic: str) -> str:
        args = ["release", topic, self.identity]
        # Release needs the LEASE_TOKEN, not the identity token
        if topic in self.lease_tokens:
            args += ["--token", self.lease_tokens[topic]]
        elif self.token:
            args += ["--token", self.token]
        out = self._run(*args)
        self.lease_tokens.pop(topic, None)
        return out

    def heartbeat(self, status: str = "isycode") -> str:
        return self._run("heartbeat", self.identity, "--status", status,
                         *self._tok())
