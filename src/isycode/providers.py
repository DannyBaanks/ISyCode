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
# supports_tools describes the endpoint's function-calling protocol, not a
# guarantee for every hosted model. Tools remain filtered by Workspace Authority;
# users must select a tool-capable model (and llama.cpp chat template).
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
               "default_model": "llama3.1:8b", "supports_tools": True},
    "llamacpp": {"base_url": "http://127.0.0.1:8080/v1", "key_env": "LLAMACPP_API_KEY",
                 "label": "llama.cpp server (local)", "key_required": False,
                 "default_model": "local", "supports_tools": True},
    "lmstudio": {"base_url": "http://127.0.0.1:1234/v1", "key_env": "LMSTUDIO_API_KEY",
                 "label": "LM Studio", "key_required": False,
                 "default_model": "local", "supports_tools": True},
    "xai": {"base_url": "https://api.x.ai/v1", "key_env": "XAI_API_KEY",
            "label": "xAI Grok", "default_model": "grok-4", "supports_tools": True},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY",
                 "label": "DeepSeek", "default_model": "deepseek-chat", "supports_tools": True},
    "fireworks": {"base_url": "https://api.fireworks.ai/inference/v1",
                  "key_env": "FIREWORKS_API_KEY", "label": "Fireworks",
                  "default_model": "accounts/fireworks/models/llama-v3p1-70b-instruct"},
    "cerebras": {"base_url": "https://api.cerebras.ai/v1", "key_env": "CEREBRAS_API_KEY",
                 "label": "Cerebras", "default_model": "llama3.1-8b"},
    "huggingface": {"base_url": "https://router.huggingface.co/v1",
                    "key_env": "HF_TOKEN", "label": "Hugging Face",
                    "default_model": "meta-llama/Llama-3.1-8B-Instruct"},
    "moonshot": {"base_url": "https://api.moonshot.ai/v1", "key_env": "MOONSHOT_API_KEY",
                 "label": "Kimi / Moonshot", "default_model": "moonshot-v1-auto",
                 "supports_tools": True},
    "zai": {"base_url": "https://api.z.ai/api/coding/paas/v4", "key_env": "ZAI_API_KEY",
            "label": "Z.AI", "default_model": "glm-4.5"},
    "opencode": {"base_url": "https://opencode.ai/zen/v1", "key_env": "OPENCODE_API_KEY",
                 "label": "OpenCode Zen", "default_model": "gpt-5-nano"},
    "opencode-go": {"base_url": "https://opencode.ai/zen/go/v1", "key_env": "OPENCODE_API_KEY",
                    "label": "OpenCode Go", "default_model": "glm-5.3"},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "key_env": "MISTRAL_API_KEY",
                "label": "Mistral", "default_model": "mistral-small-latest",
                "supports_tools": True},
    "google": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "key_env": "GEMINI_API_KEY", "label": "Google AI Studio",
               "default_model": "gemini-2.5-flash"},
    "vercel": {"base_url": "https://ai-gateway.vercel.sh/v1", "key_env": "AI_GATEWAY_API_KEY",
               "label": "Vercel AI Gateway", "default_model": "openai/gpt-4o-mini"},
    "alibaba": {"base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "key_env": "DASHSCOPE_API_KEY", "label": "Qwen / DashScope",
                "default_model": "qwen-plus"},
    "venice": {"base_url": "https://api.venice.ai/api/v1", "key_env": "VENICE_API_KEY",
               "label": "Venice", "default_model": "llama-3.3-70b"},
    "scaleway": {"base_url": "https://api.scaleway.ai/v1", "key_env": "SCALEWAY_API_KEY",
                 "label": "Scaleway", "default_model": "llama-3.1-8b-instruct"},
    "deepinfra": {"base_url": "https://api.deepinfra.com/v1/openai",
                  "key_env": "DEEPINFRA_API_KEY", "label": "DeepInfra",
                  "default_model": "meta-llama/Meta-Llama-3.1-8B-Instruct"},
}


