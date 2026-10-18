"""Provider/model capabilities and session-scoped reasoning selections.

Uses Hermes-style declared profiles, canonical effort ladder, and wire clamping.
Live catalog metadata wins; documented provider profiles and vendored catalog
metadata provide decision-grade reasoning levels without guessing on unknown models.
"""
from __future__ import annotations

import os
from typing import Sequence

_CATALOG: dict[tuple[str, str], tuple[str, ...]] = {}
_CATALOG_DEFAULTS: dict[tuple[str, str], str] = {}
_STEERING_OBSERVED: dict[tuple[str, str], bool] = {}
_STEERING: dict[tuple[str, str], bool] = {}
_SELECTIONS: dict[tuple[str, str], str] = {}
_ALLOWED = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "on", "off"})

EFFORT_LADDER: tuple[str, ...] = ("none", "off", "minimal", "low", "on", "medium", "high", "xhigh", "max", "ultra")

# Declared provider/family profiles based on Hermes (agent/reasoning_effort.py)
DEEPSEEK_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "max")
GLM53_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "max")
GLM52_EFFORTS: tuple[str, ...] = ("high", "max")
KIMI_K3_EFFORTS: tuple[str, ...] = ("low", "high", "max")
KIMI_K2_EFFORTS: tuple[str, ...] = ("low", "medium", "high")
NEMOTRON_ULTRA_EFFORTS: tuple[str, ...] = ("off", "on")
GPT_OSS_EFFORTS: tuple[str, ...] = ("low", "medium", "high")
QWEN_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "max")
OPENAI_EFFORTS: tuple[str, ...] = ("none", "low", "medium", "high", "xhigh", "max")
MINIMAX_EFFORTS: tuple[str, ...] = ("low", "medium", "high")
GEMINI_EFFORTS: tuple[str, ...] = ("low", "medium", "high")
XAI_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh")


def model_overrides(model: str) -> dict[str, str]:
    m = model.casefold()
    if "kimi" in m and "k3" in m:
        return {"medium": "high", "xhigh": "max"}
    if any(k in m for k in ("glm", "deepseek", "qwen")):
        return {"xhigh": "max"}
    return {}


def clamp_effort(
    effort: str | None,
    supported: Sequence[str] | None,
    overrides: dict[str, str] | None = None,
) -> str | None:
    """Clamp a requested reasoning effort onto a wire's supported levels (Hermes policy)."""
    requested = str(effort or "").strip().lower()
    if not requested or not supported:
        return effort
    supported_norm = [lvl for lvl in (str(s).strip().lower() for s in supported) if lvl in EFFORT_LADDER]
    if not supported_norm or requested in supported_norm:
        return effort
    if overrides and overrides.get(requested) in supported_norm:
        return overrides[requested]
    if requested not in EFFORT_LADDER:
        return effort
    candidates = [lvl for lvl in supported_norm if lvl not in {"none", "off"}]
    if not candidates:
        return effort
    requested_idx = EFFORT_LADDER.index(requested)
    below = [lvl for lvl in candidates if EFFORT_LADDER.index(lvl) < requested_idx]
    return max(below, key=EFFORT_LADDER.index) if below else min(candidates, key=EFFORT_LADDER.index)


def record_catalog(provider: str, model: str, entry: dict) -> None:
    supported = entry.get("supportsSteering")
    if isinstance(supported, bool):
        _STEERING[(provider, model)] = supported
    else:
        _STEERING.pop((provider, model), None)
    values = entry.get("supportedReasoningEfforts")
    if not isinstance(values, list):
        return
    levels = tuple(dict.fromkeys(item.get("reasoningEffort") for item in values
                   if isinstance(item, dict) and item.get("reasoningEffort") in _ALLOWED))
    _CATALOG[(provider, model)] = levels
    default = entry.get("defaultReasoningEffort")
    if default in levels:
        _CATALOG_DEFAULTS[(provider, model)] = default


