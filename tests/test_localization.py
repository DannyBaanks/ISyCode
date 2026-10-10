"""Interface language is presentation only and never a workspace grant."""
from __future__ import annotations

import shutil
from pathlib import Path

from isycode.localization import (
    catalog_diagnostic,
    configure_locale,
    current_locale,
    next_locale,
    tr,
    validate_catalogs,
)
from isycode.workspace_authority import WorkspaceAuthority

PACKAGE_LOCALES = Path(__file__).resolve().parents[1] / "src" / "isycode" / "locales"


def test_spanish_contextual_message():
    configure_locale("es")
    assert current_locale() == "es"
    assert tr("Settings") == "Configuración"
    assert tr("Context") == "Contexto"
    assert tr("Authority & Security") == "Authority & Security"


def test_english_catalog_selection():
    configure_locale("en")
    assert current_locale() == "en"
    assert tr("Settings") == "Settings"
    assert tr("Context") == "Context"
    assert tr("Language · {name}", name=tr("English")) == "Language · English"


def test_chinese_catalog_selection():
    configure_locale("zh")
    assert current_locale() == "zh"
    assert tr("Settings") == "设置"
    assert tr("Context") == "上下文"
    assert tr("Authority & Security") == "Authority & Security"
    assert tr("Context: {name}", name="AGENT.txt") == "上下文: AGENT.txt"
    assert tr("Language · {name}", name=tr("Chinese")) == "语言 · 中文"


def test_locale_cycle_order():
    assert next_locale("es") == "en"
    assert next_locale("en") == "zh"
    assert next_locale("zh") == "es"


def test_missing_catalog_entry_uses_english_and_reports_diagnostic(tmp_path):
    configure_locale("es", catalog_root=tmp_path / "missing")
    assert tr("Settings") == "Settings"
    assert "Spanish catalog" in catalog_diagnostic()


def test_named_placeholders_are_preserved():
    configure_locale("es")
    assert tr("Context: {name}", name="AGENT.txt") == "Contexto: AGENT.txt"
    configure_locale("en")
    assert tr("Context: {name}", name="AGENT.txt") == "Context: AGENT.txt"


def test_catalog_validator_rejects_missing_id_or_placeholder_mismatch(tmp_path):
    assert validate_catalogs() == []
    root = tmp_path / "locales"
    shutil.copytree(PACKAGE_LOCALES, root)
    spanish = root / "es" / "LC_MESSAGES" / "isycode.po"
    text = spanish.read_text(encoding="utf-8")
    spanish.write_text(text.replace('msgstr "Configuración"\n', 'msgstr "Ajustes {broken}"\n'),
                       encoding="utf-8")
    problems = validate_catalogs(root)
    assert any("placeholder mismatch" in item and "Settings" in item for item in problems)
    spanish.write_text(text.replace('msgid "Settings"\nmsgstr "Configuración"\n', ""),
                       encoding="utf-8")
    problems = validate_catalogs(root)
    assert any("missing Spanish entry" in item and "Settings" in item for item in problems)


def test_spanish_settings_title_and_english_switch(tmp_path, monkeypatch, capsys):
    import asyncio
    from isycode.tui import TUIApp
    from isycode.user_defaults import UserDefaultsStore
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.workspace_trust import WorkspaceTrust

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    monkeypatch.setenv("ISYCODE_MODEL", "gpt-6-luna")
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-real")
    monkeypatch.setattr("isycode.providers.Provider.models", lambda provider: [provider.model])
    monkeypatch.setattr("isycode.egress._ips", lambda _host, _port: ("93.184.216.34",))
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="classic")
    authority = WorkspaceAuthority(project)
    authority.set_mode("classic")
    WorkspaceTrust().decline(authority)

    async def no_external_catalog(self):
        return None

    monkeypatch.setattr(TUIApp, "_startup_workspace", no_external_catalog)

    async def scenario():
        app = TUIApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app._open_settings_menu()
            await pilot.pause()
            assert app._menu_title == "Configuración"
            assert any(entry["label"].startswith("Idioma ·") for entry in app._menu_entries)
            app._menu_locale_cycle({})
            await pilot.pause()
            assert app._menu_title == "Settings"
            assert UserDefaultsStore().load()["locale"] == "en"
            app._menu_locale_cycle({})
            await pilot.pause()
            assert app._menu_title == "设置"
            assert UserDefaultsStore().load()["locale"] == "zh"
            assert any(entry["kind"] == "authority_open"
                       and entry["label"] == "Authority & Security"
                       for entry in app._menu_entries)

    with capsys.disabled():
        asyncio.run(scenario())


def test_locale_is_not_a_workspace_grant(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    from isycode.user_defaults import UserDefaultsStore
    UserDefaultsStore(tmp_path / "prefs").update(locale="en")
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    assert authority.effective_policy()["grants"] == {}
