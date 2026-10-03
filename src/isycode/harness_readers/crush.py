from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_json, row, skipped


HARNESS_ID = "crush"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [skipped(HARNESS_ID, "providers.json", "secret")]

    config = load_json(root, "crush.json")
    lsp = config.get("lsp")
    if isinstance(lsp, dict):
        count = sum(1 for value in lsp.values() if isinstance(value, dict) and value.get("enabled", True) is not False)
        if count:
            settings.append(row(HARNESS_ID, "crush.json", "lsp.*.command", count, "lsp_configured_command", shown=f"{count} configured LSP" + ("s" if count != 1 else "")))

    mcp = config.get("mcp")
    if isinstance(mcp, dict):
        settings.append(row(HARNESS_ID, "crush.json", "mcp", len(mcp), "mcp_server_list", shown=f"{len(mcp)} MCP server" + ("s" if len(mcp) != 1 else "")))

    models = config.get("models")
    if isinstance(models, dict):
        large = models.get("large")
        if isinstance(large, dict):
            provider = large.get("provider")
            model = large.get("model")
            if isinstance(provider, str) and isinstance(model, str):
                settings.append(row(HARNESS_ID, "crush.json", "models.large", model, "default_model", provider_id=provider, model_id=model))

    projects = load_json(root, "projects.json").get("projects")
    if isinstance(projects, list):
        settings.append(row(HARNESS_ID, "projects.json", "projects[]", len(projects), "prior_transcript", shown=f"{len(projects)} project index entr" + ("ies" if len(projects) != 1 else "y")))

    return settings, skipped_files
