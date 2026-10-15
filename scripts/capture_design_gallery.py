#!/usr/bin/env python3
"""Export real Textual menu families in an isolated, offline demo workspace.

Provider/catalog transports are fixtures. No model prompts, effects, consent,
clipboard writes or network connections are executed. Existing captures are
never overwritten. Render SVGs with librsvg for the local HTML gallery.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

from capture_readme_screenshots import _install_demo_environment


async def capture(out: Path, size: tuple[int, int], locale: str):
    from isycode.tui import TUIApp
    from isycode.tui_screens_grants import WorkspaceModeScreen, AddCredentialScreen
    from isycode.tui_screens_harness import ModelsScreen, MultiHarnessScreen
    from isycode.tui_screens_sessions import SessionSearchScreen, IdeaNoteScreen, ShellProcessesScreen
    from isycode.tui_screens_approval import WriteApprovalScreen, CommandApprovalScreen
    from isycode.tui_screens_mcp import MCPArgumentsScreen, GatewaySemanticQueryScreen
    from isycode.tui_copy import CopyMenuScreen
    from isycode.folder_screens import AddWorkspaceFolderScreen
    from isycode.subagent_screen import SubagentModelScreen
    from isycode.rtk_tui import RTKSettingsScreen
    from isycode.security import ActionRequest
    from isycode.workspace_write import WritePreview
    from isycode.command_runner import CommandPreview
    from isycode.user_defaults import UserDefaultsStore
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.workspace_trust import WorkspaceTrust
    from textual.widgets import Button, OptionList, Tree
    import isycode.providers as providers
    import isycode.egress as egress

    async def no_external(self):
        return None

    providers.Provider.models = lambda provider: [provider.model]
    egress._ips = lambda host, port: ("93.184.216.34",)
    TUIApp._refresh_openisy = TUIApp._check_gateway_async = TUIApp._check_model = no_external
    # Avoid the test-driver idle executor stall, without changing product shutdown.
    original_unmount = TUIApp.on_unmount
    async def unmount(self, event):
        await original_unmount(self, event)
        asyncio.get_running_loop().call_later(0.5, lambda: None)
    TUIApp.on_unmount = unmount
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="classic", locale=locale)
    root = Path.cwd()
    authority = WorkspaceAuthority(root)
    authority.set_mode("classic")
    WorkspaceTrust().decline(authority)

    snapshots = []
    def save(app, name):
        path = out / (name + ".svg")
        assert not path.exists()
        app.title = "ISyCode · " + name
        app.save_screenshot(str(path))
        buttons = []
        for button in app.screen.query(Button):
            if not button.region.width or not button.region.height:
                continue
            # Mounted ancestor-clipped content is excluded from the visible action check.
            if button.has_class("model-choice") or button.has_class("child-model-choice"):
                continue
            buttons.append({"id": button.id, "region": list(button.region)})
        snapshots.append({"name": name, "screen": type(app.screen).__name__, "buttons": buttons,
                          "svg_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    app = TUIApp()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        app._set_rail_view("overview")
        for name in ("rail-mcp", "rail-lsp"):
            app.query_one("#" + name).collapsed = False
        await pilot.pause()
        save(app, "01-overview")
        app._set_rail_view("files")
        await app._load_directory(str(root / "src"))
        tree = app.query_one("#workspace-tree", Tree)
        node = next(item for item in tree.root.children if item.data["path"].endswith("helper.py"))
        tree.move_cursor(node)
        await app.on_tree_node_selected(Tree.NodeSelected(node))
        await pilot.pause()
        save(app, "02-files")
        app._open_settings_menu()
        await pilot.pause()
        save(app, "03-settings-conversation")
        categories = app.query_one("#settings-categories", OptionList)
        for index, category in enumerate(("conversation", "preferences", "permissions", "connections")):
            categories.highlighted = index
            await pilot.pause()
            if index:
                save(app, "04-settings-" + category)
        app._open_provider_menu()
        await pilot.pause()
        save(app, "05-providers")
        app._close_menu()
        app._open_authority_menu()
        await pilot.pause()
        save(app, "06-authority")
        app._close_menu()
        app._open_palette()
        await pilot.pause()
        save(app, "07-commands")
        app._close_menu()
        app._open_integrations_menu()
        await pilot.pause()
        save(app, "08-connections")
        app._close_menu()

        readme = "def helper():\n    x = 1\n    y = 2\n    return x + y\n"
        diff = "--- a/src/helper.py\n+++ b/src/helper.py\n@@ -1,2 +1,2 @@\n def helper():\n-    return 1\n+    return 2\n"
        write = WritePreview(ActionRequest("workspace.files.write", root, "src/helper.py", {}),
                             "src/helper.py", diff, False, "def helper():\n    return 2\n")
        command = CommandPreview(ActionRequest("workspace.command.run", root, "/usr/bin/python3", {}),
                                 ("python3", "-m", "unittest", "-q"), "python3", ".", 60, (), ".")
        model_entries = app._branch_entries("models")
        # The harness view shows unavailable demo folders, rather than claimed live readiness.
        harness = MultiHarnessScreen()
        for section in harness.sections:
            section["checking"] = False
        sessions = [SimpleNamespace(session_id="demo-1", title="Revisar helper", updated_at=0,
                                    messages=[{"role": "user", "content": "Revisar helper"}],
                                    model="gpt-6-luna", role="Reviewer")]
        dialogs = [
            ("09-models", ModelsScreen(model_entries, provider_scope="openai")),
            ("10-harness", harness),
            ("11-sessions", SessionSearchScreen(sessions)),
            ("12-review-edit", WriteApprovalScreen(write)),
            ("13-review-command", CommandApprovalScreen(command)),
            ("14-text-copy", CopyMenuScreen("    y = 2\n    return x + y", readme)),
            ("15-welcome", WorkspaceModeScreen(root)),
            ("16-ideas", IdeaNoteScreen("Añadir pruebas para helper()\nActualizar documentación")),
            ("17-output", ShellProcessesScreen()),
            ("18-mcp-form", MCPArgumentsScreen({"name": "symbols", "description": "Demo discovered schema", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}})),
            ("19-gateway-form", GatewaySemanticQueryScreen("https://gateway.example", "demo-workspace")),
            ("20-folders", AddWorkspaceFolderScreen(root, root.parent / "sibling")),
            ("21-subagent-model", SubagentModelScreen("Review helper.py", [{"provider": "openai", "model": "gpt-6-luna"}])),
            ("22-credentials", AddCredentialScreen()),
            ("23-rtk", RTKSettingsScreen()),
        ]
        for name, dialog in dialogs:
            await app.push_screen(dialog)
            await pilot.pause()
            save(app, name)
            await app.pop_screen()
            await pilot.pause()
    metadata = {"size": size, "locale": locale, "scope": "Offline fixture renders; no live provider or execution outcome asserted.",
                "snapshots": snapshots}
    (out / "captures.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--columns", type=int, default=140)
    parser.add_argument("--rows", type=int, default=40)
    parser.add_argument("--locale", choices=("es", "en", "zh"), default="es")
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        parser.error("Choose a new output directory; captures are preserved.")
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="isycode-gallery-") as temporary:
        private = Path(temporary)
        project = private / "sample-project"
        (project / "src").mkdir(parents=True)
        (project / "src/helper.py").write_text("def helper():\n    return 1\n")
        _install_demo_environment(private)
        previous = Path.cwd()
        os.chdir(project)
        try:
            asyncio.run(capture(out, (args.columns, args.rows), args.locale))
        finally:
            os.chdir(previous)
    print("Real Textual captures:", out)


if __name__ == "__main__":
    main()
