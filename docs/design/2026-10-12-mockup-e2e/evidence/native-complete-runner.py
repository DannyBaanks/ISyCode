"""Verify the actual installed launcher in a private native 80x24 PTY."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import struct
import subprocess
import tempfile
import termios
import time

root = Path.cwd()
out = root / "docs/design/2026-10-12-mockup-e2e/evidence"
command = Path('/home/danny/.local/bin/isycode')
assert command.resolve() == root / 'scripts/isycode'
raw = bytearray()
with tempfile.TemporaryDirectory(prefix='isycode-native-complete-') as directory:
    private = Path(directory)
    project = private / 'project'
    project.mkdir()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('ISYCODE_', 'ISYMOTRON_'))
           and not key.endswith(('_API_KEY', '_TOKEN'))}
    env.pop('PYTHONPATH', None)
    env.update(XDG_CONFIG_HOME=str(private/'config'), XDG_STATE_HOME=str(private/'xdg'),
               XDG_CACHE_HOME=str(private/'cache'), ISYCODE_STATE_HOME=str(private/'state'),
               ISYCODE_PROVIDER='openai', ISYCODE_MODEL='gpt-6-luna',
               TERM='xterm-256color', COLUMNS='80', LINES='24', PYTHONDONTWRITEBYTECODE='1')
    prepare_env = {**env, 'PYTHONPATH': str(root/'src')}
    subprocess.run([str(root/'.venv/bin/python'), '-c',
                    "from isycode.user_defaults import UserDefaultsStore; "
                    "from isycode.workspace_authority import WorkspaceAuthority; "
                    "from pathlib import Path; "
                    "UserDefaultsStore().update(new_workspace='temporary',new_workspace_mode='security',locale='en'); "
                    "WorkspaceAuthority(Path.cwd()).set_mode('security')"],
                   cwd=project, env=prepare_env, check=True)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH',24,80,0,0))
    process = subprocess.Popen([str(command)], cwd=project, env=env,
                               stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)

    def drain(seconds):
        deadline = time.monotonic()+seconds
        while time.monotonic()<deadline:
            if select.select([master],[],[],min(.1,deadline-time.monotonic()))[0]:
                try:
                    chunk=os.read(master,65536)
                except OSError:
                    break
                if not chunk:
                    break
                raw.extend(chunk)

    drain(2)
    marker = len(raw)
    os.write(master,b'\x1b[<0;78;24M\x1b[<0;78;24m')
    drain(1)
    after = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', bytes(raw[marker:]))
    opened = b'Settings' in after and b'Conversation' in after
    os.write(master,b'\x1b')
    drain(.25)
    os.write(master,b'\x03')
    drain(2)
    if process.poll() is None:
        process.terminate()
        drain(1)
    exit_code=process.wait(timeout=5)
    os.close(master)
(out/'native-complete.ansi').write_bytes(raw)
result={'command':str(command),'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'size':[80,24],'private_security_state':True,'settings_after_real_sgr_click':opened,
        'exit':exit_code,'traceback':b'Traceback' in raw,'sha256':hashlib.sha256(raw).hexdigest()}
(out/'native-complete-result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
assert opened and exit_code==0 and not result['traceback']
