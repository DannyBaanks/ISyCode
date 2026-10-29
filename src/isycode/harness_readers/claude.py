from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_json, row, safe_file, skipped


HARNESS_ID = "claude"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [
        skipped(HARNESS_ID, ".credentials.json", "secret"),
        skipped(HARNESS_ID, "mcp-needs-auth-cache.json", "secret"),
        skipped(HARNESS_ID, ".claude.json", "secret"),
    ]

    config = load_json(root, "settings.json")
    if "theme" in config:
        settings.append(row(HARNESS_ID, "settings.json", "theme", config["theme"], "ui_theme"))

    plugins = config.get("enabledPlugins")
    if isinstance(plugins, dict):
        count = sum(1 for enabled in plugins.values() if enabled is True)
        settings.append(row(
            HARNESS_ID,
            "settings.json",
            "enabledPlugins",
            count,
            "enabled_plugins",
            shown=f"{count} enabled plugin" + ("s" if count != 1 else ""),
        ))

    for key in ("skipDangerousModePermissionPrompt", "dangerouslySkipPermissions"):
        if key in config:
            settings.append(row(
                HARNESS_ID,
                "settings.json",
                key,
                config[key],
                "approval_bypass",
                edge="non_equivalent",
            ))

    hooks = config.get("hooks")
    if isinstance(hooks, dict):
        count = 0
        for event in hooks.values():
            if not isinstance(event, list):
                continue
            for group in event:
                if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                    count += len(group["hooks"])
        settings.append(row(
            HARNESS_ID,
            "settings.json",
            "hooks",
            count,
            "hook_command",
            edge="non_equivalent",
            shown=f"{count} hook command" + ("s" if count != 1 else ""),
        ))

    skills_dir = root / "skills"
    if skills_dir.is_dir() and not skills_dir.is_symlink():
        names = [p.name for p in skills_dir.iterdir() if p.is_dir() and not p.is_symlink()]
        if names:
            settings.append(row(
                HARNESS_ID,
                "skills/",
                "directory_names",
                len(names),
                "user_skills",
                shown=f"{len(names)} skill director" + ("ies" if len(names) != 1 else "y"),
            ))

    transcript_count = 0
    if safe_file(root, "history.jsonl") is not None:
        transcript_count += 1
    projects = root / "projects"
    if projects.is_dir() and not projects.is_symlink():
        for path in projects.glob("*/*.jsonl"):
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if safe_file(root, *rel.parts) is not None:
                transcript_count += 1
    if transcript_count:
        settings.append(row(
            HARNESS_ID,
            "history.jsonl;projects/*/*.jsonl",
            "index_or_filename",
            transcript_count,
            "prior_transcript",
            shown=f"{transcript_count} transcript index/file" + ("s" if transcript_count != 1 else ""),
        ))

    return settings, skipped_files
