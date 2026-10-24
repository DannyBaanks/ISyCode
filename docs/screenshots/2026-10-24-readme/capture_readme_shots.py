"""Regenerate the README screenshots (SVG): `python -m pytest docs/screenshots/2026-10-24-readme/capture_readme_shots.py`.

It uses the test fixtures and a fake model; convert the SVGs to PNG with a headless browser.
It writes /home/dev/tienda as the example project, so run it in a disposable container.
"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
import test_daily_tui
from test_gus_session import _checkout
from isycode.tui import TUIApp
from isycode.tui_composer import PromptArea
from isycode.localization import configure_locale
from isycode.user_defaults import UserDefaultsStore
from isycode.gus_session import GusState
from isycode.providers import record_model_metadata, save_model_slot
OUT = Path(__file__).resolve().parent
SIZE = (140, 40)


def project(tmp_path, monkeypatch):
    import isycode.tui
    real = test_daily_tui.configure
    def renamed(base, mp):
        root = real(base, mp)
        target = base / "tienda"
        root.rename(target)
        mp.chdir(target)
        from isycode.workspace_authority import WorkspaceAuthority
        from isycode.workspace_trust import WorkspaceTrust
        authority = WorkspaceAuthority(target)
        authority.set_mode("classic")
        WorkspaceTrust().decline(authority)
        return target
    import shutil
    base = Path("/home/dev")
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    root = renamed(base, monkeypatch)
    (root / "src").mkdir()
    (root / "src" / "carrito.py").write_text(
        "def total(items):\n    return sum(item.precio for item in items)\n\n\n"
        "def aplicar_descuento(total, porcentaje):\n    return total - total * porcentaje / 100\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_carrito.py").write_text("from src.carrito import total\n\n\ndef test_vacio():\n    assert total([]) == 0\n")
    (root / "README.md").write_text("# Tienda\n")
    UserDefaultsStore().update(locale="es", new_workspace="recurring")
    configure_locale("es")
    return root


def call(name, call_id, **arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def test_shots(tmp_path, monkeypatch, capsys):
    root = project(tmp_path, monkeypatch)
    answer = ("Revisé `src/carrito.py`. `aplicar_descuento` acepta porcentajes negativos o mayores "
              "a 100, y eso puede dar un total negativo. Propongo limitar el porcentaje entre 0 y 100 "
              "y agregar una prueba en `tests/test_carrito.py` para ese caso. ¿Lo aplico?")
    steps = [{"text": "", "tool_calls": [call("workspace_read", "c1", path="src/carrito.py")]},
             {"text": answer, "tool_calls": []}]
    seen = []

    async def complete(provider, messages, **kwargs):
        seen.append(1)
        step = steps[min(len(seen), len(steps)) - 1]
        if step["text"] and kwargs.get("on_chunk"):
            kwargs["on_chunk"]("content", step["text"])
        return step
    monkeypatch.setattr("isycode.tui.provider_complete", complete)
    monkeypatch.setattr("isycode.chat_transport.provider_complete", complete)

    async def scenario():
        app = TUIApp()
        app.title = "ISyCode"
        async with app.run_test(size=SIZE) as pilot:
            await app.wait_for_ready()
            await pilot.pause(0.5)
            app.action_toggle_sidebar()
            await pilot.pause(0.3)
            prompt = app.query_one("#prompt-input", PromptArea)
            prompt.focus()
            prompt.load_text("¿Hay algún bug en el cálculo del descuento del carrito?")
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(0.05)
                if len(seen) >= 2:
                    break
            await pilot.pause(0.6)
            app.query_one("#prompt-input", PromptArea).focus()
            await pilot.pause(0.3)
            app.save_screenshot("01-chat.svg", path=str(OUT))

            from isycode.tui_screens_grants import WorkspaceModeSwitchScreen
            task = asyncio.ensure_future(app._switch_mode_from_chip())
            for _ in range(60):
                await pilot.pause(0.05)
                if isinstance(app.screen, WorkspaceModeSwitchScreen):
                    break
            await pilot.pause(0.4)
            app.save_screenshot("02-modes.svg", path=str(OUT))
            app.screen.dismiss(None)
            await task
            await pilot.pause(0.2)

            app._open_settings_menu()
            await pilot.pause(0.6)
            app.save_screenshot("04-settings.svg", path=str(OUT))
    try:
        with capsys.disabled():
            asyncio.run(scenario())
    finally:
        configure_locale("en")


def test_gus_shot(tmp_path, monkeypatch, capsys):
    root = project(tmp_path, monkeypatch)
    _checkout(root)
    monkeypatch.setattr("isycode.egress._ips", lambda _host, _port: ("127.0.0.1",))
    record_model_metadata("ollama", "qwen3-coder:30b", {"context_length": 131_072})
    save_model_slot("gus", "ollama", "qwen3-coder:30b")
    GusState(root).enable()
    (root / ".git").mkdir(exist_ok=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/gus/descuento\n")
    text = ("Listo en gus/descuento: limité el porcentaje entre 0 y 100 en src/carrito.py y agregué "
            "test_descuento_fuera_de_rango. Las pruebas pasan en el sandbox. No toqué nada de L0. "
            "Cuando quieras, corre las puertas con /gus seal.")

    async def complete(provider, messages, **kwargs):
        return {"text": text, "tool_calls": []}
    monkeypatch.setattr("isycode.chat_transport.provider_complete", complete)

    async def scenario():
        from isycode.tui_screens_gus import GusScreen
        app = TUIApp()
        app.title = "ISyCode"
        async with app.run_test(size=SIZE) as pilot:
            await app.wait_for_ready()
            task = asyncio.ensure_future(app._open_gus("Arregla el descuento negativo del carrito y agrega su prueba"))
            for _ in range(100):
                await pilot.pause(0.05)
                if isinstance(app.screen, GusScreen) and len(app.screen.query(".gus-line")) >= 2:
                    break
            await pilot.pause(0.4)
            app.save_screenshot("03-gus.svg", path=str(OUT))
            app.screen.dismiss(None)
            await task
    try:
        with capsys.disabled():
            asyncio.run(scenario())
    finally:
        configure_locale("en")
