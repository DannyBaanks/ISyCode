"""Safe provider diagnostics: classify signals without echoing credentials or bodies."""
import json
import re

CODE_KINDS = {"unsupported_image": "IMAGES", "unsupported_image_input": "IMAGES", "image_input_not_supported": "IMAGES", "unsupported_steering": "STEER", "steering_not_supported": "STEER", "invalid_api_key": "APIKEY", "authentication_error": "APIKEY", "insufficient_quota": "QUOTA", "billing_hard_limit_reached": "QUOTA", "credit_balance_too_low": "QUOTA", "rate_limit_exceeded": "RATE_LIMIT", "rate_limit_error": "RATE_LIMIT", "model_not_found": "MODEL", "not_found_error": "CONFIG", "permission_denied": "PERMISSION", "overloaded_error": "PROVIDER", "invalid_request_error": "REQUEST", "context_length_exceeded": "CONTEXT", "string_above_max_length": "CONTEXT"}
HINTS = {"IMAGES": "Provider reports that image input is not supported", "STEER": "Provider reports that steering is not supported", "APIKEY": "Provider credentials are missing, invalid or rejected", "QUOTA": "Provider reports exhausted quota or a billing restriction", "RATE_LIMIT": "Provider request limit reached; wait before retrying", "MODEL": "Selected model is unavailable to this account", "CONFIG": "Provider model or endpoint was not found", "PERMISSION": "Provider account lacks permission for this request", "PROVIDER": "Provider service failed or is overloaded", "NETWORK": "Could not connect to the provider", "TIMEOUT": "Provider did not respond in time", "STREAM": "Provider response was interrupted", "REQUEST": "Provider rejected the request parameters", "CONTEXT": "Request is larger than the model context window", "AUTHORITY": "Workspace Authority denied or could not verify the request", "UNKNOWN": "Provider failure without a recognized diagnostic"}
# Wordings providers use when a request exceeds the model window (OpenAI, vLLM/NIM,
# Anthropic, Gemini-compatible and others); matched only inside the error message.
CONTEXT_PHRASES = ("maximum context length", "context length", "context_length", "context window",
                   "prompt is too long", "too many tokens", "input is too long",
                   "reduce the length", "exceeds the maximum number of tokens",
                   "configured context size", "maximum prompt length",
                   "exceeds maximum input length", "token limit exceeded")

_CONTEXT_EXCLUSIONS = (
    re.compile(r"rate[-_\s]?limit", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"^(?:throttling error|service unavailable):", re.IGNORECASE),
    re.compile(r"max[_ ]tokens must be less than", re.IGNORECASE),
)

# vLLM-based endpoints (NVIDIA NIM, measured 2026-10-08 on openai/gpt-oss-20b)
# do not name the context: they subtract the prompt from the window and reject
# the negative remainder, e.g. "max_tokens must be at least 1, got -50994".
_NEGATIVE_OUTPUT = re.compile(r"max_(?:completion_)?tokens must be at least 1, got -\d+")

_MIN_OBSERVED_CONTEXT = 1_024
_MAX_OBSERVED_CONTEXT = 10_000_000
_MAX_OBSERVED_INPUT = 100_000_000

_MAX_CONTEXT_PATTERNS = (
    re.compile(r"maximum context length is ([\d,]+)\s*tokens?", re.IGNORECASE),
    re.compile(r"exceeds (?:the )?(?:model'?s )?maximum context length(?: of ([\d,]+)\s*tokens?|\s*\(([\d,]+)\))", re.IGNORECASE),
    re.compile(r"configured context size is ([\d,]+)\s*tokens?", re.IGNORECASE),
    re.compile(r"context length is only ([\d,]+)\s*tokens?", re.IGNORECASE),
    re.compile(r"too large for model with ([\d,]+)\s*maximum context length", re.IGNORECASE),
    re.compile(r"maximum prompt length is ([\d,]+)", re.IGNORECASE),
    re.compile(r"exceeds (?:the )?maximum allowed input length of ([\d,]+)\s*tokens?", re.IGNORECASE),
    re.compile(r"requested input length [\d,]+ exceeds maximum input length(?:\s+of)?\s+([\d,]+)", re.IGNORECASE),
    re.compile(r"`inputs` tokens \+ `max_new_tokens` must be <= ([\d,]+)", re.IGNORECASE),
    re.compile(r"prompt is too long:\s*[\d,]+\s*tokens?\s*>\s*([\d,]+)\s*maximum", re.IGNORECASE),
    re.compile(r"input token count\s*(?:\([\d,]+\)\s*)?exceeds the maximum(?:\s+number of tokens allowed)?\s*(?:\(|of\s+)([\d,]+)", re.IGNORECASE),
    re.compile(r"model'?s context length(?: is)?\s+([\d,]+)\s*tokens?", re.IGNORECASE),
)

