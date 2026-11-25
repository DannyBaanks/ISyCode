"""Plain, bounded Telegram presentation. Model text never supplies buttons."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from isycode.telegram.state import clean

MAX_TEXT_UNITS = 4000
MAX_DOCUMENT = 4 * 1024 * 1024


def units(text: str) -> int:
    return len(text.encode('utf-16-le')) // 2


def split_text(text: str, limit: int = MAX_TEXT_UNITS) -> list[str]:
    if not 2 <= limit <= MAX_TEXT_UNITS:
        raise ValueError('invalid text limit')
    parts, current, count = [], [], 0
    for char in text:
        n = 2 if ord(char) > 0xffff else 1
        if count + n > limit:
            parts.append(''.join(current))
            current, count = [], 0
        current.append(char)
        count += n
    if current:
        parts.append(''.join(current))
    return parts


@dataclass(frozen=True)
class RenderedMessage:
    text: str
    buttons: tuple[tuple[tuple[str, str], ...], ...] = field(default_factory=tuple)
    filename: str | None = None
    document: bytes | None = None

    def __post_init__(self):
        if not isinstance(self.text, str) or not 0 < units(self.text) <= MAX_TEXT_UNITS:
            raise ValueError('invalid Telegram message length')
        if (self.document is None) != (self.filename is None):
            raise ValueError('document and filename must be supplied together')
        if self.document is not None and (not isinstance(self.document, bytes)
                or len(self.document) > MAX_DOCUMENT or units(self.text) > 1000
                or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}', self.filename or '')):
            raise ValueError('invalid Telegram document')
        if len(self.buttons) > 8 or any(not 1 <= len(row) <= 4 for row in self.buttons):
            raise ValueError('invalid Telegram keyboard')
        for row in self.buttons:
            for label, data in row:
                if not isinstance(label, str) or not 0 < units(label) <= 80 or not isinstance(data, str) or not 0 < len(data.encode()) <= 64:
                    raise ValueError('invalid Telegram button')

    def markup(self):
        return {'inline_keyboard': [[{'text': label, 'callback_data': data} for label, data in row]
                                    for row in self.buttons]} if self.buttons else None


class TelegramRenderer:
    def text(self, text: str) -> list[RenderedMessage]:
        return [RenderedMessage(part) for part in split_text(clean(text) or '(sin contenido)')]

    def event(self, event: dict) -> list[RenderedMessage]:
        safe = clean(event)
        kind = safe.get('kind', 'event')
        if kind in {'content', 'reasoning', 'command.output'}:
            text = safe.get('text') or ''
            if not text:
                return []
            prefix = {'content': '', 'reasoning': 'Thinking (proveedor): ', 'command.output': 'Comando: '}[kind]
            return self.text(prefix + str(text))
        text = json.dumps(safe, ensure_ascii=False, indent=2)
        if units(text) <= MAX_TEXT_UNITS:
            return [RenderedMessage(text)]
        raw = text.encode('utf-8')
        if len(raw) > MAX_DOCUMENT:
            raise ValueError('event detail exceeds export budget')
        return [RenderedMessage('Detalle del evento', filename='evento.txt', document=raw)]

    def review_material(self, text: str) -> list[RenderedMessage]:
        # Never silently truncate or redact a review: if exact material cannot
        # safely be exported, the caller must reject this remote review.
        if clean(text) != text:
            raise ValueError('review contains sensitive material; use local review')
        raw = text.encode('utf-8')
        if len(raw) > MAX_DOCUMENT:
            raise ValueError('review exceeds export budget')
        if 0 < units(text) <= MAX_TEXT_UNITS:
            return [RenderedMessage(text)]
        return [RenderedMessage('Material completo de revisión', filename='revision.txt', document=raw)]

    def review_buttons(self, callback_id: str) -> RenderedMessage:
        if not re.fullmatch(r'[A-Za-z0-9_-]{32}', callback_id):
            raise ValueError('invalid opaque review id')
        return RenderedMessage('¿Apruebas el material completo anterior?',
                               ((('Aprobar', 'a:' + callback_id), ('Rechazar', 'r:' + callback_id)),))
