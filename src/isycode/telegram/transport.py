"""Bounded Bot API adapter. Secrets never appear in surfaced exceptions."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import aiohttp

from isycode.telegram.render import RenderedMessage, units

MAX_RESPONSE = 8 * 1024 * 1024
TOKEN = re.compile(r'[0-9]{5,16}:[A-Za-z0-9_-]{20,100}')
METHODS = frozenset({'getMe', 'getWebhookInfo', 'getUpdates', 'sendMessage', 'sendDocument',
                     'editMessageText', 'answerCallbackQuery'})


class TelegramError(RuntimeError):
    def __init__(self, code: str, retry_after: int = 0):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


@dataclass(frozen=True)
class SendReceipt:
    chat_id: int
    message_id: int


class TelegramTransport:
    def __init__(self, secret_reader, *, session_factory=aiohttp.ClientSession):
        self._secret_reader = secret_reader
        self._session_factory = session_factory

    async def _call(self, method, *, payload=None, form=None):
        if method not in METHODS:
            raise TelegramError('method_not_allowed')
        try:
            secret = self._secret_reader()
            if not isinstance(secret, str) or not TOKEN.fullmatch(secret):
                raise TelegramError('credential_unavailable')
            url = f'https://api.telegram.org/bot{secret}/{method}'
            async with self._session_factory(trust_env=False, timeout=aiohttp.ClientTimeout(total=45)) as session:
                async with session.post(url, json=payload, data=form, allow_redirects=False) as response:
                    raw = bytearray()
                    async for block in response.content.iter_chunked(65536):
                        raw.extend(block)
                        if len(raw) > MAX_RESPONSE:
                            raise TelegramError('response_too_large')
                    status = response.status
            try:
                body = json.loads(raw)
            except (TypeError, ValueError, UnicodeError):
                raise TelegramError('malformed_response') from None
            if not isinstance(body, dict):
                raise TelegramError('malformed_response')
            code = body.get('error_code', status)
            if status == 429 or code == 429:
                params = body.get('parameters')
                retry = params.get('retry_after', 1) if isinstance(params, dict) else 1
                raise TelegramError('rate_limited', min(3600, max(1, retry)) if type(retry) is int else 1)
            if status == 409 or code == 409:
                raise TelegramError('polling_conflict')
            if status != 200 or body.get('ok') is not True or 'result' not in body:
                raise TelegramError('telegram_rejected' if 400 <= status < 500 else 'transport_failure')
            return body['result']
        except TelegramError:
            raise
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError, RuntimeError):
            # Neither exception text nor traceback chain may expose the token URL.
            raise TelegramError('transport_failure') from None

    async def get_me(self):
        result = await self._call('getMe', payload={})
        if (not isinstance(result, dict) or result.get('is_bot') is not True
                or type(result.get('id')) is not int or not 0 < result['id'] < 2**52):
            raise TelegramError('invalid_bot_identity')
        return result['id']

    async def ensure_polling(self):
        info = await self._call('getWebhookInfo', payload={})
        if not isinstance(info, dict) or info.get('url') != '':
            raise TelegramError('webhook_conflict')

    async def get_updates(self, offset: int):
        if type(offset) is not int or offset < 0:
            raise ValueError('invalid offset')
        result = await self._call('getUpdates', payload={'offset': offset, 'timeout': 25,
                                  'limit': 100, 'allowed_updates': ['message', 'callback_query']})
        if (not isinstance(result, list) or len(result) > 100 or any(not isinstance(row, dict)
                or type(row.get('update_id')) is not int or row['update_id'] < 0 for row in result)):
            raise TelegramError('malformed_updates')
        return sorted(result, key=lambda row: row['update_id'])

    @staticmethod
    def _receipt(result, chat_id):
        if (not isinstance(result, dict) or not isinstance(result.get('chat'), dict)
                or result['chat'].get('id') != chat_id or result['chat'].get('type') != 'private'
                or type(result.get('message_id')) is not int or result['message_id'] <= 0):
            raise TelegramError('unverified_delivery')
        return SendReceipt(chat_id, result['message_id'])

    async def send(self, chat_id: int, render: RenderedMessage):
        if type(chat_id) is not int or chat_id <= 0 or not isinstance(render, RenderedMessage):
            raise ValueError('invalid private delivery')
        markup = render.markup()
        if render.document is None:
            payload = {'chat_id': chat_id, 'text': render.text, 'protect_content': True,
                       'link_preview_options': {'is_disabled': True}}
            if markup:
                payload['reply_markup'] = markup
            result = await self._call('sendMessage', payload=payload)
        else:
            form = aiohttp.FormData()
            form.add_field('chat_id', str(chat_id))
            form.add_field('caption', render.text)
            form.add_field('protect_content', 'true')
            form.add_field('document', render.document, filename=render.filename, content_type='text/plain')
            if markup:
                form.add_field('reply_markup', json.dumps(markup))
            result = await self._call('sendDocument', form=form)
        return self._receipt(result, chat_id)

    async def edit(self, chat_id: int, message_id: int, render: RenderedMessage):
        if type(chat_id) is not int or chat_id <= 0 or type(message_id) is not int or message_id <= 0 or render.document is not None:
            raise ValueError('invalid text edit')
        result = await self._call('editMessageText', payload={'chat_id': chat_id, 'message_id': message_id,
                                  'text': render.text, 'reply_markup': render.markup() or {'inline_keyboard': []},
                                  'link_preview_options': {'is_disabled': True}})
        receipt = self._receipt(result, chat_id)
        if receipt.message_id != message_id:
            raise TelegramError('unverified_delivery')
        return receipt

    async def answer_callback(self, callback_id: str, text: str = ''):
        if not isinstance(callback_id, str) or not 0 < len(callback_id) <= 128 or units(text) > 200:
            raise ValueError('invalid callback answer')
        if await self._call('answerCallbackQuery', payload={'callback_query_id': callback_id, 'text': text}) is not True:
            raise TelegramError('callback_not_acknowledged')
