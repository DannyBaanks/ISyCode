"""Bounded, read-only inventory for optional private Tailscale access.

This module does not configure Tailscale. The Serve owner is responsible for
previews and changes, and must verify a live route before claiming ownership.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit


MAX_OUTPUT = 65536
COMMAND_TIMEOUT = 5.0
MAX_ROUTES = 64
DEFAULT_GATEWAY_PORT = 8787
READ_COMMANDS = (("version",), ("status", "--json"),
                 ("serve", "get-config", "--all"),
                 ("serve", "status", "--json"))


@dataclass(frozen=True)
class TailscaleCommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ServeRoute:
    host: str
    path: str
    target: str
    private: bool


@dataclass(frozen=True)
class TailscaleSnapshot:
    state: str
    serve_state: str = "unavailable"
    executable: str | None = None
    version: str | None = None
    dns_name: str | None = None
    routes: tuple[ServeRoute, ...] = ()
    serve_digest: str | None = None
    gateway_url: str | None = None
    gateway_healthy: bool = False


def _bounded_run(argv: Sequence[str], *, env: Mapping[str, str], timeout: float,
                 max_output: int) -> TailscaleCommandResult:
    """Read a child process without retaining more than max_output bytes."""
    process = subprocess.Popen(list(argv), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=dict(env), close_fds=True)
    chunks = {process.stdout: bytearray(), process.stderr: bytearray()}
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    try:
        for pipe in chunks:
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            for key, _ in selector.select(remaining):
                pipe = key.fileobj
                data = os.read(pipe.fileno(), min(4096, max_output + 1))
                if not data:
                    selector.unregister(pipe)
                    continue
                chunks[pipe].extend(data)
                if sum(map(len, chunks.values())) > max_output:
                    raise ValueError("Tailscale output exceeded limit")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(argv, timeout)
        process.wait(timeout=remaining)
        return TailscaleCommandResult(
            process.returncode,
            chunks[process.stdout].decode("utf-8", errors="replace"),
            chunks[process.stderr].decode("utf-8", errors="replace"),
        )
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()
        for pipe in chunks:
            pipe.close()


def _gateway_health(url: str) -> bool:
    parsed = urlsplit(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=1)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        response.read(1024)
        return response.status == 200
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def _valid_gateway(url: str, configured_port: int) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and type(configured_port) is int and 1 <= configured_port <= 65535
                and parsed.port == configured_port and not parsed.username
                and not parsed.password and not parsed.path.rstrip("/")
                and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def _bounded_json(raw: str) -> dict:
    if len(raw.encode("utf-8")) > MAX_OUTPUT:
        raise ValueError("oversized JSON")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 2048 or depth > 12:
            raise ValueError("JSON structure exceeded limit")
        if isinstance(item, dict):
            if len(item) > 256 or any(not isinstance(k, str) or len(k) > 256 for k in item):
                raise ValueError("invalid JSON keys")
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            if len(item) > 256:
                raise ValueError("oversized JSON array")
            pending.extend((v, depth + 1) for v in item)
        elif isinstance(item, str) and len(item) > 4096:
            raise ValueError("oversized JSON value")
    return value


def _parse_serve(value: dict) -> tuple[str, tuple[ServeRoute, ...]]:
    if not set(value) <= {"TCP", "Web", "AllowFunnel", "Services", "Foreground"}:
        raise ValueError("unknown Serve schema")
    if value.get("Foreground"):
        raise ValueError("foreground Serve configuration cannot be inventoried")
    if not isinstance(value.get("Services", {}), dict):
        raise ValueError("invalid Serve services")
    tcp, web, funnel = (value.get(key, {}) for key in ("TCP", "Web", "AllowFunnel"))
    if not all(isinstance(item, dict) for item in (tcp, web, funnel)):
        raise ValueError("invalid Serve schema")
    if len(web) > MAX_ROUTES or len(tcp) > MAX_ROUTES or len(funnel) > MAX_ROUTES:
        raise ValueError("too many Serve routes")
    routes = []
    for host, service in web.items():
        if not isinstance(host, str) or not isinstance(service, dict):
            raise ValueError("invalid Serve service")
        handlers = service.get("Handlers")
        if not isinstance(handlers, dict) or not set(service) <= {"Handlers"}:
            raise ValueError("unknown Serve handler schema")
        for path, handler in handlers.items():
            if (not isinstance(path, str) or not path.startswith("/")
                    or not isinstance(handler, dict) or not isinstance(handler.get("Proxy"), str)
                    or not set(handler) <= {"Proxy"}):
                raise ValueError("unknown Serve route")
            routes.append(ServeRoute(host, path, handler["Proxy"],
                                     not bool(funnel.get(host))))
            if len(routes) > MAX_ROUTES:
                raise ValueError("too many Serve routes")
    for port, listener in tcp.items():
        if (not isinstance(port, str) or not re.fullmatch(r"[1-9][0-9]{0,4}", port)
                or int(port) > 65535 or not isinstance(listener, dict)
                or not set(listener) <= {"HTTP", "HTTPS", "TCPForward", "TerminateTLS",
                                      "ProxyProtocol"}):
            raise ValueError("unknown Serve listener schema")
        http, https = listener.get("HTTP", False), listener.get("HTTPS", False)
        forward = listener.get("TCPForward", "")
        tls_name = listener.get("TerminateTLS", "")
        proxy_protocol = listener.get("ProxyProtocol", 0)
        if (type(http) is not bool or type(https) is not bool
                or not isinstance(forward, str) or not isinstance(tls_name, str)
                or type(proxy_protocol) is not int or proxy_protocol not in {0, 1, 2}
                or sum((http, https, bool(forward))) != 1
                or (tls_name and not forward) or (proxy_protocol and not forward)):
            raise ValueError("invalid Serve listener")
    if any(not isinstance(key, str) or not isinstance(val, bool) for key, val in funnel.items()):
        raise ValueError("invalid Funnel field")
    if any(funnel.values()):
        return "conflict", tuple(routes)
    return ("existing" if tcp or web else "empty"), tuple(routes)


def _parse_services(value: dict) -> tuple[ServeRoute, ...]:
    if (not set(value) <= {"version", "services"} or value.get("version") != "0.0.1"):
        raise ValueError("unsupported Services config version")
    services = value.get("services", {})
    if not isinstance(services, dict) or len(services) > MAX_ROUTES:
        raise ValueError("invalid Services map")
    routes = []
    for name, definition in services.items():
        if not isinstance(name, str) or not name.startswith("svc:") or not isinstance(definition, dict):
            raise ValueError("invalid Service name")
        if not set(definition) <= {"endpoints", "advertised"}:
            raise ValueError("unknown Service fields")
        if "advertised" in definition and type(definition["advertised"]) is not bool:
            raise ValueError("invalid Service advertisement")
        endpoints = definition.get("endpoints")
        if not isinstance(endpoints, dict):
            raise ValueError("invalid Service endpoints")
        for endpoint, target in endpoints.items():
            if (not isinstance(endpoint, str) or not isinstance(target, str)
                    or not re.fullmatch(r"tcp:[0-9]{1,5}(?:-[0-9]{1,5})?", endpoint)):
                raise ValueError("unsupported Service endpoint")
            routes.append(ServeRoute(name, "/", target, True))
            if len(routes) > MAX_ROUTES:
                raise ValueError("too many Service routes")
    return tuple(routes)


class TailscaleAdapter:
    """Inspect a fixed local CLI and the configured loopback Gateway only."""

    def __init__(self, runner: Callable = _bounded_run, platform: str | None = None,
                 gateway_probe: Callable[[str], bool] = _gateway_health,
                 gateway_url: str | None = None,
                 gateway_port: int = DEFAULT_GATEWAY_PORT):
        self._runner = runner
        self._platform = sys.platform if platform is None else platform
        self._gateway_probe = gateway_probe
        self._gateway_url = gateway_url or os.environ.get("GATEWAY_URL", "http://127.0.0.1:8787")
        self._gateway_port = gateway_port

    def _run(self, executable: str, command: tuple[str, ...]) -> TailscaleCommandResult:
        if command not in READ_COMMANDS:
            raise ValueError("unapproved read command")
        result = self._runner([executable, *command], env={"PATH": "/usr/bin:/bin",
            "LANG": "C", "LC_ALL": "C"}, timeout=COMMAND_TIMEOUT, max_output=MAX_OUTPUT)
        if (not isinstance(result, TailscaleCommandResult)
                or len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8")) > MAX_OUTPUT):
            raise ValueError("invalid or oversized Tailscale result")
        return result

    def inspect(self) -> TailscaleSnapshot:
        if self._platform != "linux":
            return TailscaleSnapshot("unsupported_os")
        candidate = shutil.which("tailscale")
        if candidate is None:
            return TailscaleSnapshot("missing_cli")
        try:
            executable = str(Path(candidate).resolve(strict=True))
            if not Path(executable).is_file() or not os.access(executable, os.X_OK):
                return TailscaleSnapshot("unavailable")
        except (OSError, RuntimeError):
            return TailscaleSnapshot("unavailable")
        gateway_url = (self._gateway_url if _valid_gateway(self._gateway_url, self._gateway_port)
                       else None)
        try:
            version_result = self._run(executable, ("version",))
            if version_result.returncode:
                return TailscaleSnapshot("unavailable", executable=executable,
                                         gateway_url=gateway_url)
            match = re.match(r"^([0-9]+)\.([0-9]+)(?:\.[0-9]+)?(?:\s|$)",
                             version_result.stdout.strip())
            if match is None:
                return TailscaleSnapshot("unavailable", executable=executable,
                                         gateway_url=gateway_url)
            version = match.group(0).strip()
            status_result = self._run(executable, ("status", "--json"))
            if status_result.returncode:
                error = status_result.stderr.casefold()
                state = ("daemon_unavailable" if any(token in error for token in
                    ("failed to connect", "tailscaled.sock", "not running")) else "unavailable")
                return TailscaleSnapshot(state, executable=executable,
                                         version=version, gateway_url=gateway_url)
            status = _bounded_json(status_result.stdout)
            backend = status.get("BackendState")
            if backend in {"NeedsLogin", "Stopped"}:
                state = "signed_out"
            elif backend == "Running":
                state = "signed_in"
            else:
                return TailscaleSnapshot("unavailable", executable=executable,
                                         version=version, gateway_url=gateway_url)
            self_record = status.get("Self", {})
            if not isinstance(self_record, dict):
                raise ValueError("invalid Tailscale identity")
            dns = self_record.get("DNSName")
            if dns is not None and (not isinstance(dns, str) or len(dns) > 253):
                raise ValueError("invalid Tailscale DNS name")
            dns = dns.rstrip(".") if dns else None
            healthy = bool(gateway_url and self._gateway_probe(gateway_url + "/health"))
            if tuple(map(int, match.groups())) < (1, 52):
                return TailscaleSnapshot(state, executable=executable, version=version,
                    dns_name=dns, gateway_url=gateway_url, gateway_healthy=healthy)
            try:
                services_result = self._run(executable, ("serve", "get-config", "--all"))
                node_result = self._run(executable, ("serve", "status", "--json"))
                if services_result.returncode or node_result.returncode:
                    raise ValueError("Serve inventory unavailable")
                service_routes = _parse_services(_bounded_json(services_result.stdout))
                node_state, node_routes = _parse_serve(_bounded_json(node_result.stdout))
                routes = service_routes + node_routes
                if len(routes) > MAX_ROUTES:
                    raise ValueError("too many Serve routes")
                serve_state = ("conflict" if node_state == "conflict" else
                               "existing" if routes or node_state == "existing" else "empty")
                digest = hashlib.sha256(
                    services_result.stdout.encode("utf-8") + b"\0" +
                    node_result.stdout.encode("utf-8")).hexdigest()
                return TailscaleSnapshot(state, serve_state, executable, version, dns,
                    routes, digest, gateway_url, healthy)
            except (OSError, ValueError, TypeError, UnicodeError, RecursionError,
                    subprocess.TimeoutExpired):
                return TailscaleSnapshot(state, "conflict", executable, version, dns,
                    gateway_url=gateway_url, gateway_healthy=healthy)
        except (OSError, ValueError, TypeError, UnicodeError, subprocess.TimeoutExpired):
            return TailscaleSnapshot("unavailable", "conflict", executable,
                                     gateway_url=gateway_url)
