from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_toml, row, safe_file, skipped


HARNESS_ID = "kimi"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [
        skipped(HARNESS_ID, "credentials/", "secret"),
        skipped(HARNESS_ID, "oauth/", "secret"),
        skipped(HARNESS_ID, "device_id", "identity"),
        skipped(HARNESS_ID, "config.toml#providers.*.api_key", "secret"),
        skipped(HARNESS_ID, "config.toml#services.*.api_key", "secret"),
    ]

    config = load_toml(root, "config.toml")
    default_model = config.get("default_model")
    providers = config.get("providers")
    managed_provider = "managed:kimi-code"
    if isinstance(default_model, str):
        settings.append(row(
            HARNESS_ID,
            "config.toml",
            "default_model",
            default_model,
            "default_model",
            provider_id=managed_provider,
            model_id=default_model,
        ))
    if isinstance(providers, dict):
        managed = providers.get(managed_provider)
        if isinstance(managed, dict) and "base_url" in managed:
            settings.append(row(
                HARNESS_ID,
                "config.toml",
                'providers."managed:kimi-code".base_url',
                True,
                "provider_endpoint",
                edge="non_equivalent",
                shown="present",
            ))

    thinking = config.get("thinking")
    if isinstance(thinking, dict) and "enabled" in thinking:
        settings.append(row(HARNESS_ID, "config.toml", "thinking.enabled", thinking["enabled"], None, edge="unmapped"))

    tui = load_toml(root, "tui.toml")
    if "theme" in tui:
        settings.append(row(HARNESS_ID, "tui.toml", "theme", tui["theme"], "ui_theme"))
    notifications = tui.get("notifications")
    if isinstance(notifications, dict) and "enabled" in notifications:
        settings.append(row(HARNESS_ID, "tui.toml", "notifications.enabled", notifications["enabled"], "ui_notifications"))

    trust_root = root / "workspace-trust"
    if trust_root.is_dir() and not trust_root.is_symlink():
        count = sum(1 for path in trust_root.iterdir() if not path.is_symlink())
        if count:
            settings.append(row(
                HARNESS_ID,
                "workspace-trust/",
                "entries",
                count,
                "folder_trust",
                edge="non_equivalent",
                shown=f"{count} trust entr" + ("ies" if count != 1 else "y"),
            ))

    transcript_count = 0
    if safe_file(root, "session_index.jsonl") is not None:
        transcript_count += 1
    sessions_root = root / "sessions"
    if sessions_root.is_dir() and not sessions_root.is_symlink():
        for state_file in sessions_root.glob("*/state.json"):
            try:
                rel = state_file.relative_to(root)
            except ValueError:
                continue
            if safe_file(root, *rel.parts) is not None:
                transcript_count += 1
    if transcript_count:
        settings.append(row(
            HARNESS_ID,
            "session_index.jsonl;sessions/*/state.json",
            "index_or_filename",
            transcript_count,
            "prior_transcript",
            shown=f"{transcript_count} transcript index/file" + ("s" if transcript_count != 1 else ""),
        ))

    return settings, skipped_files
