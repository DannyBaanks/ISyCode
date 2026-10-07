"""Provider/model capabilities and session-scoped reasoning selections.

Catalog metadata wins. Documented fallback profiles are deliberately narrow;
unknown models retain their provider default rather than invented effort levels.
"""
import os

_CATALOG: dict[tuple[str, str], tuple[str, ...]] = {}
_CATALOG_DEFAULTS: dict[tuple[str, str], str] = {}
_STEERING_OBSERVED: dict[tuple[str, str], bool] = {}
_STEERING: dict[tuple[str, str], bool] = {}
_SELECTIONS: dict[tuple[str, str], str] = {}
_ALLOWED = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "on", "off"})


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
    if (provider, model) in _CATALOG:
        return _CATALOG[(provider, model)]
    if provider == "nvidia" and model == "nvidia/nemotron-3-ultra-550b-a55b":
        return ("off", "on")
    if provider == "anthropic":
        from isycode.anthropic_provider import ADAPTIVE_THINKING_MODELS
        if model in ADAPTIVE_THINKING_MODELS:
            if model in {"claude-opus-4-6", "claude-sonnet-4-6"}:
                return ("low", "medium", "high", "max")
            return ("low", "medium", "high", "xhigh", "max")
    # This chat transport uses tools; Luna's Chat Completions tool calls
    # support only none (Responses API exposes the other effort levels).
    if provider == "openai" and model == "gpt-6-luna":
        return ("none",)
    return ()


def select_reasoning(provider: str, model: str, level: str) -> None:
    if level != "default" and level not in reasoning_levels(provider, model):
        raise ValueError("reasoning level is not offered for this provider/model")
    _SELECTIONS[(provider, model)] = level


def effective_reasoning(provider: str, model: str, default: str | None = None) -> str | None:
    if provider == "openai" and model == "gpt-6-luna":
        default = "none"
    default = _CATALOG_DEFAULTS.get((provider, model), default)
    choice = _SELECTIONS.get((provider, model))
    if choice is not None:
        return default if choice == "default" else choice
    return (os.environ.get("ISYCODE_REASONING_EFFORT")
            or os.environ.get("ISYMOTRON_REASONING_EFFORT") or default)


def reasoning_label(provider: str, model: str, default: str | None = None) -> str:
    return effective_reasoning(provider, model, default) or "Default"


def thinking_options(provider: str, model: str, effort: str | None) -> dict | None:
    if provider == "nvidia" and model == "nvidia/nemotron-3-ultra-550b-a55b" and effort in {"on", "off"}:
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
