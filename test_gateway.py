#!/usr/bin/env python3
"""M2 — Gateway integration tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ISYCODE_ROOT = Path(__file__).parent
sys.path.insert(0, str(ISYCODE_ROOT))

import pytest

from isycode.gateway_client import GatewayClient, GatewayError, mutation_fails_closed

# Live integration tests talk to a real Gateway (one writes and deletes a file
# on it), so they only run when explicitly requested. Degraded-mode tests below
# are offline and always run.
live_gateway = pytest.mark.skipif(
    os.environ.get("ISYCODE_LIVE_GATEWAY") != "1",
    reason="needs a running ISyCo Gateway; set ISYCODE_LIVE_GATEWAY=1 "
           "(test_gateway_write_file writes and deletes a test file)")


@pytest.mark.integration
@live_gateway
def test_gateway_read_file():
    client = GatewayClient()
    result = client.read("AGENTS.md")
    assert "content" in result
    assert len(result["content"]) > 0


@pytest.mark.integration
@live_gateway
def test_gateway_list_files():
    client = GatewayClient()
    result = client.list_files("git")
    assert "items" in result
    assert result["count"] > 0


@pytest.mark.integration
@live_gateway
def test_gateway_search():
    client = GatewayClient()
    result = client.search("ISyCode", path="git")
    assert "results" in result or "items" in result or "matches" in result


@pytest.mark.integration
@live_gateway
def test_gateway_write_file():
    client = GatewayClient()
    test_path = "git/isycode-m2-test.txt"
    try:
        result = client.write(test_path, "M2 test content")
        assert result is not None
        read_back = client.read(test_path)
        assert "M2 test content" in read_back.get("content", "")
    finally:
        try:
            client._request("DELETE", f"/v1/files?path={test_path}")
        except Exception:
            pass


def test_degraded_mode_mutation_fails_closed():
    client = GatewayClient()
    client._available = False
    allowed, reason = mutation_fails_closed(client, "filesystem.write")
    assert not allowed
    assert "DEGRADED MODE" in reason
    assert "failed closed" in reason


def test_degraded_mode_no_bash_fallback():
    client = GatewayClient()
    client._available = False
    try:
        client.write("some/path.txt", "content")
        assert False, "write should have raised GatewayError"
    except GatewayError as e:
        assert e.code == "DEGRADED_MODE"
        assert "failed closed" in e.message


@pytest.mark.integration
@live_gateway
def test_gateway_available_check():
    client = GatewayClient()
    assert client.is_available() is True


def test_gateway_unavailable_detection():
    client = GatewayClient(base_url="http://127.0.0.1:1")
    assert client.is_available() is False
    assert client.is_available() is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
