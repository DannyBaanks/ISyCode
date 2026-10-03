from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_json, row, safe_file, skipped


HARNESS_ID = "pi"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [
        skipped(HARNESS_ID, "agent/auth.json", "secret"),
        skipped(HARNESS_ID, "agent/models-store.json", "oversize"),
    ]

    config = load_json(root, "agent/settings.json")
    if "theme" in config:
        settings.append(row(HARNESS_ID, "agent/settings.json", "theme", config["theme"], "ui_theme"))

    sessions = root / "agent" / "sessions"
    count = 0
    if sessions.is_dir() and not sessions.is_symlink():
        for path in sessions.glob("*/*.jsonl"):
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if safe_file(root, *rel.parts) is not None:
                count += 1
    if count:
        settings.append(row(HARNESS_ID, "agent/sessions/*/*.jsonl", "filename", count, "prior_transcript", shown=f"{count} transcript file" + ("s" if count != 1 else "")))

    return settings, skipped_files
