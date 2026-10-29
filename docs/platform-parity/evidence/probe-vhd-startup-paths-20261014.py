"""Read-only LPAC startup matrix; no descriptor or attachment changes."""
import json,sys,tempfile
from pathlib import Path
import win32file
from isycode.windows_sandbox_storage_cli import load_storage_config
from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
req=json.loads(Path('docs/platform-parity/evidence/windows-vhd-operator-request-20261014.json').read_text(encoding='utf-8-sig'))
config=load_storage_config(Path((Path(req['setup_root'])/'config-path.txt').read_text()))
with tempfile.TemporaryDirectory(prefix='isycode-startup-control-') as source:
 with BoundedStorageProvider(config).open() as lease:
  with WindowsSandboxResources.prepare(Path(source),Path(sys.base_prefix),(),storage_lease=lease) as r:
   root=Path(win32file.GetFinalPathNameByHandle(lease._holder.root_handle,0)[4:])
   def dos(path):return root/Path(path).relative_to(lease.root)
   exe=dos(r.runtime_root/'python.exe')
   for name,cwd,convert in [('guid-env-dos-cwd',dos(r.stage_root),False),
                            ('dos-env-dos-cwd',dos(r.stage_root),True),
                            ('dos-env-guid-cwd',r.stage_root,True)]:
    env=dict(r.environment)
    if convert:
     for key in ('TEMP','TMP','LOCALAPPDATA','PATH'):env[key]=str(dos(env[key]))
    with WindowsSandboxProcess.launch(exe,(str(exe),'-I','-c','print("startup-control")'),cwd,env,
         r.profile_sid,256,r.capability_sids) as p:
     print(name,'exit',p.wait(15),'output',repr(p.read(4096)),flush=True)
   lease.assert_unchanged()
