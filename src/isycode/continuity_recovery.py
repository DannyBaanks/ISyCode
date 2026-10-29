"""Automatic recovery of one chat step after a transport/provider failure (ADR 0008).

Scope. Inside a chat turn, tools run only after a provider response has fully
arrived. A failure while a step's response is being requested or streamed
therefore happens before that step dispatched anything: every earlier tool
effect is already a receipt in the turn's messages, and nothing of the failed
step ran. Re-sending that same step's messages is a guarded continuation: a new
generation (a new provider request, journaled like any other) that cannot
repeat an effect. The partial text of the failed step is discarded, never
committed. OpenAI-compatible chat streams cannot be resumed, so same-response
recovery is not offered.

Policy. Each failure class has a fixed delay and a small attempt budget. The
delay does not grow between attempts (no exponential backoff). A valid
Retry-After is honoured up to the class cap; a longer one stops recovery and
is shown to the user instead of silently blocking. Credentials, quota,
permission, configuration, request, authority and unknown failures are never
retried. Esc cancels the waiting turn like any other await.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    kind: str
    delay_s: float          # fixed: the same before every attempt
    max_attempts: int       # automatic attempts after the original request
    retry_after_cap_s: float = 0.0  # 0: Retry-After is not consulted


# Delays are interactive: long enough for a dropped stream or a 5xx blip to
# clear, short enough that the user would not have retried faster by hand.
POLICIES: dict[str, RetryPolicy] = {
    "STREAM": RetryPolicy("STREAM", 0.75, 4),
    "NETWORK": RetryPolicy("NETWORK", 1.5, 3),
    "TIMEOUT": RetryPolicy("TIMEOUT", 2.0, 3),
    "PROVIDER": RetryPolicy("PROVIDER", 3.0, 3, retry_after_cap_s=15.0),
    "RATE_LIMIT": RetryPolicy("RATE_LIMIT", 7.0, 3, retry_after_cap_s=15.0),
}
# Everything else (APIKEY, QUOTA, PERMISSION, CONFIG, MODEL, REQUEST, AUTHORITY,
# IMAGES, STEER, PROTOCOL, UNKNOWN) is terminal: retrying cannot fix it or would guess.


# Status-less stream errors that the same request would hit again: a bad
# endpoint or credential shape, oversized frames/arguments, a malformed HTTP
# response. The diagnostic classifier calls them NETWORK; recovery must not.
_DETERMINISTIC_MARKERS = (
    "must be an http", "must not contain embedded credentials", "invalid http header",
    "invalid request-target", "exceed", "too large", "invalid http status line",
    "invalid chunked stream", "invalid content length",
)


def _deterministic(error: BaseException) -> bool:
    if getattr(error, "status", None) is not None:
        return False
    text = str(error).casefold()
    return any(marker in text for marker in _DETERMINISTIC_MARKERS)


@dataclass(frozen=True)
class RecoveryDecision:
    retry: bool
    kind: str
    delay_s: float
    attempt: int          # 1-based number of the attempt about to run
    max_attempts: int
    reason: str


def plan_recovery(error: BaseException, failures_so_far: int) -> RecoveryDecision:
    """Decide whether to re-send the failed step after ``failures_so_far`` failures."""
    from isycode.provider_errors import classify_provider_error

    info = classify_provider_error(error)
    kind = str(info.get("error_kind") or "UNKNOWN")
    if kind in {"NETWORK", "UNKNOWN"} and _deterministic(error):
        kind = "PROTOCOL"
    elif kind == "STREAM" and "streaming api error" in str(error).casefold():
        # An in-stream provider error whose code is not recognised: it may be a
        # refusal or a policy stop, so it is not repeated blindly.
        kind = "PROTOCOL"
    policy = POLICIES.get(kind)
    if policy is None:
        return RecoveryDecision(False, kind, 0.0, failures_so_far, 0, "not retryable")
    if failures_so_far > policy.max_attempts:
        return RecoveryDecision(False, kind, 0.0, failures_so_far, policy.max_attempts,
                                "recovery budget exhausted")
    delay = policy.delay_s
    hinted = info.get("retry_after_s")
    if policy.retry_after_cap_s and isinstance(hinted, (int, float)) and not isinstance(hinted, bool) \
            and hinted >= 0:
        if hinted > policy.retry_after_cap_s:
            return RecoveryDecision(False, kind, float(hinted), failures_so_far, policy.max_attempts,
                                    f"provider asks to wait {hinted:.0f}s")
        delay = max(delay, float(hinted))
    return RecoveryDecision(True, kind, delay, failures_so_far, policy.max_attempts, "scheduled")


async def wait_fixed(delay_s: float) -> None:
    """Sleep the fixed delay; cancelling the turn (Esc) cancels the wait."""
    await asyncio.sleep(delay_s)


__all__ = ["POLICIES", "RecoveryDecision", "RetryPolicy", "plan_recovery", "wait_fixed"]
