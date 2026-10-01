"""ISyCode's OpenAI-compatible provider catalog and transport metadata.

This is the chat-facing provider seam. IsyMotron may still offer a separate
planner/runtime, but importing or using this catalog does not require it.
"""
from __future__ import annotations

from pathlib import Path

import json
import os
import secrets
import stat
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from isycode.config import credential_state, load_api_key, provider_default_model


DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
PRESETS: dict[str, dict[str, Any]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY",
               "label": "OpenAI API", "default_model": "gpt-6-luna",
               "supports_tools": True,
               "token_limit_field": "max_completion_tokens", "reasoning_effort": "medium"},
    "chatgpt": {"base_url": "https://chatgpt.com/backend-api/codex", "key_env": "",
                "label": "ChatGPT subscription (Codex)", "default_model": "auto",
                "key_required": False, "supports_tools": True, "api": "codex",
                "auth_hosts": ["auth.openai.com", "chatgpt.com"]},
    "nvidia": {"base_url": "https://integrate.api.nvidia.com/v1",
               "key_env": "NVIDIA_NIM_API_KEY", "label": "NVIDIA NIM",
               "supports_tools": True},
    "nebius": {"base_url": "https://api.tokenfactory.us-central1.nebius.com/v1",
               "key_env": "NEBIUS_API_KEY", "label": "Nebius Token Factory",
               "supports_tools": True},
    "groq": {"base_url": "https://api.groq.com/openai/v1",
             "key_env": "GROQ_API_KEY", "label": "Groq",
             "default_model": "openai/gpt-oss-120b", "supports_tools": True},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",
                   "key_env": "OPENROUTER_API_KEY", "label": "OpenRouter",
                   "default_model": "openai/gpt-oss-120b"},
    # Native Messages API (optional `anthropic` SDK), not an OpenAI-compatible endpoint.
    "anthropic": {"base_url": "https://api.anthropic.com", "key_env": "ANTHROPIC_API_KEY",
                  "label": "Anthropic (Claude)", "default_model": "claude-opus-5-5",
                  "supports_tools": True, "api": "anthropic", "reasoning_effort": "medium"},
    "ollama": {"base_url": "http://127.0.0.1:11434/v1", "key_env": "OLLAMA_API_KEY",
               "label": "Ollama (local)", "key_required": False,
               "default_model": "llama3.1:8b"},
    "llamacpp": {"base_url": "http://127.0.0.1:8080/v1", "key_env": "LLAMACPP_API_KEY",
                 "label": "llama.cpp server (local)", "key_required": False,
                 "default_model": "local"},
}


# Models pinned to the top of the model picker. They are matched against the
# provider's live catalog (never invented): a pattern with no match is reported
# as missing from the account catalog.
FEATURED_MODELS: tuple[tuple[str, str], ...] = (
    ("GLM 5.3 Flash", r"glm[-_. ]?5[._]3(?![0-9]).*flash"),
    ("GLM 5.3", r"glm[-_. ]?5[._]3(?![0-9])(?!.*flash)"),
    ("Kimi K3", r"kimi[-_. ]?k3(?![0-9])"),
    ("DeepSeek V4.1 Flash", r"deepseek[-_. ]?v4[._]1(?![0-9]).*flash"),
)


def featured_models(catalog: list[str]) -> list[tuple[str, str | None]]:
    """(label, matching model id or None) for each featured model, in order."""
    import re

    result = []
    for label, pattern in FEATURED_MODELS:
        matcher = re.compile(pattern, re.IGNORECASE)
        found = sorted((model for model in catalog if matcher.search(model)), key=len)
        result.append((label, found[0] if found else None))
    return result


def _preferences_path():
    from isycode.workspace_setup import state_root
    directory = state_root() / "preferences"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink() or not directory.is_dir():
        raise OSError("ISyCode preferences directory is unsafe")
    if os.name == "posix":
        directory.chmod(0o700)
    return directory / "provider.json"


