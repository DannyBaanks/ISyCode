import pytest
from pathlib import Path
from isycode.file_preview import guess_syntax_language
from isycode.user_defaults import UserDefaultsStore

def test_guess_syntax_language_basenames():
    assert guess_syntax_language(Path(".gitattributes")) == "bash"
    assert guess_syntax_language(Path(".gitignore")) == "bash"
    assert guess_syntax_language(Path("Dockerfile")) == "bash"
    assert guess_syntax_language(Path("Dockerfile.dev")) == "bash"
    assert guess_syntax_language(Path("Makefile")) is None
    assert guess_syntax_language(Path("rules.mk")) is None
    assert guess_syntax_language(Path("compose.yaml")) == "yaml"

def test_guess_syntax_language_extensions():
    assert guess_syntax_language(Path("main.rs")) == "rust"
    assert guess_syntax_language(Path("script.py")) == "python"
    assert guess_syntax_language(Path("data.json")) == "json"
    assert guess_syntax_language(Path("config.toml")) == "toml"
    assert guess_syntax_language(Path("styles.tcss")) == "css"
    assert guess_syntax_language(Path("index.html")) == "html"
    assert guess_syntax_language(Path("app.jsx")) == "javascript"
    assert guess_syntax_language(Path(".env.local")) == "bash"

def test_guess_syntax_language_shebang():
    assert guess_syntax_language(Path("unknown_script"), code="#!/usr/bin/env python3\nprint('hi')") == "python"
    assert guess_syntax_language(Path("unknown_script"), code="#!/bin/bash\necho hi") == "bash"
    assert guess_syntax_language(Path("unknown_file"), code="plain text without shebang") is None

def test_user_defaults_sidebar_file_preview(tmp_path):
    # Let WindowsStorage create a private child with its own restrictive ACL.
    store = UserDefaultsStore(directory=tmp_path / "private-defaults")
    defaults = store.load()
    assert defaults.get("sidebar_file_preview") is False

    store.update(sidebar_file_preview=True)
    assert store.load().get("sidebar_file_preview") is True
