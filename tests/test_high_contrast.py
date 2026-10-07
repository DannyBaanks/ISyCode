"""M-UX1.3: optional high-contrast display mode.

The preference is presentation-only: it grants nothing, persists in the
user-defaults store, and restyles control surfaces onto pure black. The
semantic palette already meets WCAG AA on black, so only surfaces and
borders are overridden.
"""
import pytest

from isycode.user_defaults import UserDefaultsStore


def test_high_contrast_defaults_off_and_round_trips(tmp_path):
    store = UserDefaultsStore(tmp_path)
    assert store.load()["high_contrast"] is False
    store.update(high_contrast=True)
    assert store.load()["high_contrast"] is True
    store.update(high_contrast=False)
    assert store.load()["high_contrast"] is False


def test_high_contrast_rejects_non_bool(tmp_path):
    store = UserDefaultsStore(tmp_path)
    with pytest.raises(ValueError):
        store.update(high_contrast="yes")
    assert store.load()["high_contrast"] is False


def test_high_contrast_css_parses_and_overrides_surfaces():
    from textual.css.stylesheet import Stylesheet
    from isycode.tui_theme import HIGH_CONTRAST_CSS

    stylesheet = Stylesheet()
    stylesheet.add_source(HIGH_CONTRAST_CSS, read_from=("test", "inline"))
    stylesheet.parse()
    assert "#000000" in HIGH_CONTRAST_CSS
    assert "Screen" in HIGH_CONTRAST_CSS
    assert "#prompt-input" in HIGH_CONTRAST_CSS


def test_semantic_palette_clears_aa_on_pure_black():
    from isycode.tui_theme import GREEN, MUTED, RED, TEXT, YELLOW
    import tests.test_side_panel as side_panel

    for color in (TEXT, MUTED, GREEN, YELLOW, RED):
        assert side_panel._contrast(color, "#000000") >= 4.5, (
            f"{color} on #000000 below 4.5:1")


def test_toggle_applies_and_removes_stylesheet_source():
    from textual.css.stylesheet import Stylesheet
    from isycode.tui_theme import HIGH_CONTRAST_CSS

    read_from = ("isycode", "high-contrast")
    stylesheet = Stylesheet()
    stylesheet.add_source(HIGH_CONTRAST_CSS, read_from=read_from)
    stylesheet.reparse()
    assert stylesheet.source
    stylesheet.add_source("", read_from=read_from)
    stylesheet.reparse()
    assert all(not css.strip() for css, *_ in stylesheet.source.values())