def _load_preferences() -> dict[str, Any]:
    path = _preferences_path()
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"version": 1, "provider": "", "models": {}}
    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
        return {"version": 1, "provider": "", "models": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"version": 1, "provider": "", "models": {}}
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("provider"), str)
            or not isinstance(data.get("models"), dict)):
        return {"version": 1, "provider": "", "models": {}}
    return data


def recent_models() -> list[dict[str, str]]:
    """Registered model identities; metadata only, never credentials or grants."""
    data = _load_preferences()
    candidates = data.get("recent_models", [])
    if not isinstance(candidates, list):
        candidates = []
    candidates = candidates + [{"provider": key, "model": value} for key, value in data["models"].items()]
    result = []
    for item in candidates:
        if (not isinstance(item, dict) or not isinstance(item.get("provider"), str) or item.get("provider") not in PRESETS
                or not isinstance(item.get("model"), str) or not item["model"].strip()
                or len(item["model"]) > 256 or any(ord(char) < 32 for char in item["model"])):
            continue
        identity = {"provider": item["provider"], "model": item["model"]}
        if identity not in result:
            result.append(identity)
    return result[:12]


def save_provider_selection(name: str, model: str) -> None:
    """Persist non-secret provider/model selection in private user state."""
    provider, selected_model = name.casefold(), model.strip()
    if provider not in PRESETS or not selected_model or len(selected_model) > 256:
        raise ValueError("provider selection is invalid")
    data = _load_preferences()
    models = {key: value for key, value in data["models"].items()
              if isinstance(key, str) and isinstance(value, str) and len(value) <= 256}
    models[provider] = selected_model
    identity = {"provider": provider, "model": selected_model}
    recent = [identity] + [item for item in recent_models() if item != identity]
    data = {"version": 1, "provider": provider, "models": models, "recent_models": recent[:12]}
    path = _preferences_path()
    temporary = path.with_name(".provider-" + secrets.token_hex(8) + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str = "",
                 attempts: int = 1, transport: bool = False):
        super().__init__(message)
        self.status = status
        self.body = body
        self.attempts = attempts
        self.transport = transport


def selected_provider_name() -> str:
    explicit = os.environ.get("ISYCODE_PROVIDER", "").strip()
    if explicit:
        return explicit.casefold()
    try:
        saved = _load_preferences().get("provider", "")
        if saved in PRESETS:
            return saved
    except (OSError, ValueError):
        pass
    return os.environ.get("ISYMOTRON_PROVIDER", "nebius").casefold()


def selected_model_name() -> str:
    explicit = os.environ.get("ISYCODE_MODEL", "").strip()
    if explicit:
        return explicit
    try:
        saved = _load_preferences().get("models", {}).get(selected_provider_name(), "")
        if isinstance(saved, str):
            return saved
    except (AttributeError, OSError, ValueError):
        pass
    return os.environ.get("ISYMOTRON_MODEL", "")


def load_provider_key(name: str) -> str:
    """Prefer a named ISyCode key; keep environment/legacy stores as fallback."""
    if name == "chatgpt":
        return ""
    from isycode.credentials import read_saved_secret

    # Saved keys are read only through the registered reader (Security mode:
    # one Authority/Sentinel decision and receipt per read). Environment and
    # legacy provider stores remain supported without logging keys.
    value = read_saved_secret(name, "provider.request")
    return value or load_api_key(name)


def provider_credential_state(name: str) -> str:
    """Return key presence for the selector without exposing the key value."""
    provider = name.casefold()
    preset = PRESETS.get(provider)
    if preset is None:
        return "unavailable"
    if preset.get("api") == "codex":
        return "subscription"
    if not preset.get("key_required", True):
        return "optional"
    key_env = preset["key_env"]
    active = selected_provider_name()
    if os.environ.get(key_env, "").strip():
        return "environment"
    if provider == active and os.environ.get("ISYMOTRON_API_KEY", "").strip():
        return "environment"
    vault_error = False
    try:
        from isycode.credentials import CredentialVault, CredentialVaultError, saved_secret_exists
        try:
            CredentialVault()
        except CredentialVaultError:
            vault_error = True
        else:
            # Presence comes from metadata; showing "saved" never reads the secret.
            if saved_secret_exists(provider):
                return "saved"
    except Exception:
        vault_error = True
    # Preserve explicit env/legacy-store migrations while keeping the new
    # ISyCode vault as the first-party source of truth for newly saved keys.
    legacy = credential_state(provider)
    if legacy != "missing":
        return legacy
    return "unavailable" if vault_error else "missing"


