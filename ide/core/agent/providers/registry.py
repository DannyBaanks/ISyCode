"""Provider metadata shared by desktop/TUI; clients are owned by individual turns."""

from __future__ import annotations

import copy
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .base import ProviderConfig, BaseProvider
from .openai import OpenAIProvider
from .anthropic import AnthropicProvider
from .google import GoogleProvider
from .ollama import OllamaProvider
from .claude import ClaudeCodeProvider
from .subscription import SubscriptionProvider
from core.subscriptions import ENDPOINTS as SUBSCRIPTION_ENDPOINTS
from ...secret_broker import SecretBroker
from ...ide_state import state_home, atomic_write, state_lock

PROVIDER_MAP = {
    "openai": OpenAIProvider, "openai-compatible": OpenAIProvider,
    "anthropic": AnthropicProvider, "google": GoogleProvider,
    "ollama": OllamaProvider, "nvidia": OpenAIProvider,
    "claude": ClaudeCodeProvider,
    **{kind: SubscriptionProvider for kind in SUBSCRIPTION_ENDPOINTS},
}
DEFAULT_ENDPOINTS = {
    **SUBSCRIPTION_ENDPOINTS,
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta",
    "ollama": "http://localhost:11434",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "claude": "https://api.anthropic.com",
}
# Compatibility suggestions only: discovery, not this table, reports availability.
DEFAULT_MODELS = {
    "openai": "gpt-4o", "anthropic": "claude-3-5-sonnet-20241022",
    "google": "gemini-1.5-pro", "ollama": "llama3.1",
    "nvidia": "meta/llama-3.3-70b-instruct", "claude": "claude-sonnet-4-5",
}


class _TurnCredentials:
    """A single credential snapshot; changing a profile cannot change an active turn."""

    def __init__(self, name, key):
        self._name, self._key = name, key

    def get(self, name):
        return self._key if name == self._name else None

    def inject_into_headers(self, name, headers):
        key = self.get(name)
        if not key:
            raise ValueError("Configura una clave API para este provider.")
        return {**headers, "Authorization": f"Bearer {key}"}

    def clear(self):
        self._key = None


def validate_config(name: str, config: dict) -> dict:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
        raise ValueError("Usa un nombre de 1–64 letras, números, punto, guion o guion bajo.")
    kind = config.get("provider")
    if kind not in PROVIDER_MAP:
        raise ValueError("Protocolo de provider no soportado.")
    model = config.get("model", "")
    if not isinstance(model, str) or not model.strip() or len(model) > 256 or any(ord(c) < 32 for c in model):
        raise ValueError("Introduce un identificador de modelo válido.")
    endpoint = config.get("endpoint") or DEFAULT_ENDPOINTS.get(kind, "")
    if not isinstance(endpoint, str) or len(endpoint) > 2048 or any(c.isspace() for c in endpoint):
        raise ValueError("Introduce un endpoint HTTP(S) válido.")
    parsed = urlsplit(endpoint)
    try:
        parsed.port
    except ValueError:
        raise ValueError("El puerto del endpoint no es válido.") from None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("El endpoint debe ser HTTP(S), sin credenciales, query ni fragmento.")
    timeout = config.get("timeout", 30.0)
    maximum = config.get("max_tokens", 4096)
    temperature = config.get("temperature", 0.7)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 600:
        raise ValueError("Timeout: entre 1 y 600 segundos.")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 1_000_000:
        raise ValueError("El límite de salida debe ser un entero positivo.")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError("Temperatura: entre 0 y 2.")
    auth = config.get("auth", "subscription" if kind in SUBSCRIPTION_ENDPOINTS else "none" if kind == "ollama" else "api_key")
    if auth not in {"none", "api_key", "subscription"}:
        raise ValueError("Autenticación no soportada por este transporte.")
    if kind in SUBSCRIPTION_ENDPOINTS:
        if auth != "subscription" or endpoint.rstrip("/") != SUBSCRIPTION_ENDPOINTS[kind]:
            raise ValueError("La suscripción usa su conector y endpoint fijo; no admite claves API ni routing alternativo.")
    elif auth == "subscription":
        raise ValueError("Este protocolo no es un conector de suscripción.")
    if auth == "none" and kind not in {"ollama", "openai-compatible"}:
        raise ValueError("Este protocolo requiere una clave API.")
    return {"provider": kind, "model": model.strip(), "endpoint": endpoint.rstrip("/"),
            "timeout": float(timeout), "max_tokens": maximum,
            "temperature": float(temperature), "auth": auth}


