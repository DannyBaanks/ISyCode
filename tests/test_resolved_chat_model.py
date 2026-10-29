"""Saved model selection must survive a restart, ahead of the catalog default."""
from pathlib import Path

import pytest

from isycode.config import NVIDIA_NEMOTRON_550B, provider_default_model
from isycode.image_attachments import ImageAttachments
from isycode.providers import Provider, resolved_chat_model, save_provider_selection


SAVED = "meta/llama-3.2-11b-vision-instruct"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("ISYCODE_MODEL", raising=False)
    monkeypatch.delenv("ISYMOTRON_MODEL", raising=False)
    monkeypatch.delenv("ISYMOTRON_PROVIDER", raising=False)


def test_saved_nvidia_model_wins_over_the_truthy_catalog_default(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")
    save_provider_selection("nvidia", SAVED)

    assert provider_default_model("nvidia") == NVIDIA_NEMOTRON_550B
    assert resolved_chat_model("nvidia") == SAVED
    assert Provider(name="nvidia", model=resolved_chat_model("nvidia")).model == SAVED


def test_environment_model_still_wins_for_the_active_provider_only(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    monkeypatch.setenv("ISYCODE_MODEL", "gpt-env")
    save_provider_selection("nvidia", SAVED)
    save_provider_selection("openai", "gpt-saved")

    assert resolved_chat_model("openai") == "gpt-env"
    assert resolved_chat_model("nvidia") == SAVED


def test_missing_selection_falls_back_to_the_provider_default(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")

    assert resolved_chat_model("nvidia") == NVIDIA_NEMOTRON_550B
    assert resolved_chat_model("openai") == "gpt-6-luna"


def test_image_capability_uses_the_saved_model_not_the_catalog_default(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("ISYCODE_PROVIDER", "nvidia")
    save_provider_selection("nvidia", SAVED)
    from isycode.capability_observations import record

    assert record("nvidia", NVIDIA_NEMOTRON_550B, "images", True)
    assert record("nvidia", SAVED, "images", False)
    attachments = ImageAttachments()
    text = "look " + attachments.capture("image/png", PNG)

    with pytest.raises(ValueError, match="no image support"):
        attachments.prepare(
            [{"role": "user", "content": text}], "nvidia", resolved_chat_model("nvidia"))
    prepared = attachments.prepare(
        [{"role": "user", "content": text}], "nvidia", NVIDIA_NEMOTRON_550B)
    assert isinstance(prepared[0]["content"], list)


def test_chat_call_sites_do_not_pass_the_catalog_default_as_the_chosen_model():
    root = Path(__file__).resolve().parents[1] / "src" / "isycode"
    surfaces = [root / "headless.py", *sorted(root.glob("tui*.py"))]
    texts = [(path, path.read_text(encoding="utf-8")) for path in surfaces]
    for path, text in texts:
        assert "model=provider_default_model" not in text, path.name
        assert "model=provider_default_model" not in text.replace(" ", ""), path.name
    tui_text = "\n".join(text for path, text in texts if path.name.startswith("tui"))
    assert tui_text.count("provider_default_model(") == 1
    assert "Default model:" in tui_text