_INPUT_TOKENS_PATTERNS = (
    re.compile(r"prompt contains at least ([\d,]+)\s*input tokens?", re.IGNORECASE),
    re.compile(r"your messages resulted in ([\d,]+)\s*tokens?", re.IGNORECASE),
    re.compile(r"prompt has ([\d,]+)\s*tokens?,\s*but the configured context size", re.IGNORECASE),
    re.compile(r"prompt is too long:\s*([\d,]+)\s*tokens?\s*>\s*[\d,]+\s*maximum", re.IGNORECASE),
    re.compile(r"requested input length ([\d,]+) exceeds maximum input length", re.IGNORECASE),
    re.compile(r"input\s*\(([\d,]+)\s*tokens?\)\s*is longer than", re.IGNORECASE),
)

_EMBEDDED_MESSAGE_RE = re.compile(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _string_error_message(raw: str) -> tuple[str | None, str]:
    """Extract (code, message) from a bare or JSON-serialized (even truncated) error string."""
    trimmed = raw.strip()[:8192]
    if not trimmed:
        return None, ""
    if trimmed.startswith("{"):
        try:
            nested = json.loads(trimmed)
        except (ValueError, TypeError):
            nested = None
        if isinstance(nested, dict):
            inner = nested.get("error")
            if isinstance(inner, dict):
                code = inner.get("code") or inner.get("type")
                msg = str(inner.get("message", ""))[:4096]
                if msg:
                    return code if isinstance(code, str) else None, msg
            code = nested.get("code") or nested.get("type")
            msg = str(nested.get("message", ""))[:4096]
            if msg:
                return code if isinstance(code, str) else None, msg
        match = _EMBEDDED_MESSAGE_RE.search(trimmed)
        if match:
            try:
                return None, json.loads('"' + match.group(1) + '"')[:4096]
            except (ValueError, TypeError):
                return None, match.group(1)[:4096]
    return None, trimmed[:4096]


def _extract_error_fields(body) -> tuple[str | None, str]:
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, dict):
        decoded = body
    elif isinstance(body, str) and body.strip():
        try:
            decoded = json.loads(body)
        except (ValueError, TypeError):
            return _string_error_message(body)
    else:
        return None, ""
    if not isinstance(decoded, dict):
        return None, ""
    error = decoded.get("error")
    if isinstance(error, dict):
        code = error.get("code") or error.get("type")
        message = str(error.get("message", ""))[:4096]
        return (code if isinstance(code, str) else None), message
    if isinstance(error, str):
        return _string_error_message(error)
    code = decoded.get("code") or decoded.get("type")
    message = str(decoded.get("message", ""))[:4096]
    return (code if isinstance(code, str) else None), message


def _parse_token_int(raw: str | None, low: int, high: int) -> int | None:
    if not raw:
        return None
    try:
        value = int(raw.replace(",", ""))
    except ValueError:
        return None
    return value if low <= value <= high else None


def parse_context_overflow_limit(body) -> tuple[int | None, int | None]:
    """Return ``(max_context_tokens, input_tokens)`` when the engine states explicit limits.

    Returns ``(None, None)`` for ambiguous overflow messages, rate limits, output-token
    rejections, or server failures so transient errors can never poison persisted limits.
    """
    code, message = _extract_error_fields(body)
    raw_text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else (
        json.dumps(body) if isinstance(body, dict) else (body if isinstance(body, str) else "")
    )
    candidates = [text for text in (message, raw_text[:8192]) if text]
    expanded = []
    for text in candidates:
        expanded.append(text)
        if '\\"' in text:
            expanded.append(text.replace('\\"', '"'))
    combined = "\n".join(expanded)
    if not combined:
        return None, None
    lowered = combined.casefold()
    if any(pattern.search(combined) for pattern in _CONTEXT_EXCLUSIONS):
        return None, None
    is_overflow = (
        code in {"context_length_exceeded", "model_context_window_exceeded"}
        or any(phrase in lowered for phrase in CONTEXT_PHRASES)
        or bool(_NEGATIVE_OUTPUT.search(lowered))
    )
    if not is_overflow:
        return None, None

    max_tokens: int | None = None
    for text in expanded:
        if max_tokens is not None:
            break
        for pattern in _MAX_CONTEXT_PATTERNS:
            match = pattern.search(text)
            if match:
                captured = match.group(1) or (match.group(2) if match.lastindex and match.lastindex >= 2 else None)
                parsed = _parse_token_int(captured, _MIN_OBSERVED_CONTEXT, _MAX_OBSERVED_CONTEXT)
                if parsed is not None:
                    max_tokens = parsed
                    break

    input_tokens: int | None = None
    for text in expanded:
        if input_tokens is not None:
            break
        for pattern in _INPUT_TOKENS_PATTERNS:
            match = pattern.search(text)
            if match:
                parsed = _parse_token_int(match.group(1), 1, _MAX_OBSERVED_INPUT)
                if parsed is not None:
                    input_tokens = parsed
                    break

    return max_tokens, input_tokens


def error_signals(body, headers=None):
    try:
        code, raw_message = _extract_error_fields(body)
        message = raw_message.casefold()
        if "credit balance is too low" in message:
            code = "credit_balance_too_low"
        elif (not any(pattern.search(raw_message) for pattern in _CONTEXT_EXCLUSIONS)
              and (any(phrase in message for phrase in CONTEXT_PHRASES) or _NEGATIVE_OUTPUT.search(message))):
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
