"""The model GUS talks to (ADR 0011, MK2): a user-level slot, never authority.

GUS uses another provider or a local model through the per-provider keys that
already exist (D2): the slot stores only a provider and a model id. A model
whose window is known to be below 32k tokens cannot hold GUS's fixed context,
and one the catalog marks without tool calls cannot edit, so neither can be
assigned. A model with an unknown window is allowed but planned as 32k until
its real window is known. An empty slot never falls back to the chat model.
"""
from __future__ import annotations

from dataclasses import dataclass

from isycode.model_catalog import catalog_models
from isycode.providers import (
    PRESETS, Provider, custom_models, load_provider_key, model_context_limit, model_slot,
    provider_credential_state, provider_supports_tools, resolved_chat_model, save_model_slot)

SLOT = "gus"
MIN_CONTEXT_TOKENS = 32_000
# An unknown window is planned as the floor, never as a large default: a local
# server configured for less would truncate or reject GUS's requests.
UNKNOWN_WINDOW_PLAN_TOKENS = MIN_CONTEXT_TOKENS
MAX_MODEL_CHOICES = 40
# Usable without asking for anything new: a key the user already gave, or none needed.
READY_CREDENTIALS = frozenset({"saved", "environment", "session", "signed-in", "optional"})
# Bridges to a chat product rather than a model endpoint GUS can drive with tools.
EXCLUDED_PROVIDERS = frozenset({"isyco-web"})


class GusSlotError(ValueError):
    """The GUS slot is empty, or a model cannot serve GUS."""


@dataclass(frozen=True)
class GusModelCheck:
    allowed: bool
    window: int | None
    source: str
    reason: str = ""


def _catalog_entry(provider: str, model: str) -> dict | None:
    return next((row for row in catalog_models(provider) if row.get("id") == model), None)


def model_window(provider: str, model: str) -> tuple[int | None, str]:
    """Known context window in tokens and where it came from, else (None, "unknown")."""
    window, source = model_context_limit(provider, model)
    if window is not None:
        return window, source
    entry = _catalog_entry(provider, model)
    context = entry.get("context") if entry else None
    if type(context) is int and context > 0:
        return context, "catalog"
    return None, "unknown"


def check_gus_model(provider: str, model: str) -> GusModelCheck:
    """Whether this model can serve GUS, and why not."""
    if provider not in PRESETS or provider in EXCLUDED_PROVIDERS \
            or PRESETS[provider].get("api") == "codex":
        return GusModelCheck(False, None, "unknown", "GUS cannot use this provider.")
    if not provider_supports_tools(provider):
        return GusModelCheck(False, None, "unknown",
                             "Tool calls are off for this provider; GUS needs them to edit.")
    entry = _catalog_entry(provider, model)
    if entry is not None and entry.get("tool_call") is False:
        return GusModelCheck(False, None, "catalog", "This model has no tool calls; GUS needs them to edit.")
    window, source = model_window(provider, model)
    if window is not None and window < MIN_CONTEXT_TOKENS:
        return GusModelCheck(False, window, source,
                             "Window below 32k tokens: GUS's fixed context would not fit.")
    return GusModelCheck(True, window, source)


def planning_window(check: GusModelCheck) -> int:
    """The window GUS budgets its requests against."""
    return check.window if check.window is not None else UNKNOWN_WINDOW_PLAN_TOKENS


def gus_providers() -> list[str]:
    """Providers GUS can use now with the credentials the user already set up."""
    return [name for name in PRESETS
            if name not in EXCLUDED_PROVIDERS and PRESETS[name].get("api") != "codex"
            and provider_credential_state(name) in READY_CREDENTIALS]


def gus_model_choices(provider: str) -> list[str]:
    """Catalog, typed and currently selected model ids for one provider, without repeats."""
    ids = [row["id"] for row in catalog_models(provider)]
    ids += custom_models(provider)
    ids.append(resolved_chat_model(provider))
    return list(dict.fromkeys(item for item in ids if item))[:MAX_MODEL_CHOICES]


def save_gus_model(provider: str, model: str) -> GusModelCheck:
    """Assign the GUS slot after checking the model; raise instead of saving a bad one."""
    check = check_gus_model(provider, model)
    if not check.allowed:
        raise GusSlotError(check.reason)
    save_model_slot(SLOT, provider, model)
    return check


def gus_model() -> dict[str, str] | None:
    return model_slot(SLOT)


def gus_provider() -> Provider:
    """The provider GUS talks to; never the chat model when the slot is empty."""
    slot = gus_model()
    if slot is None:
        raise GusSlotError("GUS has no model yet. Choose one in Settings → GUS model.")
    check = check_gus_model(slot["provider"], slot["model"])
    if not check.allowed:
        raise GusSlotError(check.reason)
    return Provider(name=slot["provider"], model=slot["model"],
                    api_key=load_provider_key(slot["provider"]) or None)


__all__ = ["GusModelCheck", "GusSlotError", "MIN_CONTEXT_TOKENS", "UNKNOWN_WINDOW_PLAN_TOKENS",
           "check_gus_model", "gus_model", "gus_model_choices", "gus_provider", "gus_providers",
           "model_window", "planning_window", "save_gus_model"]
