"""Normal-user owner witness for disappearance of the exact scratch VHD."""
import asyncio,json,sys,time
from pathlib import Path
import isycode.platform_windows_sandbox as native
import isycode.platform_windows_sandbox_resources as resources
from isycode.command_runner import CommandRunOwner
from isycode.workspace_authority import WorkspaceAuthority
from isycode.approvals import ActionApprovalStore
control,project=map(Path,sys.argv[1:])
project.mkdir();(project/'.isyroot').write_text('');(project/'original.txt').write_text('preserve-original')
native.NATIVE_ACCEPTED=True  # acceptance harness only; never changes product source.
authority=WorkspaceAuthority(project);authority.set_mode('classic')
owner=CommandRunOwner(project,authority,ActionApprovalStore())
captured=[];prepare=resources.WindowsSandboxResources.prepare
def capture(*args,**kwargs):
 r=prepare(*args,**kwargs);captured.append(r);return r
resources.WindowsSandboxResources.prepare=capture
preview=owner.prepare(['python','-c','from pathlib import Path;import time;Path("not-promoted.txt").write_text("staged");print("ready",flush=True);time.sleep(6)'])
def signal(name,payload=None):(control/name).write_text(json.dumps(payload or {}),encoding='utf-8')
def wait(name):
 deadline=time.monotonic()+40
 while not (control/name).exists():
  if (control/'operator-error.json').exists():raise AssertionError((control/'operator-error.json').read_text())
  if time.monotonic()>deadline:raise TimeoutError(name)
  time.sleep(.05)
 return json.loads((control/name).read_text(encoding='utf-8'))
async def scenario():
 return await owner.run(preview,owner.approvals.issue(preview.request),on_output=lambda text:signal('lease-ready.json') if 'ready' in text else None)
try:
 outcome=asyncio.run(scenario())
 assert outcome.decision in {'ERROR','NOT_VERIFIABLE'},outcome
 assert not (project/'not-promoted.txt').exists()
 assert (project/'original.txt').read_text()=='preserve-original'
 assert captured
 signal('owner-outcome.json',{'decision':outcome.decision,'reason':outcome.reason,'root':str(captured[0].scratch_root),'original_preserved':True})
finally:signal('lease-released.json')
try:
 wait('absent-ready.json')
 assert native.WindowsSandbox().executable() is None
finally:signal('missing-checked.json')
wait('reattached.json')
print('running command: disappeared volume rejected, no promotion, original preserved')
