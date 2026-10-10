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
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="classic", locale="es")
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


def test_spanish_and_chinese_option_catalogs_cover_chrome_first_run_and_approvals():
    configure_locale("es")
    assert tr("Sidebar") == "Barra lateral"
    assert tr("Sessions") == "Sesiones"
    assert tr("Filter this list…") == "Filtrar esta lista…"
    assert tr("Quick Start · ready in under a minute") == "Inicio rápido · listo en menos de un minuto"
    assert tr("Classic · Ready To Use") == "Classic · listo para usar"
    assert tr("Allow once · y") == "Permitir una vez · y"
    assert tr("Apply change · y") == "Aplicar cambio · y"
    assert tr("Cancel · n") == "Cancelar · n"
    assert tr("Read and search workspace files") == "Leer y buscar archivos del espacio de trabajo"
    configure_locale("zh")
    assert tr("Sidebar") == "侧栏"
    assert tr("Sessions") == "会话"
    assert tr("Filter this list…") == "筛选此列表…"
    assert tr("Quick Start · ready in under a minute") == "快速开始 · 一分钟内就绪"
    assert tr("Security · everything off until I allow it") == "Security · 在我允许之前全部关闭"
    assert tr("Allow once · y") == "允许一次 · y"
    assert tr("Keep · n") == "保留 · n"


def test_spanish_chrome_and_first_run_options_render(tmp_path, monkeypatch, capsys):
    import asyncio
    from textual.widgets import Button, Input
    from isycode.tui import QuickStartScreen, TUIApp, WorkspaceModeScreen
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
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="classic", locale="es")
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
            assert str(app.query_one("#sidebar-button", Button).label) == "Barra lateral"
            assert str(app.query_one("#sessions-button", Button).label) == "Sesiones"
            assert str(app.query_one("#context-button", Button).label) == "Contexto"
            assert app.query_one("#action-search", Input).placeholder == "Filtrar esta lista…"
            await app.push_screen(QuickStartScreen(project, provider_ready=True))
            await pilot.pause()
            options = [str(option.prompt) for option in app.screen.query_one("#quick-start-options")._options]
            assert "Inicio rápido · listo en menos de un minuto" in options
            assert "Configuración personalizada · elige cada paso" in options
            await app.pop_screen()
            await app.push_screen(WorkspaceModeScreen(project))
            await pilot.pause()
            mode_options = [str(option.prompt) for option in app.screen.query_one("#workspace-mode-options")._options]
            assert "Classic · listo para usar" in mode_options
            assert "Security · todo apagado hasta que yo lo permita" in mode_options

    with capsys.disabled():
        asyncio.run(scenario())


def test_chinese_chrome_and_approval_buttons_render(tmp_path, monkeypatch, capsys):
    import asyncio
    from textual.widgets import Button, Input
    from isycode.tui import TUIApp
    from isycode.tui_screens_approval import ReviewConsentScreen
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
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="classic", locale="zh")
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
            assert str(app.query_one("#sidebar-button", Button).label) == "侧栏"
            assert str(app.query_one("#inject-context-button", Button).label) == "注入上下文"
            assert app.query_one("#action-search", Input).placeholder == "筛选此列表…"
            await app.push_screen(ReviewConsentScreen("artifact"))
            await pilot.pause()
            assert str(app.screen.query_one("#review-cancel", Button).label) == "取消"
            assert str(app.screen.query_one("#review-send", Button).label) == "发送此文本"

    with capsys.disabled():
        asyncio.run(scenario())


def test_spanish_and_chinese_authority_palette_and_defaults_options():
    configure_locale("es")
    assert tr("Read and search workspace files") == "Leer y buscar archivos del espacio de trabajo"
    assert tr("Turn on all coding tools…") == "Activar todas las herramientas de código…"
    assert tr("Ask me when I open a new folder") == "Preguntarme al abrir una carpeta nueva"
    assert tr("Guidance available to ISyCode") == "Guía disponible para ISyCode"
    assert tr("Mode · Classic · Ready To Use; switch to Security…") == (
        "Modo · Classic · listo para usar; cambiar a Security…")
    configure_locale("zh")
    assert tr("Read and search workspace files") == "读取并搜索工作区文件"
    assert tr("Ask me when I open a new folder") == "打开新文件夹时询问我"
    assert tr("Local code help") == "本地代码帮助"
    assert tr("Mode · Security · nothing runs until you allow it; switch to Classic…") == (
        "模式 · Security · 在你允许之前不运行任何操作；切换到 Classic…")


def test_spanish_authority_and_palette_options_render(tmp_path, monkeypatch, capsys):
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
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="classic", locale="es")
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
            app._open_authority_menu()
            await pilot.pause()
            labels = [entry["label"] for entry in app._menu_entries]
            assert "Leer y buscar archivos del espacio de trabajo" in labels
            assert "Activar todas las herramientas de código…" in labels
            assert "Modo · Classic · listo para usar; cambiar a Security…" in labels
            app._open_palette()
            await pilot.pause()
            palette = [entry["label"] for entry in app._menu_entries]
            assert any("Guía disponible para ISyCode" in label for label in palette)
            app._open_user_defaults_menu()
            await pilot.pause()
            defaults = [entry["label"] for entry in app._menu_entries]
            assert any("Preguntarme al abrir una carpeta nueva" in label for label in defaults)

    with capsys.disabled():
        asyncio.run(scenario())
