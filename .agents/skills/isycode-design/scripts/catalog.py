#!/usr/bin/env python3
"""Read-only lookup and integrity checks for ISyCode Design Skills."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

CORE = Path(__file__).resolve().parents[1]
SKILLS = CORE.parent
CATALOG = CORE / "references/catalog.json"

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))

def load() -> dict:
    data = json.loads(CATALOG.read_text())
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported catalog schema")
    return data

def entry_path(entry: dict) -> Path:
    target = (SKILLS / entry["path"]).resolve()
    if not target.is_relative_to(SKILLS.resolve()) or target.name != "SKILL.md":
        raise ValueError("Invalid catalog resource path")
    return target

def check(data: dict) -> list[str]:
    errors = []
    names = [e["name"] for e in data["skills"]]
    if len(names) != len(set(names)):
        errors.append("Duplicate skill names")
    for entry in data["skills"]:
        path = entry_path(entry)
        if not path.is_file():
            errors.append(f"Missing skill: {entry['name']}")
            continue
        if digest(path) != entry["sha256"]:
            errors.append(f"Changed SKILL.md: {entry['name']}; review and update the registry fingerprint")
        text = path.read_text()
        if not re.match(r"^---\nname: " + re.escape(entry["name"]) + r"\n", text):
            errors.append(f"Wrong frontmatter name: {entry['name']}")
        if not (path.parent / "agents/openai.yaml").is_file():
            errors.append(f"Missing UI metadata: {entry['name']}")
    # Check maintained Markdown links in the library, including shared references.
    for path in sorted(SKILLS.glob("isycode-*/*.md")) + sorted(SKILLS.glob("isycode-*/references/*.md")):
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if target.startswith(("https://", "http://", "#")):
                continue
            target = target.split("#", 1)[0]
            if not (path.parent / target).exists():
                errors.append(f"Broken reference in {path.relative_to(SKILLS)}: {target}")
    tokens = json.loads((CORE / "assets/tokens.json").read_text())
    palette = {v.lower() for v in tokens["colors"].values()}
    if not all(re.fullmatch(r"#[0-9a-f]{6}", value) for value in palette):
        errors.append("Invalid palette color")
    css_colors = set(re.findall(r"#[0-9a-fA-F]{6}", (CORE / "assets/tokens.tcss").read_text().lower()))
    if css_colors != palette:
        errors.append("TCSS palette differs from tokens.json")
    return errors

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List the registered skills")
    search = sub.add_parser("search", help="Find all query words in names, summaries and tags")
    search.add_argument("query", nargs="+")
    show = sub.add_parser("show", help="Print one registered SKILL.md")
    show.add_argument("name")
    sub.add_parser("check", help="Check fingerprints, references and palette consistency")
    args = parser.parse_args()
    try:
        data = load()
        entries = data["skills"]
        if args.command == "check":
            errors = check(data)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print(f"OK: {len(entries)} skills; fingerprints, references and palette consistent")
            print("Scope: authoring catalog integrity; runtime TUI behavior is not checked")
            return 0
        if args.command == "show":
            entry = next((e for e in entries if e["name"] == args.name), None)
            if entry is None:
                print("Unknown registered skill: " + args.name, file=sys.stderr)
                return 2
            path = entry_path(entry)
            if digest(path) != entry["sha256"]:
                print("Skill fingerprint changed; review it with check before use", file=sys.stderr)
                return 1
            print(path.read_text(), end="")
            return 0
        if args.command == "search":
            words = normalized(" ".join(args.query)).split()
            entries = [e for e in entries if all(w in normalized(" ".join([e["name"], e["title"], e["summary"], *e["tags"]])) for w in words)]
        for entry in entries:
            print(entry["name"] + " | " + entry["title"])
        if not entries:
            print("No matching skills")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print("Catalog error: " + str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
