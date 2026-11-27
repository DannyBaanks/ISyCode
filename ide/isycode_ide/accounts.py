"""Explicit account management for the Qt/TUI shared subscription service."""
import argparse
import asyncio
import json
import sys

from core.subscriptions import KINDS, SubscriptionService


def main(args):
    parser = argparse.ArgumentParser(prog="isycode-ide accounts")
    parser.add_argument("action", choices=["configure", "inspect", "login", "logout"])
    parser.add_argument("kind", choices=list(KINDS))
    parser.add_argument("--executable", help="CLI oficial instalado, para configure")
    options = parser.parse_args(args)
    service = SubscriptionService()
    try:
        if options.action == "configure":
            result = service.configure(options.kind, options.executable)
        elif options.action == "login":
            def challenge(value):
                print(value.get("message", "Abre esta dirección oficial y completa el acceso:"), flush=True)
                if value.get("url"):
                    print(value["url"], flush=True)
            result = asyncio.run(service.login(options.kind, challenge))
        elif options.action == "logout":
            result = asyncio.run(service.logout(options.kind))
        else:
            result = asyncio.run(service.inspect(options.kind))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print("Acceso cancelado.", file=sys.stderr)
        return 130
    except Exception:
        print("No se pudo completar la operación. Comprueba el CLI y su perfil privado en Providers → Suscripciones.", file=sys.stderr)
        return 1
