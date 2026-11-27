"""isyvm - Main entry point."""

from __future__ import annotations
import sys
import subprocess
from pathlib import Path


def run_bootstrap(args: list[str]) -> int:
    """Run legacy bootstrap commands."""
    from engine.bootstrap import main as bootstrap_main
    return bootstrap_main(args)


def run_agent(args: list[str]) -> int:
    """Run agent CLI."""
    from isyvm.agent_cli import main as agent_main
    return agent_main(args)


def main() -> int:
    if len(sys.argv) < 2:
        # No args - show bootstrap help
        return run_bootstrap(["--help"])
    
    cmd = sys.argv[1]
    
    if cmd == "agent":
        # When invoked via isyvm.cmd, the leading "agent" is preserved in %*
        return run_agent(sys.argv[1:])
    else:
        # Legacy bootstrap commands
        return run_bootstrap(sys.argv[1:])


def isycode_main() -> int:
    """Installed ``isycode`` entry point.

    With no arguments it opens the existing Textual agent UI. Subcommands are
    routed to the existing agent CLI or bootstrap CLI; no second command tree
    is created.
    """
    args = sys.argv[1:]
    if not args:
        from isyvm.agent_cli import main as agent_main
        return agent_main(["chat"])
    if args[0] in {"chat", "run", "provider", "secret", "policy", "config", "agent"}:
        from isyvm.agent_cli import main as agent_main
        return agent_main(args)
    if args[0] in {"-h", "--help"}:
        from isyvm.agent_cli import main as agent_main
        return agent_main(["--help"])
    return main()


if __name__ == "__main__":
    sys.exit(main())
