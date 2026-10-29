"""Loopback-only witnesses for the ISyCode side of the Gateway HTTP boundary."""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from isycode.gateway_client import GatewayClient, GatewayError
from isycode.openisy_client import OpenIsyClient
from isycode.semantic_gateway import SemanticGatewayClient


@contextmanager
def _server(handler_type):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_type)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _handler(routes, seen):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization"),
                         self.headers.get("X-Forwarded-Proto")))
            status, headers, body = routes(self.path)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def test_cleartext_is_only_localhost_or_a_real_loopback_address():
    for url in ("http://127.0.0.1:8787", "http://localhost:8787", "http://[::1]:8787"):
        GatewayClient._validate_base_url(url)
        OpenIsyClient._validate_base_url(url)
    for url in (
        "http://127.evil.com:8787",
        "http://127.0.0.1.attacker.example:8787",
        "http://127.1:8787",
    ):
        with pytest.raises(ValueError):
            GatewayClient._validate_base_url(url)
        with pytest.raises(ValueError):
            OpenIsyClient._validate_base_url(url)
        with pytest.raises(ValueError):
            SemanticGatewayClient(base_url=url, api_key="fixture")


def test_base_urls_reject_bearer_credentials_over_non_loopback_or_with_url_secrets():
    for url in (
        "http://gateway.example.test",
        "http://user:password@127.0.0.1:8787",
        "http://127.0.0.1:8787?token=secret",
        "http://127.0.0.1:8787#fragment",
        "ftp://127.0.0.1:8787",
    ):
        with pytest.raises(ValueError):
            GatewayClient._validate_base_url(url)
        with pytest.raises(ValueError):
            SemanticGatewayClient(base_url=url, api_key="fixture")


def test_gateway_client_same_origin_redirect_keeps_bearer_on_loopback():
    seen = []

    def routes(path):
        if path == "/start":
            return 302, {"Location": "/final"}, b""
        return 200, {"Content-Type": "application/json"}, b'{"ok":true}'

    with _server(_handler(routes, seen)) as base:
        client = GatewayClient(base_url=base, api_key="fixture-secret")
        assert client._request("GET", "/start") == {"ok": True}

    assert seen == [
        ("/start", "Bearer fixture-secret", "https"),
        ("/final", "Bearer fixture-secret", "https"),
    ]


def test_gateway_client_cross_origin_redirect_never_forwards_bearer():
    seen_primary = []
    seen_other = []
    with _server(_handler(
            lambda _path: (200, {"Content-Type": "application/json"}, b'{"ok":true}'),
            seen_other)) as other:
        def routes(path):
            if path == "/start":
                return 302, {"Location": f"{other}/capture"}, b""
            return 200, {"Content-Type": "application/json"}, b'{"unexpected":true}'

        with _server(_handler(routes, seen_primary)) as base:
            client = GatewayClient(base_url=base, api_key="fixture-secret")
            with pytest.raises(GatewayError):
                client._request("GET", "/start")

    assert seen_primary == [("/start", "Bearer fixture-secret", "https")]
    assert seen_other == []


def test_semantic_client_uses_same_origin_redirect_guard_for_identity():
    seen_primary = []
    seen_other = []
    with _server(_handler(
            lambda _path: (200, {"Content-Type": "application/json"},
                           json.dumps({"workspace_id": "should-not-arrive"}).encode()),
            seen_other)) as other:
        def routes(path):
            if path == "/v1/workspace/identity":
                return 302, {"Location": f"{other}/capture"}, b""
            return 404, {}, b"{}"

        with _server(_handler(routes, seen_primary)) as base:
            client = SemanticGatewayClient(base_url=base, api_key="fixture-secret")
            with pytest.raises(GatewayError):
                client.workspace_identity()

    assert seen_primary == [
        ("/v1/workspace/identity", "Bearer fixture-secret", "https"),
    ]
    assert seen_other == []
