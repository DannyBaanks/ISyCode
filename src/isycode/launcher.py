"""Command dispatcher for the ISyCode TUI and semantic CLI browser."""
from __future__ import annotations

import os
import re
import sys


USAGE = """ISyCode · terminal workspace agent

Usage:
  isycode                 Start the chat TUI in the current directory
  isycode tui              Start the chat TUI
  isycode cli              Browse actions by semantic category
  isycode doctor [--json]  Inspect local dependencies/configuration; no network calls
  isycode sessions ...      List/show/search/rename/delete local conversations; add --json
  isycode models [--json]   Show local provider/model metadata; no network calls
  isycode stats [--json]    Aggregate locally recorded session usage
  isycode dirs [--json]     Show config/state locations and precedence, never values
  isycode completion SHELL  Print bash, zsh or fish completion
  isycode update           Update this ISyCode installation (alias: actualizar)
  isycode update --check   Check for updates without installing or advancing
  isycode update --yes     Pre-approve the stash/merge confirmation
  isycode actualizar       Actualizar el checkout limpio o preparar una instalación
  isycode actualizar --check  Consultar actualizaciones sin instalar ni avanzar la rama
  isycode actualizar --yes    Aceptar de antemano el stash/merge que normalmente se pregunta
  isycode -p "PROMPT"      Answer once and exit (stdin if PROMPT is omitted or -);
                           add --json for machine-readable output. Only read-only
                           tools that were granted run; nothing asks for approval.
  isycode --help           Show this help
  isycode --version        Show the installed version

The CLI browser groups actions by purpose. It does not run arbitrary shell commands.
"""


def _ask(question: str, details: tuple[str, ...]) -> bool:
    for line in details:
        print(f"  {line}")
    return input(f"{question} [s/N] ").strip().casefold() in {"s", "si", "sí", "y", "yes"}


def _print_update_report(report) -> None:
    is_tty = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    last_was_blank = True
    for i, line in enumerate(report.lines):
        is_header = line.endswith(":") and not line.startswith(" ")
        is_tip = line.startswith("Para ver ") or line.startswith("Revisa el cambio") or line.startswith("Para aplicar")
        if (is_header or is_tip) and i > 0 and not last_was_blank:
            print()
            last_was_blank = True

        if not is_tty or not line:
            print(line)
            last_was_blank = not bool(line.strip())
            continue

        styled = line
        if line.startswith("✨") or line.startswith("✓"):
            styled = f"\033[1;32m{line}\033[0m"
        elif line.startswith("⚠️"):
            styled = f"\033[1;33m{line}\033[0m"
        elif line.startswith("Conflicto:") or "falló" in line.casefold() or "error" in line.casefold():
            styled = f"\033[1;31m{line}\033[0m"
        elif is_header:
            styled = f"\033[1;36m{line}\033[0m"
        elif is_tip:
            if ":" in line:
                label, cmd = line.split(":", 1)
                prefix_icon = "🚀" if "aplicar" in label.casefold() else "💡"
                color = "\033[1;35m" if "aplicar" in label.casefold() else "\033[1;34m"
                styled = f"{color}{prefix_icon} {label.strip()}:\033[0m\n   \033[1;37m{cmd.strip()}\033[0m"
        elif line.strip().startswith("• "):
            parts = line.split("• ", 1)
            tokens = parts[1].split(" ", 1)
            if len(tokens) == 2 and re.match(r"^[0-9a-f]{7,12}$", tokens[0]):
                styled = f"{parts[0]}\033[36m•\033[0m \033[1;33m{tokens[0]}\033[0m {tokens[1]}"
            else:
                styled = f"{parts[0]}\033[36m•\033[0m {parts[1]}"
        elif "|" in line and ("+" in line or "-" in line):
            parts = line.split("|", 1)
            file_part = parts[0]
            stat_part = parts[1]
            stat_colored = stat_part.replace("+", "\033[32m+\033[0m").replace("-", "\033[31m-\033[0m")
            styled = f"\033[2m{file_part}|\033[0m{stat_colored}"

        print(styled)
        last_was_blank = not bool(line.strip())


def main(argv: list[str] | None = None) -> int:
    # CLI text and JSON have the same UTF-8 wire format on every platform.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        configure = getattr(stream, 'reconfigure', None)
        if configure is not None:
            try:
                configure(encoding='utf-8')
            except (OSError, ValueError):
                pass  # Embedded/test streams may already have consumed input.
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"update", "actualizar"}:
        from isycode.updater import SelfUpdater

        if arguments[1:] not in ([], ["--check"], ["--yes"]):
            print("Uso: isycode update|actualizar [--check | --yes]", file=sys.stderr)
            return 2
        if arguments[1:] == ["--yes"]:
            confirm = lambda question, details: True  # noqa: E731
        elif sys.stdin.isatty():
            confirm = _ask
        else:
            confirm = None  # no one to ask: never stash or merge on their behalf
        report = SelfUpdater(confirm=confirm).run(check_only=arguments[1:] == ["--check"])
        _print_update_report(report)
        return 1 if report.status in {"blocked", "dirty", "error", "updated-conflicts"} else 0
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
    if arguments and arguments[0] in {"sessions", "models", "stats", "dirs", "completion"}:
        from isycode.inspection_cli import main as inspection_main

        return inspection_main(arguments)
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
            current = "1.0.0rc1 (source checkout)"
        print(f"ISyCode {current}")
        return 0
    print(f"Unknown command: {' '.join(arguments)}\n\n{USAGE}", file=sys.stderr, end="")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
