"""Provider auth capabilities and owned, explicit subscription login lifecycle."""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import shutil

from isycode.action_runtime import ActionOutcome, ActionReceipt, ProductActionGate
from isycode.security import ActionRequest
from isycode.workspace_setup import state_root

AUTH_HOSTS = ('auth.openai.com', 'chatgpt.com')
CHATGPT_ENDPOINT = 'https://chatgpt.com/backend-api/codex'
ANTIGRAVITY_AUTH_HOSTS = ('accounts.google.com', 'daily-cloudcode-pa.googleapis.com')
ANTIGRAVITY_ENDPOINT = 'https://daily-cloudcode-pa.googleapis.com'
CLAUDE_AUTH_HOSTS = ('claude.com', 'claude.ai', 'api.anthropic.com')
CLAUDE_ENDPOINT = 'https://api.anthropic.com'
SUBSCRIPTION_PROVIDERS = ('chatgpt', 'antigravity', 'claude')


def auth_methods(name: str) -> list[dict]:
    from isycode.providers import PRESETS
    if name not in PRESETS:
        return []
    if name in {'openai', 'chatgpt'}:
        return [dict(id='api_key', label='OpenAI API key', billing='OpenAI API quota'),
                dict(id='browser', label='ChatGPT subscription · browser', billing='ChatGPT plan limits'),
                dict(id='device', label='ChatGPT subscription · device code', billing='ChatGPT plan limits')]
    if name == 'antigravity':
        return [dict(id='browser', label='Google Antigravity · browser OAuth', billing='Antigravity subscription limits')]
    if name == 'claude':
        return [dict(id='browser', label='Claude subscription · browser sign-in', billing='Claude plan limits')]
    if not PRESETS[name].get('key_required', True):
        return [dict(id='local', label='Local endpoint', billing='Local compute')]
    return [dict(id='api_key', label='API key', billing='Provider API quota')]


def connector_home(slot: str | None = None) -> Path:
    from isycode.account_slots import slot_home
    return slot_home('chatgpt', slot)


def antigravity_home(slot: str | None = None) -> Path:
    from isycode.account_slots import slot_home
    return slot_home('antigravity', slot)


def claude_home(slot: str | None = None) -> Path:
    from isycode.account_slots import slot_home
    return slot_home('claude', slot)


def subscription_home(provider: str, slot: str | None = None) -> Path:
    if provider == 'chatgpt':
        return connector_home(slot)
    if provider == 'antigravity':
        return antigravity_home(slot)
    if provider == 'claude':
        return claude_home(slot)
    raise ValueError(f'Unsupported subscription provider: {provider}')


def subscription_auth_hosts(provider: str) -> tuple[str, ...]:
    if provider == 'chatgpt':
        return AUTH_HOSTS
    if provider == 'antigravity':
        return ANTIGRAVITY_AUTH_HOSTS
    if provider == 'claude':
        return CLAUDE_AUTH_HOSTS
    raise ValueError(f'Unsupported subscription provider: {provider}')


def codex_executable() -> str:
    candidate = os.environ.get('ISYCODE_CODEX_EXECUTABLE') or shutil.which('codex')
    if not candidate:
        raise ValueError('Official Codex CLI is not installed')
    path = Path(candidate).expanduser().resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Official Codex CLI is not executable')
    return str(path)


def antigravity_executable() -> str:
    candidate = os.environ.get('ISYCODE_AGY_EXECUTABLE') or shutil.which('agy')
    if not candidate:
        raise ValueError('Official Antigravity CLI (agy) is not installed')
    path = Path(candidate).expanduser().resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Official Antigravity CLI (agy) is not executable')
    return str(path)


def claude_executable() -> str:
    candidate = os.environ.get('ISYCODE_CLAUDE_EXECUTABLE') or shutil.which('claude')
    if not candidate:
        raise ValueError('Official Claude Code CLI (claude) is not installed')
    path = Path(candidate).expanduser().resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Official Claude Code CLI (claude) is not executable')
    return str(path)


def connector_identity(executable: str | None = None, *, slot: str | None = None) -> dict:
    from isycode.account_slots import PRIMARY_SLOT, active_slot, validate_slot_name
    resolved_slot = validate_slot_name(slot) if slot is not None else active_slot('chatgpt')
    identity = {'auth_method': 'chatgpt', 'executable': executable or codex_executable(),
                'home': str(connector_home(resolved_slot)), 'credential_store': 'keyring',
                'environment_access': False, 'protocol': 'codex-app-server-v2',
                'hosts': list(AUTH_HOSTS)}
    if resolved_slot != PRIMARY_SLOT:
        identity['account_slot'] = resolved_slot
    return identity


