"""Manual real-sandbox soak; run explicitly with pytest (see the evidence report)."""
import asyncio
import gc
import json
import os
import subprocess
import time
from pathlib import Path

from isycode.action_audit import ActionAuditJournal
from isycode.command_runner import CommandRunOwner, sandbox_executable
from isycode.streaming import StreamError
from isycode.tui import ChatArea, CommandApprovalScreen, TUIApp, WriteApprovalScreen
from isycode.user_defaults import UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority
from test_daily_tui import configure

REPORT = Path(os.environ.get('ISYCODE_SOAK_REPORT', '/tmp/isycode-long-session-report.json'))

def rss_kib():
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmRSS:'):
            return int(line.split()[1])


def test_long_session(tmp_path, monkeypatch):
    root = configure(tmp_path, monkeypatch)
    UserDefaultsStore().update(new_workspace='recurring')
    (root / 'app.py').write_text('value = 1\n')
    (root / 'test_app.py').write_text('import unittest\nfrom app import value\nclass ValueTest(unittest.TestCase):\n def test_positive(self): self.assertGreater(value, 0)\n')
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Soak', '-c', 'user.email=soak@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    assert sandbox_executable(), 'real Bubblewrap unavailable'
    authority = WorkspaceAuthority(root)
    authority.set_mode('classic')
    authority.set_grant('workspace.command.run', enabled=True, executables=[sandbox_executable()], path_prefixes=[str(root)])
    stats = {'provider': 'simulated', 'started': time.time(), 'requests': 0, 'summaries': 0,
             'reads': 0, 'edits': 0, 'commands': 0, 'diffs': 0, 'approvals': 0,
             'cancelled': 0, 'failures_injected': 0, 'restarts': 0, 'samples': []}
    plan, round_number = [], 0
    failed = False
    cancel_mode = False
    cancelled_ready = None
    results = []

    async def complete(provider, messages, **kwargs):
        nonlocal round_number
        stats['requests'] += 1
        if messages[0].get('content', '').startswith('Summarize the conversation below'):
            stats['summaries'] += 1
            return {'text': 'Working on app.py; completed edits and tests. Verify current state before any change.',
                    'usage': {'prompt_tokens': 800, 'completion_tokens': 100}, 'tool_calls': []}
        if cancel_mode:
            kwargs['on_chunk']('content', 'A deliberately partial answer.')
            cancelled_ready.set()
            await asyncio.Event().wait()
        if failed:
            stats['failures_injected'] += 1
            kwargs['on_chunk']('content', 'Partial output before transport failure.')
            raise StreamError('injected transport disconnect')
        if round_number:
            result = next(m['content'] for m in reversed(messages) if m.get('role') == 'tool')
            results.append(json.loads(result))
        for index in range(10):
            kwargs['on_chunk']('reasoning', f'Simulated reasoning fragment {index}.\n')
            kwargs['on_chunk']('content', 'Simulated streamed explanation for this step.\n\n')
            await asyncio.sleep(0)
        if round_number < len(plan):
            name, args = plan[round_number]
            round_number += 1
            return {'text': '', 'tool_calls': [{'id': f'soak-{stats["requests"]}', 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(args)}}],
                    'usage': {'prompt_tokens': 800, 'completion_tokens': 200}}
        return {'text': 'Completed.', 'tool_calls': [], 'usage': {'prompt_tokens': 800, 'completion_tokens': 200}}

    original_execute = CommandRunOwner._execute
    async def observed_execute(self, preview, *, promote=True):
        try:
            return await original_execute(self, preview, promote=promote)
        except Exception as exc:
            stats['command_failure'] = str(exc)
            stats['command_cause'] = repr(exc.__cause__)
            REPORT.write_text(json.dumps(stats, indent=2))
            raise
    monkeypatch.setattr(CommandRunOwner, '_execute', observed_execute)
    monkeypatch.setattr('isycode.tui.provider_complete', complete)

    async def run_with_approvals(app, pilot, prompt):
        task = asyncio.create_task(app._run_chat(prompt))
        last_screen = None
        try:
            while not task.done():
                if isinstance(app.screen, (WriteApprovalScreen, CommandApprovalScreen)) and app.screen is not last_screen:
                    last_screen = app.screen
                    stats['approvals'] += 1
                    await pilot.press('tab', 'enter')
                await pilot.pause(0.01)
            await asyncio.wait_for(task, 30)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def scenario():
        nonlocal plan, round_number, failed, cancel_mode, cancelled_ready
        sid = None
        value = 1
        for launch in range(3):
            app = TUIApp()
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                if sid:
                    stats['restarts'] += 1
                    await app._resume_chat_session(sid)
                    assert app._tool_history and app._usage.requests
                if launch == 0:
                    plan = [('workspace_read', {'path': 'app.py'})] * 60
                    round_number = 0
                    results.clear()
                    await run_with_approvals(app, pilot, 'Perform a long repository inspection.')
                    assert len(results) == 60
                    assert all('value = 1' in json.dumps(result) for result in results)
                    stats['reads'] += 60
                    assert len(app._tool_history) == 32
                    sid = app._active_chat_session_id
                    print('Long single turn completed: 60 real owned reads', flush=True)
                for cycle in range(25):
                    before = time.monotonic()
                    plan = [('workspace_read', {'path': 'app.py'}),
                            ('workspace_edit', {'path': 'app.py', 'old_text': f'value = {value}', 'new_text': f'value = {value + 1}'}),
                            ('workspace_run', {'argv': ['python3', '-B', '-m', 'unittest', '-v']}),
                            ('git_diff', {'path': 'app.py'})]
                    round_number = 0
                    results.clear()
                    await run_with_approvals(app, pilot, f'Increment app.py in cycle {launch}-{cycle}; run tests and review diff.')
                    assert len(results) == 4
                    assert results[1]['status'] == 'written', results[1]
                    assert results[2].get('exit_code') == 0 and 'Ran 1 test' in results[2]['output'], results[2]
                    assert f'+value = {value + 1}' in json.dumps(results[3]), results[3]
                    value += 1
                    assert (root / 'app.py').read_text() == f'value = {value}\n'
                    stats['reads'] += 1
                    stats['edits'] += 1
                    stats['commands'] += 1
                    stats['diffs'] += 1
                    assert len(app._tool_history) <= 32
                    assert app._active_chat_session_id == sid
                    await pilot.pause()
                    chat = app.query_one(ChatArea)
                    assert abs(chat.scroll_y - chat.max_scroll_y) <= 1, ('tail', chat.scroll_y, chat.max_scroll_y)
                    if cycle % 5 == 0:
                        chat.focus()
                        await pilot.press('home')
                        await pilot.pause()
                        old_y = chat.scroll_y
                        app._append('New output while reading earlier history.')
                        await pilot.pause()
                        assert chat.scroll_y == old_y
                        await pilot.press('end')
                        await pilot.pause()
                        assert abs(chat.scroll_y - chat.max_scroll_y) <= 1
                        await pilot.resize_terminal(80, 24)
                        await pilot.pause()
                        await pilot.resize_terminal(100, 30)
                        await pilot.pause()
                    if cycle % 10 == 0:
                        history = list(app._history)
                        failed = True
                        try:
                            await app._run_chat('Inject a recoverable stream failure.')
                        finally:
                            failed = False
                        assert app._history == history[-len(app._history):]
                        assert all(not m.get("content", "").startswith("Inject ") for m in app._history)
                        assert app._retry_prompt
                        cancel_mode = True
                        cancelled_ready = asyncio.Event()
                        task = asyncio.create_task(app._run_chat('Inject cancellation.'))
                        await asyncio.wait_for(cancelled_ready.wait(), 10)
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        cancel_mode = False
                        stats['cancelled'] += 1
                        assert app._history == history[-len(app._history):]
                        assert all(not m.get("content", "").startswith("Inject ") for m in app._history)
                        app.query_one('#prompt-input').load_text('')
                    if cycle % 8 == 0:
                        await app._compact_conversation()
                    gc.collect()
                    stats['samples'].append({'launch': launch, 'cycle': cycle, 'rss_kib': rss_kib(),
                                             'widgets': len(app.query('*')), 'seconds': time.monotonic() - before,
                                             'elapsed_s': time.time() - stats['started']})
                    if cycle % 5 == 0:
                        REPORT.write_text(json.dumps(stats, indent=2))
                        print(json.dumps(stats['samples'][-1]), flush=True)
                stored = app._chat_session_owner.resume(sid)[1]
                assert stored and len(stored.state['tool_history']) <= 32
                assert stored.state['usage'] == app._usage.to_state()
                audit = ActionAuditJournal(root).verify()
                assert audit.status == 'PASS', audit
                stats['audit_records'] = audit.records
                stats['audit_receipts'] = audit.receipts
            del app
            gc.collect()
            stats.setdefault('restart_rss_kib', []).append(rss_kib())
        stats['elapsed_s'] = time.time() - stats['started']
        stats['final_value'] = value
        stats['status'] = 'PASS'
        REPORT.write_text(json.dumps(stats, indent=2))
        print('FINAL ' + json.dumps({k:v for k,v in stats.items() if k != 'samples'}), flush=True)
    try:
        asyncio.run(scenario())
    except BaseException as exc:
        stats['status'] = 'FAIL'
        stats['failure'] = type(exc).__name__ + ': ' + str(exc)
        stats['elapsed_s'] = time.time() - stats['started']
        REPORT.write_text(json.dumps(stats, indent=2))
        raise
