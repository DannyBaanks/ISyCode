"""Allowlisted, read-only readers for external agent harness homes."""
from __future__ import annotations

from importlib import import_module
from pathlib import Path

from isycode.harness_graph import CATALOG_IDS, HarnessSetting, SkippedFile


def read_harness_root(
    harness_id: str,
    root: Path,
    *,
    automatic: bool = True,
) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    if harness_id not in CATALOG_IDS:
        raise ValueError("unknown harness id")
    module = import_module(f"isycode.harness_readers.{harness_id}")
    if harness_id == "opencode":
        return module.read_root(root, automatic=automatic)
    return module.read_root(root)


__all__ = ["read_harness_root"]
