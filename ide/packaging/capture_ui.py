"""Render the actual Qt interface with labeled fixture data; no account requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="isycode-ui-fixture-") as directory:
        os.environ["ISYCODE_IDE_HOME"] = str(Path(directory) / "state")
        from PySide6.QtWidgets import QApplication
        from ui.app import AppController
        from ui.main_window import MainWindow
        from ui.theme import apply_theme
        from ui.shell import NAVIGATION
        app = QApplication([])
        apply_theme(app)
        project = Path(directory) / "DemoProject"
        project.mkdir()
        (project / "app.py").write_text('def greet(name: str) -> str:\n    return f"Hola, {name}!"\n\nprint(greet("Danny"))\n')
        for name, content in {"main.js": "console.log('Hola');\n", "types.ts": "type Name = string;\n", "README.md": "# DemoProject\n", "config.yaml": "example: true\n", "package.json": "{}\n"}.items():
            (project / name).write_text(content)
        (project / "src").mkdir()
        controller = AppController(project)
        controller.add_provider("local-example", "ollama", "fixture-model")
        session = controller.conversations.create("Ejemplo visual · revisar saludo")
        turn = controller.conversations.begin(session, "Ayúdame a revisar el saludo de app.py", "local-example", "fixture-model", "ollama")
        controller.conversations.append_response(session, turn, "El saludo está en `app.py`. Revisa el diff y el comando antes de aprobarlos.")
        controller.conversations.finish(turn, "completed")
        window = MainWindow(controller)
        window._open_file(str(project / "app.py"))
        window.show()
        # These fixtures never call gh; screenshots exercise the real widgets.
        from core.github_service import GitHubService
        from tests.test_ide_github_activity import fake_api, fixture_responses
        fixture = fixture_responses()
        fixture["pulls"] = [
            {"number": 42, "title": "Separar Conversación de Archivos", "user": {"login": "Fixture"}, "updated_at": "2026-10-11T03:00:00Z"},
            {"number": 41, "title": "Mejorar selección de providers", "draft": True, "user": {"login": "Fixture"}, "updated_at": "2026-10-10T23:00:00Z"}]
        window.github_panel.service._gh = fake_api(fixture, [])
        window.github_panel.service.links.add("Fixture/project", str(project))
        window.github_panel._catalog_ready({"verified": True, "login": "Fixture", "may_have_more": False,
            "repositories": [{"name": "Fixture/project", "private": True,
                              "description": "Native IDE · visual fixture"}]})
        from PySide6.QtTest import QTest
        for _ in range(60):
            app.processEvents()
            if window.github_panel._worker is None and window.github_panel.metrics["stars"].text() == "8":
                break
            QTest.qWait(20)
        assert window.github_panel.metrics["stars"].text() == "8"
        from PySide6.QtWidgets import QLabel
        window.statusBar().addPermanentWidget(QLabel("Vista real · datos de ejemplo"))
        window._set_mode("coder")
        window.chat.add_approval_card("visual-files", "Cambios listos para revisar",
            {"path": "app.py", "approval_kind": "files"},
            "--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,3 @@\n def greet(name: str) -> str:\n+    name = name.strip()\n     return f'Hola, {name}!'")
        window.chat.add_approval_card("visual-command", "Comando pendiente de aprobación",
            {"approval_kind": "command", "argv": ["python3", "-m", "pytest", "tests/test_app.py"]},
            "python3 -m pytest tests/test_app.py")
        rows = []
        def save(name):
            from PySide6.QtTest import QTest
            app.processEvents()
            QTest.qWait(80)
            app.processEvents()
            path = output / (name + ".png")
            assert window.grab().save(str(path))
            rows.append({"path": path.name, "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
                         "logical_size": [window.width(), window.height()], "device_pixel_ratio": window.devicePixelRatio()})
        for width, height in [(1024,768),(1366,768),(1672,941),(1920,1080)]:
            window.resize(width,height)
            for view in ("conversation", "code"):
                window.panel_bar.set_view(view)
                window.chat.scroll.verticalScrollBar().setValue(0)
                save(f"{view}-{width}")
            for title, label, symbol in NAVIGATION:
                if title in {"Conversaciones", "Editor", "Cambios"}:
                    continue
                window.panel_bar.show_title(title)
                save(f"{symbol}-{width}")
                if title == "GitHub":
                    for key in ("issues", "commits", "actions"):
                        window.github_panel.activity_tabs.setCurrentWidget(window.github_panel.activity_views[key])
                        save(f"github-{key}-{width}")
                    window.github_panel.activity_tabs.setCurrentIndex(0)
                    from core.github_service import GitStatus
                    status = GitStatus(str(project), "Fixture/project", "main", "origin/main", "origin", "main",
                                       "a" * 40, "b" * 40, 0, 5, 0, 0, 0, 0, False, False,
                                       "2026-10-11T03:00:00Z", True, "behind")
                    window.github_panel._statuses[str(project)] = (status, [
                        "b7b2910 Corregir streaming del chat", "e1c5d4a Mejorar selector de providers",
                        "9b7e2c Ajustar permisos de herramientas"])
                    item = window.github_panel.tree.topLevelItem(0)
                    window.github_panel.tree.setCurrentItem(item.child(0))
                    save(f"github-linked-{width}")
                    window.github_panel.tree.setCurrentItem(item)
            window.panel_bar.show_title("Config")
            window.config_panel.tabs.setCurrentWidget(window.config_panel.subscriptions)
            save(f"subscriptions-{width}")
            window.config_panel.tabs.setCurrentIndex(0)
        window.close()
        (output / "manifest.json").write_text(json.dumps({"scope":"actual Qt renders; fictitious project/messages; no network/account requests", "renders":rows},indent=2)+"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
