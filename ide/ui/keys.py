"""Compatibility helpers; credential interpretation belongs to the backend."""

from pathlib import Path
from core.secret_broker import parse_api_credentials


def parse_opencode_auth(path: str | Path) -> dict[str, str]:
    return parse_api_credentials(path)


def import_opencode_keys_ui(controller, path: str | Path) -> dict[str, bool]:
    imported = {}
    for name, key in parse_api_credentials(path).items():
        controller.set_key(name, key)
        imported[name] = True
    return imported
