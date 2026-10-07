from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_simple_yaml, row, safe_file, skipped


HARNESS_ID = "hermes"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [
        skipped(HARNESS_ID, "auth", "secret"),
        skipped(HARNESS_ID, "updates", "unknown"),
        skipped(HARNESS_ID, ".env", "secret"),
        skipped(HARNESS_ID, "auth.json", "secret"),
        skipped(HARNESS_ID, "auth.lock", "secret"),
        skipped(HARNESS_ID, "nous_auth.json", "secret"),
        skipped(HARNESS_ID, "install_id", "identity"),
    ]

    config = load_simple_yaml(root, "config.yaml")
    model = config.get("model")
    if isinstance(model, dict):
        default = model.get("default")
        provider = model.get("provider")
        if isinstance(default, str):
            settings.append(row(
                HARNESS_ID,
                "config.yaml",
                "model.default",
                default,
                "default_model",
                provider_id=provider if isinstance(provider, str) else None,
                model_id=default,
            ))
        if "base_url" in model:
            settings.append(row(HARNESS_ID, "config.yaml", "model.base_url", True, "provider_endpoint", edge="non_equivalent", shown="present"))

    agent = config.get("agent")
    if isinstance(agent, dict) and "reasoning_effort" in agent:
        settings.append(row(HARNESS_ID, "config.yaml", "agent.reasoning_effort", agent["reasoning_effort"], "reasoning_effort"))

    display = config.get("display")
    if isinstance(display, dict) and "skin" in display:
        settings.append(row(HARNESS_ID, "config.yaml", "display.skin", display["skin"], "ui_skin"))

    allowlist = config.get("command_allowlist")
    if isinstance(allowlist, list):
        settings.append(row(HARNESS_ID, "config.yaml", "command_allowlist", len(allowlist), "command_allowlist", edge="non_equivalent", shown=f"{len(allowlist)} command rule" + ("s" if len(allowlist) != 1 else "")))

    toolsets = []
    for key in ("platform_toolsets", "known_plugin_toolsets"):
        value = config.get(key)
        if isinstance(value, list):
            toolsets.extend(value)
    if toolsets:
        settings.append(row(HARNESS_ID, "config.yaml", "*_toolsets", len(toolsets), "toolset_list", shown=f"{len(toolsets)} toolset" + ("s" if len(toolsets) != 1 else "")))

    web = config.get("web")
    if isinstance(web, dict) and "backend" in web:
        settings.append(row(HARNESS_ID, "config.yaml", "web.backend", web["backend"], None, edge="unmapped"))

    skills_dir = root / "skills"
    if skills_dir.is_dir() and not skills_dir.is_symlink():
        count = sum(1 for path in skills_dir.iterdir() if path.is_dir() and not path.is_symlink())
        if count:
            settings.append(row(HARNESS_ID, "skills/", "directory_names", count, "user_skills", shown=f"{count} skill director" + ("ies" if count != 1 else "y")))

    if safe_file(root, "SOUL.md") is not None:
        settings.append(row(HARNESS_ID, "SOUL.md", "file_presence", True, "agent_persona", shown="SOUL.md present"))
    if safe_file(root, "memories", "USER.md") is not None:
        settings.append(row(HARNESS_ID, "memories/USER.md", "file_presence", True, "user_profile_file", shown="USER.md present"))

    sessions = root / "sessions"
    if sessions.is_dir() and not sessions.is_symlink():
        count = 0
        for path in sessions.glob("request_dump_*.json"):
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if safe_file(root, *rel.parts) is not None:
                count += 1
        if count:
            settings.append(row(HARNESS_ID, "sessions/request_dump_*.json", "filename", count, "prior_transcript", shown=f"{count} request dump file" + ("s" if count != 1 else "")))

    return settings, skipped_files