class Provider:
    """Metadata and model discovery for an OpenAI chat-completions endpoint."""

    def __init__(self, name: str | None = None, model: str | None = None,
                 base_url: str | None = None, api_key: str | None = None,
                 timeout_s: float = 60.0):
        self.name = (name or selected_provider_name()).casefold()
        preset = PRESETS.get(self.name)
        if preset is None:
            raise ProviderError(f"unknown provider {self.name!r}")
        self.label = preset["label"]
        self.base_url = (base_url or os.environ.get("ISYCODE_BASE_URL")
                         or os.environ.get("ISYMOTRON_BASE_URL")
                         or (os.environ.get("OLLAMA_HOST", "").rstrip("/") + "/v1"
                             if self.name == "ollama" and os.environ.get("OLLAMA_HOST")
                             else preset["base_url"])).rstrip("/")
        self.model = (model or selected_model_name()
                      or provider_default_model(self.name)
                      or preset.get("default_model") or DEFAULT_MODEL)
        self.connector_identity = None
        if preset.get("api") == "codex":
            from isycode.provider_auth import CHATGPT_ENDPOINT, connector_identity
            try:
                self.connector_identity = connector_identity()
            except (ValueError, OSError) as exc:
                raise ProviderError("Official Codex CLI is required for ChatGPT subscription login") from exc
            self.base_url = CHATGPT_ENDPOINT
        self.key_env = preset["key_env"]
        self.key_required = preset.get("key_required", True)
        self.supports_tools = bool(preset.get("supports_tools", False))
        self.api_key = "" if preset.get("api") == "codex" else (api_key if api_key is not None else load_provider_key(self.name))
        self.token_limit_field = preset.get("token_limit_field", "max_tokens")
        self.reasoning_effort = (os.environ.get("ISYCODE_REASONING_EFFORT")
                                 or os.environ.get("ISYMOTRON_REASONING_EFFORT")
                                 or preset.get("reasoning_effort"))
        self.temperature_supported = not (
            self.name == "openai" and self.reasoning_effort not in (None, "none")
        )
        self.timeout_s = max(1.0, min(float(timeout_s), 180.0))
        if (self.api_key and self.base_url.startswith("http://")
                and (urllib.parse.urlsplit(self.base_url).hostname or "") not in
                {"localhost", "127.0.0.1", "::1", "[::1]"}):
            raise ProviderError("refusing to send an API key over plain HTTP to a remote host")

    def configured(self) -> bool:
        return bool(self.api_key) or not self.key_required

    def models(self) -> list[str]:
        if PRESETS[self.name].get("api") == "codex":
            import asyncio
            from isycode.codex_connector import CodexConnector
            async def catalog():
                async with CodexConnector(self.connector_identity["executable"],
                                          Path(self.connector_identity["home"])) as connector:
                    return await connector.models()
            return asyncio.run(catalog())
        if not self.configured():
            raise ProviderError(f"no credential configured for {self.name}")
        if PRESETS[self.name].get("api") == "anthropic":
            from isycode.anthropic_provider import list_models

            return list_models(self.api_key, self.base_url)
        request = urllib.request.Request(
            self.base_url + "/models", headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read(2_000_001))
        except urllib.error.HTTPError as exc:
            raise ProviderError("provider model catalog request failed", exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderError("provider model catalog is unavailable", transport=True) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ProviderError("provider returned an invalid model catalog")
        return sorted(item["id"] for item in payload["data"]
                      if isinstance(item, dict) and isinstance(item.get("id"), str))

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


__all__ = ["DEFAULT_MODEL", "FEATURED_MODELS", "PRESETS", "Provider", "ProviderError",
           "featured_models",
           "load_provider_key", "provider_credential_state",
           "save_provider_selection", "selected_model_name", "selected_provider_name"]
