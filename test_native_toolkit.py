import json
import pytest

def test_bundled_skill_catalog_is_pinned_and_validated():
    from isycode.skill_catalog import skills, read_skill
    catalog=skills()
    assert 'brainstorming' in catalog and 'systematic-debugging' in catalog
    assert len(catalog)>=6
    for name in catalog:
        assert read_skill(name).strip()
    with pytest.raises(ValueError):read_skill('../secrets')

def test_mcp_presets_preserve_private_config_and_never_replace(tmp_path):
    from isycode.mcp_presets import add_preset
    from isycode.mcp_local import load_config
    path=tmp_path/'mcp.json'
    path.write_text(json.dumps({'servers':{'mine':{'command':['custom'], 'env':{'PRIVATE':'secret'}}}}))
    path.chmod(0o600)
    add_preset('playwright',path)
    configs=load_config(path)
    assert configs['mine'].env==(('PRIVATE','secret'),)
    assert configs['playwright'].argv==('npx','-y','@playwright/mcp@0.0.83')
    assert path.stat().st_mode&0o777==0o600
    before=path.read_bytes()
    with pytest.raises(ValueError):add_preset('playwright',path)
    assert path.read_bytes()==before
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(ValueError):add_preset('context7',link)
    with pytest.raises(ValueError):add_preset('untrusted',path)

def test_native_lsp_catalog_and_read_only_runtime(tmp_path,monkeypatch):
    import isycode.lsp as lsp
    binary=tmp_path/'rust-analyzer';binary.write_text('#!/bin/sh\n');binary.chmod(0o755)
    bwrap=tmp_path/'bwrap';bwrap.write_text('');bwrap.chmod(0o755)
    monkeypatch.setattr(lsp.shutil,'which',lambda name:str(binary) if name=='rust-analyzer' else str(bwrap) if name=='bwrap' else None)
    monkeypatch.setattr(lsp.ctypes.util,'find_library',lambda _: 'libseccomp.so.2')
    server=next(s for s in lsp.discover_servers() if s['id']=='rust-analyzer')
    assert server['state']=='sandbox_ready'
    command=lsp._sandbox_command(tmp_path,server)
    assert '/runtime/server' in command
    assert str(binary) in command
    assert '--ro-bind' in command and '--bind' not in command
    assert str(tmp_path/'unrelated') not in command
    assert 'socket socketpair' in ' '.join(command)

def test_lsp_source_index_skips_fifos_links_and_oversized_files(tmp_path):
    import os
    from isycode.lsp import _read_indexed_source
    regular=tmp_path/'safe.ts';regular.write_text('export class Safe {}')
    fifo=tmp_path/'blocked.ts';os.mkfifo(fifo)
    target=tmp_path/'target.ts';target.write_text('private')
    link=tmp_path/'linked.ts';link.symlink_to(target)
    large=tmp_path/'large.ts';large.write_bytes(b'x'*(64*1024+1))
    assert _read_indexed_source(tmp_path,regular)=='export class Safe {}'
    assert _read_indexed_source(tmp_path,fifo) is None
    assert _read_indexed_source(tmp_path,link) is None
    assert _read_indexed_source(tmp_path,large) is None

def test_typescript_real_symbols_and_anonymous_ipc_still_deny_network_and_writes(tmp_path):
    import asyncio,subprocess
    from isycode.lsp import discover_servers,workspace_symbols,_sandbox_command,network_deny_bootstrap
    server=next((s for s in discover_servers() if s['id']=='typescript'),None)
    if not server or server['state']!='sandbox_ready':pytest.skip('TypeScript sandbox runtime not installed')
    (tmp_path/'sample.ts').write_text('export class TypeScriptWitness {}\n')
    (tmp_path/'.private.ts').write_text('export class PrivateWitness {}\n')
    result=asyncio.run(workspace_symbols(tmp_path,'TypeScriptWitness',server))
    assert any(symbol['name']=='TypeScriptWitness' for symbol in result['symbols'])
    command=_sandbox_command(tmp_path,server);prefix=command[:command.index('--')+1]
    probe="""import socket
from pathlib import Path
a,b=socket.socketpair();a.sendmsg([b'local']);assert b.recvmsg(10)[0]==b'local'
try:socket.socket()
except PermissionError:pass
else:raise SystemExit('network not denied')
try:Path('/workspace/forbidden').write_text('x')
except OSError:pass
else:raise SystemExit('writes not denied')
print('local IPC only; network and writes denied')
"""
    output=subprocess.run(prefix+['/usr/bin/python3','-c',network_deny_bootstrap(32,allow_local_ipc=True),'/usr/bin/python3','-c',probe],capture_output=True,text=True,timeout=10)
    assert output.returncode==0,output.stderr
    assert 'network and writes denied' in output.stdout


def test_skill_manifest_tamper_is_rejected(tmp_path,monkeypatch):
    import isycode.skill_catalog as catalog
    (tmp_path/'manifest.json').write_text('{"skills":{"../private":{}}}')
    monkeypatch.setattr(catalog,'BUNDLE',tmp_path)
    with pytest.raises(ValueError):catalog.skills()

def test_native_skill_activation_enters_owned_prompt_without_granting_tools(tmp_path,monkeypatch,capsys):
    import asyncio
    from test_daily_tui import configure
    from isycode.tui import TUIApp
    from isycode.workspace_authority import WorkspaceAuthority
    root=configure(tmp_path,monkeypatch);seen=[]
    async def complete(provider,messages,**kwargs):
        seen.append(messages)
        kwargs['on_chunk']('content','Plan ready.')
        return {'text':'Plan ready.','tool_calls':[]}
    monkeypatch.setattr('isycode.tui.provider_complete',complete)
    async def scenario():
        app=TUIApp()
        async with app.run_test() as pilot:
            await pilot.pause();before=WorkspaceAuthority(root).effective_policy()
            app._select_skill('brainstorming')
            await app._run_chat('Help design a small UI.')
            assert any('User-selected workflow guidance' in message['content'] for message in seen[0] if message['role']=='system')
            assert WorkspaceAuthority(root).effective_policy()==before
            app._select_skill('brainstorming');assert app._active_skills==[]
    with capsys.disabled():asyncio.run(scenario())
