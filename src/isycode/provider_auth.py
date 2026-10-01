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


def auth_methods(name: str) -> list[dict]:
    from isycode.providers import PRESETS
    if name not in PRESETS:
        return []
    if name in {'openai', 'chatgpt'}:
        return [dict(id='api_key', label='OpenAI API key', billing='OpenAI API quota'),
                dict(id='browser', label='ChatGPT subscription · browser', billing='ChatGPT plan limits'),
                dict(id='device', label='ChatGPT subscription · device code', billing='ChatGPT plan limits')]
    if not PRESETS[name].get('key_required', True):
        return [dict(id='local', label='Local endpoint', billing='Local compute')]
    return [dict(id='api_key', label='API key', billing='Provider API quota')]


def connector_home() -> Path:
    return (state_root() / 'accounts' / 'chatgpt-codex').absolute()


def codex_executable() -> str:
    candidate = os.environ.get('ISYCODE_CODEX_EXECUTABLE') or shutil.which('codex')
    if not candidate:
        raise ValueError('Official Codex CLI is not installed')
    path = Path(candidate).expanduser().resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Official Codex CLI is not executable')
    return str(path)


def connector_identity(executable: str | None = None) -> dict:
    return {'auth_method': 'chatgpt', 'executable': executable or codex_executable(),
            'home': str(connector_home()), 'credential_store': 'keyring',
            'environment_access': False, 'protocol': 'codex-app-server-v2',
            'hosts': list(AUTH_HOSTS)}


def connector_scope_matches(grant: dict, identity: dict) -> bool:
    return (grant.get('enabled') is True and 'chatgpt' in grant.get('targets', [])
            and identity.get('executable') in grant.get('executables', [])
            and set(AUTH_HOSTS).issubset(grant.get('network_hosts', [])))


class ProviderAuthOwner:
    """Manage only an official connector login, with no token reads or API fallback."""
    def __init__(self, root, authority, approvals, *, executable=None, connector_factory=None):
        self.root = Path(root).resolve(strict=True)
        self.authority, self.approvals = authority, approvals
        self.executable = executable or codex_executable()
        self.connector_factory = connector_factory
        self.gate = ProductActionGate(self.root, authority, owner_id='provider_auth')
        self.connector = None
        self.active_request = None
        self.challenge = None

    def request(self, operation: str, method: str = 'device') -> ActionRequest:
        if operation not in {'login', 'logout'} or method not in {'browser', 'device'}:
            raise ValueError('Unsupported authentication operation')
        return ActionRequest('provider.authenticate', self.root, 'chatgpt',
                             {'operation': operation, 'method': method,
                              'connector': connector_identity(self.executable)},
                             execution_owner='provider_auth')

    def _scope_valid(self) -> bool:
        try:
            grant = self.authority.effective_policy()['grants'].get('provider.authenticate', {})
            return connector_scope_matches(grant, connector_identity(self.executable))
        except (OSError, ValueError):
            return False

    def _result(self, request, status, decision='ALLOW'):
        result = f'chatgpt:{status}'
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
        try:
            expected = self.request(request.parameters.get('operation'), request.parameters.get('method'))
        except (AttributeError, ValueError, OSError):
            return ActionOutcome('Authentication denied.', 'DENY', None, 'invalid login request'), None
        if request != expected:
            return ActionOutcome('Authentication denied.', 'DENY', None, 'login identity changed'), None
        _, decision = self.gate.authorize(request, approvals=self.approvals, approval=approval)
        if not decision.allowed:
            reason = '; '.join(check.reason for check in decision.checks if not check.passed)
            return ActionOutcome('Authentication denied.', 'DENY', None, reason), None
        await self.cancel()
        if self.connector_factory is None:
            from isycode.codex_connector import CodexConnector
            factory = CodexConnector
        else:
            factory = self.connector_factory
        self.active_request = request
        self.connector = factory(self.executable, connector_home(), timeout_s=300)
        try:
            await self._while_granted(self.connector.__aenter__())
            if request.parameters['operation'] == 'logout':
                await self._while_granted(self.connector.logout())
                await self.cancel()
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
            if not account.get('authenticated') or account.get('method') != 'chatgpt':
                return self._result(request, 'subscription login not established', 'ERROR'), None
            return self._result(request, 'signed-in'), account
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
