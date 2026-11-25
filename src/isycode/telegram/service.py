"""Private Telegram frontend: durable intake, native turns, bounded delivery."""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from pathlib import Path

from isycode.agent_runtime import AgentTurn, TurnPorts
from isycode.agent_tools import LocalAgentTools, policy_fingerprint
from isycode.approvals import ActionApprovalStore
from isycode.credential_owner import CredentialUseOwner
from isycode.providers import Provider, PRESETS, resolved_chat_model, selected_provider_name
from isycode.session_owner import ChatSessionOwner
from isycode.state_index import get_state_index
from isycode.telegram.owner import Peer, RemoteReviews, ReviewContext, TelegramOwner
from isycode.telegram.render import RenderedMessage, TelegramRenderer
from isycode.telegram.state import TelegramStore, clean
from isycode.telegram.transport import TelegramError
from isycode.tool_history import record_tool_result, tool_history_context
from isycode.turn_journal import TurnJournal
from isycode.workspace_authority import WorkspaceAuthority


def native_sessions(root, authority):
    return ChatSessionOwner(root, authority, get_state_index().sessions_path(root))


def require_outcome(outcome):
    if outcome.decision != 'ALLOW' or outcome.receipt is None:
        raise PermissionError('native session operation refused or unverified')


def native_provider(root, authority, state):
    name = state.get('provider') or selected_provider_name()
    model = state.get('model') or resolved_chat_model(name)
    key = ''
    if PRESETS[name].get('key_required', True):
        outcome, key = CredentialUseOwner(root, authority).secret_for(name, 'provider.request')
        if outcome.decision != 'ALLOW' or not key:
            raise PermissionError('workspace provider credential unavailable')
    return Provider(name=name, model=model, api_key=key)


class NativeRunner:
    def __init__(self, service, item, *, provider_factory=native_provider, transport=None):
        self.service, self.item = service, item
        self.provider_factory, self.transport = provider_factory, transport

    async def run(self):
        s, item = self.service, self.item
        authority = WorkspaceAuthority(item.workspace)
        owner = native_sessions(item.workspace, authority)
        s.guard(item.workspace)
        outcome, session = owner.resume(item.session_id)
        require_outcome(outcome)
        state = dict(session.state)
        provider = self.provider_factory(item.workspace, authority, state)
        state.update(provider=provider.name, model=provider.model)
        history = state.get('tool_history', [])
        outcome, _ = owner.record(item.session_id, 'user', item.text, state=state)
        require_outcome(outcome)
        messages = [{'role': 'system', 'content': f'You are ISyCode, operating in the locally registered workspace {item.workspace}. Use native tools only.'}]
        if state.get('conversation_summary'):
            from isycode.agent_loop import summary_system_message
            messages.append(summary_system_message(clean(state['conversation_summary'])))
        notes = tool_history_context(clean(history))
        if notes:
            messages.append({'role': 'system', 'content': notes})
        messages += [{'role': m['role'], 'content': m['content']} for m in session.messages]
        messages.append({'role': 'user', 'content': item.text})
        def guard():
            s.guard(item.workspace)
            outcome, _, revision = owner.review(item.session_id)
            require_outcome(outcome)
            if revision != owner.base_revision(item.session_id):
                raise PermissionError('native transcript changed in another frontend')
        buffers = {}
        def flush():
            for kind, parts in buffers.items():
                s.store.append_event(item.turn_id, kind, {'text': ''.join(parts)})
            buffers.clear()
        def emit(kind, payload):
            if kind in {'reasoning', 'content', 'command.output'}:
                parts = buffers.setdefault(kind, [])
                parts.append(payload.get('text', ''))
                if sum(len(p) for p in parts) > 900_000:
                    raise ValueError('stream exceeds Telegram event budget')
            else:
                flush()
                # AgentTurn emits finish before the assistant transcript is saved.
                if kind != 'turn.finish':
                    s.store.append_event(item.turn_id, kind, payload)
        tools = LocalAgentTools(item.workspace, authority, ActionApprovalStore(),
                                Interactions(s, item, authority), emit=emit, guard=guard)
        async def dispatch(call):
            nonlocal history
            guard()
            returned_id, result = await tools.dispatch(call)
            history = clean(record_tool_result(history, call, result))
            return returned_id, result
        async def before_step(_):
            guard()
        journal = TurnJournal.begin(item.workspace, scope=item.session_id) if authority.mode() == 'flow' else None
        pin = journal.pin() if journal else None
        try:
            result = await AgentTurn(item.workspace, authority).run(
                messages, provider=provider, tools=tools.schemas(),
                ports=TurnPorts(emit, dispatch, before_step), transport=self.transport)
            flush()
            guard()
            state['tool_history'] = history
            outcome, _ = owner.record(item.session_id, 'assistant', clean(result.text), state=state)
            require_outcome(outcome)
            s.store.append_event(item.turn_id, 'session.saved', {'receipt': outcome.receipt.receipt_id})
        finally:
            if journal:
                TurnJournal.unpin(pin)
                journal.finish()


