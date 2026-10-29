from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_json, row, safe_file, skipped


HARNESS_ID = "openclaw"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [
        skipped(HARNESS_ID, "openclaw.json#auth", "secret"),
        skipped(HARNESS_ID, "openclaw.json#gateway.auth", "secret"),
        skipped(HARNESS_ID, "openclaw.json#plugins.entries.*.config", "secret"),
        skipped(HARNESS_ID, "state/openclaw.sqlite", "denied_table"),
    ]

    config = load_json(root, "openclaw.json")
    agents = config.get("agents")
    if isinstance(agents, dict):
        defaults = agents.get("defaults")
        if isinstance(defaults, dict):
            model = defaults.get("model")
            if isinstance(model, dict) and isinstance(model.get("primary"), str):
                model_id = model["primary"]
                settings.append(row(HARNESS_ID, "openclaw.json", "agents.defaults.model.primary", model_id, "default_model", model_id=model_id))

    models = config.get("models")
    if isinstance(models, dict):
        providers = models.get("providers")
        if isinstance(providers, dict) and any(
            isinstance(value, dict) and "baseUrl" in value for value in providers.values()
        ):
            settings.append(row(HARNESS_ID, "openclaw.json", "models.providers.*.baseUrl", True, "provider_endpoint", edge="non_equivalent", shown="present"))

    plugins = config.get("plugins")
    if isinstance(plugins, dict):
        entries = plugins.get("entries")
        if isinstance(entries, dict):
            count = sum(1 for value in entries.values() if isinstance(value, dict) and value.get("enabled") is True)
            settings.append(row(HARNESS_ID, "openclaw.json", "plugins.entries.*.enabled", count, "enabled_plugins", shown=f"{count} enabled plugin" + ("s" if count != 1 else "")))

    skills = config.get("skills")
    if isinstance(skills, dict):
        entries = skills.get("entries")
        if isinstance(entries, dict):
            count = sum(1 for value in entries.values() if isinstance(value, dict) and value.get("enabled") is True)
            settings.append(row(HARNESS_ID, "openclaw.json", "skills.entries.*.enabled", count, "user_skills", shown=f"{count} enabled skill" + ("s" if count != 1 else "")))

    roles = (
        ("workspace/AGENTS.md", "project_instructions", "AGENTS.md present"),
        ("workspace/SOUL.md", "agent_persona", "SOUL.md present"),
        ("workspace/IDENTITY.md", "agent_identity", "IDENTITY.md present"),
        ("workspace/USER.md", "user_profile_file", "USER.md present"),
    )
    for relative_path, semantic_id, shown in roles:
        if safe_file(root, *Path(relative_path).parts) is not None:
            settings.append(row(HARNESS_ID, relative_path, "file_presence", True, semantic_id, shown=shown))

    return settings, skipped_files
