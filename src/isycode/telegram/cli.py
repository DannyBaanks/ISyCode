"""Explicit local configuration and foreground service controls; no auto-start."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import secrets
import sys
import time
from pathlib import Path

from isycode.approvals import ActionApprovalStore
from isycode.credential_owner import CredentialOwner, CredentialUseOwner, TELEGRAM_SERVICE
from isycode.credentials import CredentialVault, CredentialVaultError
from isycode.telegram.owner import ACTIONS, Peer
from isycode.telegram.service import TelegramService
from isycode.telegram.state import TelegramStore, ID
from isycode.telegram.transport import TelegramTransport, TelegramError
from isycode.workspace_authority import WorkspaceAuthority


def confirm(text):
    if not sys.stdin.isatty():
        raise PermissionError('interactive local consent required')
    return input(text + ' [s/N] ').strip().casefold() in {'s', 'si', 'sí', 'yes'}


def grant_target(authority, action, target):
    grant = authority.policy()['grants'].get(action, {})
    if action.startswith('credentials.') and grant.get('enabled') is False:
        raise PermissionError('explicit credential denial must be changed locally first')
    targets = set(grant.get('targets', [])) if grant.get('enabled') else set()
    authority.set_grant(action, enabled=True, targets=sorted(targets | {target}))


def read_peer(store):
    value = store.setting('peer')
    if not isinstance(value, dict):
        raise ValueError('profile is not configured')
    peer = Peer(store.profile, **value)
    if not peer.valid():
        raise ValueError('invalid profile pairing')
    return peer


async def verify_pairing(store, transport, expected_user, *, timeout=120, show=print):
    bot = await transport.get_me()
    peer = Peer(store.profile, bot, expected_user, expected_user)
    if not peer.valid():
        raise ValueError('invalid private user identity')
    await transport.ensure_polling()
    pin = secrets.token_hex(6)
    show(f'Bot {bot}; usuario esperado {expected_user}. Desde su chat privado envía: /pair {pin}')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        updates = await asyncio.wait_for(transport.get_updates(store.cursor()), timeout=max(.01, remaining))
        for update in updates:
            if update['update_id'] < store.cursor():
                continue
            message = update.get('message', {})
            matched = (isinstance(message, dict) and peer.accepts(message, message.get('from', {}))
                       and message.get('text') == '/pair ' + pin)
            store.accept_update(update['update_id'], expected_user if matched else 0, {'rejected': not matched})
            if matched:
                return peer
        await asyncio.sleep(.1)
    raise PermissionError('pairing expired')


async def configure(store, root, alias, user_id, *, vault_factory=CredentialVault,
                    transport_factory=TelegramTransport, consent=confirm, secret_input=getpass.getpass):
    if not ID.fullmatch(alias) or type(user_id) is not int or not 0 < user_id < 2**52:
        raise ValueError('invalid alias or expected user')
    with store.service_lock():
        if store.setting('peer') is not None or store.setting('credential_id') is not None or store.workspaces():
            raise ValueError('profile already used; choose a new profile to preserve previous data')
        if store.cursor():
            raise ValueError('profile has prior pairing updates; choose a new profile')
        root = root.resolve(strict=True)
        authority = WorkspaceAuthority(root)
        for action in ('credentials.add', 'credentials.use', 'credentials.revoke'):
            if authority.policy()['grants'].get(action, {}).get('enabled') is False:
                raise PermissionError('explicit credential denial must be changed locally first')
        vault = vault_factory()  # Fail before any network operation if keyring unavailable.
        if not consent(f'Configurar bot personal para {root}, modo {authority.mode()}, usuario {user_id}; verificar en Telegram?'):
            raise PermissionError('setup cancelled')
        token = secret_input('Token de BotFather (no se guarda en archivos): ')
        peer = await verify_pairing(store, transport_factory(lambda: token), user_id)
        if not consent(f'Autorizar bot {peer.bot_id}, chat privado {peer.user_id}, workspace {root}, modo {authority.mode()}: recepción y exportación de contenido/herramientas al servicio Telegram, y uso de credencial en keyring?'):
            raise PermissionError('setup cancelled')
        for action in ('credentials.add', 'credentials.use', 'credentials.revoke'):
            grant_target(authority, action, TELEGRAM_SERVICE)
        approvals = ActionApprovalStore()
        owner = CredentialOwner(root, authority, approvals, vault=vault)
        request = owner.add_request(TELEGRAM_SERVICE, f'Telegram {store.profile}', 'Personal Telegram frontend')
        result = owner.add(request, token, approvals.issue(request))
        if result.decision != 'ALLOW' or not result.receipt:
            raise PermissionError('credential save refused or unverified')
        # Keep the profile disabled until all local configuration has committed.
        store.set_setting('revoked', True)
        store.set_setting('credential_id', result.reason)
        store.set_setting('credential_workspace', str(root))
        store.set_setting('peer', {'bot_id': peer.bot_id, 'user_id': peer.user_id, 'chat_id': peer.chat_id})
        store.add_workspace(alias, root)
        for action in sorted(ACTIONS):
            grant_target(authority, action, peer.target)
        store.set_setting('revoked', False)
        print('Perfil configurado. El servicio sigue detenido.')


def is_running(store):
    try:
        with store.service_lock():
            return False
    except (BlockingIOError, PermissionError):
        return True


async def serve(store):
    peer = read_peer(store)
    key_id = store.setting('credential_id')
    location = store.setting('credential_workspace')
    if not isinstance(location, str) or not isinstance(key_id, str) or store.setting('revoked', False):
        raise PermissionError('profile unavailable')
    root = Path(location).resolve(strict=True)
    if root not in store.workspaces().values():
        raise PermissionError('credential workspace unavailable')
    def secret_reader():
        if store.setting('revoked', False) or store.setting('stop_requested', False):
            return None
        outcome, value = CredentialUseOwner(root, WorkspaceAuthority(root)).secret_for(
            TELEGRAM_SERVICE, 'telegram', key_id=key_id)
        return value if outcome.decision == 'ALLOW' and outcome.receipt else None
    service = TelegramService(store, TelegramTransport(secret_reader))
    try:
        await service.start()
        print(f'Servicio activo: {peer.profile}. Ctrl+C para detener.')
        while service.running:
            await asyncio.sleep(.2)
        if not store.setting('stop_requested', False) and not store.setting('revoked', False):
            raise RuntimeError('service stopped unexpectedly; check local policy or polling conflict')
    finally:
        await service.stop()


def revoke(store):
    peer = read_peer(store)
    if not confirm(f'Revocar perfil {peer.profile}, bot {peer.bot_id}, y su credencial local?'):
        raise PermissionError('revocation cancelled')
    store.revoke_pending()
    for root in store.workspaces().values():
        authority = WorkspaceAuthority(root)
        for action in sorted(ACTIONS):
            grant = authority.policy()['grants'].get(action, {})
            targets = set(grant.get('targets', [])) - {peer.target}
            authority.set_grant(action, enabled=bool(grant.get('enabled') and targets), targets=sorted(targets))
    location, key_id = store.setting('credential_workspace'), store.setting('credential_id')
    if location and key_id:
        root = Path(location)
        approvals = ActionApprovalStore()
        owner = CredentialOwner(root, WorkspaceAuthority(root), approvals)
        request = owner.revoke_request(key_id)
        if request.parameters.get('service') != TELEGRAM_SERVICE:
            raise PermissionError('bound key belongs to another service')
        outcome = owner.revoke(request, approvals.issue(request))
        if outcome.decision != 'ALLOW' or not outcome.receipt:
            raise PermissionError('profile disabled; credential removal not verified')
    print('Perfil revocado; parada solicitada. Historial conservado.')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='isycode telegram', description='Frontend personal de Telegram (opt-in)')
    parser.add_argument('--profile', default='personal')
    commands = parser.add_subparsers(dest='command', required=True)
    cfg = commands.add_parser('configure')
    cfg.add_argument('--user-id', type=int, required=True)
    cfg.add_argument('--workspace', type=Path, default=Path.cwd())
    cfg.add_argument('--alias', default='main')
    for name in ('serve', 'status', 'stop', 'revoke'):
        commands.add_parser(name)
    workspace = commands.add_parser('workspace').add_subparsers(dest='workspace_command', required=True)
    add = workspace.add_parser('add')
    add.add_argument('alias')
    add.add_argument('path', type=Path)
    args = parser.parse_args(argv)
    try:
        store = TelegramStore(args.profile)
        if args.command == 'configure':
            asyncio.run(configure(store, args.workspace, args.alias, args.user_id))
        elif args.command == 'serve':
            asyncio.run(serve(store))
        elif args.command == 'status':
            print(f'Perfil: {store.profile}; configurado: {bool(store.setting("peer"))}; activo: {is_running(store)}; revocado: {store.setting("revoked", False)}')
        elif args.command == 'stop':
            store.set_setting('stop_requested', True)
            print('Parada solicitada; no se matan PIDs.')
        elif args.command == 'revoke':
            revoke(store)
        elif args.command == 'workspace':
            with store.service_lock():
                peer = read_peer(store)
                if store.setting('revoked', False):
                    raise PermissionError('profile revoked')
                root = args.path.resolve(strict=True)
                authority = WorkspaceAuthority(root)
                if not confirm(f'Autorizar {root}, modo {authority.mode()}, para bot {peer.bot_id}, usuario {peer.user_id}, recepción y exportación a Telegram?'):
                    raise PermissionError('workspace setup cancelled')
                store.add_workspace(args.alias, root)
                for action in sorted(ACTIONS):
                    grant_target(authority, action, peer.target)
                print('Workspace registrado.')
        return 0
    except KeyboardInterrupt:
        return 130
    except (CredentialVaultError, TelegramError, OSError, ValueError, TypeError, RuntimeError, TimeoutError, asyncio.TimeoutError) as error:
        # Never print arbitrary exception text, which could contain a token or URL.
        print('Telegram: operación no completada (' + type(error).__name__ + ').', file=sys.stderr)
        return 1
