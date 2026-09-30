"""Local control-plane host used by ISyCode and its mobile client.

The host is intentionally loopback-only unless an explicit TLS certificate and
private key are configured. Pairing PINs are short-lived; bearer credentials
are random, stored only as SHA-256 digests, and checked against explicit scopes.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import sqlite3
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web
from isycode.action_runtime import ActionReceipt, ProductActionGate
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority


PAIR_TTL_SECONDS = 5 * 60
API_KEY_TTL_SECONDS = 60 * 60
CLIENT_TTL_SECONDS = 45
PAIR_MAX_FAILURES = 5
PAIR_MAX_GLOBAL_FAILURES = 20
CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
PAIR_SCOPES = frozenset({"runtime:read", "runtime:select", "client:heartbeat"})
DEFAULT_SCOPES = PAIR_SCOPES
# Secure only mints the narrow pairing scopes backed by current read/select/
# heartbeat endpoints. Session, file, and operator scopes stay unissuable until
# their execution owners and approval paths exist.
VALID_SCOPES = PAIR_SCOPES


def _state_dir() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".local" / "state"
    path = root / "isycode" / "mobile-host"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        path.chmod(0o700)
    return path


class ApiKeyStore:
    """Small external keystore for multiple scoped, expiring mobile tokens."""

    def __init__(self, path: Path | None = None):
        self.path = path or (_state_dir() / "keystore.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.path.parent.chmod(0o700)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                digest TEXT NOT NULL UNIQUE,
                scopes TEXT NOT NULL,
                runtimes TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                revoked_at REAL
            )""")
        self._secure_file()

    def _secure_file(self) -> None:
        if os.name != "nt" and self.path.exists():
            self.path.chmod(0o600)

    def issue(
        self, name: str, *, scopes: frozenset[str] = DEFAULT_SCOPES,
        runtimes: tuple[str, ...] = ("*",), ttl_seconds: int = API_KEY_TTL_SECONDS,
    ) -> tuple[str, str, float]:
        if not name or len(name) > 96 or any(ord(ch) < 32 for ch in name):
            raise ValueError("key name must be 1-96 printable characters")
        if not scopes or not scopes <= VALID_SCOPES:
            raise ValueError("key contains an unknown or empty scope set")
        if not 60 <= ttl_seconds <= 30 * 24 * 60 * 60:
            raise ValueError("key expiry must be between 1 minute and 30 days")
        if not runtimes or any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}|\*", item)
                               for item in runtimes):
            raise ValueError("invalid runtime scope")
        raw_key = "isy_" + secrets.token_urlsafe(32)
        key_id = "key_" + secrets.token_hex(8)
        expires_at = time.time() + ttl_seconds
        digest = hashlib.sha256(raw_key.encode()).hexdigest()
        with self._connect() as db:
            db.execute(
                "INSERT INTO api_keys VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (key_id, name, digest, json.dumps(sorted(scopes)),
                 json.dumps(sorted(set(runtimes))), time.time(), expires_at),
            )
        self._secure_file()
        return key_id, raw_key, expires_at

    def authenticate(self, raw_key: str) -> dict[str, Any] | None:
        if not raw_key or len(raw_key) > 160:
            return None
        digest = hashlib.sha256(raw_key.encode()).hexdigest()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM api_keys WHERE digest=? AND revoked_at IS NULL", (digest,)
            ).fetchone()
        if not row or row["expires_at"] <= time.time():
            return None
        if not hmac.compare_digest(row["digest"], digest):
            return None
        try:
            scope_values = json.loads(row["scopes"])
            runtime_values = json.loads(row["runtimes"])
        except (TypeError, json.JSONDecodeError):
            return None
        if (not isinstance(scope_values, list)
                or any(not isinstance(scope, str) for scope in scope_values)):
            return None
        scopes = frozenset(scope_values)
        if not scopes or not scopes <= VALID_SCOPES:
            return None
        if (not isinstance(runtime_values, list)
                or any(not isinstance(runtime, str) for runtime in runtime_values)):
            return None
        return {
            "id": row["id"], "name": row["name"],
            "scopes": scopes,
            "runtimes": frozenset(runtime_values),
            "expires_at": row["expires_at"],
        }

    def revoke(self, key_id: str) -> bool:
        with self._connect() as db:
            result = db.execute(
                "UPDATE api_keys SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (time.time(), key_id),
            )
            return result.rowcount == 1

    def list_metadata(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,name,scopes,runtimes,created_at,expires_at,revoked_at "
                "FROM api_keys ORDER BY created_at DESC"
            ).fetchall()
        return [{
            "id": row["id"], "name": row["name"],
            "scopes": json.loads(row["scopes"]),
            "runtimes": json.loads(row["runtimes"]),
            "created_at": row["created_at"], "expires_at": row["expires_at"],
            "revoked": row["revoked_at"] is not None or row["expires_at"] <= time.time(),
        } for row in rows]


