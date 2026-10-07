from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_json, row, safe_file, skipped


HARNESS_ID = "commandcode"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    root = Path(root)
    settings: list[HarnessSetting] = []
    skipped_files = [
        skipped(HARNESS_ID, "auth.json", "secret"),
        # Raw prompt history: past user text, never shown.
        skipped(HARNESS_ID, "history.jsonl", "unknown"),
    ]

    config = load_json(root, "config.json")
    model = config.get("model")
    provider = config.get("provider")
    if isinstance(model, str):
        settings.append(row(
            HARNESS_ID, "config.json", "model", model, "default_model",
            provider_id=provider if isinstance(provider, str) else None, model_id=model,
        ))
        efforts = config.get("reasoningEffort")
        if isinstance(efforts, dict) and isinstance(efforts.get(model), str):
            settings.append(row(HARNESS_ID, "config.json", "reasoningEffort.<model>", efforts[model], "reasoning_effort"))

    # projects/<slug>/<session>.jsonl are conversations; *.checkpoints.jsonl are file snapshots.
    projects = root / "projects"
    count = 0
    if projects.is_dir() and not projects.is_symlink():
        for path in projects.glob("*/*.jsonl"):
            if path.name.endswith(".checkpoints.jsonl"):
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if safe_file(root, *rel.parts) is not None:
                count += 1
    if count:
        settings.append(row(HARNESS_ID, "projects/*/*.jsonl", "filename", count, "prior_transcript",
                            shown=f"{count} transcript file" + ("s" if count != 1 else "")))

    return settings, skipped_files
