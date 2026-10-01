#!/usr/bin/env python3
"""M4 — L1 self-extension with INV-4 enforcement.

Gate: TUI creates a destructive tool -> tool remains unusable until
independently registered and granted.
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
from pathlib import Path

ISYCODE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ISYCODE_ROOT))

from isycode.l1 import L1Store, ToolCandidate


def make_store():
    d = Path(tempfile.mkdtemp(prefix="isycode-m4-"))
    return L1Store(str(d)), d


DESTRUCTIVE_MANIFEST = {
    "id": "custom-wipe",
    "version": "0.1.0",
    "description": "Wipes a directory tree",
    "capability": "filesystem.delete",
    "effect_class": "DESTRUCTIVE",
    "entry": "tool.py",
}

DESTRUCTIVE_SOURCE = '''
def main(args):
    return {"wiped": args.get("path", "???"), "dry_run": True}
'''


def test_destructive_tool_unusable_until_registered_and_granted():
    """INV-4: creation != activation != grant. Passes gates, still unusable."""
    store, tmp = make_store()
    try:
        # 1. Create + pass all gates
        cand = store.create(DESTRUCTIVE_MANIFEST, DESTRUCTIVE_SOURCE)
        assert not cand.usable, "fresh candidate must not be usable"
        assert store.validate(cand).passed
        assert store.test(cand).passed
        assert store.probe(cand, {"path": "/tmp/x"}).passed
        assert set(cand.gates_passed) == {"V", "T", "P"}

        # 2. Still unusable — gates are not grants
        assert not cand.usable, "gates passed but tool must remain unusable"
        assert not store.is_usable(cand.id)

        # 3. Register capability + effect class (separate action)
        store.register(cand)
        assert cand.registered
        assert not cand.usable, "registered but not granted -> still unusable"
        assert not store.is_usable(cand.id)

        # 4. Grant (separate action) -> now usable
        store.grant(cand)
        store.mark_granted(cand.id)
        assert cand.usable
        assert store.is_usable(cand.id)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_grant_before_register_fails():
    """Cannot grant an unregistered tool."""
    store, tmp = make_store()
    try:
        cand = store.create(DESTRUCTIVE_MANIFEST, DESTRUCTIVE_SOURCE)
        try:
            store.grant(cand)
            assert False, "grant before register must fail"
        except ValueError as e:
            assert "unregistered" in str(e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_bad_manifest_rejected():
    """Gate V rejects malformed manifests and unknown effect classes."""
    store, tmp = make_store()
    try:
        bad = dict(DESTRUCTIVE_MANIFEST)
        del bad["capability"]
        try:
            store.create(bad, DESTRUCTIVE_SOURCE)
            assert False, "missing key must fail"
        except ValueError:
            pass
        bad2 = dict(DESTRUCTIVE_MANIFEST)
        bad2["effect_class"] = "NUKES"
        try:
            store.create(bad2, DESTRUCTIVE_SOURCE)
            assert False, "unknown effect class must fail"
        except ValueError:
            pass
        bad3 = dict(DESTRUCTIVE_MANIFEST)
        bad3["entry"] = "../evil.py"
        cand = store.create(bad3, DESTRUCTIVE_SOURCE)
        assert not store.validate(cand).passed, "path escape must fail gate V"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_broken_tool_fails_probe():
    """Gate P rejects tools that crash or return non-JSON."""
    store, tmp = make_store()
    try:
        cand = store.create(DESTRUCTIVE_MANIFEST, "def main(a): raise Boom()")
        assert store.validate(cand).passed
        assert store.test(cand).passed  # compiles fine
        assert not store.probe(cand, {}).passed, "crashing tool must fail probe"
        assert not cand.usable
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    import pytest
