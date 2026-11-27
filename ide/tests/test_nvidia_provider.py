"""Test the provider screens and NVIDIA provider addition."""

import asyncio
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))


from core.secret_broker import SecretBroker
from core.agent.providers import ProviderRegistry
from core.agent.providers.registry import PROVIDER_MAP, DEFAULT_ENDPOINTS, DEFAULT_MODELS


def test_nvidia_registered():
    print("=== NVIDIA provider registration ===")
    assert "nvidia" in PROVIDER_MAP, "nvidia missing from PROVIDER_MAP"
    assert "nvidia" in DEFAULT_ENDPOINTS, "nvidia missing from DEFAULT_ENDPOINTS"
    assert "nvidia" in DEFAULT_MODELS, "nvidia missing from DEFAULT_MODELS"
    print(f"  Provider class: {PROVIDER_MAP['nvidia'].__name__} (OpenAI-compatible)")
    print(f"  Endpoint: {DEFAULT_ENDPOINTS['nvidia']}")
    print(f"  Default model: {DEFAULT_MODELS['nvidia']}")
    print("  OK")


def test_add_provider_flow():
    print("\n=== Add NVIDIA provider via flow ===")
    tmp = Path(tempfile.mkdtemp())
    broker = SecretBroker()
    registry = ProviderRegistry(broker, config_path=tmp / "config.yaml")

    # Simulate what AddProviderScreen._save does
    name = "nvidia"
    provider_type = "nvidia"
    model = DEFAULT_MODELS["nvidia"]
    api_key = "nvapi-test-key-xyz"

    registry.add(name, provider_type, model, endpoint=None, api_key=api_key)

    providers = registry.list()
    assert name in providers, "provider not in registry"
    assert providers[name]["provider"] == "nvidia"
    assert providers[name]["endpoint"] == DEFAULT_ENDPOINTS["nvidia"]
    assert "api_key" not in providers[name], "api key leaked into config list!"

    has_key = registry.has_key(name)
    assert has_key, "key not stored in broker"

    # Key should NOT be in the config file
    config_text = (tmp / "config.yaml").read_text(encoding="utf-8")
    assert "nvapi-test-key-xyz" not in config_text, "API key leaked into config.yaml!"

    print(f"  Registered: {name} -> {provider_type}/{model}")
    print(f"  Endpoint: {providers[name]['endpoint']}")
    print(f"  Key stored in broker: {has_key}")
    print(f"  Config file clean (no key): OK")

    # Now verify a provider instance can be created
    provider = registry.get(name)
    assert provider.config.endpoint == DEFAULT_ENDPOINTS["nvidia"]
    print(f"  Provider instance: {provider.__class__.__name__} @ {provider.config.endpoint}")
    print("  OK")


def test_persistence_reuse():
    print("\n=== Secret persistence (reuse on restart) ===")
    tmp = Path(tempfile.mkdtemp())
    broker1 = SecretBroker()
    registry1 = ProviderRegistry(broker1, config_path=tmp / "config.yaml")
    registry1.add("nvidia", "nvidia", DEFAULT_MODELS["nvidia"], api_key="nvapi-persist-key")

    # Simulate new session - new broker instance reads from same storage
    import keyring
    stored = keyring.get_password(SecretBroker.SERVICE, "provider:nvidia")
    assert stored == "nvapi-persist-key"
    assert not (tmp / "secrets.json").exists()

    # New registry should see the provider config
    broker2 = SecretBroker()
    registry2 = ProviderRegistry(broker2, config_path=tmp / "config.yaml")
    assert "nvidia" in registry2.list(), "config not persistent across sessions"
    assert registry2.has_key("nvidia"), "key not persistent across sessions"
    print("  New session sees: provider config + key  OK")

    # Cleanup test keys
    broker1.remove("nvidia")
    broker2.remove("nvidia")
    print("  Cleaned up test key")


if __name__ == "__main__":
    test_nvidia_registered()
    test_add_provider_flow()
    test_persistence_reuse()
    print("\nALL PROVIDER SCREEN TESTS PASSED")