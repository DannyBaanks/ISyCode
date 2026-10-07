from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_jsonc, row, skipped


HARNESS_ID = "opencode"


def read_root(root: Path, *, automatic: bool = False) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    if automatic:
        return [], []

    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [
        skipped(HARNESS_ID, "auth.json", "secret"),
        skipped(HARNESS_ID, "mcp-auth.json", "secret"),
    ]
    config = load_jsonc(root, "opencode.jsonc")

    lsp = config.get("lsp")
    if isinstance(lsp, dict):
        count = sum(1 for value in lsp.values() if isinstance(value, dict) and isinstance(value.get("command"), list))
        if count:
            settings.append(row(
                HARNESS_ID,
                "opencode.jsonc",
                "lsp.*.command",
                count,
                "lsp_configured_command",
                shown=f"{count} configured LSP" + ("s" if count != 1 else ""),
            ))

    mcp = config.get("mcp")
    if isinstance(mcp, dict):
        settings.append(row(
            HARNESS_ID,
            "opencode.jsonc",
            "mcp",
            len(mcp),
            "mcp_server_list",
            shown=f"{len(mcp)} MCP server" + ("s" if len(mcp) != 1 else ""),
        ))

    plugins = config.get("plugin")
    if isinstance(plugins, list):
        settings.append(row(
            HARNESS_ID,
            "opencode.jsonc",
            "plugin[]",
            len(plugins),
            "enabled_plugins",
            edge="non_equivalent",
            shown=f"{len(plugins)} plugin entr" + ("ies" if len(plugins) != 1 else "y"),
            counts_toward_n=False,
        ))

    return settings, skipped_files
