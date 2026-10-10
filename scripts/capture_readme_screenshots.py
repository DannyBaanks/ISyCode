#!/usr/bin/env python3
"""Render the README screenshots from a real Textual session.

The README shows three PNGs under docs/screenshots/. No CI workflow builds
them, so this script is the reproducible procedure: it starts the real TUI on a
throwaway demo workspace with a simulated provider and exports each screen as
SVG (Textual's own export). Nothing external is called: no provider, no
Gateway, no MCP tool, no shell command.

Usage:
  PYTHONPATH=src python3 scripts/capture_readme_screenshots.py --out /tmp/shots
"""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from pathlib import Path


def _install_demo_environment(root: Path) -> None:
    os.environ["ISYCODE_STATE_HOME"] = str(root / "state")
    os.environ["XDG_STATE_HOME"] = str(root / "xdg-state")
    os.environ["XDG_CONFIG_HOME"] = str(root / "xdg-config")
    os.environ["ISYCODE_PROVIDER"] = "openai"
    os.environ["ISYCODE_MODEL"] = "gpt-6-luna"
    os.environ["OPENAI_API_KEY"] = "test-not-real"


async def _capture(out: Path, columns: int, rows: int) -> list[Path]:
    import isycode.egress as egress
    import isycode.providers as providers_module
    from isycode.tui import TUIApp
    from isycode.user_defaults import UserDefaultsStore
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.workspace_trust import WorkspaceTrust

    providers_module.Provider.models = lambda provider: [provider.model]
    egress._ips = lambda _host, _port: ("93.184.216.34",)

    async def _no_external(self):
        return None

    # Only the optional catalog and Gateway probes are suppressed. The model
    # line is left alone: it reports the configured provider from local state
    # and never opens a socket, so the screenshot shows the real label.
    TUIApp._refresh_openisy = _no_external
    TUIApp._check_gateway_async = _no_external

    original_unmount = TUIApp.on_unmount

    async def _test_unmount(self, event):
        await original_unmount(self, event)
        asyncio.get_running_loop().call_later(0.5, lambda: None)

    TUIApp.on_unmount = _test_unmount

    UserDefaultsStore().update(new_workspace="temporary",
                               new_workspace_mode="classic", locale="es")
    authority = WorkspaceAuthority(Path.cwd())
    authority.set_mode("classic")
    WorkspaceTrust().decline(authority)

    written: list[Path] = []

    def snapshot(app, name: str) -> None:
        app.title = "IsyCode"
        app.save_screenshot(str(out / name))
        written.append(out / name)

    app = TUIApp()
    async with app.run_test(size=(columns, rows)) as pilot:
        await pilot.pause()
        # The rail starts collapsed; the README shows it open on Overview.
        app.action_toggle_sidebar()
        await pilot.pause()
        snapshot(app, "01-overview.svg")

        app.query_one("#show-files").press()
        await pilot.pause()
        snapshot(app, "02-files.svg")

        app._open_settings_menu()
        await pilot.pause()
        snapshot(app, "03-settings.svg")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--columns", type=int, default=197)
    parser.add_argument("--rows", type=int, default=58)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="isycode-demo-") as tmp:
        project = Path(tmp) / "isycode-demo-workspace"
        project.mkdir()
        _install_demo_environment(Path(tmp))
        previous = Path.cwd()
        os.chdir(project)
        try:
            written = asyncio.run(_capture(args.out, args.columns, args.rows))
        finally:
            os.chdir(previous)

    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