def antigravity_identity(executable: str | None = None, *, slot: str | None = None) -> dict:
    from isycode.account_slots import PRIMARY_SLOT, active_slot, validate_slot_name
    resolved_slot = validate_slot_name(slot) if slot is not None else active_slot('antigravity')
    identity = {'auth_method': 'antigravity', 'executable': executable or antigravity_executable(),
                'home': str(antigravity_home(resolved_slot)), 'credential_store': 'official-cli',
                'environment_access': False, 'protocol': 'antigravity-acp-v1',
                'hosts': list(ANTIGRAVITY_AUTH_HOSTS)}
    if resolved_slot != PRIMARY_SLOT:
        identity['account_slot'] = resolved_slot
    return identity


def claude_identity(executable: str | None = None, *, slot: str | None = None) -> dict:
    from isycode.account_slots import PRIMARY_SLOT, active_slot, validate_slot_name
    resolved_slot = validate_slot_name(slot) if slot is not None else active_slot('claude')
    identity = {'auth_method': 'claude', 'executable': executable or claude_executable(),
                'home': str(claude_home(resolved_slot)), 'credential_store': 'official-cli',
                'environment_access': False, 'protocol': 'claude-code-stream-json-v1',
                'hosts': list(CLAUDE_AUTH_HOSTS)}
    if resolved_slot != PRIMARY_SLOT:
        identity['account_slot'] = resolved_slot
    return identity


def subscription_identity(provider: str, executable: str | None = None, *,
                          slot: str | None = None) -> dict:
    if provider == 'chatgpt':
        return connector_identity(executable, slot=slot)
    if provider == 'antigravity':
        return antigravity_identity(executable, slot=slot)
    if provider == 'claude':
        return claude_identity(executable, slot=slot)
    raise ValueError(f'Unsupported subscription provider: {provider}')


def connector_scope_matches(grant: dict, identity: dict, *, target: str | None = None) -> bool:
    provider = target or identity.get('auth_method') or 'chatgpt'
    hosts = subscription_auth_hosts(provider)
    return (grant.get('enabled') is True and provider in grant.get('targets', [])
            and identity.get('executable') in grant.get('executables', [])
            and set(hosts).issubset(grant.get('network_hosts', [])))


