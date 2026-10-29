import asyncio, json, sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, '/tmp/isycode-rtk-native-20261009/tests')
from test_daily_tui import configure
from isycode.tui import TUIApp, CommandApprovalScreen
from isycode.rtk_integration import Settings
from isycode.rtk_tui import RTKSettingsScreen, RTKRawOutputScreen

async def probe():
    monkey = pytest.MonkeyPatch()
    try:
        with tempfile.TemporaryDirectory(prefix='rtk-tui-probe-') as raw:
            root = configure(Path(raw), monkey)
            (root / 'notes.txt').write_text(''.join('needle_' + str(i) + '\n' for i in range(300)))
            app = TUIApp()
            async with app.run_test(size=(145, 45)) as pilot:
                _, cmd, arg = app._plugins.route('/rtk')
                await cmd.handler(app, arg)
                for _ in range(60):
                    await pilot.pause(.05)
                    if isinstance(app.screen, RTKSettingsScreen) and app.screen.candidate is not None:
                        break
                assert isinstance(app.screen, RTKSettingsScreen) and app.screen.candidate is not None
                app.save_screenshot(filename='settings2.svg', path='/tmp/isycode-rtk-native-evidence-20261009')
                await pilot.click('#rtk-enable')
                for _ in range(60):
                    await pilot.pause(.05)
                    if Settings().load()['enabled']:
                        break
                assert Settings().load()['enabled'] is True
                await pilot.click('#rtk-close')
                task = asyncio.create_task(app._run_workspace_command({'argv': ['grep', '-H', '-n', 'needle', 'notes.txt']}))
                approvals = 0
                for _ in range(100):
                    await pilot.pause(.05)
                    if isinstance(app.screen, CommandApprovalScreen) and app.screen.query('#command-approval-run'):
                        await pilot.click('#command-approval-run')
                        approvals += 1
                    if task.done():break
                result = json.loads(await asyncio.wait_for(task, 20))
                assert result['exit_code'] == 0 and result['command_success'] is True
                assert result['rtk']['saved_bytes'] > 0 and approvals == 1
                _, cmd, arg = app._plugins.route('/rtk recall ' + result['rtk']['raw_sha256'])
                await cmd.handler(app, arg)
                assert isinstance(app.screen, RTKRawOutputScreen)
                assert 'notes.txt:300:needle_299' in app.screen.output
                result['probe'] = {'normal_approval_modals': approvals, 'raw_recall_verified': True,
                                   'settings_enabled_via_button': True}
                Path('/tmp/isycode-rtk-native-evidence-20261009/tui-result.json').write_text(json.dumps(result, indent=2)+'\n')
                print(json.dumps({'exit_code': result['exit_code'], 'raw_bytes': result['rtk']['captured_bytes'],
                                  'model_bytes': result['rtk']['model_bytes'], 'saved_bytes': result['rtk']['saved_bytes'],
                                  'raw_recall_verified': True, 'approval_modals': approvals}))
    finally:
        monkey.undo()

asyncio.run(probe())
