from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_toml, row, safe_file, skipped


HARNESS_ID = "codex"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [skipped(HARNESS_ID, "auth.json", "secret")]

    config = load_toml(root, "config.toml")
    if "model" in config:
        settings.append(row(HARNESS_ID, "config.toml", "model", config["model"], "default_model"))
    if "model_reasoning_effort" in config:
        settings.append(row(HARNESS_ID, "config.toml", "model_reasoning_effort", config["model_reasoning_effort"], "reasoning_effort"))
    if "approvals_reviewer" in config:
        settings.append(row(HARNESS_ID, "config.toml", "approvals_reviewer", config["approvals_reviewer"], None, edge="unmapped"))
    if "openai_base_url" in config:
        settings.append(row(HARNESS_ID, "config.toml", "openai_base_url", True, "provider_endpoint", edge="non_equivalent", shown="present"))

    projects = config.get("projects")
    if isinstance(projects, dict) and projects:
        settings.append(row(HARNESS_ID, "config.toml", "projects.*.trust_level", len(projects), "folder_trust", edge="non_equivalent", shown=f"{len(projects)} trusted folder"))
    mcp = config.get("mcp_servers")
    if isinstance(mcp, dict):
        settings.append(row(HARNESS_ID, "config.toml", "mcp_servers", len(mcp), "mcp_server_list", shown=f"{len(mcp)} MCP server"))
    plugins = config.get("plugins")
    if isinstance(plugins, dict):
        settings.append(row(HARNESS_ID, "config.toml", "plugins.*.enabled", len(plugins), "enabled_plugins", shown=f"{len(plugins)} enabled plugin"))
    skills = config.get("skills")
    if isinstance(skills, dict) and isinstance(skills.get("config"), list):
        count = len(skills["config"])
        settings.append(row(HARNESS_ID, "config.toml", "skills.config", count, "user_skills", shown=f"{count} configured skill"))

    if safe_file(root, "AGENTS.md") is not None:
        settings.append(row(HARNESS_ID, "AGENTS.md", "file_presence", True, "project_instructions", shown="AGENTS.md"))
    if safe_file(root, "session_index.jsonl") is not None:
        settings.append(row(HARNESS_ID, "session_index.jsonl", "id,thread_name,updated_at", True, "prior_transcript", shown="session index present"))

    return settings, skipped_files
