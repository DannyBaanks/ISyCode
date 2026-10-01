"""Local diagnostic metadata: no network probes or credential values."""
from __future__ import annotations

import json
import os
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import urlsplit

from isycode.command_runner import sandbox_executable
from isycode.providers import PRESETS, selected_model_name, selected_provider_name
from isycode.user_defaults import UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority


def collect_diagnostics(root: Path) -> dict:
    dependencies = {'python': platform.python_version()}
    for name in ('isycode', 'textual', 'rich', 'aiohttp', 'keyring', 'anthropic'):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = 'not-installed'
    name = selected_provider_name()
    preset = PRESETS.get(name, {})
    url = os.environ.get('ISYCODE_BASE_URL') or os.environ.get('ISYMOTRON_BASE_URL') or preset.get('base_url', '')
    if name == 'chatgpt':
        url = preset.get('base_url', '')
    try:
        parsed = urlsplit(url)
        endpoint = ('invalid-credential-bearing-url' if parsed.username or parsed.password or parsed.query
                    else parsed.hostname or 'not-configured')
    except ValueError:
        endpoint = 'invalid-url'
    credential = ('environment-present' if os.environ.get(preset.get('key_env', ''))
                  else 'not-required' if preset.get('key_required') is False
                  else 'environment-absent; saved keys require an authorized lookup')
    if name == 'chatgpt':
        credential = 'subscription; sign-in verified on request; dedicated Codex account and unlocked OS keyring required'
    try:
        UserDefaultsStore().load()
        defaults = 'valid'
    except (OSError, ValueError):
        defaults = 'invalid; inspect private user defaults'
    try:
        authority = WorkspaceAuthority(root)
        policy = authority.effective_policy()
        mode = authority.mode() or 'security'
        grants = sorted(action for action, grant in policy.get('grants', {}).items() if grant.get('enabled'))
    except (OSError, ValueError):
        mode, grants = 'unavailable; actions remain denied', []
    return {'version': 1, 'network_tested': False, 'dependencies': dependencies,
            'provider': {'name': name if name in PRESETS else 'unknown',
                         'model_selected': bool(selected_model_name()),
                         'credential': credential, 'endpoint': endpoint,
                         'connection': 'not-tested; use /check for an explicit owned request'},
            'defaults': defaults, 'workspace_mode': mode, 'enabled_actions': grants,
            'command_sandbox': 'ingredients-installed; execution not-probed' if sandbox_executable()
                               else 'unavailable; needs Linux bubblewrap, libseccomp and /usr/bin/python3',
            'next_steps': ['Use Settings → Authority to inspect scoped permissions.',
                           'Use /context to read AGENTS.md with a workspace read grant.',
                           'Use /check only when a provider and its network permission are configured.']}


def format_diagnostics(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
