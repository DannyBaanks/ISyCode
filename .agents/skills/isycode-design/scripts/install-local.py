#!/usr/bin/env python3
"""Expose this versioned skill library in the user's Codex skills directory."""
from pathlib import Path
import json
import os
import sys

CORE = Path(__file__).resolve().parents[1]
SKILLS = CORE.parent
data = json.loads((CORE / "references/catalog.json").read_text())
destination = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills"
items = [(entry["name"], SKILLS / entry["name"], destination / entry["name"]) for entry in data["skills"]]

# Inspect every destination before creating any link. Never replace a skill.
conflicts = []
for name, source, target in items:
    if not (source / "SKILL.md").is_file():
        conflicts.append(f"Missing source: {name}")
    elif os.path.lexists(target) and not (target.is_symlink() and target.resolve() == source.resolve()):
        conflicts.append(f"Existing different destination: {target}")
if conflicts:
    print("\n".join(conflicts), file=sys.stderr)
    raise SystemExit(1)

destination.mkdir(parents=True, exist_ok=True)
for name, source, target in items:
    if os.path.lexists(target):
        print("READY: " + name)
    else:
        target.symlink_to(source.resolve(), target_is_directory=True)
        print("LINKED: " + name)
print("Canonical files stay in the ISyCode repository; reload skills/start a new Codex session to refresh discovery.")
