import asyncio
from types import SimpleNamespace
import pytest
from isycode import vision_probe
from isycode.capability_observations import observed
from isycode.providers import ProviderError

@pytest.mark.parametrize("reply,expected", [("ABC234", "DEMONSTRATED"), ("OK", "CHALLENGE_FAILED"), ("NO", "CHALLENGE_FAILED")])
def test_only_visual_challenge_demonstrates_vision(tmp_path, monkeypatch, reply, expected):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(vision_probe, "challenge", lambda: ("ABC234", b"png"))
    async def execute(self, provider, material, send):
        assert "ABC234" not in material["messages"][0]["content"][0]["text"]
        return {"text": reply}, SimpleNamespace(decision="ALLOW", receipt=SimpleNamespace(receipt_id="r"))
    monkeypatch.setattr(vision_probe.ProviderNetworkOwner, "execute", execute)
    provider = SimpleNamespace(name="fixture", model="model", token_limit_field="max_tokens", reasoning_effort=None, temperature_supported=True)
    result = asyncio.run(vision_probe.probe(tmp_path, None, provider))
    assert result["outcome"] == expected
    assert observed("fixture", "model", "images") is (True if expected == "DEMONSTRATED" else None)

@pytest.mark.parametrize("status,expected", [(404, False), (401, None), (429, None), (500, None)])
def test_only_missing_endpoint_is_filtered(tmp_path, monkeypatch, status, expected):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    async def execute(*args):
        raise ProviderError("failure", status)
    monkeypatch.setattr(vision_probe.ProviderNetworkOwner, "execute", execute)
    provider = SimpleNamespace(name="fixture", model="model", token_limit_field="max_tokens", reasoning_effort=None, temperature_supported=True)
    asyncio.run(vision_probe.availability(tmp_path, None, provider))
    assert observed("fixture", "model", "chat_available") is expected
