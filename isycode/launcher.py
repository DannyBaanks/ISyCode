"""Command dispatcher for the ISyCode TUI and semantic CLI browser."""
from __future__ import annotations

import sys


USAGE = """ISyCode · terminal workspace agent

Usage:
  isycode                 Start the chat TUI in the current directory
  isycode tui              Start the chat TUI
  isycode cli              Browse actions by semantic category
  isycode doctor [--json]  Inspect local dependencies/configuration; no network calls
  isycode -p "PROMPT"      Answer once and exit (stdin if PROMPT is omitted or -);
                           add --json for machine-readable output. Only read-only
                           tools that were granted run; nothing asks for approval.
  isycode --help           Show this help
  isycode --version        Show the installed version

The CLI browser groups actions by purpose. It does not run arbitrary shell commands.
"""


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments == ["tui"]:
        from isycode.tui import TUIApp

        TUIApp().run()
        return 0
    if arguments == ["cli"]:
        from isycode.cli import main as cli_main

        cli_main(["cli"])
        return 0
    if arguments in (["doctor"], ["doctor", "--json"]):
        from pathlib import Path
        from isycode.diagnostics import collect_diagnostics, format_diagnostics
        from isycode.config import discover_workspace_identity

        root = discover_workspace_identity(Path.cwd()).workspace_root
        print(format_diagnostics(collect_diagnostics(root)))
        return 0
    if arguments and arguments[0] in {"-p", "--print"} or arguments[:2] in (
            ["--json", "-p"], ["--json", "--print"]):
        from isycode.headless import main as headless_main

        return headless_main(arguments)
    if arguments in (["--help"], ["-h"], ["help"]):
        print(USAGE, end="")
        return 0
    if arguments == ["--version"]:
        from importlib.metadata import PackageNotFoundError, version

        try:
            current = version("isycode")
        except PackageNotFoundError:
            current = "0.1.0 (source checkout)"
        print(f"ISyCode {current}")
        return 0
    print(f"Unknown command: {' '.join(arguments)}\n\n{USAGE}", file=sys.stderr, end="")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
