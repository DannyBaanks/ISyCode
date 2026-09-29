"""Narrow HTTP client for ISyCo's read-only semantic Gateway surface.

This adapter does not itself grant authority. Callers must first obtain the
appropriate IsyMotron decision; the Gateway key is a separate authentication
credential carrying the ``isyco.semantic`` scope.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from isycode.gateway_client import GatewayClient, GatewayError, _SameOriginRedirectHandler


OPERATIONS: dict[str, str] = {
    "context": "context",
    "symbols/search": "symbols/search",
    "document-symbols": "document-symbols",
    "definition": "definition",
    "references": "references",
    "hover": "hover",
    "diagnostics": "diagnostics",
    "semantic-slice": "semantic-slice",
    "callers": "callers",
    "callees": "callees",
    "implementations": "implementations",
}

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

_COMMON_FIELDS = {"path", "target", "symbol", "query", "budget_chars", "max_results", "include"}
_OPERATION_FIELDS = {
    "context": _COMMON_FIELDS,
    "symbols/search": {"path", "query", "symbol", "max_results", "include"},
    "document-symbols": {"path", "target", "max_results", "include"},
    "definition": {"path", "target", "symbol", "budget_chars"},
    "references": {"path", "target", "symbol", "max_results", "include"},
    "hover": {"path", "target", "symbol", "budget_chars"},
    "diagnostics": {"path", "target"},
    "semantic-slice": {"path", "target", "symbol", "budget_chars"},
    "implementations": {"path", "target", "symbol", "max_results", "include"},
    "callers": {"path", "target", "symbol", "max_results", "include"},
    "callees": {"path", "target", "symbol", "max_results", "include"},
}


def validate_semantic_payload(operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the bounded, operation-specific read-only HTTP request shape."""
    if operation not in OPERATIONS:
        raise ValueError("Unsupported semantic operation.")
    if not isinstance(payload, Mapping) or set(payload) - _OPERATION_FIELDS[operation]:
        raise ValueError("Semantic payload contains fields not supported by this operation.")
    result = dict(payload)
    for key in ("path", "target", "symbol", "query"):
        value = result.get(key)
        maximum = {"path": 400, "query": 128, "symbol": 256, "target": 512}[key]
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > maximum):
            raise ValueError(f"Semantic field '{key}' is invalid.")
    if "budget_chars" in result and (type(result["budget_chars"]) is not int or not 256 <= result["budget_chars"] <= 24_000):
        raise ValueError("Semantic budget_chars must be between 256 and 24000.")
    if "max_results" in result and (type(result["max_results"]) is not int or not 1 <= result["max_results"] <= 250):
        raise ValueError("Semantic max_results must be between 1 and 250.")
    if "include" in result:
        include = result["include"]
        if (not isinstance(include, (list, tuple)) or len(include) > 32
                or not all(isinstance(item, str) and 0 < len(item) <= 64 for item in include)):
            raise ValueError("Semantic include must be a list of at most 32 short strings.")
        result["include"] = list(include)
    if operation == "symbols/search" and not (result.get("query") or result.get("symbol")):
        raise ValueError("symbols/search requires query or symbol.")
    if operation == "context" and not any(result.get(key) for key in ("path", "target", "query", "symbol")):
        raise ValueError("context requires a path, target, query, or symbol.")
    if operation in {"document-symbols", "diagnostics"} and not (result.get("path") or result.get("target")):
        raise ValueError(f"{operation} requires path or target.")
    if operation in {"definition", "hover", "semantic-slice"}:
        if not (result.get("target") or (result.get("path") and result.get("symbol"))):
            raise ValueError(f"{operation} requires target or a path and symbol.")
    if operation in {"references", "implementations", "callers", "callees"} and not (result.get("symbol") or result.get("target")):
        raise ValueError(f"{operation} requires symbol or target.")
    return result


