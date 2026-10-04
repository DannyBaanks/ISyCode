import asyncio
from isycode.providers import Provider
from isycode.chat_transport import provider_complete

def test_subscription_uses_official_connector_never_api_key_transport(tmp_path,monkeypatch):
    executable=tmp_path/'codex';executable.write_text('#!/bin/sh\nexit 0\n');executable.chmod(0o700)
    monkeypatch.setenv('ISYCODE_CODEX_EXECUTABLE',str(executable))
    monkeypatch.setenv('ISYCODE_STATE_HOME',str(tmp_path/'state'))
    monkeypatch.setenv('OPENAI_API_KEY','must-not-be-used')
    called=[]
    class Peer:
        def __init__(self,*args,**kwargs): called.append('created')
        async def __aenter__(self): return self
        async def __aexit__(self,*args): called.append('closed')
        async def complete(self,model,messages,tools,on_chunk,*,effort=None): return {'text':'subscription answer','tool_calls':[]}
    async def forbidden(*args,**kwargs): raise AssertionError('Subscription fell back to API-key billing')
    monkeypatch.setattr('isycode.codex_connector.CodexConnector',Peer)
    monkeypatch.setattr('isycode.chat_transport.async_stream_complete',forbidden)
    provider=Provider(name='chatgpt',model='auto',api_key='never-used')
    response=asyncio.run(provider_complete(provider,[{'role':'user','content':'Hola'}],max_tokens=20))
    assert response['text']=='subscription answer'
    assert called==['created','closed'] and provider.api_key==''
