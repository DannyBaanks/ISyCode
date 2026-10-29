"""Real fixed-VHD lifecycle, network and host IPC acceptance controls."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import pytest

pytestmark=pytest.mark.skipif(os.name!='nt',reason='native Windows VHD lifecycle')


@pytest.fixture
def storage():
    if not os.environ.get('ISYCODE_WINDOWS_SANDBOX_STORAGE_CONFIG'):
        pytest.skip('NOT_DEMONSTRATED: private operator VHD required')
    from isycode.windows_sandbox_storage_cli import configured_storage
    from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
    config=configured_storage()
    with BoundedStorageProvider(config).open():pass
    return config


@pytest.fixture
def prepared(tmp_path,storage):
    from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
    from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
    with BoundedStorageProvider(storage).open() as lease:
        with WindowsSandboxResources.prepare(tmp_path,Path(sys.base_prefix),(),storage_lease=lease) as resource:
            yield resource,lease


def run(resource,code):
    from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
    exe=resource.runtime_root/'python.exe'
    with WindowsSandboxProcess.launch(exe,(str(exe),'-I','-c',code),resource.stage_root,
            resource.environment,resource.profile_sid,256,resource.capability_sids) as p:
        status=p.wait(25)
        output=p.read(16384)
    assert status==0,output.decode(errors='replace')
    return output


@pytest.mark.parametrize('phase',['copy','profile-created','running'])
def test_real_volume_recovery_after_abrupt_owner_death(storage,tmp_path,phase):
    from isycode.platform_windows_sandbox_recovery import recover_owned_scratch
    code=r'''
import json,os,sys
from pathlib import Path
from isycode.windows_sandbox_storage_cli import configured_storage
from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
import isycode.platform_windows_sandbox_resources as native
from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
lease=BoundedStorageProvider(configured_storage()).open()
phase=sys.argv[2]
if phase=='copy':
 def die_copy(source,target,*args,**kwargs):
  Path(target).mkdir();Path(target,'partial.txt').write_text('partial-control')
  print(json.dumps({'root':str(Path(target).parent)}),flush=True);os._exit(17)
 native.shutil.copytree=die_copy
elif phase=='profile-created':
 original=native.write_ownership
 def die_record(root,name,sid,**kwargs):
  original(root,name,sid,**kwargs)
  if kwargs.get('phase')=='PROFILE_CREATED':
   print(json.dumps({'root':str(root)}),flush=True);os._exit(17)
 native.write_ownership=die_record
r=native.WindowsSandboxResources.prepare(Path(sys.argv[1]),Path(sys.base_prefix),(),storage_lease=lease)
exe=r.runtime_root/'python.exe'
p=WindowsSandboxProcess.launch(exe,(str(exe),'-I','-c','import time;time.sleep(120)'),r.stage_root,r.environment,r.profile_sid,256,r.capability_sids)
print(json.dumps({'root':str(r.scratch_root),'pid':p.pid}),flush=True)
os._exit(17)
'''
    source_root=Path(__file__).resolve().parents[1]/'src'
    child_env=os.environ.copy()
    child_env['PYTHONPATH']=os.pathsep.join(
        part for part in (str(source_root),child_env.get('PYTHONPATH','')) if part
    )
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path),phase],capture_output=True,
                          text=True,timeout=90,env=child_env)
    assert result.returncode==17,result.stderr
    witness=json.loads(result.stdout)
    root=Path(witness['root'])
    assert json.loads((root/'ownership.json').read_text())['schema']=='isycode-native-scratch/2'
    if 'pid' in witness:
        import pywintypes,win32api,win32event
        try:process=win32api.OpenProcess(0x100000,False,witness['pid'])
        except pywintypes.error as exc:assert exc.winerror==87
        else:
            try:assert win32event.WaitForSingleObject(process,10000)==0
            finally:process.Close()
    assert recover_owned_scratch(root,storage_config=storage)=='RECOVERED'
    assert not root.exists()
    print('real schema2 recovery:',phase,'RECOVERED')


@pytest.mark.parametrize('family',[socket.AF_INET,socket.AF_INET6])
@pytest.mark.parametrize('kind',[socket.SOCK_STREAM,socket.SOCK_DGRAM])
def test_real_volume_network_creation_denied(prepared,family,kind):
    resource,lease=prepared
    # A successful host socket is the positive control; LPAC must fail before traffic.
    with socket.socket(family,kind):pass
    code=(f'import socket\ntry: s=socket.socket({family},{kind})\n'
          'except PermissionError: print("network-creation-denied")\n'
          'else: s.close();raise RuntimeError("network socket created")\n')
    assert b'network-creation-denied' in run(resource,code)
    lease.assert_unchanged()


def test_real_volume_host_named_pipe_denied(prepared):
    import secrets,win32pipe,win32file,win32security as security,pywintypes
    from isycode.platform_windows_storage import WindowsStorage
    resource,lease=prepared
    name=r'\\.\pipe\isycode-control-'+secrets.token_hex(16)
    sid=security.ConvertSidToStringSid(WindowsStorage()._user())
    attributes=pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR=security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f'D:P(A;;GA;;;{sid})(A;;GA;;;SY)',1)
    pipe=win32pipe.CreateNamedPipe(name,0x40000003,0,1,4096,4096,0,attributes)
    try:
        # Host user can open the seeded witness, then disconnect the instance.
        control=win32file.CreateFile(name,0xc0000000,0,None,3,0,None)
        control.Close();win32pipe.DisconnectNamedPipe(pipe)
        code=('import ctypes as c\nk=c.WinDLL("kernel32",use_last_error=True)\n'
              'k.CreateFileW.argtypes=[c.c_wchar_p,c.c_ulong,c.c_ulong,c.c_void_p,c.c_ulong,c.c_ulong,c.c_void_p]\n'
              'k.CreateFileW.restype=c.c_void_p\nk.CloseHandle.argtypes=[c.c_void_p]\n'
              f'h=k.CreateFileW({name!r},0xc0000000,0,None,3,0,None)\n'
              'if h!=c.c_void_p(-1).value: k.CloseHandle(h);raise RuntimeError("host pipe opened")\n'
              'assert c.get_last_error()==5,c.get_last_error()\nprint("host-pipe-denied")\n')
        assert b'host-pipe-denied' in run(resource,code)
    finally:pipe.Close()
    lease.assert_unchanged()


def test_real_volume_appcontainer_named_pipe_denied_to_host(prepared):
    import secrets,win32security,win32file,pywintypes
    from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
    resource,lease=prepared
    name=r'\\.\pipe\isycode-lpac-control-'+secrets.token_hex(16)
    appcontainer_sid=win32security.ConvertSidToStringSid(win32security.SID(resource.profile_sid))
    code=r'''
import ctypes as c,sys
from ctypes import wintypes as w
class SA(c.Structure):
 _fields_=[('nLength',w.DWORD),('lpSecurityDescriptor',c.c_void_p),('bInheritHandle',w.BOOL)]
a=c.WinDLL('advapi32',use_last_error=True)
k=c.WinDLL('kernel32',use_last_error=True)
convert=a.ConvertStringSecurityDescriptorToSecurityDescriptorW
convert.argtypes=[w.LPCWSTR,w.DWORD,c.POINTER(c.c_void_p),c.POINTER(w.DWORD)]
convert.restype=w.BOOL
create=k.CreateNamedPipeW
create.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,w.DWORD,w.DWORD,w.DWORD,w.DWORD,c.POINTER(SA)]
create.restype=w.HANDLE
connect=k.ConnectNamedPipe
connect.argtypes=[w.HANDLE,c.c_void_p]
connect.restype=w.BOOL
close=k.CloseHandle
close.argtypes=[w.HANDLE]
free=k.LocalFree
free.argtypes=[c.c_void_p]
descriptor=c.c_void_p();size=w.DWORD()
sddl='D:P(A;;GA;;;'+sys.argv[2]+')(A;;GA;;;SY)'
if not convert(sddl,1,c.byref(descriptor),c.byref(size)):
 raise c.WinError(c.get_last_error())
attributes=SA(c.sizeof(SA),descriptor,False)
try:
 pipe=create(sys.argv[1],0x40000003,0,1,4096,4096,0,c.byref(attributes))
 if pipe==c.c_void_p(-1).value:
  error=c.get_last_error()
  if error==5:
   print('lpac-pipe-create-denied:5',flush=True)
   raise SystemExit(0)
  raise c.WinError(error)
 try:
  print('lpac-pipe-ready',flush=True)
  if not connect(pipe,None) and c.get_last_error()!=535:raise c.WinError(c.get_last_error())
 finally:close(pipe)
finally:free(descriptor)
'''
    exe=resource.runtime_root/'python.exe'
    with WindowsSandboxProcess.launch(exe,(str(exe),'-I','-c',code,name,appcontainer_sid),
            resource.stage_root,resource.environment,resource.profile_sid,256,
            resource.capability_sids) as process:
        ready=process.read(512)
        if b'lpac-pipe-create-denied:5' in ready:
            assert process.wait(5)==0
            lease.assert_unchanged()
            print('LPAC named-pipe creation denied with ERROR_ACCESS_DENIED; '
                  'reverse host-open remains NOT_DEMONSTRATED')
            return
        if b'lpac-pipe-ready' not in ready:
            try:status=process.wait(5)
            except TimeoutError:status='still-running'
            chunks=[ready]
            if status!='still-running':
                while True:
                    chunk=process.read(512)
                    if not chunk:break
                    chunks.append(chunk)
            pytest.fail('LPAC named-pipe witness did not start; status='
                        +str(status)+' output='+b''.join(chunks).decode(errors='replace'))
        try:
            handle=win32file.CreateFile(name,0xc0000000,0,None,3,0,None)
        except pywintypes.error as exc:
            assert exc.winerror==5,f'expected ERROR_ACCESS_DENIED, got {exc.winerror}'
        else:
            handle.Close()
            pytest.fail('host unexpectedly opened LPAC-created named pipe')
    lease.assert_unchanged()
    print('LPAC-created named pipe: host open denied with ERROR_ACCESS_DENIED')


def test_real_volume_winhttp_internet_denied_with_host_control(prepared):
    resource,lease=prepared
    code=r'''
import ctypes as c,sys
from ctypes import wintypes as w
v=c.WinDLL('winhttp',use_last_error=True)
def bind(name,args,result):
 f=getattr(v,name);f.argtypes=args;f.restype=result;return f
open_=bind('WinHttpOpen',[w.LPCWSTR,w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD],w.HANDLE)
connect=bind('WinHttpConnect',[w.HANDLE,w.LPCWSTR,w.WORD,w.DWORD],w.HANDLE)
request=bind('WinHttpOpenRequest',[w.HANDLE,w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,c.c_void_p,w.DWORD],w.HANDLE)
timeouts=bind('WinHttpSetTimeouts',[w.HANDLE,c.c_int,c.c_int,c.c_int,c.c_int],w.BOOL)
send=bind('WinHttpSendRequest',[w.HANDLE,w.LPCWSTR,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,c.c_size_t],w.BOOL)
receive=bind('WinHttpReceiveResponse',[w.HANDLE,c.c_void_p],w.BOOL)
close=bind('WinHttpCloseHandle',[w.HANDLE],w.BOOL)
handles=[]
try:
 session=open_('ISyCode-Parity-Control',1,None,None,0)
 if not session:raise c.WinError(c.get_last_error())
 handles.append(session);timeouts(session,2500,2500,2500,2500)
 connection=connect(session,'www.microsoft.com',443,0)
 if not connection:raise c.WinError(c.get_last_error())
 handles.append(connection)
 req=request(connection,'HEAD','/',None,None,None,0x800000)
 if not req:raise c.WinError(c.get_last_error())
 handles.append(req)
 if not send(req,None,0,None,0,0,0):raise c.WinError(c.get_last_error())
 if not receive(req,None):raise c.WinError(c.get_last_error())
 print('HTTP_OK')
except OSError as exc:
 print('HTTP_DENIED',exc.winerror)
 if len(sys.argv)>1 and sys.argv[1]=='host':raise
 assert exc.winerror in (5,10013,12029),exc
finally:
 for handle in reversed(handles):close(handle)
'''
    control=subprocess.run([sys.executable,'-c',code,'host'],capture_output=True,text=True,timeout=20)
    if control.returncode!=0:
        pytest.skip('NOT_DEMONSTRATED: host WinHTTP Internet positive control unavailable')
    output=run(resource,code)
    assert b'HTTP_DENIED' in output and b'HTTP_OK' not in output,output
    print('WinHTTP: host Internet HEAD succeeded; LPAC denied:',output.decode().strip())
    lease.assert_unchanged()


def test_real_volume_cancellation_during_preparation_preserves_original(storage,tmp_path,monkeypatch):
    import asyncio,threading
    from isycode.platform_windows_sandbox import WindowsSandbox
    import isycode.platform_windows_sandbox_resources as native
    (tmp_path/'original.txt').write_text('preserve-original')
    backend=WindowsSandbox();identity=backend.identity()
    original_copy=native.shutil.copytree
    entered,release=threading.Event(),threading.Event();roots=[]
    def blocked_copy(source,target,*args,**kwargs):
        roots.append(Path(target).parent);entered.set()
        if not release.wait(10):raise TimeoutError('test did not release preparation')
        return original_copy(source,target,*args,**kwargs)
    monkeypatch.setattr(native.shutil,'copytree',blocked_copy)
    async def scenario():
        task=asyncio.create_task(backend.start(tmp_path,'runtime/python.exe',('python','-c','print(1)'),'.',(),30,identity=identity))
        try:
            assert await asyncio.to_thread(entered.wait,5)
            task.cancel();release.set()
            with pytest.raises(asyncio.CancelledError):await task
        finally:
            release.set()
            if not task.done():task.cancel()
    asyncio.run(scenario())
    assert roots and all(not root.exists() for root in roots)
    assert (tmp_path/'original.txt').read_text()=='preserve-original'
    print('real cancellation: preparation clean, original preserved')


def test_real_volume_owner_cancellation_does_not_promote(storage,tmp_path,monkeypatch):
    import asyncio
    import isycode.platform_windows_sandbox as backend
    import isycode.platform_windows_sandbox_resources as native
    from isycode.command_runner import CommandRunOwner
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.approvals import ActionApprovalStore
    monkeypatch.setattr(backend,'NATIVE_ACCEPTED',True)
    (tmp_path/'.isyroot').write_text('');(tmp_path/'original.txt').write_text('preserve-original')
    authority=WorkspaceAuthority(tmp_path);authority.set_mode('classic')
    owner=CommandRunOwner(tmp_path,authority,ActionApprovalStore())
    captured=[];prepare=native.WindowsSandboxResources.prepare
    def capture(*args,**kwargs):
        resource=prepare(*args,**kwargs);captured.append(resource);return resource
    monkeypatch.setattr(native.WindowsSandboxResources,'prepare',capture)
    preview=owner.prepare(['python','-c','from pathlib import Path;import time;Path("not-promoted.txt").write_text("staged");print("ready",flush=True);time.sleep(120)'])
    async def scenario():
        ready=asyncio.Event()
        task=asyncio.create_task(owner.run(preview,owner.approvals.issue(preview.request),
            on_output=lambda text:ready.set() if 'ready' in text else None))
        try:
            await asyncio.wait_for(ready.wait(),30)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        finally:
            if not task.done():task.cancel()
    asyncio.run(scenario())
    assert captured and all(not resource.scratch_root.exists() for resource in captured)
    assert not (tmp_path/'not-promoted.txt').exists()
    assert (tmp_path/'original.txt').read_text()=='preserve-original'
    print('real cancellation: executing Job stopped, no promotion, scratch clean')


def test_real_volume_disappearance_refuses_start_without_fallback(storage,tmp_path,monkeypatch):
    import time,asyncio
    from isycode.platform_windows_sandbox_volume import BoundedStorageProvider
    import isycode.platform_windows_sandbox as native
    directory=os.environ.get('ISYCODE_TEST_VHD_DISAPPEARANCE_CONTROL')
    if not directory:pytest.skip('NOT_DEMONSTRATED: exact-image operator control required')
    control=Path(directory)
    def wait(name):
        deadline=time.monotonic()+40
        while not (control/name).exists():
            if (control/'operator-error.json').exists():raise AssertionError((control/'operator-error.json').read_text())
            if time.monotonic()>deadline:raise TimeoutError(name)
            time.sleep(.05)
        return json.loads((control/name).read_text(encoding='utf-8'))
    def signal(name):(control/name).write_text('{}',encoding='utf-8')
    wait('operator-ready.json')
    lease=BoundedStorageProvider(storage).open()
    identity=lease.identity
    try:
        signal('lease-ready.json');attempt=wait('lease-attempt.json')
        if attempt['still_attached']:lease.assert_unchanged()
        else:
            with pytest.raises(OSError):lease.assert_unchanged()
    finally:
        lease.close();signal('lease-released.json')
    try:
        wait('absent-ready.json')
        monkeypatch.setattr(native,'NATIVE_ACCEPTED',True)
        (tmp_path/'original.txt').write_text('preserve-original')
        backend=native.WindowsSandbox()
        assert backend.executable() is None
        with pytest.raises(OSError):BoundedStorageProvider(storage).open()
        approved={'backend':'windows-lpac-job/2','storage':identity.payload(),'runtime_sha256':'0'*64}
        with pytest.raises(OSError):
            asyncio.run(backend.start(tmp_path,'runtime/python.exe',('python','-c','raise RuntimeError("must not run")'),'.',(),30,identity=approved))
        assert (tmp_path/'original.txt').read_text()=='preserve-original'
        assert list(tmp_path.glob('isycode-lpac-*'))==[]
    finally:signal('missing-checked.json')
    restored=wait('reattached.json')
    assert restored['image']==identity.image_identifier
    with BoundedStorageProvider(storage).open(identity):pass
    print('real disappearance: active lease attempt',attempt,'missing volume refused; exact image restored')


def test_real_volume_disappearance_during_execution_never_promotes(storage,tmp_path):
    from isycode.platform_windows_sandbox_recovery import recover_owned_scratch
    directory=os.environ.get('ISYCODE_TEST_VHD_DISAPPEARANCE_CONTROL')
    if not directory:pytest.skip('NOT_DEMONSTRATED: exact-image operator control required')
    control=Path(directory)
    script=Path(__file__).resolve().parents[1]/'docs/platform-parity/evidence/owner-vhd-disappearance-20261014.py'
    source_root=Path(__file__).resolve().parents[1]/'src'
    child_env=os.environ.copy()
    child_env['PYTHONPATH']=os.pathsep.join(
        part for part in (str(source_root),child_env.get('PYTHONPATH','')) if part
    )
    result=subprocess.run([sys.executable,str(script),str(control),str(tmp_path/'project')],
                          capture_output=True,text=True,timeout=90,env=child_env)
    assert result.returncode==0,result.stderr
    witness=json.loads((control/'owner-outcome.json').read_text(encoding='utf-8'))
    root=Path(witness['root'])
    assert witness['original_preserved'] and witness['decision']!='ALLOW'
    if root.exists():assert recover_owned_scratch(root,storage_config=storage)=='RECOVERED'
    assert not root.exists()
    print(result.stdout.strip(),'; recovery clean')