class SemanticGatewayClient:
    """Call only the documented semantic POST routes on a configured Gateway."""

    def __init__(self, *, base_url: str | None = None,
                 api_key: str | None = None, timeout_s: float = 20.0):
        self.base_url = (base_url or os.environ.get("GATEWAY_URL")
                         or "http://127.0.0.1:8787").strip().rstrip("/")
        GatewayClient._validate_base_url(self.base_url)
        self._api_key = api_key if api_key is not None else self._load_key()
        self.timeout_s = max(1.0, min(float(timeout_s), 30.0))

    @staticmethod
    def _load_key() -> str:
        configured = os.environ.get("GATEWAY_API_KEY", "")
        if configured:
            return configured
        try:
            from isycode.credentials import CredentialVault, CredentialVaultError

            return CredentialVault().latest_secret_for_service("isyco-gateway") or ""
        except (CredentialVaultError, OSError, ValueError):
            return ""

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def workspace_identity(self) -> str:
        """Read the opaque configured identity; the Gateway never returns its path."""
        request = urllib.request.Request(
            f"{self.base_url}/v1/workspace/identity", method="GET",
            headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
        )
        self._mark_loopback_as_local_tls(request)
        opener = urllib.request.build_opener(_SameOriginRedirectHandler)
        try:
            with opener.open(request, timeout=self.timeout_s) as response:
                raw = response.read(16 * 1024)
            data = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise GatewayError("WORKSPACE_IDENTITY_ERROR", f"Gateway identity returned HTTP {exc.code}.", exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GatewayError("SEMANTIC_UNAVAILABLE", "Semantic Gateway is unavailable.", 0) from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GatewayError("INVALID_RESPONSE", "Gateway identity returned invalid JSON.", 502) from None
        result = data.get("result", data) if isinstance(data, dict) else None
        identity = result.get("workspace_id") if isinstance(result, dict) else None
        if not isinstance(identity, str) or not identity or len(identity) > 128:
            raise GatewayError("WORKSPACE_ID_NOT_CONFIGURED", "Gateway workspace identity is not configured.", 503)
        return identity

    def call(self, operation: str, payload: Mapping[str, Any], *,
             workspace_id: str | None = None) -> dict[str, Any]:
        """Perform one bounded semantic request; never follow cross-origin redirects."""
        route = OPERATIONS.get(operation)
        if route is None:
            raise ValueError("Unsupported semantic operation.")
        if not self._api_key:
            raise GatewayError("AUTH_REQUIRED", "Add a named Gateway key with isyco.semantic scope.", 401)
        payload = validate_semantic_payload(operation, payload)
        if not isinstance(workspace_id, str) or not workspace_id or len(workspace_id) > 128:
            raise ValueError("A configured workspace identity is required.")
        payload["workspace_id"] = workspace_id
        try:
            data = json.dumps(dict(payload), ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Semantic request payload must contain JSON values.") from exc
        if len(data) > MAX_REQUEST_BYTES:
            raise ValueError("Semantic request exceeds the 64 KiB limit.")

        request = urllib.request.Request(
            f"{self.base_url}/v1/{route}", data=data, method="POST",
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json",
                     "Accept": "application/json"},
        )
        self._mark_loopback_as_local_tls(request)
        opener = urllib.request.build_opener(_SameOriginRedirectHandler)
        try:
            with opener.open(request, timeout=self.timeout_s) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise GatewayError("RESPONSE_TOO_LARGE", "Semantic Gateway response exceeded 2 MiB.", 502)
            result = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Deliberately omit response bodies: upstream errors can include
            # workspace paths and should not be echoed into chat or logs.
            raise GatewayError("SEMANTIC_HTTP_ERROR", f"Semantic Gateway returned HTTP {exc.code}.", exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GatewayError("SEMANTIC_UNAVAILABLE", "Semantic Gateway is unavailable.", 0) from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GatewayError("INVALID_RESPONSE", "Semantic Gateway returned invalid JSON.", 502) from None
        if not isinstance(result, dict):
            raise GatewayError("INVALID_RESPONSE", "Semantic Gateway returned an invalid response.", 502)
        # ISyCo Gateway responses use the standard {result: ...} envelope.
        payload_result = result.get("result", result)
        if not isinstance(payload_result, dict):
            raise GatewayError("INVALID_RESPONSE", "Semantic Gateway result is not an object.", 502)
        return payload_result

    def _mark_loopback_as_local_tls(self, request: urllib.request.Request) -> None:
        """Satisfy a loopback-only Gateway TLS terminator policy locally."""
        from urllib.parse import urlsplit

        host = (urlsplit(self.base_url).hostname or "").casefold().rstrip(".")
        if host in {"localhost", "127.0.0.1", "::1"}:
            request.add_header("X-Forwarded-Proto", "https")


__all__ = ["OPERATIONS", "SemanticGatewayClient", "validate_semantic_payload"]
