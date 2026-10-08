"""A reviewed provider address is the peer. A later DNS answer is not."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from isycode.egress import ReviewedDestination
from isycode.providers import Provider, ProviderError
from isycode.streaming import stream_complete


class _Capture:
    def __init__(self, body: bytes, status: int = 200, content_type: str = "application/json"):
        self.hits: list[tuple[str, str, str | None]] = []
        body_bytes = body
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self._record()

            def do_POST(self):
                self._record()

            def _record(self):
                parent.hits.append((self.path, self.headers.get("Host", ""),
                                    self.headers.get("Authorization") or self.headers.get("X-Api-Key")))
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.server_port

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()


def _refuse_second_lookup(monkeypatch):
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host == "rebind.example.test":
            raise OSError("second resolution is not the reviewed address")
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)


def _reviewed(port: int):
    return ReviewedDestination("rebind.example.test", port, ("127.0.0.1",), "http")


def test_sync_stream_dials_the_reviewed_address(monkeypatch):
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    _refuse_second_lookup(monkeypatch)
    capture = _Capture(b'data: {"choices":[{"delta":{"content":"pinned"}}]}\n\ndata: [DONE]\n\n',
                       content_type="text/event-stream")
    try:
        monkeypatch.setattr(
            "isycode.streaming.review_destination", lambda url: _reviewed(capture.port))
        result = stream_complete(
            f"http://rebind.example.test:{capture.port}/v1", "unit-test-token", "m", [], timeout_s=2)
    finally:
        capture.close()
    assert result["text"] == "pinned"
    assert capture.hits
    host, auth = capture.hits[0][1], capture.hits[0][2]
    assert host.startswith("rebind.example.test")
    assert auth == "Bearer unit-test-token"


def test_model_catalog_dials_the_reviewed_address(monkeypatch):
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    _refuse_second_lookup(monkeypatch)
    capture = _Capture(b'{"data":[{"id":"pinned-model"}]}')
    try:
        monkeypatch.setattr(
            "isycode.egress.review_destination", lambda url: _reviewed(capture.port))
        # The constructor already refuses cleartext to a name. The catalog
        # request is what must stay pinned after that URL is the one reviewed.
        provider = Provider("ollama", base_url="http://127.0.0.1:9/v1",
                            api_key="unit-test-token", timeout_s=2)
        provider.base_url = f"http://rebind.example.test:{capture.port}/v1"
        assert provider.models() == ["pinned-model"]
    finally:
        capture.close()
    assert capture.hits
    assert capture.hits[0][1].startswith("rebind.example.test")
    assert capture.hits[0][2] == "Bearer unit-test-token"


def test_anthropic_catalog_and_stream_dial_the_reviewed_address(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    _refuse_second_lookup(monkeypatch)
    catalog = _Capture(json.dumps({
        "data": [{
            "id": "pinned-model",
            "type": "model",
            "display_name": "Pinned",
            "created_at": "2020-01-01T00:00:00Z",
        }],
        "has_more": False,
    }).encode())
    stream = _Capture(b'{"type":"error","error":{"type":"authentication_error","message":"no"}}',
                      status=401)
    try:
        from isycode.anthropic_provider import anthropic_stream_complete, list_models
        peer = {"port": catalog.port}
        monkeypatch.setattr(
            "isycode.egress.review_destination", lambda url: _reviewed(peer["port"]))
        assert list_models("unit-test-token", f"http://rebind.example.test:{catalog.port}") == ["pinned-model"]
        peer["port"] = stream.port

        async def once():
            await anthropic_stream_complete(
                "unit-test-token", "pinned-model", [{"role": "user", "content": "hi"}],
                max_tokens=8, base_url=f"http://rebind.example.test:{stream.port}", timeout_s=2)

        import asyncio
        with pytest.raises(ProviderError):
            asyncio.run(once())
    finally:
        catalog.close()
        stream.close()
    assert catalog.hits and catalog.hits[0][1].startswith("rebind.example.test")
    assert catalog.hits[0][2] == "unit-test-token"
    assert stream.hits and stream.hits[0][1].startswith("rebind.example.test")
    assert stream.hits[0][2] == "unit-test-token"
