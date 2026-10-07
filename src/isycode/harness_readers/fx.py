from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_json, row, safe_file, skipped


HARNESS_ID = "fx"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [
        skipped(HARNESS_ID, "settings.json#credential_source", "secret"),
        skipped(HARNESS_ID, "auth.json", "secret"),
        skipped(HARNESS_ID, "auth.lock", "secret"),
        skipped(HARNESS_ID, "chatgpt-auth.json", "secret"),
        skipped(HARNESS_ID, "chatgpt-auth.lock", "secret"),
    ]

    config = load_json(root, "settings.json")
    provider = config.get("provider")
    models = config.get("models")
    if isinstance(provider, str) and isinstance(models, dict):
        model = models.get("gateway") or models.get("codex")
        if isinstance(model, str):
            settings.append(row(
                HARNESS_ID,
                "settings.json",
                "provider+models.gateway",
                model,
                "default_model",
                provider_id=provider,
                model_id=model,
            ))
    if "effort" in config:
        settings.append(row(HARNESS_ID, "settings.json", "effort", config["effort"], "reasoning_effort"))

    sessions_root = root / "sessions"
    transcript_count = 0
    if sessions_root.is_dir() and not sessions_root.is_symlink():
        for session_file in sorted(sessions_root.glob("*/session.json")):
            try:
                rel = session_file.relative_to(root).as_posix()
            except ValueError:
                continue
            session = load_json(root, rel)
            session_model = session.get("model")
            session_provider = session.get("provider")
            if isinstance(session_model, str):
                settings.append(row(
                    HARNESS_ID,
                    rel,
                    "model",
                    session_model,
                    "session_model",
                    provider_id=session_provider if isinstance(session_provider, str) else None,
                    model_id=session_model,
                ))
            transcript_count += 1

            permissions_rel = str(Path(rel).with_name("permissions.json"))
            permissions = load_json(root, permissions_rel)
            rules = permissions.get("rules")
            if isinstance(rules, list):
                settings.append(row(
                    HARNESS_ID,
                    permissions_rel,
                    "rules",
                    len(rules),
                    "shell_approval",
                    edge="non_equivalent",
                    shown=f"{len(rules)} permission rule" + ("s" if len(rules) != 1 else ""),
                ))

    if transcript_count:
        settings.append(row(
            HARNESS_ID,
            "sessions/*/session.json",
            "filename",
            transcript_count,
            "prior_transcript",
            shown=f"{transcript_count} session file" + ("s" if transcript_count != 1 else ""),
        ))

    return settings, skipped_files
