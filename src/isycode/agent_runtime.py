"""Frontend-independent provider boundary and owned agent/tool protocol."""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from isycode.action_runtime import ProviderNetworkOwner
from isycode.chat_transport import assistant_turn, provider_complete
from isycode.providers import Provider
from isycode.workspace_authority import WorkspaceAuthority


@dataclass
class TurnPorts:
    emit: Callable[[str, dict], None]
    dispatch: Callable[[dict], Awaitable[tuple[str, str]]]
    before_step: Callable[[list[dict]], Awaitable[None]] | None = None
    checkpoint: Callable[[list[dict]], None] | None = None


@dataclass
class TurnResult:
    text: str
    messages: list[dict]
    usage: dict
    provider_receipts: list[str]


async def provider_step(owner, provider, material, send):
    """Common Authority/Sentinel/provider boundary for every frontend."""
    return await owner.execute(provider, material, send)


def tool_message(call_id: str, text: str) -> dict:
    return {'role': 'tool', 'tool_call_id': call_id, 'content': text}


class ToolCallLedger:
    """Shared per-turn tool-call identity and deduplication table across frontends.

    Ensures a repeated tool call with the same ``id``:
    - reuses the recorded result without repeating side effects when its
      canonical payload digest matches;
    - raises ``ValueError`` when the same ``id`` is reused with different
      arguments or tool name.
    """

    def __init__(self) -> None:
        self._executed: dict[str, tuple[str, str]] = {}

    @staticmethod
    def validate_and_digest(call: object) -> tuple[str, str]:
        if not isinstance(call, dict) or not isinstance(call.get('id'), str) or not call['id']:
            raise ValueError('Provider returned a tool call without an identity')
        call_id = call['id']
        digest = hashlib.sha256(json.dumps(call, sort_keys=True).encode('utf-8')).hexdigest()
        return call_id, digest

    def lookup(self, call_id: str, digest: str) -> str | None:
        if call_id not in self._executed:
            return None
        old_digest, result = self._executed[call_id]
        if old_digest != digest:
            raise ValueError('Provider reused a tool identity with different arguments')
        return result

    def record(self, call_id: str, digest: str, result: str) -> None:
        self._executed[call_id] = (digest, result)


class AgentTurn:
    def __init__(self, root: Path, authority: WorkspaceAuthority):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.owner = ProviderNetworkOwner(self.root, authority)

    async def run(self, messages: list[dict], *, provider: Provider, tools: list[dict],
                  ports: TurnPorts, transport=None) -> TurnResult:
        receipts: list[str] = []
        usage: dict = {}
        ledger = ToolCallLedger()
        ports.emit('turn.start', {})
        try:
            while True:
                if ports.before_step:
                    await ports.before_step(messages)
                chunks: list[str] = []
                def chunk(kind, text):
                    if not isinstance(text, str) or not text:
                        return
                    if kind == 'content':
                        chunks.append(text)
                    if kind in {'content', 'reasoning'}:
                        ports.emit(kind, {'text': text})
                async def send():
                    if transport is not None:
                        return await transport(messages, tools or None, chunk)
                    return await provider_complete(provider, messages, max_tokens=None,
                                                   on_chunk=chunk, tools=tools or None)
                material = {'operation': 'chat.completions', 'messages': messages,
                            'max_tokens': None, 'token_limit_field': provider.token_limit_field,
                            'reasoning_effort': provider.reasoning_effort,
                            'temperature_supported': provider.temperature_supported,
                            'tools': tools or None}
                ports.emit('provider.request', {'provider': provider.name, 'model': provider.model})
                response, outcome = await provider_step(self.owner, provider, material, send)
                if outcome.decision != 'ALLOW' or outcome.receipt is None or not isinstance(response, dict):
                    raise PermissionError('Provider request refused: ' + outcome.reason[:240])
                receipts.append(outcome.receipt.receipt_id)
                for key, value in (response.get('usage') or {}).items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        usage[key] = usage.get(key, 0) + value
                ports.emit('provider.result', {'receipt': outcome.receipt.receipt_id})
                text = response.get('text') or ''.join(chunks)
                if text and not chunks:
                    ports.emit('content', {'text': text})
                calls = response.get('tool_calls') or []
                if not isinstance(calls, list):
                    raise ValueError('Provider returned invalid tool calls')
                if not calls:
                    messages.append({'role': 'assistant', 'content': text})
                    if ports.checkpoint:
                        ports.checkpoint(messages)
                    ports.emit('turn.finish', {'status': 'completed'})
                    return TurnResult(text, messages, usage, receipts)
                messages.append(assistant_turn(response))
                for call in calls:
                    call_id, digest = ledger.validate_and_digest(call)
                    cached = ledger.lookup(call_id, digest)
                    if cached is not None:
                        result = cached
                    else:
                        ports.emit('tool.start', {'call_id': call_id, 'function': call.get('function')})
                        if ports.checkpoint:
                            ports.checkpoint(messages)
                        returned_id, result = await ports.dispatch(call)
                        if returned_id != call_id or not isinstance(result, str):
                            raise ValueError('Tool returned a mismatched protocol identity')
                        ledger.record(call_id, digest, result)
                        ports.emit('tool.result', {'call_id': call_id, 'result': result})
                    messages.append(tool_message(call_id, result))
                    if ports.checkpoint:
                        ports.checkpoint(messages)
        except asyncio.CancelledError:
            ports.emit('turn.finish', {'status': 'cancelled'})
            raise
        except Exception as error:
            ports.emit('turn.finish', {'status': 'failed', 'error': type(error).__name__})
            raise