# Provider screen, in the order it is painted. A key that is absent from PRESETS
# is listed only: selecting it does not send traffic.
# group, key, label, blurb
PROVIDER_SCREEN: tuple[tuple[str, str, str, str], ...] = (
    ("popular", "nvidia", "NVIDIA NIM", "Nemotron via NVIDIA NIM"),
    ("popular", "openai", "OpenAI", "API key or ChatGPT subscription"),
    ("popular", "anthropic", "Anthropic", "Claude models via API key"),
    ("popular", "opencode", "OpenCode Zen", "OpenCode catalog, OpenAI-compatible"),
    ("popular", "opencode-go", "OpenCode Go", "OpenCode Go endpoint"),
    ("popular", "xai", "xAI Grok", "API key or Grok sign-in"),
    ("popular", "google", "Google AI Studio", "Gemini, OpenAI-compatible endpoint"),
    ("popular", "openrouter", "OpenRouter", "One key, many models"),
    ("providers", "groq", "Groq", "Fast OpenAI-compatible inference"),
    ("providers", "deepseek", "DeepSeek", "Direct API"),
    ("providers", "fireworks", "Fireworks", "Fireworks inference API"),
    ("providers", "cerebras", "Cerebras", "OpenAI-compatible inference"),
    ("providers", "mistral", "Mistral", "Direct API"),
    ("providers", "moonshot", "Kimi / Moonshot", "Moonshot OpenAI-compatible API"),
    ("providers", "zai", "Z.AI", "GLM coding endpoint"),
    ("providers", "alibaba", "Qwen / DashScope", "Alibaba compatible-mode API"),
    ("providers", "huggingface", "Hugging Face", "Router, OpenAI-compatible"),
    ("providers", "deepinfra", "DeepInfra", "OpenAI-compatible catalog"),
    ("providers", "vercel", "Vercel AI Gateway", "AI Gateway endpoint"),
    ("providers", "venice", "Venice", "OpenAI-compatible API"),
    ("providers", "scaleway", "Scaleway", "Scaleway Generative APIs"),
    ("providers", "nebius", "Nebius Token Factory", "Token Factory, OpenAI-compatible"),
    ("providers", "ollama", "Ollama", "Local server"),
    ("providers", "lmstudio", "LM Studio", "Local server on 127.0.0.1:1234"),
    ("providers", "llamacpp", "llama.cpp", "Local server on 127.0.0.1:8080"),
    ("providers", "", "GitHub Copilot", "No ISyCode transport yet"),
    ("providers", "", "Google Vertex AI", "No ISyCode transport yet"),
    ("providers", "", "AWS Bedrock", "No ISyCode transport yet"),
    ("providers", "", "Azure OpenAI", "No ISyCode transport yet"),
    ("providers", "", "NovitaAI", "No ISyCode transport yet"),
    ("providers", "", "Nous Portal", "No ISyCode transport yet"),
    ("providers", "", "MiniMax", "No ISyCode transport yet"),
    ("providers", "", "StepFun", "No ISyCode transport yet"),
    ("providers", "", "Xiaomi MiMo", "No ISyCode transport yet"),
    ("providers", "", "Tencent Hy", "No ISyCode transport yet"),
    ("providers", "", "Ollama Cloud", "No ISyCode transport yet"),
    ("providers", "", "Arcee", "No ISyCode transport yet"),
    ("providers", "", "302.AI", "No ISyCode transport yet"),
    ("providers", "", "Abacus", "No ISyCode transport yet"),
    ("providers", "", "Above.dev", "No ISyCode transport yet"),
    ("providers", "", "AgentRouter", "No ISyCode transport yet"),
    ("providers", "", "Cloudflare AI", "No ISyCode transport yet"),
    ("providers", "", "Cohere", "No ISyCode transport yet"),
    ("providers", "", "Perplexity", "No ISyCode transport yet"),
    ("providers", "", "Together AI", "No ISyCode transport yet"),
    ("providers", "", "Custom endpoint", "Set a preset, or ask for a base URL before one is added"),
)


# Models pinned to the top of the model picker. They are matched against the
# provider's live catalog (never invented): a pattern with no match is reported
# as missing from the account catalog.
FEATURED_MODELS: tuple[tuple[str, str], ...] = (
    ("GLM 5.3 Flash", r"glm[-_. ]?5[._]3(?![0-9]).*flash"),
    ("GLM 5.3", r"glm[-_. ]?5[._]3(?![0-9])(?!.*flash)"),
    ("Kimi K3", r"kimi[-_. ]?k3(?![0-9])"),
    ("DeepSeek V4.1 Flash", r"deepseek[-_. ]?v4[._]1(?![0-9]).*flash"),
)


