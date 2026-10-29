"""Narrow writes explicitly allowed by Multi Harness."""
from __future__ import annotations

import os

from isycode.harness_graph import copyable_default_model
from isycode.providers import PRESETS, save_provider_selection


def copy_default_model_selection(provider_id: object, model_id: object) -> tuple[str, str]:
    """Copy one safe provider/model identity into ISyCode process preferences."""
    if not copyable_default_model(provider_id, model_id, preset_ids=set(PRESETS)):
        raise ValueError("default model is not copyable")
    provider = str(provider_id).casefold()
    model = str(model_id).strip()
    os.environ["ISYCODE_PROVIDER"] = provider
    os.environ["ISYCODE_MODEL"] = model
    save_provider_selection(provider, model)
    return provider, model


__all__ = ["copy_default_model_selection"]