@dataclass(frozen=True)
class MobileHostStatus:
    state: str
    address: str
    port: int
    secure_transport: bool
    pairing_expires_at: float | None
    clients: tuple[dict[str, Any], ...]
    error: str = ""

    @property
    def alive(self) -> bool:
        return self.state == "ready"


class MobileHost:
    """Async HTTP control plane owned by a TUI or ``isycode host`` process."""

    def __init__(self, *, key_store: ApiKeyStore | None = None, pair_authorizer=None):
        self._key_store = key_store
        self.bind = os.environ.get("ISYCODE_MOBILE_HOST_BIND", "127.0.0.1").strip()
        try:
            self.port = int(os.environ.get("ISYCODE_MOBILE_HOST_PORT", "8765"))
        except ValueError:
            self.port = -1
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._pair_digest: str | None = None
        self._pair_expires_at: float | None = None
        self._pair_challenge_id: str | None = None
        self._pair_failures: dict[str, list[float]] = {}
        self._pair_global_failures: list[float] = []
        self._clients: dict[tuple[str, str], dict[str, Any]] = {}
        self._state = "stopped"
        self._error = ""
        self._ssl_context: ssl.SSLContext | None = None
        self._pair_authorizer = pair_authorizer
        self._pair_recorder = None

    @property
    def key_store(self) -> ApiKeyStore:
        if self._key_store is None:
            self._key_store = ApiKeyStore()
        return self._key_store

    def _make_ssl_context(self) -> ssl.SSLContext | None:
        cert = os.environ.get("ISYCODE_MOBILE_HOST_TLS_CERT")
        key = os.environ.get("ISYCODE_MOBILE_HOST_TLS_KEY")
        try:
            loopback = self.bind == "localhost" or ipaddress.ip_address(self.bind).is_loopback
        except ValueError:
            loopback = False
        if loopback and not cert and not key:
            return None
        if not cert or not key:
            raise RuntimeError("remote mobile host requires both TLS_CERT and TLS_KEY")
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(cert, key)
        return context

    def rotate_pairing_code(self) -> tuple[str, float]:
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._pair_code = code
        self._pair_digest = hashlib.sha256(code.encode()).hexdigest()
        self._pair_expires_at = time.time() + PAIR_TTL_SECONDS
        self._pair_challenge_id = secrets.token_hex(32)
        self._pair_failures.clear()
        self._pair_global_failures.clear()
        return code, self._pair_expires_at

    def status(self) -> MobileHostStatus:
        now = time.time()
        clients = tuple(sorted(
            (dict(client) for client in self._clients.values()
             if now - client["last_seen"] <= CLIENT_TTL_SECONDS),
            key=lambda client: client["last_seen"], reverse=True,
        ))
        code_active = bool(self._pair_digest and self._pair_expires_at
                           and self._pair_expires_at > now)
        return MobileHostStatus(
            state=self._state, address=self.bind, port=self.port,
            secure_transport=self._ssl_context is not None,
            pairing_expires_at=self._pair_expires_at if code_active else None,
            clients=clients, error=self._error,
        )

    def pairing_code_for_local_settings(self) -> str | None:
        if not self._pair_digest or not self._pair_expires_at or self._pair_expires_at <= time.time():
            return None
        # The clear-text PIN exists only in memory so Settings can display it.
        return getattr(self, "_pair_code", None)

    async def start(self) -> MobileHostStatus:
        if self._runner is not None:
            return self.status()
        try:
            if not 0 <= self.port <= 65535:
                raise ValueError("ISYCODE_MOBILE_HOST_PORT must be between 0 and 65535")
            self._key_store = self.key_store
            self._ssl_context = self._make_ssl_context()
            app = web.Application(client_max_size=8 * 1024)
            app.add_routes([
                web.get("/v1/health", self._health),
                web.get("/v1/status", self._status_endpoint),
                web.post("/v1/pair/exchange", self._pair),
                web.get("/v1/runtimes", self._runtimes),
                web.post("/v1/runtimes/select", self._select_runtime),
                web.post("/v1/clients/heartbeat", self._heartbeat),
                web.get("/isycode/v1/health", self._health),
                web.get("/isycode/v1/status", self._status_endpoint),
                web.post("/isycode/v1/pair/exchange", self._pair),
                web.get("/isycode/v1/runtimes", self._runtimes),
                web.post("/isycode/v1/runtimes/select", self._select_runtime),
                web.post("/isycode/v1/clients/heartbeat", self._heartbeat),
            ])
            self._runner = web.AppRunner(app, access_log=None)
            await self._runner.setup()
            self._site = web.TCPSite(
                self._runner, self.bind, self.port, ssl_context=self._ssl_context)
            await self._site.start()
            server = self._site._server
            if server and server.sockets:
                self.port = int(server.sockets[0].getsockname()[1])
            self._state = "ready"
            self._error = ""
            self._issue_pairing_code()
        except Exception as exc:
            self._state = "error"
            self._error = type(exc).__name__
            await self.stop()
            self._state = "error"
            self._error = type(exc).__name__
        return self.status()

    async def stop(self) -> None:
        runner, self._runner, self._site = self._runner, None, None
        if runner is not None:
            await runner.cleanup()
        self._pair_code = None
        self._pair_digest = None
        self._pair_challenge_id = None
        self._pair_expires_at = None
        self._clients.clear()
        self._state = "stopped"

    def _issue_pairing_code(self) -> None:
        self.rotate_pairing_code()

    async def _json_body(self, request: web.Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except (ValueError, json.JSONDecodeError):
            raise web.HTTPBadRequest(text="invalid JSON")
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text="JSON object required")
        return data

    async def _health(self, request: web.Request) -> web.Response:
        del request
        status = self.status()
        return web.json_response({
            "service": "isycode-mobile-host", "version": 1,
            "state": status.state,
        })

    async def _status_endpoint(self, request: web.Request) -> web.Response:
        self._auth(request, "host:status")
        status = self.status()
        return web.json_response({
            "service": "isycode-mobile-host", "version": 1,
            "state": status.state,
            "connected_clients": [
                {key: value for key, value in client.items() if key != "last_seen"}
                for client in status.clients
            ],
            "pairing_pending": status.pairing_expires_at is not None,
        })

    async def _pair(self, request: web.Request) -> web.Response:
        now = time.time()
        peer = request.remote or "unknown"
        failures = [stamp for stamp in self._pair_failures.get(peer, []) if now - stamp < 60]
        self._pair_failures[peer] = failures
        self._pair_global_failures = [
            stamp for stamp in self._pair_global_failures
            if now - stamp < PAIR_TTL_SECONDS
        ]
        if (len(failures) >= PAIR_MAX_FAILURES
                or len(self._pair_global_failures) >= PAIR_MAX_GLOBAL_FAILURES):
            raise web.HTTPTooManyRequests(text="pairing temporarily rate-limited")
        data = await self._json_body(request)
        code = data.get("code")
        label = data.get("device_name", "Mobile device")
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
            self._pair_failures[peer].append(now)
            self._pair_global_failures.append(now)
            raise web.HTTPUnauthorized(text="pairing code rejected")
        if (not self._pair_digest or not self._pair_expires_at
                or self._pair_expires_at <= now
                or not hmac.compare_digest(
                    hashlib.sha256(code.encode()).hexdigest(), self._pair_digest)):
            self._pair_failures[peer].append(now)
            self._pair_global_failures.append(now)
            raise web.HTTPUnauthorized(text="pairing code rejected")
        if not isinstance(label, str) or not 1 <= len(label) <= 96 or any(ord(ch) < 32 for ch in label):
            raise web.HTTPBadRequest(text="invalid device_name")
        challenge_id = self._pair_challenge_id
        if self._pair_authorizer is None or not challenge_id or not self._pair_authorizer(
                challenge_id, label):
            raise web.HTTPForbidden(text="pairing is not authorized by the local host owner")
        key_id, api_key, expires_at = self.key_store.issue(
            f"paired · {label}", scopes=PAIR_SCOPES, runtimes=("*",),
            ttl_seconds=API_KEY_TTL_SECONDS)
        self._pair_digest = None
        self._pair_expires_at = None
        self._pair_challenge_id = None
        self._pair_code = None
        if self._pair_recorder is None or not self._pair_recorder(
                challenge_id, label, key_id, expires_at):
            self.key_store.revoke(key_id)
            raise web.HTTPServiceUnavailable(text="pairing result could not be recorded")
        return web.json_response({
            "api_key": api_key, "key_id": key_id,
            "expires_at": expires_at, "scopes": sorted(PAIR_SCOPES),
        }, status=201)

    def _auth(self, request: web.Request, required_scope: str) -> dict[str, Any]:
        authorization = request.headers.get("Authorization", "")
        scheme, _, raw_key = authorization.partition(" ")
        record = self.key_store.authenticate(raw_key) if scheme.casefold() == "bearer" else None
        if record is None:
            raise web.HTTPUnauthorized(text="valid bearer credential required")
        if required_scope not in record["scopes"]:
            raise web.HTTPForbidden(text="credential lacks required scope")
        return record

    async def _runtimes(self, request: web.Request) -> web.Response:
        record = self._auth(request, "runtime:read")
        candidates = {
            "opencode": ("OpenCode", "opencode"),
            "openisy": ("OpenISy", "bun"),
            "codex": ("Codex", "codex"),
            "claude-code": ("Claude Code", "claude"),
            "crush": ("Crush", "crush"),
            "gemini": ("Gemini CLI", "gemini"),
        }
        items = [{
            "id": runtime_id, "name": label,
            "installed": shutil.which(binary) is not None,
            "adapter": "pending",
            "selectable": False,
        } for runtime_id, (label, binary) in candidates.items()]
        if "*" not in record["runtimes"]:
            items = [item for item in items if item["id"] in record["runtimes"]]
        return web.json_response({"runtimes": items, "selection_available": False})

    async def _select_runtime(self, request: web.Request) -> web.Response:
        record = self._auth(request, "runtime:select")
        data = await self._json_body(request)
        runtime_id = data.get("runtime_id")
        if not isinstance(runtime_id, str) or not re.fullmatch(
                r"[a-z0-9][a-z0-9_-]{0,63}", runtime_id):
            raise web.HTTPBadRequest(text="invalid runtime_id")
        if "*" not in record["runtimes"] and runtime_id not in record["runtimes"]:
            raise web.HTTPForbidden(text="credential is not scoped for this runtime")
        raise web.HTTPConflict(text="runtime has no active ISyCode adapter")

    async def _heartbeat(self, request: web.Request) -> web.Response:
        record = self._auth(request, "client:heartbeat")
        data = await self._json_body(request)
        client_id = data.get("client_id")
        device_name = data.get("device_name", record["name"])
        if not isinstance(client_id, str) or not CLIENT_ID_RE.fullmatch(client_id):
            raise web.HTTPBadRequest(text="invalid client_id")
        if (not isinstance(device_name, str) or not 1 <= len(device_name) <= 96
                or any(ord(ch) < 32 for ch in device_name)):
            raise web.HTTPBadRequest(text="invalid device_name")
        # Heartbeats prove client liveness only. Runtime and session state are
        # host-owned and cannot be asserted by the remote client.
        self._clients[(record["id"], client_id)] = {
            "client_id": client_id, "device_name": device_name,
            "last_seen": time.time(),
        }
        return web.json_response({"accepted": True, "lease_seconds": CLIENT_TTL_SECONDS})


