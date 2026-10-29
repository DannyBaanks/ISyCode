from isycode.bridge import BridgeClient


def test_bridge_agent_listing_uses_the_handshake_command(monkeypatch):
    client = object.__new__(BridgeClient)
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return (
            "Agents registry (/private/bridge/agents.json):\n"
            "  isycode         caps=[tui,read] last_hb=2026-09-28T12:00:00Z status=alive\n"
        )

    monkeypatch.setattr(client, "_run", run)

    agents = client.agents()

    assert calls == [(('agents',), {})]
    assert agents == {
        "isycode": {
            "status": "alive",
            "last_heartbeat": "2026-09-28T12:00:00Z",
            "capabilities": ["tui", "read"],
        }
    }