class Interactions:
    def __init__(self, service, item, authority):
        self.service, self.item, self.authority = service, item, authority

    async def review(self, request, material):
        s, item = self.service, self.item
        if s.selected != item.session_id:
            return False
        ctx = ReviewContext(s.peer, item.workspace, item.session_id, item.turn_id,
                            policy_fingerprint(self.authority))
        review = s.reviews.open(ctx, material)
        future = asyncio.get_running_loop().create_future()
        try:
            await s.send_owned(item.workspace, RenderedMessage(f'Revisión {material.label} · workspace {item.workspace.name} · sesión {item.session_id} · turno {item.turn_id} · digest {material.digest}'))
            s.store.append_event(item.turn_id, 'review.request', {'action': material.label, 'digest': material.digest})
            for rendered in s.renderer.review_material(material.text):
                await s.send_owned(item.workspace, rendered)
            if not s.reviews.mark_delivered(review.callback_id, hashlib.sha256(material.text.encode()).hexdigest()):
                return False
            receipt = await s.send_owned(item.workspace, s.renderer.review_buttons(review.callback_id))
            s.callbacks[review.callback_id] = (ctx, request, self.authority, receipt.message_id, future)
            accepted = await asyncio.wait_for(future, timeout=120)
            s.store.append_event(item.turn_id, 'review.response', {'accepted': accepted is True, 'digest': material.digest})
            return accepted
        except (TimeoutError, asyncio.TimeoutError, ValueError, PermissionError, TelegramError):
            return False
        finally:
            s.callbacks.pop(review.callback_id, None)
            s.reviews.resolve(review.callback_id, ctx, False, request=request, authority=self.authority)

    async def ask(self, question):
        s, item = self.service, self.item
        if s.selected != item.session_id:
            return {'status': 'cancelled'}
        identity = secrets.token_hex(6)
        future = asyncio.get_running_loop().create_future()
        s.questions[identity] = (item, future)
        try:
            text = question['question'] + '\n' + '\n'.join(question['choices']) + f'\n/respuesta {identity} <texto>'
            s.store.append_event(item.turn_id, 'question.request', {'question': question['question']})
            await s.send_owned(item.workspace, RenderedMessage(clean(text)))
            response = await asyncio.wait_for(future, timeout=120)
            s.store.append_event(item.turn_id, 'question.response', {'status': response.get('status')})
            return response
        except (TimeoutError, asyncio.TimeoutError, PermissionError, TelegramError):
            return {'status': 'cancelled'}
        finally:
            s.questions.pop(identity, None)


