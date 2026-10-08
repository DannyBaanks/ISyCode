import json
import pytest
from isycode import web_fetch as web
from isycode.workspace_authority import WorkspaceAuthority
from isycode.action_audit import ActionAuditJournal

@pytest.mark.parametrize('url', ['http://example.com', 'https://localhost', 'https://127.0.0.1', 'https://[::1]', 'https://169.254.169.254', 'https://100.100.100.200/', 'https://[64:ff9b::a9fe:a9fe]/', 'https://[ff02::1]/', 'https://user:secret@example.com', 'https://example.com?q=secret', 'https://example.com/#secret', 'https://example.com:444/', 'https://example.com/\nheader'])
def test_private_or_credential_urls_denied(url):
    with pytest.raises(ValueError): web.validate_url(url)


def test_owner_requires_separate_host_grant_and_receipts_result(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path/'state'))
    root=tmp_path/'workspace';root.mkdir()
    authority=WorkspaceAuthority(root)
    owner=web.WebFetchOwner(root,authority)
    calls=[]
    monkeypatch.setattr(web,'fetch_public',lambda url: calls.append(url) or {'content':'fixture','untrusted':True})
    authority.set_grant('provider.request', enabled=True,network_hosts=['example.com'])
    assert owner.execute('https://example.com')['decision']=='DENY'
    assert calls==[]
    authority.set_grant('web.fetch',enabled=True,network_hosts=['example.com'])
    assert owner.execute('https://example.com')['content']=='fixture'
    assert owner.execute('https://other.example')['decision']=='DENY'
    assert calls==['https://example.com/']
    assert ActionAuditJournal(root).verify().status=='PASS'


def test_private_dns_and_redirect_denied(monkeypatch):
    from isycode.egress import ReviewedDestination
    monkeypatch.setattr(web,'review_destination',lambda url:ReviewedDestination('example.com',443,('127.0.0.1',),'https'))
    with pytest.raises(ValueError):web.fetch_public('https://example.com')
    for address in ('64:ff9b::a9fe:a9fe', 'ff02::1', '100.100.100.200'):
        monkeypatch.setattr(web,'review_destination',lambda url, address=address: ReviewedDestination('example.com',443,(address,),'https'))
        with pytest.raises(ValueError):web.fetch_public('https://example.com')
    monkeypatch.setattr(web,'review_destination',lambda url:ReviewedDestination('example.com',443,('93.184.216.34',),'https'))
    class Response:
        status=302
    class Conn:
        def __init__(self,*args):pass
        def request(self,*args,**kwargs):pass
        def getresponse(self):return Response()
        def close(self):pass
    monkeypatch.setattr(web,'PinnedHTTPS',Conn)
    assert web.fetch_public('https://example.com')['http_status']==302


def test_html_removes_executable_content():
    parser=web.PageText();parser.feed('<h1>Title</h1><script>secret()</script><style>css</style><p>Body</p>')
    assert ''.join(parser.parts)=='\nTitle\nBody'


def test_headless_web_grant_does_not_require_filesystem_grant(tmp_path,monkeypatch):
    from isycode.headless import available_tools, _dispatch
    from io import StringIO
    monkeypatch.setenv('XDG_STATE_HOME',str(tmp_path/'state'))
    root=tmp_path/'workspace';root.mkdir()
    a=WorkspaceAuthority(root)
    a.set_grant('web.fetch',enabled=True,network_hosts=['example.com'])
    assert [t['function']['name'] for t in available_tools(root,a)]==['webfetch']
    monkeypatch.setattr(web,'fetch_public',lambda url:{'content':'verified'})
    _,output=_dispatch(root,a,{'id':'test','function':{'name':'webfetch','arguments':json.dumps({'url':'https://example.com'})}},StringIO())
    assert json.loads(output)['content']=='verified'


@pytest.mark.parametrize('approved',[False,True])
def test_interactive_web_read_requires_actual_host_confirmation(tmp_path,monkeypatch,approved):
    import asyncio
    from test_daily_tui import configure
    from isycode.tui import TUIApp, GrantProviderNetworkScreen
    configure(tmp_path,monkeypatch)
    calls=[]
    monkeypatch.setattr(web,'fetch_public',lambda url:calls.append(url) or {'content':'fixture'})
    async def run():
        app=TUIApp()
        async with app.run_test(size=(120,40)) as pilot:
            await pilot.pause()
            job=asyncio.create_task(app._dispatch_chat_tool_impl({'id':'web','function':{'name':'webfetch','arguments':json.dumps({'url':'https://example.com'})}}))
            await pilot.pause()
            assert isinstance(app.screen,GrantProviderNetworkScreen)
            assert app.screen.host=='example.com'
            assert 'example.com' in str(app.screen.query_one('#provider-network-copy').render())
            assert calls==[]
            await pilot.click('#provider-network-confirm' if approved else '#provider-network-cancel')
            _,output=await job
            result=json.loads(output)
            assert calls==(['https://example.com/'] if approved else [])
            assert (result.get('content')=='fixture')==approved
    asyncio.run(run())
