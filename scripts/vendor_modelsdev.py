#!/usr/bin/env python3
"""Vendor the models.dev catalog into the repo (offline snapshot, hashed).

Fetches https://models.dev/api.json once, keeps only the providers ISyCode
ships presets for and only the fields the picker uses, validates the
shape, and writes src/isycode/assets/modelsdev-catalog.json with its own
provenance (source URL, fetch date, source sha256). Runtime never fetches;
refreshing the snapshot is this script + a commit.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "isycode" / "assets" / "modelsdev-catalog.json"
SOURCE_URL = "https://models.dev/api.json"

# ISyCode preset key -> models.dev provider id (None: local/user-managed, no catalog)
PROVIDER_MAP = {
    "alibaba": "alibaba",
    "anthropic": "anthropic",
    "cerebras": "cerebras",
    "deepinfra": "deepinfra",
    "deepseek": "deepseek",
    "fireworks": "fireworks-ai",
    "google": "google",
    "groq": "groq",
    "huggingface": "huggingface",
    "mistral": "mistral",
    "moonshot": "moonshotai",
    "nebius": "nebius",
    "nvidia": "nvidia",
    "openai": "openai",
    "opencode": "opencode",
    "openrouter": "openrouter",
    "scaleway": "scaleway",
    "venice": "venice",
    "vercel": "vercel",
    "xai": "xai",
    "zai": "zai",
    "ollama": None,
    "llamacpp": None,
    "lmstudio": "lmstudio",
    "chatgpt": None,
    "isyco-web": None,
    "opencode-go": None,
}
MAX_MODELS_PER_PROVIDER = 25


def main() -> int:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "isycode-catalog-vendor/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    source_sha = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw)
    if not isinstance(data, dict) or len(data) < 100:
        raise ValueError("models.dev response is not the expected provider catalog")
    catalog: dict[str, list[dict]] = {}
    for preset_key, dev_id in PROVIDER_MAP.items():
        if dev_id is None or dev_id not in data:
            continue
        models = data[dev_id].get("models", {})
        entries = []
        for model in models.values():
            if not isinstance(model, dict) or not isinstance(model.get("id"), str):
                continue
            modalities = model.get("modalities") or {}
            if "text" not in (modalities.get("input") or []):
                continue
            entries.append({
                "id": model["id"],
                "name": str(model.get("name") or model["id"]),
                "family": str(model.get("family") or ""),
                "tool_call": bool(model.get("tool_call")),
                "reasoning": bool(model.get("reasoning")),
                "context": int((model.get("limit") or {}).get("context") or 0),
                "cost_in": (model.get("cost") or {}).get("input"),
                "cost_out": (model.get("cost") or {}).get("output"),
            })
        entries.sort(key=lambda item: (not item["tool_call"], -(item["context"] or 0), item["id"]))
        catalog[preset_key] = entries[:MAX_MODELS_PER_PROVIDER]
    missing = [key for key, dev_id in PROVIDER_MAP.items()
               if dev_id is not None and key not in catalog]
    if missing:
        raise ValueError(f"mapped providers missing from models.dev: {missing}")
    payload = {
        "format": "isycode.modelsdev-catalog.v1",
        "source": SOURCE_URL,
        "source_sha256": source_sha,
        "providers": catalog,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    total = sum(len(entries) for entries in catalog.values())
    print(f"vendored {total} models across {len(catalog)} providers; source sha256 {source_sha[:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
