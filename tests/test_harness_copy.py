import ast
import os
from pathlib import Path

import pytest

from isycode.harness_copy import copy_default_model_selection


SOURCE = Path(__file__).resolve().parents[1] / "src" / "isycode" / "harness_copy.py"


def test_copy_default_model_sets_process_selection_then_saves_without_credentials(monkeypatch):
    saved = []
    monkeypatch.delenv("ISYCODE_PROVIDER", raising=False)
    monkeypatch.delenv("ISYCODE_MODEL", raising=False)
    monkeypatch.setattr(
        "isycode.harness_copy.save_provider_selection",
        lambda provider, model: saved.append((provider, model)),
    )

    assert copy_default_model_selection("openai", "gpt-5.6-sol") == (
        "openai", "gpt-5.6-sol")
    assert os.environ["ISYCODE_PROVIDER"] == "openai"
    assert os.environ["ISYCODE_MODEL"] == "gpt-5.6-sol"
    assert saved == [("openai", "gpt-5.6-sol")]


@pytest.mark.parametrize("provider,model", [
    ("managed:kimi-code", "kimi-test"),
    ("OPENAI-WRONG", "gpt-5.6-sol"),
    ("openai", "bad model with spaces"),
    ("openai", "x" * 257),
])
def test_copy_default_model_rejects_non_preset_or_unsafe_identity(monkeypatch, provider, model):
    saved = []
    monkeypatch.setattr(
        "isycode.harness_copy.save_provider_selection",
        lambda *args: saved.append(args),
    )
    with pytest.raises(ValueError):
        copy_default_model_selection(provider, model)
    assert saved == []


def test_copy_helper_has_no_provider_or_key_loading_or_network_surface():
    source = SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source)
    names = {
        node.func.id
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attrs = {
        node.func.attr
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "Provider" not in names
    assert "load_provider_key" not in names
    assert not ({"urlopen", "request", "connect"} & attrs)
