"""Text for a decision that was already made.

Visual code may import this module. This module does not import Workspace
Authority, IsySentinel, approvals, or execution owners, and it never decides
whether an action is allowed.
"""
from __future__ import annotations


def verified_receipt_line(receipt_id: str, *, local: bool = True) -> str:
    """One verified-receipt line. The caller supplies an id it already checked."""
    if not isinstance(receipt_id, str) or not receipt_id or len(receipt_id) > 80:
        raise ValueError("receipt id must be a short string")
    label = "local receipt" if local else "receipt"
    return f"ISySentinel ALLOW · {label} {receipt_id[:12]} verified"


def denied_line(reason: str) -> str:
    """A denial line that cannot be turned into a success by its own text."""
    text = " ".join(str(reason or "denied").split())
    if not text:
        text = "denied"
    return f"ISySentinel DENY · {text[:240]}"
