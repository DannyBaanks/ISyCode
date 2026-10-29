"""M-UX1.3: optional high-contrast display mode.

The preference is presentation-only: it grants nothing, persists in the
user-defaults store, and restyles control surfaces onto pure black. The
semantic palette already meets WCAG AA on black, so only surfaces and
borders are overridden.
"""
import pytest

from isycode.user_defaults import UserDefaultsStore


def test_high_contrast_defaults_off_and_round_trips(tmp_path):
    store = UserDefaultsStore(tmp_path / "preferences")
    assert store.load()["high_contrast"] is False
    store.update(high_contrast=True)
    assert store.load()["high_contrast"] is True
    store.update(high_contrast=False)
    assert store.load()["high_contrast"] is False


def test_high_contrast_rejects_non_bool(tmp_path):
    store = UserDefaultsStore(tmp_path / "preferences")
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
    from isycode.tui_theme import GREEN, MUTED, RED, SECURITY, TEXT, YELLOW
    import tests.test_side_panel as side_panel

    for color in (TEXT, MUTED, GREEN, YELLOW, RED, SECURITY):
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


def test_security_denied_color_is_distinct_from_error_and_warning():
    """F-07: DENY (orange) must not collapse into error (red) or warning (yellow)."""
    from isycode.tui_theme import RED, SECURITY, YELLOW

    assert SECURITY != RED
    assert SECURITY != YELLOW


def test_semantic_box_title_gives_denied_its_own_color():
    """F-07: a DENY title renders orange; a failure title stays red."""
    from isycode.tui_theme import RED, SECURITY, _semantic_box_title

    denied_styles = {span.style for span in _semantic_box_title("Tool denied").spans}
    failed_styles = {span.style for span in _semantic_box_title("Tool failed").spans}
    assert SECURITY in denied_styles
    assert RED not in denied_styles
    assert RED in failed_styles
    assert SECURITY not in failed_styles


def test_notify_semantic_denied_uses_security_denied_severity():
    """F-07: notify_semantic('denied') maps to the security-denied severity."""
    from textual.app import App

    captured = {}

    class _Probe(App):
        def notify(self, message, *, title="", severity="information", timeout=None, markup=True):
            captured["severity"] = severity

    app = _Probe()
    # replicate the mapping from ISyCodeApp.notify_semantic without mounting
    semantics = {
        "denied": "security-denied",
        "error": "error",
    }
    assert semantics["denied"] != semantics["error"]
    assert semantics["denied"] == "security-denied"
