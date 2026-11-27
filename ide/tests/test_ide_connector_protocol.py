"""Actual subprocess protocol boundary using a local peer fixture, no account."""
import asyncio
import json
from pathlib import Path

import pytest

from core.connectors.codex import CodexConnector, CodexConnectorError


SCRIPT = r'''#!/usr/bin/python3
import json,os,sys,time
scenario = SCENARIO
def send(value):
 print(json.dumps(value),flush=True)
for line in sys.stdin:
 request=json.loads(line)
 method=request.get('method')
 if method=='initialize': result={'codexHome':os.environ['CODEX_HOME'],'userAgent':'fixture'}
 elif method=='account/read': result={'account':{'type':'apiKey'} if scenario=='api' else {'type':'chatgpt','planType':'plus'}}
 elif method=='thread/start':
  assert request['params']['environments']==[]
  assert request['params']['approvalPolicy']=='untrusted'
  assert request['params']['sandbox']=='read-only'
  assert request['params']['config']['features']['shell_tool'] is False
  result={'thread':{'id':'thread','environments':[]}}
 elif method=='turn/start': result={'turn':{'id':'turn'}}
 elif 'id' not in request: continue
 else:
  open('unexpected-ack','w').write(line)
  continue
 send({'id':request['id'],'result':result})
 if method=='turn/start':
  if scenario=='wait': continue
  params={'threadId':'thread','turnId':'turn','callId':'call','tool':'write','arguments':{'path':'app.py','content':'proposed'}}
  send({'id':'server-call','method':'item/tool/call' if scenario=='dynamic' else 'item/commandExecution/requestApproval','params':params})
'''


@pytest.mark.parametrize("scenario", ["dynamic", "builtin", "api", "wait"])
def test_codex_peer_is_reaped_and_tools_return_to_owner(tmp_path, scenario):
    executable = tmp_path / "codex-peer"
    executable.write_text(SCRIPT.replace("SCENARIO", repr(scenario)))
    executable.chmod(0o755)
    home = tmp_path / "private-home"
    async def run():
        peer = CodexConnector(str(executable), home, timeout_s=2)
        async with peer:
            operation = peer.complete("fixture-model", [{"role": "user", "content": "modify"}],
                [{"type": "function", "function": {"name": "write", "parameters": {"type": "object"}}}])
            if scenario == "dynamic":
                result = await operation
                assert result["tool_calls"][0]["function"]["name"] == "write"
                assert not (home / "unexpected-ack").exists()
            elif scenario == "wait":
                task = asyncio.create_task(operation)
                await asyncio.sleep(0.1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(CodexConnectorError):
                    await operation
        assert peer._process.returncode is not None
        assert not (home / "app.py").exists()
    asyncio.run(run())
