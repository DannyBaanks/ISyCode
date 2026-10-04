"""Safe provider diagnostics: classify signals without echoing credentials or bodies."""
import json

CODE_KINDS = {"invalid_api_key": "APIKEY", "authentication_error": "APIKEY", "insufficient_quota": "QUOTA", "billing_hard_limit_reached": "QUOTA", "credit_balance_too_low": "QUOTA", "rate_limit_exceeded": "RATE_LIMIT", "rate_limit_error": "RATE_LIMIT", "model_not_found": "MODEL", "not_found_error": "CONFIG", "permission_denied": "PERMISSION", "overloaded_error": "PROVIDER", "invalid_request_error": "REQUEST"}
HINTS = {"APIKEY": "Provider credentials are missing, invalid or rejected", "QUOTA": "Provider reports exhausted quota or a billing restriction", "RATE_LIMIT": "Provider request limit reached; wait before retrying", "MODEL": "Selected model is unavailable to this account", "CONFIG": "Provider model or endpoint was not found", "PERMISSION": "Provider account lacks permission for this request", "PROVIDER": "Provider service failed or is overloaded", "NETWORK": "Could not connect to the provider", "TIMEOUT": "Provider did not respond in time", "STREAM": "Provider response was interrupted", "REQUEST": "Provider rejected the request parameters", "AUTHORITY": "Workspace Authority denied or could not verify the request", "UNKNOWN": "Provider failure without a recognized diagnostic"}

def error_signals(body, headers=None):
    try:
        decoded = json.loads(body)
        error = decoded.get("error", {})
        if not isinstance(error, dict):
            error = {}
        code = error.get("code") or error.get("type")
        if "credit balance is too low" in str(error.get("message", ""))[:4096].casefold():
            code = "credit_balance_too_low"
    except (ValueError, TypeError, AttributeError):
        code = None
    code = code if isinstance(code, str) and code in CODE_KINDS else None
    try:
        retry = float((headers or {}).get("retry-after", ""))
        if not 0 <= retry <= 3600:
            retry = None
    except (ValueError, TypeError):
        retry = None
    return code, retry

def classify_provider_error(exc):
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    code = getattr(exc, "provider_code", None)
    if not code:
        cause = getattr(exc, "__cause__", None)
        body = getattr(exc, "body", None) or getattr(cause, "body", None)
        if isinstance(body, dict):
            body = json.dumps(body)
        code, _ = error_signals(body)

    if code not in CODE_KINDS:
        code = None
    if code:
        kind = CODE_KINDS[code]
    elif isinstance(exc, PermissionError):
        kind = "AUTHORITY"
    elif status == 401:
        kind = "APIKEY"
    elif status == 402:
        kind = "QUOTA"
    elif status == 403:
        kind = "PERMISSION"
    elif status == 429:
        kind = "RATE_LIMIT"
    elif status == 404:
        kind = "CONFIG"
    elif isinstance(status, int) and status >= 500:
        kind = "PROVIDER"
    elif isinstance(status, int) and status >= 400:
        kind = "REQUEST"
    elif isinstance(exc, TimeoutError) or "timed out" in str(exc).casefold():
        kind = "TIMEOUT"
    elif any(word in str(exc).casefold() for word in ("truncated", "incomplete", "closed", "streaming api", "stream interrupted")):
        kind = "STREAM"
    elif isinstance(exc, (ConnectionError, OSError)) or getattr(exc, "transport", False) or "connection failed" in str(exc).casefold():
        kind = "NETWORK"
    else:
        kind = "UNKNOWN"
    return {"error_kind": kind, "http_status": status if isinstance(status, int) else None, "provider_code": code, "provider_hint": HINTS[kind], "retry_after_s": getattr(exc, "retry_after", None), "phase": "stream" if kind == "STREAM" else "request"}
