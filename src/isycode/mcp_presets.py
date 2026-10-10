"""Native opt-in configuration for pinned official MCP packages. Never starts them."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from isycode.mcp_local import config_path, load_config, MAX_CONFIG_BYTES, MAX_SERVERS

PRESETS = {
    'playwright': {'command': ['npx', '-y', '@playwright/mcp@0.0.83'],
                   'description': ('Read-only current-page snapshot; filtered before preview and '
                                   'explicit sharing; npm download on approved start'),
                   'repository': 'https://github.com/microsoft/playwright-mcp'},
    'context7': {'command': ['npx', '-y', '@upstash/context7-mcp@4.1.1'],
                'description': 'Upstash documentation lookup; service limits apply',
                'repository': 'https://github.com/upstash/context7'},
}


def add_preset(name: str, path: Path | None = None) -> None:
    if name not in PRESETS:
        raise ValueError('Unknown MCP preset')
    path = path or config_path()
    configs = load_config(path)
    if name in configs or len(configs) >= MAX_SERVERS:
        raise ValueError('Preset already exists or server limit reached; existing configuration preserved')
    servers = {key: {'command': list(value.argv), 'env': dict(value.env)} for key, value in configs.items()}
    servers[name] = {'command': PRESETS[name]['command']}
    payload = (json.dumps({'servers': servers}, indent=2) + '\n').encode('utf-8')
    if len(payload) > MAX_CONFIG_BYTES:
        raise ValueError('MCP configuration exceeds its limit')
    if path.parent.is_symlink():
        raise ValueError('MCP configuration directory must not be a symlink')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.mcp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(payload); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
