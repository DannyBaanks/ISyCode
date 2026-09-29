"""Offline witnesses for bounded, read-only Tailscale inventory."""

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from isycode.tailscale import TailscaleAdapter, TailscaleCommandResult, _gateway_health


STATUS = {"BackendState": "Running", "Self": {"DNSName": "desk.tailnet.ts.net."}}
EMPTY_SERVE = {"version": "0.0.1", "services": {}}
EMPTY_NODE = {"TCP": {}, "Web": {}, "AllowFunnel": {}}
EXISTING_SERVE = {
    "TCP": {"443": {"HTTPS": True}},
    "Web": {"desk.tailnet.ts.net:443": {"Handlers": {
        "/other": {"Proxy": "http://127.0.0.1:9999"}}}},
    "AllowFunnel": {},
}


def adapter(monkeypatch, answers=None, *, platform="linux", gateway_url="http://127.0.0.1:8787", probe=None,
            gateway_port=8787):
    monkeypatch.setattr("isycode.tailscale.shutil.which", lambda name: sys.executable if name == "tailscale" else None)
    calls = []

    def runner(argv, *, env, timeout, max_output):
        calls.append((tuple(argv), env, timeout, max_output))
        assert isinstance(argv, list)
        assert set(env) <= {"PATH", "LANG", "LC_ALL"}
        assert timeout <= 5 and max_output <= 65536
        answer = (answers or {}).get(tuple(argv[1:]), (0, "{}", ""))
        if isinstance(answer, Exception):
            raise answer
        return TailscaleCommandResult(*answer)

    instance = TailscaleAdapter(runner=runner, platform=platform,
                                gateway_probe=probe or (lambda url: True), gateway_url=gateway_url,
                                gateway_port=gateway_port)
    return instance, calls


def replies(status=STATUS, serve=EMPTY_SERVE, node=EMPTY_NODE, version="1.84.0"):
    return {("version",): (0, version, ""),
            ("status", "--json"): (0, json.dumps(status), ""),
            ("serve", "get-config", "--all"): (0, json.dumps(serve), ""),
            ("serve", "status", "--json"): (0, json.dumps(node), "")}


def test_missing_cli_is_structured_and_runs_nothing(monkeypatch):
    monkeypatch.setattr("isycode.tailscale.shutil.which", lambda name: None)
    snap = TailscaleAdapter(runner=lambda *a, **k: pytest.fail("runner called"),
                            platform="linux", gateway_probe=lambda url: True).inspect()
    assert snap.state == "missing_cli"
    assert snap.serve_state == "unavailable"


def test_unsupported_os_runs_nothing(monkeypatch):
    instance, calls = adapter(monkeypatch, platform="darwin")
    assert instance.inspect().state == "unsupported_os"
    assert calls == []


def test_daemon_unavailable(monkeypatch):
    instance, _ = adapter(monkeypatch, replies() | {("status", "--json"): (1, "", "failed to connect to local tailscaled")})
    snap = instance.inspect()
    assert snap.state == "daemon_unavailable" and snap.serve_state == "unavailable"


def test_unsupported_status_command_is_unavailable(monkeypatch):
    instance, _ = adapter(monkeypatch, replies() | {("status", "--json"): (1, "", "unknown flag: --json")})
    assert instance.inspect().state == "unavailable"


def test_signed_out_and_signed_in_are_distinct(monkeypatch):
    out, _ = adapter(monkeypatch, replies(status={"BackendState": "NeedsLogin"}))
    assert out.inspect().state == "signed_out"
    online, _ = adapter(monkeypatch, replies())
    snap = online.inspect()
    assert snap.state == "signed_in" and snap.dns_name == "desk.tailnet.ts.net"
    assert snap.serve_state == "empty" and snap.gateway_healthy
    with pytest.raises(FrozenInstanceError):
        snap.state = "forged"


def test_malformed_status_json_is_unavailable(monkeypatch):
    instance, _ = adapter(monkeypatch, replies() | {("status", "--json"): (0, "not json", "")})
    assert instance.inspect().state == "unavailable"


def test_timeout_is_bounded_and_unavailable(monkeypatch):
    instance, _ = adapter(monkeypatch, replies() | {("status", "--json"): subprocess.TimeoutExpired("tailscale", 5)})
    assert instance.inspect().state == "unavailable"


def test_oversized_output_is_unavailable(monkeypatch):
    instance, _ = adapter(monkeypatch, replies() | {("status", "--json"): (0, "x" * 65537, "")})
    assert instance.inspect().state == "unavailable"


