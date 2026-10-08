"""Safe provider diagnostics: classify signals without echoing credentials or bodies."""
import json
import re

CODE_KINDS = {"unsupported_image": "IMAGES", "unsupported_image_input": "IMAGES", "image_input_not_supported": "IMAGES", "unsupported_steering": "STEER", "steering_not_supported": "STEER", "invalid_api_key": "APIKEY", "authentication_error": "APIKEY", "insufficient_quota": "QUOTA", "billing_hard_limit_reached": "QUOTA", "credit_balance_too_low": "QUOTA", "rate_limit_exceeded": "RATE_LIMIT", "rate_limit_error": "RATE_LIMIT", "model_not_found": "MODEL", "not_found_error": "CONFIG", "permission_denied": "PERMISSION", "overloaded_error": "PROVIDER", "invalid_request_error": "REQUEST", "context_length_exceeded": "CONTEXT", "string_above_max_length": "CONTEXT"}
HINTS = {"IMAGES": "Provider reports that image input is not supported", "STEER": "Provider reports that steering is not supported", "APIKEY": "Provider credentials are missing, invalid or rejected", "QUOTA": "Provider reports exhausted quota or a billing restriction", "RATE_LIMIT": "Provider request limit reached; wait before retrying", "MODEL": "Selected model is unavailable to this account", "CONFIG": "Provider model or endpoint was not found", "PERMISSION": "Provider account lacks permission for this request", "PROVIDER": "Provider service failed or is overloaded", "NETWORK": "Could not connect to the provider", "TIMEOUT": "Provider did not respond in time", "STREAM": "Provider response was interrupted", "REQUEST": "Provider rejected the request parameters", "CONTEXT": "Request is larger than the model context window", "AUTHORITY": "Workspace Authority denied or could not verify the request", "UNKNOWN": "Provider failure without a recognized diagnostic"}
# Wordings providers use when a request exceeds the model window (OpenAI, vLLM/NIM,
# Anthropic, Gemini-compatible and others); matched only inside the error message.
CONTEXT_PHRASES = ("maximum context length", "context length", "context_length", "context window",
                   "prompt is too long", "too many tokens", "input is too long",
                   "reduce the length", "exceeds the maximum number of tokens")

# vLLM-based endpoints (NVIDIA NIM, measured 2026-10-08 on openai/gpt-oss-20b)
# do not name the context: they subtract the prompt from the window and reject
# the negative remainder, e.g. "max_tokens must be at least 1, got -50994".
_NEGATIVE_OUTPUT = re.compile(r"max_(?:completion_)?tokens must be at least 1, got -\d+")

def error_signals(body, headers=None):
    try:
        decoded = json.loads(body)
        error = decoded.get("error", {})
        if not isinstance(error, dict):
            error = {}
        code = error.get("code") or error.get("type")
        message = str(error.get("message", ""))[:4096].casefold()
        if "credit balance is too low" in message:
            code = "credit_balance_too_low"
        elif any(phrase in message for phrase in CONTEXT_PHRASES) or _NEGATIVE_OUTPUT.search(message):
            code = "context_length_exceeded"
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
    elif status == 413:
        kind = "CONTEXT"
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
