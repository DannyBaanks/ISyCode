"""Desktop by default, bundled TUI and explicit legacy metadata migration."""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "accounts":
        from .accounts import main as accounts_main
        return accounts_main(args[1:])
    if args == ["--self-check"]:
        from .self_check import main as self_check
        return self_check()
    if args and args[0] == "tui":
        from isyvm.agent_cli import main as tui_main
        return tui_main(args[1:] or ["chat"])
    if args and args[0] == "migrate":
        from core.ide_state import migrate_provider_metadata, migrate_project_metadata
        parser = argparse.ArgumentParser(prog="isycode-ide migrate", description="Migración aditiva, sin importar credenciales")
        parser.add_argument("--project", help="Migrar metadatos de un proyecto, en lugar de providers globales")
        migration = parser.parse_args(args[1:])
        try:
            result = migrate_project_metadata(migration.project) if migration.project else migrate_provider_metadata()
        except (OSError, ValueError):
            print("No se pudo importar la configuración. El origen se conserva.", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["conflicts"] else 0
    parser = argparse.ArgumentParser(prog="isycode-ide", description="ISyCode IDE — interfaz gráfica nativa")
    parser.add_argument("workspace", nargs="?", help="Carpeta del proyecto")
    parser.epilog = "Otros modos: isycode-ide tui [comandos] · accounts (suscripciones) · migrate (solo metadatos) · --self-check"
    parsed = parser.parse_args(args)
    try:
        from ui.main import main as gui_main
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            print('Instala la interfaz: pip install "isycode-ide[ui]"', file=sys.stderr)
            return 1
        raise
    return gui_main(parsed.workspace)


if __name__ == "__main__":
    raise SystemExit(main())