def test_existing_serve_routes_and_conflict_are_explicit(monkeypatch):
    instance, _ = adapter(monkeypatch, replies(node=EXISTING_SERVE))
    snap = instance.inspect()
    assert snap.serve_state == "existing"
    assert len(snap.routes) == 1 and snap.routes[0].path == "/other"
    unknown, _ = adapter(monkeypatch, replies(serve={"unexpected": "schema"}))
    assert unknown.inspect().serve_state == "conflict"


@pytest.mark.parametrize("port,listener", [
    ("443", {"UnknownMode": True}),
    ("443", {"HTTPS": "true"}),
    ("70000", {"HTTPS": True}),
    ("443", {"HTTPS": True, "TCPForward": "127.0.0.1:8787"}),
    ("443", {"TerminateTLS": "desk.tailnet.ts.net"}),
])
def test_malformed_tcp_listener_is_conflict(monkeypatch, port, listener):
    instance, _ = adapter(monkeypatch, replies(node={"TCP": {port: listener}}))
    assert instance.inspect().serve_state == "conflict"


def test_services_inventory_and_node_routes_are_both_visible(monkeypatch):
    service_config = {"version": "0.0.1", "services": {
        "svc:printer": {"endpoints": {"tcp:443": "http://127.0.0.1:9998"}}}}
    instance, _ = adapter(monkeypatch, replies(serve=service_config, node=EXISTING_SERVE))
    snap = instance.inspect()
    assert snap.serve_state == "existing"
    assert {(route.host, route.target) for route in snap.routes} == {
        ("svc:printer", "http://127.0.0.1:9998"),
        ("desk.tailnet.ts.net:443", "http://127.0.0.1:9999")}


def test_get_config_omits_empty_services_map(monkeypatch):
    instance, _ = adapter(monkeypatch, replies(serve={"version": "0.0.1"}))
    assert instance.inspect().serve_state == "empty"


def test_node_status_failure_does_not_look_empty(monkeypatch):
    instance, _ = adapter(monkeypatch, replies() | {("serve", "status", "--json"): (1, "", "unsupported")})
    assert instance.inspect().serve_state == "conflict"


def test_unsupported_version_and_non_json_serve_fail_closed(monkeypatch):
    old, _ = adapter(monkeypatch, replies(version="1.50.0"))
    assert old.inspect().serve_state == "unavailable"
    bad, _ = adapter(monkeypatch, replies() | {("serve", "get-config", "--all"): (0, "no serve config", "")})
    assert bad.inspect().serve_state == "conflict"


def test_gateway_probe_rejects_non_loopback_and_wrong_port(monkeypatch):
    seen = []
    for url in ("http://0.0.0.0:8787", "http://127.0.0.1:9999"):
        instance, _ = adapter(monkeypatch, replies(), gateway_url=url,
                              probe=lambda target: seen.append(target) or True)
        assert not instance.inspect().gateway_healthy
    assert seen == []


def test_gateway_probe_uses_explicit_configured_port(monkeypatch):
    seen = []
    instance, _ = adapter(monkeypatch, replies(), gateway_url="http://127.0.0.1:8899",
                          gateway_port=8899, probe=lambda target: seen.append(target) or True)
    assert instance.inspect().gateway_healthy
    assert seen == ["http://127.0.0.1:8899/health"]


def test_gateway_health_probe_models_https_terminated_proxy(monkeypatch):
    seen = {}

    class Response:
        status = 200

        @staticmethod
        def read(limit):
            assert limit == 1024

    class Connection:
        def __init__(self, host, port, timeout):
            seen["endpoint"] = (host, port, timeout)

        def request(self, method, path, *, headers):
            seen["request"] = (method, path, headers)

        @staticmethod
        def getresponse():
            return Response()

        @staticmethod
        def close():
            pass

    monkeypatch.setattr("isycode.tailscale.http.client.HTTPConnection", Connection)
    assert _gateway_health("http://127.0.0.1:8787")
    assert seen == {
        "endpoint": ("127.0.0.1", 8787, 1),
        "request": ("GET", "/health", {"X-Forwarded-Proto": "https"}),
    }


def test_inspect_runs_read_commands_only(monkeypatch):
    instance, calls = adapter(monkeypatch, replies())
    instance.inspect()
    assert [argv[1:] for argv, *_ in calls] == [
        ("version",), ("status", "--json"), ("serve", "get-config", "--all"),
        ("serve", "status", "--json")]
    assert all("reset" not in argv and "set-config" not in argv and "up" not in argv
               and "off" not in argv for argv, *_ in calls)