class TelegramService:
    def __init__(self, store: TelegramStore, transport, runner_factory=NativeRunner):
        self.store, self.transport, self.runner_factory = store, transport, runner_factory
        self.peer = Peer(store.profile, **store.setting('peer', {}))
        if not self.peer.valid():
            raise ValueError('profile has no valid private pairing')
        self.renderer, self.reviews = TelegramRenderer(), RemoteReviews()
        self.callbacks, self.questions, self.active = {}, {}, {}
        self.selected = store.setting('selected_session')
        self._lock = None
        self._tasks = []
        self.running = False
        self._cancelled = set()

    def _cancel(self, task):
        if task not in self._cancelled and not task.done():
            self._cancelled.add(task)
            task.cancel()

    def guard(self, root):
        if self.store.setting('revoked', False) or self.store.setting('stop_requested', False) or root not in self.store.workspaces().values():
            raise PermissionError('Telegram profile or workspace revoked')
        owner = TelegramOwner(root, WorkspaceAuthority(root))
        owner.authorize('telegram.connect', self.peer)
        owner.authorize('telegram.receive', self.peer)
        return owner

    async def send_owned(self, root, rendered):
        owner = self.guard(root)
        material = json.dumps({'text': rendered.text, 'buttons': rendered.buttons,
                               'filename': rendered.filename, 'document_sha256': hashlib.sha256(rendered.document or b'').hexdigest()},
                              sort_keys=True).encode()
        request = owner.authorize('telegram.send', self.peer, material)
        receipt = await self.transport.send(self.peer.chat_id, rendered)
        if receipt.chat_id != self.peer.chat_id or type(receipt.message_id) is not int or receipt.message_id <= 0:
            raise TelegramError('unverified_delivery')
        owner.receipt(request, str(receipt.message_id).encode())
        return receipt

    def select(self, session_id):
        self.reviews.invalidate()
        for _, _, _, _, future in self.callbacks.values():
            if not future.done():
                future.set_result(False)
        for _, future in self.questions.values():
            if not future.done():
                future.set_result({'status': 'cancelled'})
        self.selected = session_id
        self.store.set_setting('selected_session', session_id)

    def current_root(self):
        return self.store.sessions().get(self.selected)

    async def handle_update(self, update):
        update_id = update.get('update_id')
        if type(update_id) is not int or update_id < self.store.cursor():
            return
        callback = update.get('callback_query')
        message = callback.get('message', {}) if isinstance(callback, dict) else update.get('message', {})
        sender = callback.get('from', {}) if isinstance(callback, dict) else message.get('from', {}) if isinstance(message, dict) else {}
        if not self.peer.accepts(message, sender):
            self.store.accept_update(update_id, 0, {'rejected': True})
            return
        root = self.current_root()
        text = message.get('text') if not callback else None
        if isinstance(text, str) and text.partition(' ')[0] == '/nueva':
            root = self.store.workspaces().get(text.partition(' ')[2])
        elif isinstance(text, str) and text.partition(' ')[0] == '/usar':
            identity = text.partition(' ')[2]
            root = self.store.sessions().get(identity)
            if root is None:
                matches = []
                for candidate in self.store.workspaces().values():
                    if self._can_connect(candidate):
                        outcome, sessions = native_sessions(candidate, WorkspaceAuthority(candidate)).list_conversations()
                        if outcome.decision == 'ALLOW' and outcome.receipt and any(x.session_id == identity for x in sessions):
                            matches.append(candidate)
                if len(matches) == 1:
                    root = matches[0]
        if root is None and text in {'/proyectos', '/inicio', '/ayuda', '/sesiones'}:
            for candidate in self.store.workspaces().values():
                try:
                    self.guard(candidate)
                    root = candidate
                    break
                except PermissionError:
                    continue
        try:
            if root is None:
                raise PermissionError('no bound workspace')
            owner = self.guard(root)
            material = json.dumps(update, sort_keys=True, ensure_ascii=False).encode()
            request = owner.authorize('telegram.receive', self.peer, material)
        except (PermissionError, ValueError, OSError):
            self.store.accept_update(update_id, self.peer.user_id, {'rejected': True})
            return
        if not callback and isinstance(text, str) and text and not text.startswith('/') and len(text) <= 262144:
            result = self.store.accept_update(update_id, self.peer.user_id, {'session_id': self.selected, 'text': text})
            owner.receipt(request, str(result.queue_id).encode())
            if result.queue_id:
                queue = self.store.queue()
                row = next(r for r in queue if r['id'] == result.queue_id)
                ahead = sum(r['session_id'] == self.selected and r['state'] in {'queued', 'running'}
                            for r in queue if r['seq'] < row['seq'])
                self.store.append_event(row['turn_id'], 'queue.accepted', {'id': row['id'], 'ahead': ahead})
            return
        result = self.store.accept_update(update_id, self.peer.user_id, {'rejected': not callback and (not isinstance(text, str) or not text.startswith('/'))})
        if not result.accepted:
            return
        owner.receipt(request, b'accepted control')
        if callback:
            data = callback.get('data', '')
            if not isinstance(data, str) or data[:2] not in {'a:', 'r:'}:
                return
            record = self.callbacks.get(data[2:])
            if not record:
                return
            ctx, action, authority, message_id, future = record
            if (ctx.session_id != self.selected or message.get('message_id') != message_id
                    or not isinstance(message.get('from'), dict) or message['from'].get('id') != self.peer.bot_id or future.done()):
                return
            decision = self.reviews.resolve(data[2:], ctx, data[:2] == 'a:', request=action, authority=authority)
            future.set_result(decision)
            callback_id = callback.get('id')
            if isinstance(callback_id, str) and callback_id:
                ack = owner.authorize('telegram.send', self.peer, callback_id.encode())
                await self.transport.answer_callback(callback_id, 'Aprobación registrada' if decision else 'No aprobado')
                owner.receipt(ack, b'callback acknowledged')
            return
        if not isinstance(text, str):
            return
        command, _, arg = text.partition(' ')
        answer = None
        if command == '/nueva':
            outcome, session_id = native_sessions(root, WorkspaceAuthority(root)).manage('state', None, '{}')
            require_outcome(outcome)
            self.store.bind_session(session_id, root)
            self.select(session_id)
            answer = 'Nueva sesión: ' + session_id
        elif command == '/usar':
            outcome, _ = native_sessions(root, WorkspaceAuthority(root)).resume(arg)
            require_outcome(outcome)
            self.store.bind_session(arg, root)
            self.select(arg)
            answer = 'Sesión seleccionada: ' + arg
        elif command == '/proyectos':
            aliases = []
            for alias, candidate in self.store.workspaces().items():
                try:
                    self.guard(candidate)
                    aliases.append(alias)
                except PermissionError:
                    pass
            answer = '\n'.join(aliases) or 'Sin proyectos autorizados'
        elif command in {'/inicio', '/ayuda'}:
            answer = '/proyectos · /nueva <alias> · /sesiones · /usar <id> · /estado · /cola · /retirar <id> · /cancelar · /continuar · /detalle <turno>'
        elif command == '/sesiones':
            outcome, sessions = native_sessions(root, WorkspaceAuthority(root)).list_conversations()
            require_outcome(outcome)
            answer = '\n'.join(f'{session.session_id} {session.title}' for session in sessions) or 'Sin sesiones visibles'
        elif command in {'/estado', '/cola'}:
            answer = '\n'.join(f"{row['id']} {row['state']} turno={row['turn_id']}" for row in self.store.queue() if row['session_id'] == self.selected) or 'Cola vacía'
            if command == '/estado':
                outcome, session = native_sessions(root, WorkspaceAuthority(root)).resume(self.selected)
                require_outcome(outcome)
                answer = f"Sesión {self.selected} · {session.state.get('provider', 'local')} / {session.state.get('model', 'local')}\n" + answer
        elif command == '/retirar':
            eligible = any(row['id'] == arg and row['session_id'] == self.selected for row in self.store.queue())
            answer = 'Retirada' if eligible and self.store.cancel_pending(arg) else 'No se retiró'
        elif command == '/continuar':
            answer = 'Cola habilitada; no se repiten turnos interrumpidos' if self.store.resume_pending(self.selected) else 'Sin pausa'
        elif command == '/cancelar':
            for item, task in self.active.values():
                if item.session_id == self.selected:
                    self._cancel(task)
            self.select(self.selected)
            answer = 'Cancelación solicitada'
        elif command == '/respuesta':
            identity, _, value = arg.partition(' ')
            record = self.questions.get(identity)
            if record and record[0].session_id == self.selected and not record[1].done() and 0 < len(value) <= 500:
                record[1].set_result({'status': 'answered', 'text': clean(value)})
        elif command == '/detalle':
            for row in self.store.queue():
                if row['turn_id'] == arg and row['session_id'] == self.selected:
                    for event in self.store.events(arg):
                        for rendered in self.renderer.event({**event['payload'], 'kind': event['kind']}):
                            await self.send_owned(root, rendered)
        if answer:
            for rendered in self.renderer.text(answer):
                await self.send_owned(root, rendered)

    async def _run_item(self, item):
        status = 'interrupted'
        try:
            self.guard(item.workspace)
            await self.runner_factory(self, item).run()
            status = 'completed'
        except asyncio.CancelledError:
            status = 'cancelled'
            raise
        except Exception as error:
            self.store.append_event(item.turn_id, 'turn.error', {'error': type(error).__name__})
        finally:
            self.store.finish(item.turn_id, status)
            self.store.append_event(item.turn_id, 'turn.finish', {'status': status})

    async def work_once(self):
        for key, (_, task) in list(self.active.items()):
            if task.done():
                await asyncio.gather(task, return_exceptions=True)
                # A task cancelled before its first instruction never executes its finally.
                self.store.finish(key, 'interrupted')
                self.active.pop(key)
                self._cancelled.discard(task)
        if self.store.setting('revoked', False):
            self.store.revoke_pending()
            for _, task in self.active.values():
                self._cancel(task)
            return
        while len(self.active) < 2:
            item = self.store.claim_next()
            if item is None:
                break
            task = asyncio.create_task(self._run_item(item))
            self.active[item.turn_id] = (item, task)

    async def deliver_once(self):
        roots = {row['turn_id']: Path(row['workspace']) for row in self.store.queue()}
        for event in self.store.pending_deliveries():
            root = roots.get(event.turn_id)
            if root is None:
                continue
            try:
                last = None
                for rendered in self.renderer.event(event.payload):
                    last = await self.send_owned(root, rendered)
                self.store.ack_delivery(event.id, last.message_id if last else 0)
            except (TelegramError, PermissionError, OSError, ValueError, RuntimeError) as error:
                self.store.retry_delivery(event.id, getattr(error, 'retry_after', 0) or min(300, 2 ** min(event.attempts + 1, 8)))

    async def _receive(self):
        while self.running:
            try:
                if not any(self._can_connect(root) for root in self.store.workspaces().values()):
                    self.running = False
                    return
                updates = await self.transport.get_updates(self.store.cursor())
                for update in updates:
                    try:
                        await self.handle_update(update)
                    except (PermissionError, ValueError, OSError, TelegramError, RuntimeError):
                        # A committed update is never replayed because its notification failed.
                        # Do not advance over an update whose transaction did not commit.
                        if self.store.cursor() <= update['update_id']:
                            break
                        continue
            except TelegramError as error:
                if error.code in {'polling_conflict', 'webhook_conflict', 'invalid_bot_identity', 'credential_unavailable'}:
                    self.running = False
                    return
                await asyncio.sleep(error.retry_after or 2)
            await asyncio.sleep(.1)

    def _can_connect(self, root):
        try:
            self.guard(root)
            return True
        except (PermissionError, OSError, ValueError):
            return False

    async def _schedule(self):
        while self.running:
            if self.store.setting('stop_requested', False) or self.store.setting('revoked', False):
                self.running = False
                break
            for item, task in self.active.values():
                if not self._can_connect(item.workspace):
                    self._cancel(task)
            await self.work_once()
            await asyncio.sleep(.1)

    async def _deliver(self):
        while self.running:
            await self.deliver_once()
            await asyncio.sleep(.25)

    async def start(self):
        if self._lock is not None:
            raise RuntimeError('service already started')
        lock = self.store.service_lock()
        lock.__enter__()
        self._lock = lock
        try:
            self.store.set_setting('stop_requested', False)
            if not any(self._can_connect(root) for root in self.store.workspaces().values()):
                raise PermissionError('no authorized Telegram workspace')
            if await self.transport.get_me() != self.peer.bot_id:
                raise PermissionError('configured bot identity changed')
            await self.transport.ensure_polling()
            self.store.recover()
            self.running = True
            self._tasks = [asyncio.create_task(fn()) for fn in (self._receive, self._schedule, self._deliver)]
            for task in self._tasks:
                task.add_done_callback(lambda _: setattr(self, 'running', False))
        except BaseException:
            await self.stop()
            raise

    async def stop(self):
        self.running = False
        self.reviews.invalidate()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for _, task in self.active.values():
            self._cancel(task)
        await asyncio.gather(*(task for _, task in self.active.values()), return_exceptions=True)
        for turn_id in self.active:
            self.store.finish(turn_id, 'interrupted')
        self.active.clear()
        self._cancelled.clear()
        self.callbacks.clear()
        self.questions.clear()
        if self._lock is not None:
            self._lock.__exit__(None, None, None)
            self._lock = None