class ProviderRegistry:
    def __init__(self, secret_broker: SecretBroker, config_path: Path | None = None):
        self.secret_broker = secret_broker
        self.config_path = Path(config_path or state_home() / "config.yaml")
        self._configs = {}
        self._document = {}
        self._load_config()

    def _load_config(self) -> None:
        try:
            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {} if self.config_path.exists() else {}
        except (OSError, yaml.YAMLError):
            raise ValueError("No se pudo leer la configuración; no se modificó el archivo.") from None
        if not isinstance(data, dict) or not isinstance(data.get("providers", {}), dict):
            raise ValueError("La configuración de providers debe ser un mapa.")
        self._document = data
        self._configs = data.get("providers", {})

    def _save_config(self) -> None:
        self._document["providers"] = self._configs
        atomic_write(self.config_path, yaml.safe_dump(self._document, sort_keys=False))

    def add(self, name: str, provider_type: str, model: str, **kwargs) -> str:
        if provider_type in SUBSCRIPTION_ENDPOINTS and kwargs.get("api_key"):
            raise ValueError("No pegues claves API en un conector de suscripción.")
        config = validate_config(name, {"provider": provider_type, "model": model,
                                       **{k: v for k, v in kwargs.items() if k != "api_key"}})
        storage = None
        if kwargs.get("api_key"):
            storage = self.secret_broker.set(name, kwargs["api_key"])
        with state_lock(self.config_path.with_suffix(".lock")):
            self._load_config()
            self._configs[name] = config
            self._save_config()
        return storage or self.secret_broker.storage_status(name)

    def remove(self, name: str) -> bool:
        with state_lock(self.config_path.with_suffix(".lock")):
            self._load_config()
            if name not in self._configs:
                return False
            self.secret_broker.remove(name)
            del self._configs[name]
            self._save_config()
            return True

    def list(self) -> dict[str, dict]:
        self._load_config()
        fields = {"provider", "model", "endpoint", "timeout", "max_tokens", "temperature", "auth"}
        return {name: copy.deepcopy({k: v for k, v in cfg.items() if k in fields})
                for name, cfg in self._configs.items() if isinstance(cfg, dict)}

    def get_config(self, name: str, model: str | None = None) -> ProviderConfig:
        self._load_config()
        if name not in self._configs:
            raise ValueError("Selecciona un provider configurado en Providers.")
        config = dict(self._configs[name])
        if model is not None:
            config["model"] = model
        config = validate_config(name, config)
        return ProviderConfig(name=name, provider_type=config["provider"], model=config["model"],
                              endpoint=config["endpoint"], timeout=config["timeout"],
                              max_tokens=config["max_tokens"], temperature=config["temperature"],
                              auth=config["auth"])

    def get(self, name: str, model: str | None = None) -> BaseProvider:
        # AsyncClient must not survive an asyncio loop or a changed configuration.
        config = self.get_config(name, model)
        return self.from_config(config)

    def from_config(self, config: ProviderConfig) -> BaseProvider:
        """Create a loop-local client from the captured configuration of a turn."""
        if config.provider_type == "claude":
            raise ValueError("Usa el conector restringido claude-subscription o Anthropic API; el transporte Claude legado está deshabilitado.")
        if config.provider_type in SUBSCRIPTION_ENDPOINTS:
            return SubscriptionProvider(config, None)
        credentials = _TurnCredentials(config.name, self.secret_broker.get(config.name))
        return PROVIDER_MAP[config.provider_type](config, credentials)

    def has_key(self, name: str) -> bool:
        return self.secret_broker.has_key(name)

    def get_default_endpoint(self, provider_type: str) -> str:
        return DEFAULT_ENDPOINTS.get(provider_type, "")

    def list_provider_types(self) -> list[str]:
        return list(PROVIDER_MAP)