def provider_base_url(name: str, base_url: str | None = None) -> str:
    """Resolve the transport endpoint without credentials or workspace grants."""
    preset = PRESETS[name]
    return (base_url or os.environ.get("ISYCODE_BASE_URL")
            or os.environ.get("ISYMOTRON_BASE_URL")
            or (os.environ.get("OLLAMA_HOST", "").rstrip("/") + "/v1"
                if name == "ollama" and os.environ.get("OLLAMA_HOST")
                else preset["base_url"])).rstrip("/")


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
        return {"version": 1, "provider": "", "models": {}, "slots": {}, "model_metadata": {}}
    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
        return {"version": 1, "provider": "", "models": {}, "slots": {}, "model_metadata": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"version": 1, "provider": "", "models": {}, "slots": {}, "model_metadata": {}}
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("provider"), str)
            or not isinstance(data.get("models"), dict)):
        return {"version": 1, "provider": "", "models": {}, "slots": {}, "model_metadata": {}}
    slots = data.get("slots", {})
    if not isinstance(slots, dict):
        slots = {}
    data["slots"] = slots
    metadata = data.get("model_metadata", {})
    data["model_metadata"] = metadata if isinstance(metadata, dict) else {}
    return data


def model_context_limit(provider: str, model: str) -> tuple[int | None, str]:
    """Return a validated model window and whether it came from a live catalog or user config."""
    provider_rows = _load_preferences()["model_metadata"].get(provider, {})
    entry = provider_rows.get(model) if isinstance(provider_rows, dict) else None
    if isinstance(entry, dict):
        limit = entry.get("context_window")
        if type(limit) is int and 0 < limit <= 10**9:
            source = entry.get("context_source")
            return limit, source if source in {"live-catalog", "user-config"} else "live-catalog"
    return None, "unknown"


def record_model_metadata(provider: str, model: str, entry: dict[str, Any]) -> None:
    """Persist bounded public model metadata outside the workspace; never store credentials."""
    if provider not in PRESETS or not isinstance(model, str) or not model or len(model) > 256:
        return
    raw = entry.get("context_length", entry.get("contextWindow", entry.get("context_window")))
    if type(raw) is not int or not 0 < raw <= 10**9:
        return
    data = _load_preferences()
    models = data["model_metadata"].setdefault(provider, {})
    if not isinstance(models, dict):
        models = {}
        data["model_metadata"][provider] = models
    if model not in models and sum(len(rows) for rows in data["model_metadata"].values()
                                   if isinstance(rows, dict)) >= 512:
        return
    models[model] = {"context_window": raw, "context_source": "live-catalog"}
    _write_preferences(data)


def _write_preferences(data: dict[str, Any]) -> None:
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


def child_model_choices() -> list[dict[str, str]]:
    """Models the user can assign to a child. Metadata only; no network, no keys."""
    choices = list(recent_models())
    saved = _load_preferences().get("models", {})
    for name, preset in PRESETS.items():
        if provider_credential_state(name) == "missing":
            continue
        model = saved.get(name) if isinstance(saved.get(name), str) else ""
        if not str(model).strip():
            model = str(preset.get("default_model") or provider_default_model(name) or "")
        model = model.strip()
        if not model or len(model) > 256 or any(ord(char) < 32 for char in model):
            continue
        identity = {"provider": name, "model": model}
        if identity not in choices:
            choices.append(identity)
    return choices[:24]


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
    data = {"version": 1, "provider": provider, "models": models,
            "recent_models": recent[:12], "slots": data.get("slots", {}),
            "model_metadata": data.get("model_metadata", {})}
    _write_preferences(data)


def model_slot(slot: str) -> dict[str, str] | None:
    """Return one optional model role; slots carry metadata, never authority."""
    if slot != "small":
        return None
    item = _load_preferences().get("slots", {}).get(slot)
    if (not isinstance(item, dict) or set(item) != {"provider", "model"}
            or item.get("provider") not in PRESETS
            or not isinstance(item.get("model"), str)
            or not 1 <= len(item["model"]) <= 256
            or any(ord(char) < 32 for char in item["model"])):
        return None
    return {"provider": item["provider"], "model": item["model"]}


