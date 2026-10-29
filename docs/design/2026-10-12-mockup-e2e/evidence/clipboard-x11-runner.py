"""Real widgets -> clipboard owner -> private Xvfb/xclip; user's clip untouched."""
import asyncio
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile

from rich.text import Text
from textual.app import App
from textual.widgets import Button
from isycode.action_audit import ActionAuditJournal
from isycode.clipboard_owner import CLIPBOARD_TARGET, ClipboardOwner
from isycode.tui_copy import CopyMenuScreen
from isycode.tui_widgets import BoxTitle, ExpandableBox, SelectableText
from isycode.workspace_authority import WorkspaceAuthority

root = Path.cwd()
out = root / 'docs/design/2026-10-12-mockup-e2e/evidence'
source = 'uno  \ndos\ntres\n'
results = []

with tempfile.TemporaryDirectory(prefix='isycode-private-clipboard-') as directory:
    private = Path(directory)
    project = private/'project'
    project.mkdir()
    os.environ.update(ISYCODE_STATE_HOME=str(private/'state'), XDG_STATE_HOME=str(private/'xdg'),
                      XDG_CONFIG_HOME=str(private/'config'))
    os.environ.pop('WAYLAND_DISPLAY', None)
    os.environ.pop('XAUTHORITY', None)
    read_fd, write_fd = os.pipe()
    with (out/'clipboard-x11-server.txt').open('x') as log:
        server = subprocess.Popen(['Xvfb','-displayfd',str(write_fd),'-screen','0','1280x1024x24','-nolisten','tcp'],
                                  pass_fds=[write_fd],stdout=log,stderr=log)
        os.close(write_fd)
        try:
            assert select.select([read_fd],[],[],5)[0], 'Private X server did not start'
            display = os.read(read_fd,128).decode().strip()
            assert display.isdigit()
            os.environ['DISPLAY'] = ':'+display
            authority = WorkspaceAuthority(project)
            owner = ClipboardOwner(project,authority)
            assert owner.copy('denied',source='selection').decision == 'DENY'
            authority.set_grant('clipboard.copy',enabled=True,targets=[CLIPBOARD_TARGET])

            def read_clip():
                return subprocess.check_output(['xclip','-selection','clipboard','-o'],timeout=3).decode()

            class Host(App):
                CSS_PATH = root/'src/isycode/design.tcss'

                def compose(self):
                    yield ExpandableBox(SelectableText(Text(source)),title='Result',collapsed=False)

                async def _request_clipboard_copy(self,text,source):
                    outcome = owner.copy(text,source=source)
                    assert outcome.decision=='ALLOW' and outcome.text=='xclip'
                    assert read_clip()==text
                    results.append({'source':source,'text':text,'backend':outcome.text,'receipt':bool(outcome.receipt)})

            async def scenario():
                async with Host().run_test(size=(80,24)) as pilot:
                    box=pilot.app.query_one(ExpandableBox)
                    title=box.query_one(BoxTitle)
                    body=box.query_one(SelectableText)
                    for start,end in [((0,0),(2,1)),((2,1),(0,0))]:
                        await pilot.mouse_down(body,offset=start)
                        await pilot.hover(body,offset=end)
                        await pilot.mouse_up(body,offset=end)
                        await pilot.press('ctrl+c')
                        await pilot.pause()
                        assert read_clip()=='uno  \ndos'
                    await pilot.click(title,times=2)
                    assert isinstance(pilot.app.screen,CopyMenuScreen)
                    assert not box.collapsed
                    await pilot.click('#copy-selection')
                    await pilot.pause()
                    assert read_clip()=='uno  \ndos'
                    body.screen.selections={}
                    await pilot.click(title,times=2)
                    assert pilot.app.screen.query_one('#copy-selection',Button).disabled
                    await pilot.click('#copy-whole')
                    await pilot.pause()
                    assert read_clip()==source
                    title.focus()
                    await pilot.press('enter')
                    assert not box.collapsed
                    await pilot.press('space')
                    assert box.collapsed

            asyncio.run(scenario())
            verification = ActionAuditJournal(project).verify()
            assert verification.receipts==4
            result={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                    'scope':'Actual native widget mouse selection and copy-menu gestures, real ClipboardOwner/Sentinel/grant/journal, private Xvfb and xclip; user desktop clipboard untouched.',
                    'copies':results,'receipts':verification.receipts,'space_only_expansion':True,'denied_before_grant':True,'exit':0}
            (out/'clipboard-x11-result.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result,indent=2))
        finally:
            os.close(read_fd)
            server.terminate()
            server.wait(timeout=5)