def reasoning_levels(provider: str, model: str) -> tuple[str, ...]:
    key = (provider, model)
    if key in _CATALOG:
        return _CATALOG[key]

    m = model.casefold()

    if "nemotron-3-ultra" in m:
        return NEMOTRON_ULTRA_EFFORTS

    if provider == "anthropic":
        from isycode.anthropic_provider import ADAPTIVE_THINKING_MODELS
        if model in ADAPTIVE_THINKING_MODELS:
            if model in {"claude-opus-4-6", "claude-sonnet-4-6"}:
                return ("low", "medium", "high", "max")
            return ("low", "medium", "high", "xhigh", "max")
        return ()

    if provider == "openai" and model == "gpt-6-luna":
        return ("none",)

    if provider in {"openai", "chatgpt"}:
        if any(token in m for token in ("gpt-5.6", "gpt-6", "sol", "o3", "o4", "gpt-oss")):
            return OPENAI_EFFORTS

    if "glm-5.2" in m:
        return GLM52_EFFORTS
    if "glm-5" in m or "glm-zero" in m:
        return GLM53_EFFORTS

    if ("kimi" in m and "k3" in m) or m.endswith("k3"):
        return KIMI_K3_EFFORTS
    if "kimi" in m:
        return KIMI_K2_EFFORTS

    if "deepseek" in m and any(k in m for k in ("v4", "r1", "flash", "pro", "coder", "reasoner")):
        return DEEPSEEK_EFFORTS

    if "gpt-oss" in m:
        return GPT_OSS_EFFORTS

    if any(k in m for k in ("qwq", "qwen3", "qwen2.5-max")):
        return QWEN_EFFORTS

    if "minimax" in m:
        return MINIMAX_EFFORTS

    if "grok" in m and any(k in m for k in ("4", "beta", "reason")):
        return XAI_EFFORTS

    if any(k in m for k in ("gemini-2", "gemini-3", "gemini-4")):
        return GEMINI_EFFORTS

    # Snapshot fallback: if models.dev catalog specifically marks reasoning: True
    from isycode.model_card import catalog_entry
    entry = catalog_entry(provider, model)
    if entry and entry.get("reasoning") is True:
        return ("low", "medium", "high", "max")

    return ()


def selected_reasoning(provider: str, model: str) -> str | None:
    """The level chosen this session for exactly this model, if any."""
    return _SELECTIONS.get((provider, model))


def select_reasoning(provider: str, model: str, level: str) -> None:
    if level != "default" and level not in reasoning_levels(provider, model):
        raise ValueError("reasoning level is not offered for this provider/model")
    _SELECTIONS[(provider, model)] = level


def effective_reasoning(provider: str, model: str, default: str | None = None) -> str | None:
    if provider == "openai" and model == "gpt-6-luna":
        default = "none"
    default = _CATALOG_DEFAULTS.get((provider, model), default)
    choice = _SELECTIONS.get((provider, model))
    val = default if choice == "default" else (choice if choice is not None else (
        os.environ.get("ISYCODE_REASONING_EFFORT")
        or os.environ.get("ISYMOTRON_REASONING_EFFORT") or default
    ))
    levels = reasoning_levels(provider, model)
    if levels and val in EFFORT_LADDER:
        return clamp_effort(val, levels, model_overrides(model))
    return val


def reasoning_label(provider: str, model: str, default: str | None = None) -> str:
    return effective_reasoning(provider, model, default) or "Default"


def thinking_options(provider: str, model: str, effort: str | None) -> dict | None:
    m = model.casefold()
    if provider == "nvidia" and "nemotron-3-ultra" in m and effort in {"on", "off"}:
        return {"enable_thinking": effort == "on"}
    return None


def steering_support(provider: str, model: str) -> bool | None:
    """Observed support is advisory; provider execution still uses existing owners."""
    key = (provider, model)
    if _STEERING.get(key) is False:
        return False
    from isycode.capability_observations import observed
    learned = observed(provider, model, "steer")
    return _STEERING_OBSERVED.get(key, learned if learned is not None else _STEERING.get(key))


def steering_models() -> tuple[tuple[str, str], ...]:
    from isycode.capability_observations import supported_models
    keys = set(_STEERING) | set(_STEERING_OBSERVED) | set(supported_models("steer"))
    return tuple(sorted(key for key in keys if steering_support(*key) is True))


def record_steering_result(provider: str, model: str, supported: bool):
    _STEERING_OBSERVED[(provider, model)] = supported
    from isycode.capability_observations import record
    record(provider, model, "steer", supported)

