"""Interactive local audit of the real Textual widget tree (no live services).

Run with the repository venv, PYTHONPATH=src and ISYCODE_AUDIT_OUT set.
JSON-line commands: state, capture/name, press/keys, click/selector,
resize/width/height, fill/text, provider/mode, quit.
The deterministic provider replaces only inference; owners and UI stay real.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback

OUT = Path(os.environ['ISYCODE_AUDIT_OUT'])
FIXTURE = Path(tempfile.mkdtemp(prefix='isycode-e2e-audit-'))
ROOT = FIXTURE / 'project'
ROOT.mkdir()
(ROOT / 'app.py').write_text('value = 1\n', encoding='utf-8')
(ROOT / 'README.md').write_text('# Audit fixture\n\nA local example project.\n', encoding='utf-8')
(ROOT / 'src').mkdir()
(ROOT / 'src/helper.py').write_text('def helper():\n    return 1\n', encoding='utf-8')
(ROOT / '.env').write_text('AUDIT_SECRET=never_display_this_canary\n', encoding='utf-8')
(ROOT / 'test_app.py').write_text('import unittest\nfrom app import value\nclass TestApp(unittest.TestCase):\n def test_value(self): self.assertEqual(value, 2)\n', encoding='utf-8')
subprocess.run(['git', 'init', '-q', str(ROOT)], check=True)
subprocess.run(['git', '-C', str(ROOT), 'add', 'app.py', 'README.md', 'src/helper.py', 'test_app.py'], check=True)
subprocess.run(['git', '-C', str(ROOT), '-c', 'user.name=Audit', '-c', 'user.email=audit@example.invalid', 'commit', '-qm', 'fixture baseline'], check=True)
for key in list(os.environ):
    if any(x in key for x in ('API_KEY', 'TOKEN', 'SECRET')) or key.startswith(('ISYCODE_', 'ISYMOTRON_', 'ISYCO_ROOT')):
        if key != 'ISYCODE_AUDIT_OUT':
            os.environ.pop(key, None)
for key, directory in [('HOME', 'home'), ('XDG_STATE_HOME', 'xdg-state'), ('XDG_CONFIG_HOME', 'xdg-config'), ('XDG_CACHE_HOME', 'cache'), ('ISYCODE_STATE_HOME', 'state')]:
    path = FIXTURE / directory
    path.mkdir()
    os.environ[key] = str(path)
os.environ['ISYCODE_PROVIDER'] = 'openai'
os.environ['ISYCODE_MODEL'] = 'gpt-6-luna'
os.environ['ISYCO_ROOT'] = str(FIXTURE / 'absent-bridge')
os.environ.pop('NO_COLOR', None)
os.environ['TERM'] = 'xterm-256color'
os.environ['COLORTERM'] = 'truecolor'
os.chdir(ROOT)

import pytest
from textual.widgets import Button, Input, Static, OptionList
from isycode.tui import TUIApp, PromptArea
from isycode.user_defaults import UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_trust import WorkspaceTrust
from isycode.providers import ProviderError

patch = pytest.MonkeyPatch()
patch.setattr('isycode.providers.Provider.models', lambda provider: [provider.model])
patch.setattr('isycode.egress._ips', lambda host, port: ('93.184.216.34',))

async def no_external(self):
    return None

for method in ('_refresh_openisy', '_check_gateway_async', '_check_model'):
    patch.setattr(TUIApp, method, no_external)
original_unmount = TUIApp.on_unmount

async def unmount(self, event):
    await original_unmount(self, event)
    asyncio.get_running_loop().call_later(.5, lambda: None)

patch.setattr(TUIApp, 'on_unmount', unmount)
PROVIDER = {'mode': 'success', 'index': 0, 'calls': []}

async def complete(provider, messages, **kwargs):
    PROVIDER['calls'].append([dict(m) for m in messages])
    mode = PROVIDER['mode']
    if mode == 'failure':
        raise ProviderError('fixture HTTP 401', status=401)
    if mode == 'slow':
        kwargs['on_chunk']('content', 'Respuesta parcial de prueba…')
        await asyncio.Event().wait()
    if mode == 'tools':
        actions = [('workspace_read', {'path': 'app.py'}), ('workspace_edit', {'path': 'app.py', 'old_text': 'value = 1', 'new_text': 'value = 2'}), ('workspace_run', {'argv': ['python3', '-m', 'unittest', '-v']}), ('git_diff', {'path': 'app.py'})]
        index = PROVIDER['index']
        PROVIDER['index'] += 1
        if index < len(actions):
            name, args = actions[index]
            return {'text': '', 'tool_calls': [{'id': f'audit-{index}', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
    answer = '## Resultado de prueba\n\nHe terminado el recorrido local.\n\n- El chat conserva el orden.\n- Puedes continuar con otra tarea.\n\n```python\nvalue = 2\n```'
    kwargs['on_chunk']('reasoning', 'Revisando el ejemplo local sin servicios externos.')
    kwargs['on_chunk']('content', answer)
    return {'text': answer, 'tool_calls': []}

patch.setattr('isycode.tui.provider_complete', complete)
profile = sys.argv[1] if len(sys.argv) > 1 else 'fresh'
if profile in ('classic', 'security'):
    os.environ['OPENAI_API_KEY'] = 'test-not-real'
    UserDefaultsStore().update(new_workspace='recurring', new_workspace_mode=profile, locale='es')
    authority = WorkspaceAuthority(ROOT)
    authority.set_mode(profile)
    if profile == 'classic':
        WorkspaceTrust().decline(authority)
else:
    UserDefaultsStore().update(new_workspace='ask', new_workspace_mode='ask', locale='es')

def describe(app):
    items = []
    for widget in app.screen.query('*'):
        if not widget.display:
            continue
        row = {'type': type(widget).__name__, 'id': widget.id, 'region': list(widget.region), 'focus': widget.has_focus}
        if isinstance(widget, Button):
            row['label'] = str(widget.label)
        elif isinstance(widget, Input):
            row.update(value=widget.value, placeholder=widget.placeholder)
        elif isinstance(widget, PromptArea):
            row['text'] = widget.text
        elif isinstance(widget, Static):
            try:
                row['text'] = str(widget.render())[:1400]
            except Exception:
                pass
        elif isinstance(widget, OptionList):
            row['options'] = [str(widget.get_option_at_index(i).prompt) for i in range(widget.option_count)]
            row['highlighted'] = widget.highlighted
        items.append(row)
    return {'screen': type(app.screen).__name__, 'size': list(app.size), 'fixture': str(FIXTURE), 'mode': WorkspaceAuthority(ROOT).mode(), 'widgets': items, 'provider_mode': PROVIDER['mode'], 'provider_calls': len(PROVIDER['calls']), 'file_value': (ROOT / 'app.py').read_text()}

async def main():
    app = TUIApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(.5)
        print('AUDIT_READY ' + json.dumps(describe(app), ensure_ascii=False), flush=True)
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break
            try:
                cmd = json.loads(line)
                op = cmd['op']
                if op == 'quit':
                    (OUT / (profile + '-provider-calls.json')).write_text(json.dumps(PROVIDER['calls'], ensure_ascii=False, indent=2)+'\n')
                    break
                if op == 'press':
                    await pilot.press(*cmd['keys'])
                elif op == 'click':
                    await pilot.click(cmd['selector'])
                elif op == 'fill':
                    widget = app.screen.query_one(cmd.get('selector', '#prompt-input'))
                    if isinstance(widget, Input):
                        widget.value = cmd['text']
                    else:
                        widget.load_text(cmd['text'])
                elif op == 'resize':
                    await pilot.resize_terminal(cmd['width'], cmd['height'])
                elif op == 'provider':
                    PROVIDER.update(mode=cmd['mode'], index=0)
                elif op == 'capture':
                    await pilot.pause(.3)
                    name = cmd['name']
                    svg, png, state = (OUT/(name+ext) for ext in ('.svg', '.png', '.json'))
                    if any(p.exists() for p in (svg, png, state)):
                        raise ValueError('capture paths already exist; do not overwrite evidence')
                    app.save_screenshot(str(svg))
                    result = await asyncio.create_subprocess_exec('/usr/bin/python3', str(OUT/'render_svg.py'), str(svg), str(png), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, stderr = await result.communicate()
                    if result.returncode:
                        raise RuntimeError(stderr.decode())
                    state.write_text(json.dumps(describe(app), ensure_ascii=False, indent=2)+'\n')
                    print('AUDIT_CAPTURE ' + str(png), flush=True)
                await pilot.pause(cmd.get('pause', .2))
                state = describe(app)
                print('AUDIT_STATE ' + json.dumps(state, ensure_ascii=False), flush=True)
                with (OUT/(profile+'-events.jsonl')).open('a') as file:
                    file.write(json.dumps({'command': cmd, 'state': state}, ensure_ascii=False)+'\n')
            except Exception as error:
                print('AUDIT_ERROR '+ repr(error), flush=True)
                traceback.print_exc()
    patch.undo()

if __name__ == '__main__':
    asyncio.run(main())
