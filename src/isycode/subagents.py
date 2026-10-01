"""Bounded child conversation. Trusted caller supplies owned transport and tools."""
from __future__ import annotations
import json
from isycode.chat_transport import assistant_turn
from isycode.agent_loop import compact_turn

DELEGATE_TOOL = {'type': 'function', 'function': {
    'name': 'delegate_task',
    'description': 'Delegate a bounded task to a child agent. The user selects a recent model before launch. The parent waits; file actions retain current approvals. No nested delegation.',
    'parameters': {'type': 'object', 'properties': {'task': {'type': 'string'}},
                   'required': ['task'], 'additionalProperties': False}}}


async def run_child(provider, task: str, context: list[dict], allowed_tools: list[str],
                    complete, dispatch, *, max_steps: int = 20, on_status=None) -> dict:
    if not isinstance(task, str) or not task.strip() or len(task) > 8000:
        raise ValueError('Child task must contain 1–8000 characters')
    if type(max_steps) is not int or not 1 <= max_steps <= 20:
        raise ValueError('Invalid child step limit')
    messages = [dict(message) for message in context] + [{'role': 'user', 'content': task}]
    result = {'provider': provider.name, 'model': provider.model, 'status': 'limit', 'steps': 0, 'text': ''}
    allowed = set(allowed_tools) - {'delegate_task'}
    for step in range(max_steps):
        if on_status:
            on_status(f'working · step {step + 1}/{max_steps}')
        messages[:], _ = compact_turn(messages)
        response = await complete(messages)
        if not isinstance(response, dict) or not isinstance(response.get('text', ''), str):
            raise ValueError('Invalid child response')
        result['steps'] = step + 1
        result['text'] = response.get('text', '')[:32000]
        calls = response.get('tool_calls', [])
        if not isinstance(calls, list) or len(calls) > 16:
            raise ValueError('Invalid child tool batch')
        if not calls:
            result['status'] = 'completed'
            break
        messages.append(assistant_turn(response))
        for call in calls:
            function = call.get('function') if isinstance(call, dict) else None
            name = function.get('name') if isinstance(function, dict) else None
            call_id = call.get('id') if isinstance(call, dict) else None
            if not isinstance(call_id, str) or not call_id:
                raise ValueError('Invalid child tool identity')
            if not isinstance(name, str):
                raise ValueError('Invalid child tool name')
            if name not in allowed:
                output = json.dumps({'error': 'Tool unavailable to this child; nested delegation is disabled'})
            else:
                if on_status:
                    on_status(f'tool · {name}')
                actual_id, output = await dispatch(call)
                if actual_id != call_id or not isinstance(output, str):
                    raise ValueError('Child tool result does not match request')
            messages.append({'role': 'tool', 'tool_call_id': call_id, 'content': output[:32000]})
    return result
