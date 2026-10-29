from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_json, row, skipped


HARNESS_ID = "cursor"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [skipped(HARNESS_ID, "statsig-cache.json", "unknown")]
    config = load_json(root, "cli-config.json")

    editor = config.get("editor")
    if isinstance(editor, dict) and "vimMode" in editor:
        settings.append(row(HARNESS_ID, "cli-config.json", "editor.vimMode", editor["vimMode"], "vim_mode"))

    display = config.get("display")
    if isinstance(display, dict) and "mode" in display:
        settings.append(row(HARNESS_ID, "cli-config.json", "display.mode", display["mode"], "display_layout"))

    if "notifications" in config:
        settings.append(row(HARNESS_ID, "cli-config.json", "notifications", config["notifications"], "ui_notifications"))
    if "hints" in config:
        settings.append(row(HARNESS_ID, "cli-config.json", "hints", config["hints"], "ui_hints"))
    if "exploreSubagentModel" in config:
        settings.append(row(HARNESS_ID, "cli-config.json", "exploreSubagentModel", config["exploreSubagentModel"], "explore_subagent_model"))

    permissions = config.get("permissions")
    if isinstance(permissions, dict):
        allow_count = len(permissions.get("allow", [])) if isinstance(permissions.get("allow"), list) else 0
        deny_count = len(permissions.get("deny", [])) if isinstance(permissions.get("deny"), list) else 0
        settings.append(row(
            HARNESS_ID,
            "cli-config.json",
            "permissions",
            allow_count + deny_count,
            "permission_rules",
            edge="non_equivalent",
            shown=f"allow {allow_count} · deny {deny_count}",
        ))

    if "approvalMode" in config:
        settings.append(row(HARNESS_ID, "cli-config.json", "approvalMode", config["approvalMode"], "approval_mode", edge="non_equivalent"))
    if "sandbox" in config:
        settings.append(row(HARNESS_ID, "cli-config.json", "sandbox", "configured", "sandbox_policy", edge="non_equivalent", shown="configured"))
    if "autoAcceptWebSearch" in config:
        settings.append(row(HARNESS_ID, "cli-config.json", "autoAcceptWebSearch", config["autoAcceptWebSearch"], "auto_accept_web_search", edge="non_equivalent"))
    if "runEverythingSettingsPromptStreak" in config:
        settings.append(row(HARNESS_ID, "cli-config.json", "runEverythingSettingsPromptStreak", config["runEverythingSettingsPromptStreak"], "run_everything_streak", edge="non_equivalent"))

    return settings, skipped_files
