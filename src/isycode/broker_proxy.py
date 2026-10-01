"""Loopback-only HTTP forwarder for a broker on an internal Docker network."""
from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


MAX_BODY_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 1_048_576
OPERATIONS = frozenset({
    "context", "symbols/search", "document-symbols", "definition", "references",
    "hover", "diagnostics", "semantic-slice", "callers", "callees", "implementations",
})


def make_server(target_ip: str, port: int) -> ThreadingHTTPServer:
    address = ipaddress.ip_address(target_ip)
    if address.version != 4 or not address.is_private:
        raise ValueError("broker target must be a private IPv4 address")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _forward(self, method: str) -> None:
            parsed = urlsplit(self.path)
            path = parsed.path
            if parsed.query or parsed.fragment or not (
                (method == "GET" and path == "/health")
                or (method == "POST" and path.startswith("/v1/")
                    and path[4:] in OPERATIONS)
            ):
                self.send_error(404)
                return

            body = b""
            if method == "POST":
                raw_length = self.headers.get("Content-Length", "")
                if not raw_length.isdigit() or int(raw_length) > MAX_BODY_BYTES:
                    self.send_error(413)
                    return
                if self.headers.get("Transfer-Encoding"):
                    self.send_error(400)
                    return
                body = self.rfile.read(int(raw_length))
                try:
                    payload = json.loads(body)
                except (UnicodeError, json.JSONDecodeError):
                    self.send_error(400)
                    return
                if not isinstance(payload, dict):
                    self.send_error(400)
                    return

            connection = http.client.HTTPConnection(target_ip, 8791, timeout=10)
            try:
                connection.request(method, path, body=body if method == "POST" else None,
                                   headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    self.send_error(502)
                    return
                self.send_response(response.status)
                self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload)
            except (OSError, http.client.HTTPException):
                self.send_error(502)
            finally:
                connection.close()
                self.close_connection = True

        def do_GET(self) -> None:  # noqa: N802
            self._forward("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._forward("POST")

        def do_CONNECT(self) -> None:  # noqa: N802
            self.send_error(405)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.timeout = 0.5
    return server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker-id", required=True)
    parser.add_argument("--target-ip", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    server = make_server(args.target_ip, args.port)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
