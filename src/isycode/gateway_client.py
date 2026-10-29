#!/usr/bin/env python3
"""ISyCode Gateway Client — HTTP client for the ISyCo Gateway.

DEGRADED MODE (INV-2): if the gateway is unavailable, mutating operations
FAIL CLOSED. No silent bash fallback. Raw shell is never invoked.
"""
from __future__ import annotations

import os
import json
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass

from isycode.egress import cleartext_loopback_host


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward a Gateway bearer token to a different origin."""

    def redirect_request(self, request, fp, code, message, headers, new_url):
        old = urllib.parse.urlsplit(request.full_url)
        new = urllib.parse.urlsplit(new_url)
        if (old.hostname != new.hostname or old.port != new.port
                or (old.scheme == "https" and new.scheme != "https")):
            return None
        return super().redirect_request(request, fp, code, message, headers, new_url)


@dataclass
class GatewayError(Exception):
    code: str
    message: str
    status: int = 0


class GatewayClient:
    """HTTP client for the OpenISy Gateway (files, search, read, write)."""

    def __init__(self, base_url: str | None = None,
                 api_key: str | None = None, timeout_s: float = 10.0):
        self.base_url = (base_url or os.environ.get("GATEWAY_URL")
                         or "http://127.0.0.1:8787").strip().rstrip("/")
        self._validate_base_url(self.base_url)
        self.api_key = api_key or os.environ.get("GATEWAY_API_KEY", "")
        if not self.api_key:
            from isycode.credentials import read_saved_secret

            self.api_key = read_saved_secret("isyco-gateway", "gateway") or ""
        self.timeout_s = timeout_s
        self._available: bool | None = None

    @staticmethod
    def _validate_base_url(base_url: str) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("GATEWAY_URL must be an http(s) server URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("GATEWAY_URL must not contain credentials, query, or fragment.")
        if parsed.scheme != "https" and not cleartext_loopback_host(parsed.hostname):
            raise ValueError("Gateway bearer credentials require HTTPS unless the server is loopback.")

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method)
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.hostname and parsed.hostname.casefold().rstrip(".") in {"localhost", "127.0.0.1", "::1"}:
            # The local Gateway is bound to host loopback and enforces HTTPS
            # based on the trusted tunnel's forwarded-proto header. This
            # marker is sent only to loopback so the local client can use the
            # same deployment policy without weakening remote TLS checks.
            req.add_header("X-Forwarded-Proto", "https")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")
        try:
            opener = urllib.request.build_opener(_SameOriginRedirectHandler)
            with opener.open(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")
            try:
                err = json.loads(err_body)
                raise GatewayError(
                    err.get("error", {}).get("code", "HTTP_ERROR"),
                    err.get("error", {}).get("message", err_body), e.code)
            except (json.JSONDecodeError, KeyError):
                raise GatewayError("HTTP_ERROR", err_body, e.code)
        except (urllib.error.URLError, OSError) as e:
            self._available = False
            raise GatewayError("GATEWAY_UNAVAILABLE", f"gateway unreachable: {e}", 0)

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            self._request("GET", "/health")
            self._available = True
        except GatewayError:
            self._available = False
        return self._available

    def read(self, path: str) -> dict:
        return self._request("GET", f"/v1/read?path={urllib.parse.quote(path)}")

    def list_files(self, path: str = "", recursive: bool = False) -> dict:
        q = f"?path={urllib.parse.quote(path)}&recursive={str(recursive).lower()}"
        return self._request("GET", f"/v1/files{q}")

    def search(self, query: str, path: str = "") -> dict:
        q = f"?q={urllib.parse.quote(query)}&path={urllib.parse.quote(path)}"
        return self._request("GET", f"/v1/search{q}")

    def write(self, path: str, content: str) -> dict:
        if not self.is_available():
            raise GatewayError("DEGRADED_MODE",
                "Gateway unavailable: mutation failed closed. No bash fallback.")
        return self._request("POST", "/v1/write", {"path": path, "content": content})


def mutation_fails_closed(client: GatewayClient, operation: str) -> tuple[bool, str]:
    if not client.is_available():
        return False, (f"DEGRADED MODE: gateway unavailable. "
                       f"'{operation}' failed closed. No bash fallback.")
    return True, "gateway available"
