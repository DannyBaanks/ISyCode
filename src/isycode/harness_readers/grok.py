from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_json, load_toml, row, safe_file, skipped


HARNESS_ID = "grok"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [
        skipped(HARNESS_ID, "auth.json", "secret"),
        skipped(HARNESS_ID, "agent_id", "identity"),
        skipped(HARNESS_ID, "models_cache.json", "unknown"),
        skipped(HARNESS_ID, "settings_cache.json", "unknown"),
        skipped(HARNESS_ID, "prompt_context.json", "unknown"),
        skipped(HARNESS_ID, "system_prompt.txt", "unknown"),
    ]

    config = load_toml(root, "config.toml")
    ui = config.get("ui")
    if isinstance(ui, dict):
        mappings = (
            ("yolo", "approval_bypass", "same"),
            ("vim_mode", "vim_mode", "same"),
            ("fork_secondary_model", "fork_secondary_model", "same"),
            ("auto_dark_theme", "ui_auto_dark_theme", "same"),
        )
        for key, semantic_id, edge in mappings:
            if key in ui:
                settings.append(row(HARNESS_ID, "config.toml", f"ui.{key}", ui[key], semantic_id, edge=edge))
        if "permission_mode" in ui:
            settings.append(row(
                HARNESS_ID,
                "config.toml",
                "ui.permission_mode",
                ui["permission_mode"],
                None,
                edge="unmapped",
            ))

    trusted = load_toml(root, "trusted_folders.toml")
    folders = trusted.get("folders")
    if isinstance(folders, dict):
        trusted_count = sum(
            1 for value in folders.values()
            if isinstance(value, dict) and value.get("trusted") is True
        )
        if trusted_count:
            settings.append(row(
                HARNESS_ID,
                "trusted_folders.toml",
                "folders.*.trusted",
                trusted_count,
                "folder_trust",
                edge="non_equivalent",
                shown=f"{trusted_count} trusted folder" + ("s" if trusted_count != 1 else ""),
            ))

    sessions_root = root / "sessions"
    transcript_count = 0
    if sessions_root.is_dir() and not sessions_root.is_symlink():
        for summary_path in sorted(sessions_root.glob("*/*/summary.json")):
            try:
                relative = summary_path.relative_to(root).as_posix()
            except ValueError:
                continue
            summary = load_json(root, relative)
            for key, semantic_id, edge in (
                ("current_model_id", "session_model", "same"),
                ("sandbox_profile", "sandbox_policy", "same"),
            ):
                if key in summary:
                    settings.append(row(HARNESS_ID, relative, key, summary[key], semantic_id, edge=edge))
            if "reasoning_effort" in summary:
                settings.append(row(
                    HARNESS_ID,
                    relative,
                    "reasoning_effort",
                    summary["reasoning_effort"],
                    None,
                    edge="unmapped",
                ))
            if "num_messages" in summary:
                settings.append(row(
                    HARNESS_ID,
                    relative,
                    "num_messages",
                    summary["num_messages"],
                    None,
                    edge="unmapped",
                ))

        for history_path in sorted(sessions_root.glob("*/*/chat_history.jsonl")):
            try:
                relative = history_path.relative_to(root).as_posix()
            except ValueError:
                continue
            if safe_file(root, *Path(relative).parts) is not None:
                transcript_count += 1

    if transcript_count:
        settings.append(row(
            HARNESS_ID,
            "sessions/*/*/chat_history.jsonl",
            "filename",
            transcript_count,
            "prior_transcript",
            shown=f"{transcript_count} transcript file" + ("s" if transcript_count != 1 else ""),
        ))

    return settings, skipped_files
