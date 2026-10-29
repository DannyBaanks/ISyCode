"""Failure, recovery and tool-state text follows the chosen language."""
import pytest

from isycode.localization import configure_locale
from isycode.providers import ProviderError
from isycode.tui import TUIApp
from isycode.tui_theme import GREEN, RED, _semantic_box_title


@pytest.fixture
def spanish():
    configure_locale("es")
    yield
    configure_locale("en")


def _span_text(title, word):
    plain = title.plain
    return next(span for span in title.spans if plain[span.start:span.end] == word)


def test_tool_states_are_translated_but_keep_their_color(spanish):
    done = _semantic_box_title("workspace_run · Exit 0 · 1s")
    failed = _semantic_box_title("git_diff · app.py · Failed · <1s")

    assert done.plain == "workspace_run · Salida 0 · 1s"
    assert str(_span_text(done, "Salida 0").style) == GREEN
    assert failed.plain == "git_diff · app.py · Falló · <1s"
    assert str(_span_text(failed, "Falló").style) == RED


def test_provider_failure_is_translated(spanish):
    text = TUIApp._provider_failure(ProviderError("fixture", status=401), "Chat")

    assert text == ("Chat falló · APIKEY: Las credenciales del proveedor faltan, "
                    "no son válidas o fueron rechazadas · HTTP 401.")


def test_english_source_text_is_unchanged():
    configure_locale("en")

    assert _semantic_box_title("workspace_run · Exit 0 · 1s").plain == "workspace_run · Exit 0 · 1s"
    assert TUIApp._provider_failure(ProviderError("fixture", status=401), "Chat") == (
        "Chat failed · APIKEY: Provider credentials are missing, invalid or rejected · HTTP 401.")
