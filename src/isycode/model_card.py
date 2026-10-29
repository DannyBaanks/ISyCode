"""Decision-grade facts about one provider/model, each with where it came from.

Only facts ISyCode already holds are shown: the live account catalog (context
windows it reported), the vendored models.dev snapshot (offline; not verified
against the account), the reasoning levels ISyCode knows how to send, its own
tool transport, and capability observations measured on this machine. Nothing
is derived or guessed: a field without a source reads "Unknown" or "Not
reported", and the catalog entry is matched by exact model id only.
"""
from __future__ import annotations

from dataclasses import dataclass

# Source labels shown in the card (compact provenance).
LIVE = "Account catalog"
SNAPSHOT = "models.dev snapshot"
CONFIGURED = "Configured"
MEASURED = "Measured"
ISYCODE = "ISyCode"
UNKNOWN = "Unknown"


@dataclass(frozen=True)
class Fact:
    label: str
    value: str
    source: str


def catalog_entry(provider: str, model: str) -> dict | None:
    """The models.dev snapshot row for exactly this id (case-insensitive), or None."""
    from isycode.model_catalog import catalog_models

    wanted = model.casefold()
    return next((row for row in catalog_models(provider)
                 if isinstance(row.get("id"), str) and row["id"].casefold() == wanted), None)


def _tokens(value: int) -> str:
    if value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{value // 1_000_000}M tokens"
    if value >= 1000:
        return f"{round(value / 1000):,}K tokens"
    return f"{value:,} tokens"


def _price(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return f"${value:,.2f} / 1M tokens"


def model_facts(provider: str, model: str) -> list[Fact]:
    """Ordered facts for the detail card. Every value names its source."""
    from isycode.capability_observations import observed
    from isycode.model_presentation import model_display_name
    from isycode.providers import PRESETS, model_context_limit, provider_supports_tools
    from isycode.reasoning_options import reasoning_levels

    preset = PRESETS.get(provider, {})
    entry = catalog_entry(provider, model)
    facts = [
        Fact("Model", model_display_name(model), ISYCODE),
        Fact("Provider", str(preset.get("label", provider)), CONFIGURED),
        Fact("Model ID", model, CONFIGURED),
    ]
    if entry and isinstance(entry.get("family"), str) and entry["family"]:
        facts.append(Fact("Family", entry["family"], SNAPSHOT))

    limit, source = model_context_limit(provider, model)
    if limit:
        facts.append(Fact("Context", _tokens(limit), LIVE if source == "live-catalog" else CONFIGURED))
    elif entry and type(entry.get("context")) is int and entry["context"] > 0:
        facts.append(Fact("Context", _tokens(entry["context"]), SNAPSHOT))
    else:
        facts.append(Fact("Context", "Unknown", UNKNOWN))

    levels = reasoning_levels(provider, model)
    if levels:
        facts.append(Fact("Reasoning", " · ".join(level.capitalize() for level in levels), ISYCODE))
    elif entry and type(entry.get("reasoning")) is bool:
        facts.append(Fact("Reasoning", "Yes (no selectable levels)" if entry["reasoning"] else "No",
                          SNAPSHOT))
    else:
        facts.append(Fact("Reasoning", "Unknown", UNKNOWN))

    if entry and type(entry.get("tool_call")) is bool:
        facts.append(Fact("Tools (model)", "Yes" if entry["tool_call"] else "No", SNAPSHOT))
    facts.append(Fact("Tools (route)", "Sent by ISyCode" if provider_supports_tools(provider)
                      else "Not sent by ISyCode for this provider", ISYCODE))

    price_in = _price(entry.get("cost_in")) if entry else None
    price_out = _price(entry.get("cost_out")) if entry else None
    if price_in or price_out:
        facts.append(Fact("Input", price_in or "Not reported", SNAPSHOT))
        facts.append(Fact("Output", price_out or "Not reported", SNAPSHOT))
        facts.append(Fact("Cached input", "Not reported", UNKNOWN))
    else:
        facts.append(Fact("Pricing", "Unavailable", UNKNOWN))

    available = observed(provider, model, "chat_available")
    if available is not None:
        facts.append(Fact("Chat on this machine", "Worked" if available else "Failed", MEASURED))
    return facts


__all__ = ["Fact", "catalog_entry", "model_facts"]
