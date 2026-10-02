"""Provider protocol capability is separate from workspace authorization."""
import pytest

from isycode.headless import available_tools
from isycode.providers import PRESETS, Provider
from isycode.workspace_authority import WorkspaceAuthority


@pytest.fixture(autouse=True)
def isolated_provider_environment(monkeypatch):
    for name in ("ISYCODE_BASE_URL", "ISYMOTRON_BASE_URL", "OLLAMA_HOST"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("name", ["ollama", "llamacpp"])
def test_compatible_presets_offer_classic_tools_but_not_security_tools(tmp_path, name):
    provider = Provider(name=name, model="tool-capable-model", api_key="")
    authority = WorkspaceAuthority(tmp_path, state_directory=tmp_path / "state")
    authority.set_mode("classic")
    tools = available_tools(tmp_path, authority) if provider.supports_tools else []
    assert PRESETS[name].get("supports_tools") is True
    assert tools
    assert all(tool["type"] == "function" for tool in tools)

    authority.set_mode("security")
    assert available_tools(tmp_path, authority) == []
    authority.set_mode("classic")
    authority.set_grant("workspace.files.read", enabled=False)
    assert available_tools(tmp_path, authority) == []


def test_openrouter_does_not_assume_tool_support_for_every_selected_model():
    provider = Provider(name="openrouter", model="unknown/model", api_key="")
    assert provider.supports_tools is False


@pytest.mark.parametrize("endpoint", [
    "http://127.0.0.1:21434", "http://localhost:21434",
])
def test_classic_ollama_custom_endpoint_matches_transport(tmp_path, monkeypatch, endpoint):
    from urllib.parse import urlsplit
    from isycode.action_runtime import ProductActionGate
    from isycode.security import ActionRequest

    monkeypatch.delenv("ISYCODE_BASE_URL", raising=False)
    monkeypatch.delenv("ISYMOTRON_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", endpoint)
    provider = Provider(name="ollama", model="local", api_key="")
    parsed = urlsplit(provider.base_url)
    assert parsed.hostname is not None
    hostname = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    host = hostname + f":{parsed.port}"
    authority = WorkspaceAuthority(tmp_path, state_directory=tmp_path / "state")
    authority.set_mode("classic")

    def allowed(target):
        request = ActionRequest("provider.request", tmp_path, target,
                                {"url": provider.base_url}, execution_owner="provider_network")
        return ProductActionGate(tmp_path, authority, owner_id="provider_network").authorize(request)[1].allowed

    assert allowed(host)
    assert not allowed(parsed.hostname + ":21435")
    authority.set_grant("provider.request", enabled=False)
    assert not allowed(host)
    authority.set_mode("security")
    assert not allowed(host)


def test_endpoint_resolution_precedence_does_not_grant_shadowed_hosts(monkeypatch):
    from isycode.providers import provider_base_url
    from isycode.workspace_authority import _known_provider_hosts

    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:21434")
    assert provider_base_url("ollama") == "http://localhost:21434/v1"
    monkeypatch.setenv("ISYMOTRON_BASE_URL", "http://localhost:31434/v1/")
    assert provider_base_url("ollama") == "http://localhost:31434/v1"
    monkeypatch.setenv("ISYCODE_BASE_URL", "http://localhost:41434/v1/")
    assert Provider(name="ollama", model="local", api_key="").base_url == "http://localhost:41434/v1"
    assert "localhost:41434" in _known_provider_hosts()
    assert "localhost:31434" not in _known_provider_hosts()
    assert "localhost:21434" not in _known_provider_hosts()
    assert provider_base_url("ollama", "http://localhost:51434/v1/") == "http://localhost:51434/v1"


@pytest.mark.parametrize("endpoint", [
    "http://localhost:invalid", "ftp://localhost:21434", "http://user@localhost:21434",
])
def test_unsafe_ollama_endpoint_does_not_add_an_authority_host(monkeypatch, endpoint):
    from isycode.workspace_authority import _known_provider_hosts

    monkeypatch.setenv("OLLAMA_HOST", endpoint)
    assert not any(host.startswith("localhost") for host in _known_provider_hosts())