class ProviderAuthOwner:
    """Manage only an official connector login, with no token reads or API fallback."""
    def __init__(self, root, authority, approvals, *, executable=None, connector_factory=None,
                 provider: str = 'chatgpt', slot: str | None = None):
        if provider not in SUBSCRIPTION_PROVIDERS:
            raise ValueError('Unsupported subscription provider')
        from isycode.account_slots import active_slot, validate_slot_name
        self.root = Path(root).resolve(strict=True)
        self.authority, self.approvals = authority, approvals
        self.provider = provider
        self.slot = validate_slot_name(slot) if slot is not None else active_slot(provider)
        if executable is not None:
            self.executable = executable
        elif provider == 'antigravity':
            self.executable = antigravity_executable()
        elif provider == 'claude':
            self.executable = claude_executable()
        else:
            self.executable = codex_executable()
        self.connector_factory = connector_factory
        self.gate = ProductActionGate(self.root, authority, owner_id='provider_auth')
        self.connector = None
        self.active_request = None
        self.active_slot = self.slot
        self.challenge = None

    def request(self, operation: str, method: str = 'device', *, slot: str | None = None) -> ActionRequest:
        allowed_methods = {'browser'} if self.provider in {'antigravity', 'claude'} else {'browser', 'device'}
        if operation not in {'login', 'logout'} or method not in allowed_methods:
            raise ValueError('Unsupported authentication operation')
        from isycode.account_slots import validate_slot_name
        target_slot = validate_slot_name(slot) if slot is not None else self.slot
        return ActionRequest('provider.authenticate', self.root, self.provider,
                             {'operation': operation, 'method': method,
                              'connector': subscription_identity(self.provider, self.executable, slot=target_slot)},
                             execution_owner='provider_auth')

    def _scope_valid(self) -> bool:
        try:
            grant = self.authority.effective_policy()['grants'].get('provider.authenticate', {})
            return connector_scope_matches(
                grant, subscription_identity(self.provider, self.executable, slot=self.active_slot),
                target=self.provider)
        except (OSError, ValueError):
            return False

    def _result(self, request, status, decision='ALLOW'):
        result = f'{self.provider}:{status}'
        if decision != 'ALLOW':
            return ActionOutcome('Subscription account unchanged.', decision, None, status)
        receipt = ActionReceipt('rcpt_' + os.urandom(8).hex(), request.action_id, request.digest,
                                'ALLOW', 'SUCCESS', hashlib.sha256(result.encode()).hexdigest())
        if not self.gate.persist_receipt(request, receipt):
            return ActionOutcome('Subscription state not verifiable.', 'NOT_VERIFIABLE', None,
                                 'durable authentication receipt unavailable')
        return ActionOutcome(result, 'ALLOW', receipt, status)

    async def _while_granted(self, awaitable):
        operation = asyncio.create_task(awaitable)
        async def watch():
            while self._scope_valid():
                await asyncio.sleep(0.05)
        watcher = asyncio.create_task(watch())
        try:
            done, _ = await asyncio.wait({operation, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if watcher in done or not self._scope_valid():
                raise PermissionError('Connector permission revoked')
            return await operation
        finally:
            watcher.cancel()
            if not operation.done(): operation.cancel()
            await asyncio.gather(operation, watcher, return_exceptions=True)

    async def begin(self, request, approval):
        from collections.abc import Mapping
        from isycode.account_slots import PRIMARY_SLOT, record_account_auth, validate_slot_name
        try:
            conn_param = request.parameters.get('connector')
            req_slot = conn_param.get('account_slot', PRIMARY_SLOT) if isinstance(conn_param, Mapping) else PRIMARY_SLOT
            req_slot = validate_slot_name(req_slot)
            expected = self.request(request.parameters.get('operation'), request.parameters.get('method'),
                                    slot=req_slot)
        except (AttributeError, ValueError, OSError):
            return ActionOutcome('Authentication denied.', 'DENY', None, 'invalid login request'), None
        if request != expected:
            return ActionOutcome('Authentication denied.', 'DENY', None, 'login identity changed'), None
        _, decision = self.gate.authorize(request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            reason = '; '.join(check.reason for check in decision.checks if not check.passed)
            return ActionOutcome('Authentication denied.', 'DENY', None, reason), None
        await self.cancel()
        self.active_slot = req_slot
        home = subscription_home(self.provider, req_slot)
        if self.connector_factory is None:
            if self.provider == 'claude':
                from isycode.claude_connector import ClaudeConnector
                self.connector = ClaudeConnector(
                    self.executable, home, timeout_s=300,
                    allow_browser_capture=(request.parameters['operation'] == 'login'))
            elif self.provider == 'antigravity':
                from isycode.antigravity_connector import AntigravityConnector
                self.connector = AntigravityConnector(
                    self.executable, home, timeout_s=300,
                    allow_browser_capture=(request.parameters['operation'] == 'login'))
            else:
                from isycode.codex_connector import CodexConnector
                self.connector = CodexConnector(self.executable, home, timeout_s=300)
        else:
            self.connector = self.connector_factory(self.executable, home, timeout_s=300)
        self.active_request = request
        try:
            await self._while_granted(self.connector.__aenter__())
            if request.parameters['operation'] == 'logout':
                await self._while_granted(self.connector.logout())
                await self.cancel()
                record_account_auth(self.provider, req_slot, authenticated=False)
                return self._result(request, 'signed-out'), None
            self.challenge = await self._while_granted(self.connector.start_login(request.parameters['method']))
            outcome = self._result(request, 'login-started')
            if outcome.decision != 'ALLOW':
                await self.cancel()
                return outcome, None
            return outcome, self.challenge
        except PermissionError:
            await self.cancel()
            return ActionOutcome('Authentication denied.', 'DENY', None, 'connector permission revoked'), None
        except asyncio.CancelledError:
            await self.cancel()
            raise
        except Exception as exc:
            await self.cancel()
            return ActionOutcome('Authentication failed.', 'ERROR', None,
                                 f'official connector failed ({type(exc).__name__})'), None

    async def finish(self):
        if self.connector is None or self.challenge is None or self.active_request is None:
            return ActionOutcome('No active login.', 'DENY', None, 'login is not active'), None
        request = self.active_request
        slot = self.active_slot
        if not self._scope_valid():
            await self.cancel()
            return self._result(request, 'connector grant revoked', 'DENY'), None
        connector, challenge = self.connector, self.challenge
        async def watch():
            while self._scope_valid():
                await asyncio.sleep(0.5)
        waiting = asyncio.create_task(connector.wait_login(challenge['login_id']))
        watching = asyncio.create_task(watch())
        try:
            done, _ = await asyncio.wait({waiting, watching}, return_when=asyncio.FIRST_COMPLETED)
            if watching in done or not self._scope_valid():
                return self._result(request, 'connector grant revoked', 'DENY'), None
            if not await waiting:
                return self._result(request, 'login not completed', 'ERROR'), None
            account = await connector.account()
            if not self._scope_valid():
                return self._result(request, 'connector grant revoked', 'DENY'), None
            if not account.get('authenticated') or account.get('method') != self.provider:
                return self._result(request, 'subscription login not established', 'ERROR'), None
            from isycode.account_slots import record_account_auth
            record_account_auth(self.provider, slot, authenticated=True,
                                plan=account.get('plan'), email=account.get('email'))
            enriched = dict(account)
            enriched['slot'] = slot
            return self._result(request, 'signed-in'), enriched
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._result(request, f'login failed ({type(exc).__name__})', 'ERROR'), None
        finally:
            for task in (waiting, watching):
                task.cancel()
            await asyncio.gather(waiting, watching, return_exceptions=True)
            await self.cancel()

    async def cancel(self):
        connector, self.connector = self.connector, None
        self.active_request = self.challenge = None
        if connector is not None:
            await connector.close()
