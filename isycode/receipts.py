"""IsyMotron receipt verification adapter shared by runtime and workspace."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReceiptAudit:
    """Canonical IsyMotron verification plus an explicit seal result."""

    verification: Any
    seal_status: str

    @property
    def status(self) -> str:
        return self.verification.status

    @property
    def reason(self) -> str:
        return self.verification.reason

    @property
    def claim_matched(self) -> bool | None:
        return self.verification.claim_matched

    @property
    def request_matched(self) -> bool | None:
        return self.verification.request_matched

    @property
    def decision_matched(self) -> bool | None:
        return self.verification.decision_matched

    @property
    def rederived(self) -> Any:
        return self.verification.rederived


class IsyMotronReceiptVerifier:
    """Delegate verification to IsyMotron's canonical verifier."""

    def verify(self, receipt: Any, claim_bundle: Any) -> Any:
        from isymotron.seal import HMAC_SHA256, resolve_key
        from isymotron.verify import NOT_VERIFIABLE, Verification, verify_receipt

        if (receipt is not None and getattr(receipt, "seal_kind", None) == HMAC_SHA256
                and not resolve_key()):
            return ReceiptAudit(
                Verification(
                    False,
                    NOT_VERIFIABLE,
                    "ISYMOTRON_RECEIPT_KEY is not configured",
                    None,
                    False,
                    False,
                    False,
                ),
                "NOT_VERIFIABLE",
            )
        verification = verify_receipt(receipt, claim_bundle)
        if receipt is None or claim_bundle is None:
            seal_status = "NOT_VERIFIABLE"
        else:
            seal_status = "PASS" if receipt.verify() else "REJECT"
        return ReceiptAudit(verification, seal_status)
