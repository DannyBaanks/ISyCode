"""Explicit Telegram grants and process-local, request-bound remote reviews."""
from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from isycode.action_runtime import ActionReceipt, ProductActionGate
from isycode.agent_tools import ReviewMaterial, policy_fingerprint
from isycode.security import ActionRequest

ACTIONS = frozenset({'telegram.connect', 'telegram.receive', 'telegram.send'})


@dataclass(frozen=True)
class Peer:
    profile: str
    bot_id: int
    user_id: int
    chat_id: int

    def valid(self) -> bool:
        return (isinstance(self.profile, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', self.profile) is not None
                and type(self.bot_id) is int and 0 < self.bot_id < 2**52
                and type(self.user_id) is int and 0 < self.user_id < 2**52
                and type(self.chat_id) is int and self.chat_id == self.user_id)

    @property
    def target(self) -> str:
        if not self.valid():
            raise ValueError('invalid private Telegram peer')
        return f'{self.profile}:{self.bot_id}:{self.user_id}'

    def accepts(self, message: dict, sender: dict) -> bool:
        if not self.valid() or not isinstance(message, dict) or not isinstance(sender, dict):
            return False
        chat = message.get('chat')
        return (isinstance(chat, dict) and chat.get('type') == 'private'
                and type(chat.get('id')) is int and chat['id'] == self.chat_id
                and type(sender.get('id')) is int and sender['id'] == self.user_id
                and sender.get('is_bot') is False
                and not any(key in message for key in ('forward_origin', 'forward_from', 'forward_from_chat', 'is_automatic_forward')))


class TelegramOwner:
    """No implicit integration grants, even in Classic and Flow.

    This owner authorizes a particular peer and exact material digest. The
    service must keep the transport private and call these methods at intake
    and egress. No remote content may select a different peer or grant.
    """
    def __init__(self, root: Path, authority, approvals=None):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.gate = ProductActionGate(self.root, authority, owner_id='telegram')

    def request(self, action: str, peer: Peer, material: bytes = b'') -> ActionRequest:
        if action not in ACTIONS or not isinstance(peer, Peer) or not peer.valid() or not isinstance(material, bytes):
            raise ValueError('invalid Telegram action')
        return ActionRequest(action, self.root, peer.target, {
            'profile': peer.profile, 'bot_id': peer.bot_id, 'user_id': peer.user_id,
            'chat_id': peer.chat_id, 'material_sha256': hashlib.sha256(material).hexdigest(),
        }, execution_owner='telegram')

    def authorize(self, action: str, peer: Peer, material: bytes = b'') -> ActionRequest:
        request = self.request(action, peer, material)
        authority, decision = self.gate.authorize(request)
        if not authority.allowed or not decision.allowed:
            raise PermissionError('Telegram integration is not granted for this workspace and peer')
        return request

    def receipt(self, request: ActionRequest, result: bytes) -> ActionReceipt:
        receipt = ActionReceipt('rcpt_' + secrets.token_hex(8), request.action_id, request.digest,
                                'ALLOW', 'SUCCESS', hashlib.sha256(result).hexdigest())
        if not self.gate.persist_receipt(request, receipt):
            raise RuntimeError('Telegram outcome could not be journaled')
        return receipt


@dataclass(frozen=True)
class ReviewContext:
    peer: Peer
    workspace: Path
    session_id: str
    turn_id: str
    policy_fingerprint: str


@dataclass(frozen=True)
class PendingReview:
    callback_id: str
    request_digest: str
    material_digest: str
    expires_at: float
    context: ReviewContext


class RemoteReviews:
    """Callbacks are not native approval tokens. No state survives a restart."""
    def __init__(self, *, clock=time.monotonic, ttl=120):
        self.clock, self.ttl = clock, min(120, max(1, ttl))
        self._pending: dict[str, PendingReview] = {}
        self._delivered: set[str] = set()
        self._lock = threading.Lock()

    def open(self, context: ReviewContext, material: ReviewMaterial) -> PendingReview:
        if (not context.peer.valid() or context.policy_fingerprint != material.policy_fingerprint
                or not re.fullmatch(r'[a-f0-9]{64}', material.digest)
                or not re.fullmatch(r'[a-f0-9]{32}', context.session_id)
                or not re.fullmatch(r'[a-f0-9]{32}', context.turn_id)):
            raise ValueError('invalid remote review context')
        if len(material.text.encode('utf-8')) > 4 * 1024 * 1024:
            raise ValueError('review material exceeds the delivery budget')
        review = PendingReview(secrets.token_urlsafe(24), material.digest,
                               hashlib.sha256(material.text.encode()).hexdigest(),
                               self.clock() + self.ttl, context)
        with self._lock:
            for key in list(self._pending):
                if self._pending[key].expires_at <= self.clock():
                    self._pending.pop(key)
                    self._delivered.discard(key)
            if len(self._pending) >= 128:
                raise RuntimeError('too many pending remote reviews')
            self._pending[review.callback_id] = review
        return review

    def mark_delivered(self, callback_id: str, material_digest: str) -> bool:
        """Only call after the complete, exact material was successfully exported."""
        with self._lock:
            review = self._pending.get(callback_id)
            if not review or review.expires_at <= self.clock() or review.material_digest != material_digest:
                return False
            self._delivered.add(callback_id)
            return True

    def resolve(self, callback_id: str, context: ReviewContext, approve: bool, *,
                request: ActionRequest, authority) -> bool:
        with self._lock:
            review = self._pending.get(callback_id)
            if review is None or review.context != context:
                return False
            self._pending.pop(callback_id)
            delivered = callback_id in self._delivered
            self._delivered.discard(callback_id)
        return (approve is True and delivered and review.expires_at > self.clock()
                and request.digest == review.request_digest
                and request.workspace_root == context.workspace
                and authority.root == context.workspace
                and policy_fingerprint(authority) == context.policy_fingerprint)

    def invalidate(self) -> None:
        with self._lock:
            self._pending.clear()
            self._delivered.clear()