def save_model_slot(slot: str, provider: str, model: str) -> None:
    """Persist a bounded non-secret model role in the same private preferences file."""
    provider = provider.casefold()
    model = model.strip()
    if slot != "small":
        raise ValueError("unknown model slot")
    if (provider not in PRESETS or not model or len(model) > 256
            or any(ord(char) < 32 for char in model)):
        raise ValueError("model slot selection is invalid")
    data = _load_preferences()
    slots = dict(data.get("slots", {}))
    slots[slot] = {"provider": provider, "model": model}
    data["slots"] = slots
    _write_preferences(data)


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward provider authorization headers to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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


def resolved_chat_model(provider_name: str | None = None) -> str:
    """Model a chat request should use for this provider.

    A saved selection wins over the catalog default. ``ISYCODE_MODEL`` and
    ``ISYMOTRON_MODEL`` apply only to the active provider, the same rule as
    ``selected_model_name``. Passing ``provider_default_model`` into
    ``Provider`` skips that saved selection because the NVIDIA default is
    always truthy.
    """
    name = (provider_name or selected_provider_name()).casefold()
    if name == selected_provider_name():
        saved = selected_model_name().strip()
    else:
        saved = ""
        try:
            value = _load_preferences().get("models", {}).get(name, "")
            if isinstance(value, str):
                saved = value.strip()
        except (AttributeError, OSError, ValueError):
            saved = ""
    if saved:
        return saved
    preset = PRESETS.get(name, {})
    return (provider_default_model(name)
            or str(preset.get("default_model") or "")
            or DEFAULT_MODEL)


def load_provider_key(name: str) -> str:
    """Prefer a named ISyCode key; keep environment/legacy stores as fallback."""
    if name == "chatgpt":
        return ""
    if name == "xai":
        from isycode.grok_session import access_token, xai_auth_mode
        if xai_auth_mode() == "session":
            return access_token()
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
    if provider == "xai":
        from isycode.grok_session import status as grok_status, xai_auth_mode
        if xai_auth_mode() == "session" and grok_status() == "signed-in":
            return "signed-in"
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
        self.base_url = provider_base_url(self.name, base_url)
        if (self.name == "xai" and base_url is None
                and not os.environ.get("ISYCODE_BASE_URL")
                and not os.environ.get("ISYMOTRON_BASE_URL")):
            from isycode.grok_session import session_transport
            session_url = session_transport()
            if session_url:
                self.base_url = session_url
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
        from isycode.reasoning_options import effective_reasoning
        self.reasoning_effort = effective_reasoning(self.name, self.model, preset.get("reasoning_effort"))
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
        from isycode.egress import EgressDenied, review_destination
        try:
            review_destination(self.base_url)
        except EgressDenied as exc:
            raise ProviderError(str(exc), transport=True) from exc
        if PRESETS[self.name].get("api") == "anthropic":
            from isycode.anthropic_provider import list_models

            return list_models(self.api_key, self.base_url)
        request = urllib.request.Request(
            self.base_url + "/models", headers=self._headers(), method="GET")
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), _RejectRedirectHandler)
            with opener.open(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read(2_000_001))
        except urllib.error.HTTPError as exc:
            raise ProviderError("provider model catalog request failed", exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderError("provider model catalog is unavailable", transport=True) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ProviderError("provider returned an invalid model catalog")
        from isycode.reasoning_options import record_catalog
        from isycode.providers import record_model_metadata
        for item in payload["data"]:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                record_catalog(self.name, item["id"], item)
                record_model_metadata(self.name, item["id"], item)
                from isycode.image_attachments import record_image_capability
                record_image_capability(self.name, item["id"], item)
        return sorted(item["id"] for item in payload["data"]
                      if isinstance(item, dict) and isinstance(item.get("id"), str))

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


__all__ = ["DEFAULT_MODEL", "FEATURED_MODELS", "PRESETS", "PROVIDER_SCREEN",
           "Provider", "ProviderError", "featured_models",
           "load_provider_key", "model_context_limit", "provider_credential_state",
           "record_model_metadata",
           "save_provider_selection", "selected_model_name", "selected_provider_name"]
