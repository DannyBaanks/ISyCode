"""Check or export the accepted skill palette to the packaged TUI assets."""
from pathlib import Path
import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="export palette and TCSS variables")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / ".agents/skills/isycode-design/assets/tokens.json"
    packaged = root / "src/isycode/assets/design-tokens.json"
    css = root / "src/isycode/design.tcss"
    tokens = source.read_text(encoding="utf-8")
    variables = "\n".join(f"$isy-{name.replace('_', '-')}: {value};"
                          for name, value in json.loads(tokens)["colors"].items())
    current = css.read_text(encoding="utf-8")
    comment, body = current.split("\n", 1)
    _, rules = body.split("\n\n", 1)
    expected = comment + "\n" + variables + "\n\n" + rules
    if args.write:
        packaged.write_text(tokens, encoding="utf-8")
        css.write_text(expected, encoding="utf-8")
    if packaged.read_text(encoding="utf-8") != tokens or css.read_text(encoding="utf-8") != expected:
        raise SystemExit("Design palette drift: run scripts/sync_design_tokens.py --write")
    print("Design tokens match the accepted skill palette.")


if __name__ == "__main__":
    main()
