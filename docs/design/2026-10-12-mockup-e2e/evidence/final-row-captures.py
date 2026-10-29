"""Preserve readable focused model rows from final native Textual source."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path.cwd()
sys.path.insert(0, str(root / "scripts"))
from capture_readme_screenshots import _install_demo_environment


async def capture(out, size):
    from textual.widgets import Input
    from isycode.tui import TUIApp
    from isycode.tui_screens_harness import ModelsScreen
    from isycode.subagent_screen import SubagentModelScreen
    from isycode.user_defaults import UserDefaultsStore
    from isycode.workspace_authority import WorkspaceAuthority

    async def idle(self):
        return None

    TUIApp._refresh_openisy = TUIApp._check_gateway_async = TUIApp._check_model = idle
    UserDefaultsStore().update(new_workspace="temporary", new_workspace_mode="security", locale="es")
    authority = WorkspaceAuthority(Path.cwd())
    authority.set_mode("security")
    app = TUIApp()
    async with app.run_test(size=size) as pilot:
        entries = [{"kind": "model", "value": "openai|" + model, "label": model}
                   for model in ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra")]
        await app.push_screen(ModelsScreen(entries, provider_scope="openai"))
        await pilot.pause()
        app.title = "ISyCode · model rows"
        app.save_screenshot(str(out / "09-models-readable.svg"))
        await pilot.press("escape")
        await app.push_screen(SubagentModelScreen("Revisar helper.py", [
            {"provider": "openai", "model": "gpt-6-luna"},
            {"provider": "openai", "model": "gpt-6-sol"}]))
        await pilot.pause()
        app.screen.query_one("#child-search", Input).value = "gpt"
        await pilot.pause()
        app.screen.query_one("#child-choice-0").focus()
        await pilot.pause()
        app.title = "ISyCode · subagent model rows"
        app.save_screenshot(str(out / "21-subagent-model-readable.svg"))
        await pilot.press("escape")


results = []
for columns, rows in ((80, 24), (100, 30), (140, 40)):
    out = root / f"docs/design/2026-10-12-mockup-e2e/rows-complete-{columns}x{rows}"
    assert not out.exists()
    out.mkdir()
    with tempfile.TemporaryDirectory(prefix="isycode-final-rows-") as temporary:
        private = Path(temporary)
        project = private / "project"
        project.mkdir()
        _install_demo_environment(private)
        os.chdir(project)
        try:
            asyncio.run(capture(out, (columns, rows)))
        finally:
            os.chdir(root)
    results.extend({"file": str(p.relative_to(root)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in sorted(out.glob("*.svg")))
manifest = {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "scope": "Native Textual focused/hover-safe model rows; temporary Security state; no model or effect executed.",
            "captures": results}
(root / "docs/design/2026-10-12-mockup-e2e/evidence/final-row-captures.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest, indent=2))
