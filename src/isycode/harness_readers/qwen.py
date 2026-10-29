from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import row, safe_file, skipped


HARNESS_ID = "qwen"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    skipped_files = [
        skipped(HARNESS_ID, "settings.json", "unknown"),
        skipped(HARNESS_ID, "installation_id", "identity"),
        skipped(HARNESS_ID, "usage_record.jsonl", "unknown"),
        skipped(HARNESS_ID, "output-language.md", "unknown"),
    ]
    count = 0
    projects = root / "projects"
    if projects.is_dir() and not projects.is_symlink():
        for path in projects.glob("*/chats/*"):
            if path.suffix not in {".json", ".jsonl"}:
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if safe_file(root, *rel.parts) is not None:
                count += 1
    settings: list[HarnessSetting] = []
    if count:
        settings.append(row(
            HARNESS_ID,
            "projects/*/chats/*.{json,jsonl}",
            "filename",
            count,
            "prior_transcript",
            shown=f"{count} transcript file" + ("s" if count != 1 else ""),
        ))
    return settings, skipped_files
