import asyncio
import json

import pytest

from isycode.telegram.render import TelegramRenderer, RenderedMessage, split_text, units
from isycode.telegram.transport import TelegramTransport, TelegramError

TOKEN = '123456:' + 'A' * 35


class Response:
    def __init__(self, status, body):
        self.status, self.body, self.content = status, body, self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def iter_chunked(self, n):
        yield json.dumps(self.body).encode()


class Session:
    def __init__(self, response, calls):
        self.response, self.calls = response, calls
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def post(self, url, **kwargs):
        self.calls.append((url.rsplit('/', 1)[-1], kwargs))
        return self.response


def transport(status, body):
    calls = []
    def factory(**kwargs):
        assert kwargs['trust_env'] is False
        return Session(Response(status, body), calls)
    return TelegramTransport(lambda: TOKEN, session_factory=factory), calls


def test_plain_text_no_model_markup_and_private_receipt():
    adapter, calls = transport(200, {'ok': True, 'result': {'chat': {'id': 42, 'type': 'private'}, 'message_id': 3}})
    messages = TelegramRenderer().event({'kind': 'content', 'text': '<b>hostile</b>', 'buttons': ['fake']})
    receipt = asyncio.run(adapter.send(42, messages[0]))
    assert receipt.message_id == 3
    method, request = calls[0]
    assert method == 'sendMessage' and request['allow_redirects'] is False
    assert request['json']['text'] == '<b>hostile</b>'
    assert 'parse_mode' not in request['json'] and 'reply_markup' not in request['json']
    assert request['json']['protect_content'] is True


@pytest.mark.parametrize('status,body,code,retry', [
    (429, {'ok': False, 'error_code': 429, 'parameters': {'retry_after': 7}, 'description': TOKEN}, 'rate_limited', 7),
    (409, {'ok': False, 'description': TOKEN}, 'polling_conflict', 0),
    (302, {'ok': False}, 'transport_failure', 0),
    (200, {'ok': True, 'result': 'bad'}, 'malformed_updates', 0),
])
def test_errors_do_not_surface_token(status, body, code, retry):
    adapter, _ = transport(status, body)
    with pytest.raises(TelegramError) as error:
        asyncio.run(adapter.get_updates(0))
    assert error.value.code == code and error.value.retry_after == retry
    assert TOKEN not in str(error.value)


def test_unicode_chunks_preserve_text_and_bound_units():
    text = 'a' * 3999 + '🌎' + 'x' * 4000
    pieces = split_text(text)
    assert ''.join(pieces) == text
    assert all(units(part) <= 4000 for part in pieces)
    assert pieces[1].startswith('🌎')


def test_full_review_document_and_secrets_refused():
    renderer = TelegramRenderer()
    text = '🌎' * 6000
    rendered = renderer.review_material(text)[0]
    assert rendered.document == text.encode()
    assert not rendered.buttons
    with pytest.raises(ValueError): renderer.review_material('token=' + TOKEN)
    buttons = renderer.review_buttons('A' * 32).markup()['inline_keyboard']
    assert buttons[0][0]['callback_data'] == 'a:' + 'A' * 32


def test_wrong_chat_receipt_and_webhook_conflict():
    adapter, _ = transport(200, {'ok': True, 'result': {'chat': {'id': 99, 'type': 'private'}, 'message_id': 3}})
    with pytest.raises(TelegramError, match='unverified_delivery'):
        asyncio.run(adapter.send(42, RenderedMessage('hi')))
    adapter, _ = transport(200, {'ok': True, 'result': {'url': 'https://example.invalid'}})
    with pytest.raises(TelegramError, match='webhook_conflict'):
        asyncio.run(adapter.ensure_polling())