class MobileHostOwner:
    """Own MobileHost lifecycle through Workspace Authority and IsySentinel."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore, host: MobileHost | None = None):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.gate = ProductActionGate(self.root, authority, owner_id="mobile_host")
        self.host = host or MobileHost(pair_authorizer=self.authorize_pair)
        self.host._pair_authorizer = self.authorize_pair
        self.host._pair_recorder = self.record_pair

    def start_request(self) -> ActionRequest:
        return ActionRequest("mobile.host.start", self.root, "127.0.0.1:8765",
                             {"bind": "127.0.0.1", "port": 8765,
                              "transport": "loopback"}, execution_owner="mobile_host")

    async def authorize_and_launch(self, approval: ActionApproval) -> tuple[bool, str]:
        if self.host.bind != "127.0.0.1" or self.host.port != 8765:
            return False, "Secure TUI requires a loopback listener on port 8765"
        request = self.start_request()
        authority, decision = self.gate.authorize(
            request, approvals=self.approvals, approval=approval)
        if not authority.allowed or not decision.allowed:
            reason = authority.reason if not authority.allowed else next(
                (check.reason for check in decision.checks if not check.passed),
                "IsySentinel denied the host start")
            return False, reason
        status = await self.host.start()
        if not status.alive:
            return False, status.error or "host did not become healthy"
        result = json.dumps({"state": "ready", "bind": status.address,
                             "port": status.port}, sort_keys=True)
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), request.action_id, request.digest,
            "ALLOW", "SUCCESS", hashlib.sha256(result.encode("utf-8")).hexdigest())
        if not self.gate.persist_receipt(request, receipt):
            try:
                await self.host.stop()
            except Exception:
                return False, "host started but receipt failed and listener cleanup failed"
            return False, "host start receipt could not be persisted; listener stopped"
        return True, "Mobile Host started on loopback"

    async def shutdown(self) -> None:
        """Release the loopback listener when the owning TUI exits."""
        await self.host.stop()

    def authorize_pair(self, challenge_id: str, device_name: str) -> bool:
        request = ActionRequest("mobile.pair", self.root, "mobile-host", {
            "challenge_id": challenge_id, "device_name": device_name,
        }, execution_owner="mobile_host")
        authority, decision = self.gate.authorize(request)
        return authority.allowed and decision.allowed

    def record_pair(self, challenge_id: str, device_name: str,
                    key_id: str, expires_at: float) -> bool:
        request = ActionRequest("mobile.pair", self.root, "mobile-host", {
            "challenge_id": challenge_id, "device_name": device_name,
        }, execution_owner="mobile_host")
        result = f"paired:{key_id}:{expires_at:.3f}:runtime:read,runtime:select,client:heartbeat"
        receipt = ActionReceipt(
            "rcpt_" + secrets.token_hex(8), "mobile.pair", request.digest,
            "ALLOW", "SUCCESS", hashlib.sha256(result.encode("utf-8")).hexdigest())
        return self.gate.persist_receipt(request, receipt)
