"""Offline models.dev catalog snapshot for the model picker.

The snapshot is vendored (scripts/vendor_modelsdev.py) and validated on
load: it augments the hardcoded presets with maintained model lists and
metadata, and it never fetches at runtime. The provider's live account
catalog, when loaded, always wins over this snapshot.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent / "assets" / "modelsdev-catalog.json"
FORMAT = "isycode.modelsdev-catalog.v1"


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, list[dict]]:
    """Validated vendored snapshot; empty on any corruption (fail closed)."""
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return {}
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return {}
    clean: dict[str, list[dict]] = {}
    for key, entries in providers.items():
        if not isinstance(key, str) or not isinstance(entries, list):
            return {}
        for entry in entries:
            if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                    or not isinstance(entry.get("name"), str)
                    or type(entry.get("tool_call")) is not bool
                    or type(entry.get("reasoning")) is not bool):
                return {}
        clean[key] = entries
    return clean


def catalog_models(provider_key: str) -> list[dict]:
    return list(load_catalog().get(provider_key, []))


def source_provenance() -> dict[str, str]:
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        return {"source": str(data.get("source", "")), "source_sha256": str(data.get("source_sha256", ""))}
    except (OSError, ValueError):
        return {"source": "", "source_sha256": ""}


__all__ = ["catalog_models", "load_catalog", "source_provenance"]
