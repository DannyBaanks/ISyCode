from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_jsonc, row, skipped


HARNESS_ID = "copilot"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [skipped(HARNESS_ID, "logs/", "unknown")]
    config = load_jsonc(root, "config.json")

    trusted = config.get("trustedFolders")
    if isinstance(trusted, list):
        count = len(trusted)
        settings.append(row(
            HARNESS_ID,
            "config.json",
            "trustedFolders",
            count,
            "folder_trust",
            edge="non_equivalent",
            shown=f"{count} trusted folder" + ("s" if count != 1 else ""),
        ))

    return settings, skipped_files
