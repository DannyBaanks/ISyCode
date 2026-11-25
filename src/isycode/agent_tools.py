"""Core local tool routing with frontend-provided reviews/questions.

All effects go through existing ISyCode execution owners. Preparing a review
never grants authority; policy and preview are revalidated on execution.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from isycode.action_runtime import LocalWorkspaceReadOwner, TOOL_ACTIONS
from isycode.agent_questions import validate_question, ASK_USER_TOOL
from isycode.approvals import ActionApprovalStore
from isycode.command_runner import CommandRunOwner, command_tool, COMMAND_DEFAULT_STAGE_BYTES
from isycode.git_owner import GitOwner, GIT_TOOLS
from isycode.security import ActionRequest, _plain
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_trust import quiet_request
from isycode.workspace_write import WorkspaceWriteOwner, write_tools_for_mode


def policy_fingerprint(authority) -> str:
    return hashlib.sha256(json.dumps(authority.effective_policy(), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ReviewMaterial:
    digest: str
    text: str
    label: str
    policy_fingerprint: str


class InteractionPort(Protocol):
    async def review(self, request: ActionRequest, material: ReviewMaterial) -> bool: ...
    async def ask(self, question: dict) -> dict: ...


def prepare_write(owner, arguments: dict, *, edit: bool = False):
    if edit:
        replace_all = arguments.get('replace_all', False)
        if type(replace_all) is not bool:
            raise ValueError('replace_all must be a boolean')
        return owner.preview_edit(arguments.get('path'), arguments.get('old_text'),
                                  arguments.get('new_text'), replace_all)
    return owner.preview(arguments.get('path'), arguments.get('content'))


def prepare_command(owner, arguments: dict):
    return owner.prepare(arguments.get('argv'), arguments.get('cwd', '.'),
                         arguments.get('timeout_s', 120), scope=arguments.get('scope', '.'),
                         max_stage_bytes=arguments.get('max_stage_bytes', COMMAND_DEFAULT_STAGE_BYTES))


class LocalAgentTools:
    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore, interactions: InteractionPort, *, emit=None, guard=None):
        self.root, self.authority = root.resolve(strict=True), authority
        self.approvals, self.interactions = approvals, interactions
        self.emit = emit or (lambda *args: None)
        self.guard = guard or (lambda: None)

    def schemas(self):
        from isycode.action_runtime import workspace_tools_for_mode
        mode = self.authority.mode()
        supported = (set(TOOL_ACTIONS) - {'workspace_read_image'}) | {
            'workspace_write', 'workspace_edit', 'workspace_delete', 'workspace_move',
            'workspace_run', 'git_status', 'git_diff', 'git_commit', 'ask_user'}
        return [tool for tool in [*workspace_tools_for_mode(mode), *write_tools_for_mode(mode),
                command_tool(mode), *GIT_TOOLS, ASK_USER_TOOL]
                if tool['function']['name'] in supported]

    async def approval(self, preview, label, text):
        self.guard()
        request = preview.request
        fingerprint = policy_fingerprint(self.authority)
        if quiet_request(self.authority, request):
            return True, None
        accepted = await self.interactions.review(request, ReviewMaterial(
            request.digest, text, label, fingerprint))
        if accepted is not True or policy_fingerprint(self.authority) != fingerprint:
            return False, None
        self.guard()
        return True, self.approvals.issue(request)

    async def _settled_effect(self, fn, *args):
        self.guard()
        task = asyncio.create_task(asyncio.to_thread(fn, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Do not release the workspace while an owned synchronous effect is running.
            await asyncio.gather(task, return_exceptions=True)
            raise

    @staticmethod
    def _result(outcome):
        if outcome.decision != 'ALLOW' or outcome.receipt is None:
            return json.dumps({'error': 'ISyCode refused the action', 'decision': outcome.decision,
                               'reason': outcome.reason[:300]})
        try:
            result = json.loads(outcome.text)
        except (ValueError, TypeError):
            result = outcome.text
        return json.dumps({'result': result, 'receipt': outcome.receipt.receipt_id}, ensure_ascii=False)

    async def dispatch(self, call: dict) -> tuple[str, str]:
        call_id = call.get('id', '') if isinstance(call, dict) else ''
        try:
            self.guard()
            fn = call['function']
            name = fn['name']
            if name not in {tool['function']['name'] for tool in self.schemas()}:
                raise ValueError('tool is unavailable in this frontend')
            raw = fn.get('arguments', '{}')
            if not isinstance(raw, str) or len(raw) > 65536:
                raise ValueError('tool arguments exceed the protocol limit')
            arguments = json.loads(raw)
            if not isinstance(arguments, dict):
                raise ValueError('tool arguments must be an object')
            if arguments.get('folder', 'main') != 'main':
                raise ValueError('additional folders are unavailable in this frontend')
            arguments.pop('folder', None)
            if name == 'ask_user':
                return call_id, json.dumps(await self.interactions.ask(validate_question(arguments)))
            if name in TOOL_ACTIONS:
                result = await asyncio.to_thread(LocalWorkspaceReadOwner(
                    self.root, self.authority).execute, TOOL_ACTIONS[name], arguments)
                return call_id, self._result(result)
            if name in {'git_status', 'git_diff'}:
                owner = GitOwner(self.root, self.authority, self.approvals)
                result = await asyncio.to_thread(owner.status if name == 'git_status' else owner.diff,
                    *(() if name == 'git_status' else (arguments.get('path', '.'), arguments.get('staged', False))))
                return call_id, self._result(result)
            if name == 'git_commit':
                owner = GitOwner(self.root, self.authority, self.approvals)
                preview = await asyncio.to_thread(owner.preview_commit, arguments.get('message'), arguments.get('paths'))
                accepted, approval = await self.approval(preview, name, preview.diff)
                result = await self._settled_effect(owner.commit, preview, approval) if accepted else None
            elif name == 'workspace_run':
                if arguments.get('background'):
                    raise ValueError('background shell jobs are unavailable; the session itself is asynchronous')
                owner = CommandRunOwner(self.root, self.authority, self.approvals)
                preview = await asyncio.to_thread(prepare_command, owner, arguments)
                accepted, approval = await self.approval(preview, name, json.dumps({
                    'action': preview.request.action_id, 'target': preview.request.target,
                    'workspace': str(self.root), 'parameters': _plain(preview.request.parameters),
                    'scope': preview.scope, 'max_stage_bytes': preview.max_stage_bytes,
                    'host_execution': preview.host_execution}, ensure_ascii=False, indent=2))
                if accepted:
                    self.guard()
                result = await owner.run(preview, approval, on_output=lambda text: self.emit('command.output', {'text': text})) if accepted else None
            elif name in {'workspace_write', 'workspace_edit', 'workspace_delete', 'workspace_move'}:
                owner = WorkspaceWriteOwner(self.root, self.authority, self.approvals)
                if name in {'workspace_write', 'workspace_edit'}:
                    preview = await asyncio.to_thread(prepare_write, owner, arguments, edit=name == 'workspace_edit')
                elif name == 'workspace_delete':
                    preview = await asyncio.to_thread(owner.preview_delete, arguments.get('path'))
                else:
                    preview = await asyncio.to_thread(owner.preview_move, arguments.get('path'), arguments.get('to'))
                accepted, approval = await self.approval(preview, name, preview.diff)
                result = await self._settled_effect(owner.apply, preview, approval) if accepted else None
            else:
                raise ValueError('tool is unavailable in this frontend')
            return call_id, self._result(result) if result else json.dumps({'status': 'rejected_by_user', 'error': 'review rejected or policy changed'})
        except (ValueError, KeyError, TypeError, OSError) as error:
            return call_id, json.dumps({'error': type(error).__name__ + ': ' + str(error)[:240]})
