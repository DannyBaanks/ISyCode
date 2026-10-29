"""Credential-bearing provider requests must not follow HTTP redirects."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from isycode.providers import Provider, ProviderError
from isycode.streaming import StreamError, stream_complete


class _Server:
    def __init__(self, handler):
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()


def _redirect_pair():
    received = []
    receiver = None

    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.path, self.headers.get("Authorization")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data":[]}')

        def do_POST(self):
            received.append((self.path, self.headers.get("Authorization")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            pass

    receiver = _Server(Receiver)

    class Redirector(BaseHTTPRequestHandler):
        def _redirect(self):
            self.send_response(302)
            self.send_header("Location", receiver.url + "/capture")
            self.end_headers()

        do_GET = _redirect
        do_POST = _redirect

        def log_message(self, *_args):
            pass

    return received, receiver, _Server(Redirector)


def test_model_catalog_does_not_forward_bearer_to_redirect_target():
    received, receiver, redirector = _redirect_pair()
    try:
        provider = Provider("ollama", base_url=redirector.url + "/v1", api_key="unit-test-token")
        with pytest.raises(ProviderError):
            provider.models()
        assert received == []
    finally:
        redirector.close()
        receiver.close()


def test_legacy_stream_transport_does_not_follow_redirect_with_bearer():
    received, receiver, redirector = _redirect_pair()
    try:
        with pytest.raises(StreamError):
            stream_complete(redirector.url + "/v1", "unit-test-token", "test-model", [])
        assert received == []
    finally:
        redirector.close()
        receiver.close()
