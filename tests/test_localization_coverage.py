"""Every translated string used by the TUI exists in every catalog.

A `tr()` call whose msgid is missing from the catalogs silently renders the
English source, which is how one screen ended up with "Chat listo" next to
"Idea box" and "Ready". This test is the gate that keeps that from coming
back, and it also catches a catalog entry that was written as a raw
multi-line string instead of an escaped one.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from isycode.localization import SUPPORTED_LOCALES, _load_catalog, configure_locale

SOURCE = Path(__file__).resolve().parents[1] / "src" / "isycode"


def _literal_messages() -> set[str]:
    messages: set[str] = set()
    for path in sorted(SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "tr":
                continue
            if not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                messages.add(first.value)
    return messages


def test_catalogs_cover_every_translated_string():
    catalogs = {locale: {key[1] for key in _load_catalog(locale)} for locale in SUPPORTED_LOCALES}
    missing: dict[str, list[str]] = {}
    for message in sorted(_literal_messages()):
        if not message.strip():
            # Empty labels are placeholders for widgets without text.
            continue
        absent = [locale for locale in SUPPORTED_LOCALES if message not in catalogs[locale]]
        if absent:
            missing[message] = absent
    assert not missing, missing


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_catalog_entries_are_not_truncated(locale):
    """A raw newline inside a msgid breaks the parser and loses the entry."""
    catalog = _load_catalog(locale)
    roots = [msgid for (_context, msgid) in catalog if msgid.startswith("{root")]
    assert len(roots) == 2, roots
    for msgid in roots:
        assert msgid.startswith("{root}\n"), msgid[:40]
        assert msgid.endswith("."), msgid[-40:]


def test_rail_chips_follow_the_active_locale():
    """A rail chip is one message: no English status word inside a Spanish rail."""
    from isycode.tui_theme import status_chip

    configure_locale("es")
    assert status_chip("LSPs · {ready} ready", ready=2) == "LSPs · 2 listos"
    assert status_chip("Skills · {count} available", count=6) == "Skills · 6 disponibles"
    assert status_chip("MCPs · {state}", state="sin activar") == "MCPs · sin activar"
    configure_locale("en")
    assert status_chip("LSPs · {ready} ready", ready=2) == "LSPs · 2 Ready"
    assert status_chip("Skills · {count} available", count=6) == "Skills · 6 Available"
