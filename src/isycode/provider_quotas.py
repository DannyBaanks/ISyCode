"""Normalized provider quota and rate-limit snapshots for OAuth and API-key providers.

Only facts directly reported by the provider (official OAuth quota endpoints,
Codex app-server ``account/rateLimits/read``, OpenRouter/DeepSeek account
endpoints, or HTTP response rate-limit headers) are stored or displayed.
Nothing is guessed, and no credentials or raw headers are ever persisted.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from isycode.antigravity_connector import (
    family_quota_pair,
    format_reset_countdown,
    model_to_quota_family,
)
from isycode.localization import tr

_LOCK = threading.Lock()
_MEMORY_CACHE: dict[tuple[str, str], dict[str, Any]] = {}

# Providers that expose a dedicated read-only quota/balance query (always gated by
# ProviderNetworkOwner before any network or subprocess call).
LIVE_QUOTA_PROVIDERS = frozenset({"antigravity", "chatgpt", "openrouter", "deepseek"})


def _state_file() -> Path:
    from isycode.state_index import StateIndex

    return StateIndex.default_root() / "provider_quotas.json"


def _cache_scope_key() -> str:
    return str(_state_file())


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _safe_text(value: Any, limit: int = 80) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = "".join(ch for ch in value if 32 <= ord(ch) < 127 or ord(ch) >= 160).strip()
    return cleaned[:limit]


def _format_count(value: float | None, unit: str = "") -> str:
    if value is None:
        return "?"
    if unit == "usd":
        return f"${value:,.2f}"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1_000:.1f}K"
    if abs(value - round(value)) < 1e-6:
        return f"{int(round(value)):,}"
    return f"{value:,.2f}"


def _format_reset_value(raw: str, *, now: dt.datetime | None = None) -> str:
    text = _safe_text(raw, 48)
    if not text:
        return ""
    # ISO-8601 timestamp
    if "T" in text and ("Z" in text or "+" in text or "-" in text[10:]):
        return format_reset_countdown(text, now=now)
    # Unix epoch seconds or relative seconds
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        num = float(text)
        current = now or dt.datetime.now(dt.timezone.utc)
        if num > 1_000_000_000:
            target = dt.datetime.fromtimestamp(num, tz=dt.timezone.utc)
            return format_reset_countdown(target.strftime("%Y-%m-%dT%H:%M:%SZ"), now=current)
        secs = int(round(num))
        if secs <= 0:
            return "now"
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        mins, sec = divmod(rem, 60)
        if days:
            return f"{days}d{hours}h"
        if hours:
            return f"{hours}h{mins:02d}m"
        if mins:
            return f"{mins}m{sec:02d}s" if sec else f"{mins}m"
        return f"{sec}s"
    # Duration strings such as "12s", "1m30s", "2h5m", "450ms"
    if re.fullmatch(r"[0-9a-zA-Z.]+", text) and len(text) <= 20:
        return text
    return ""


def _window_label_from_minutes(minutes: int | None, fallback: str) -> str:
    if not isinstance(minutes, int) or minutes <= 0:
        return fallback
    if minutes == 300:
        return "5h"
    if minutes == 10080:
        return "7d"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def _load_disk_locked() -> dict[str, dict[str, Any]]:
    path = _state_file()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): v
        for k, v in raw.items()
        if isinstance(k, str) and isinstance(v, dict)
    }


def _save_snapshot(provider: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    key = provider.strip().lower()
    scope = _cache_scope_key()
    with _LOCK:
        _MEMORY_CACHE[(scope, key)] = snapshot
        try:
            path = _state_file()
            data = _load_disk_locked()
            data[key] = snapshot
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass
    return snapshot


def get_provider_quota(provider: str) -> dict[str, Any] | None:
    """Return the latest sanitized quota snapshot observed for ``provider``, or None."""
    key = (provider or "").strip().lower()
    if not key:
        return None
    scope = _cache_scope_key()
    with _LOCK:
        cached = _MEMORY_CACHE.get((scope, key))
        if isinstance(cached, dict):
            return dict(cached)
        disk = _load_disk_locked()
        found = disk.get(key)
        if isinstance(found, dict):
            _MEMORY_CACHE[(scope, key)] = found
            return dict(found)
    return None


def clear_provider_quota(provider: str) -> None:
    """Remove cached quota data for ``provider`` (e.g. on logout or key removal)."""
    key = (provider or "").strip().lower()
    if not key:
        return
    scope = _cache_scope_key()
    with _LOCK:
        _MEMORY_CACHE.pop((scope, key), None)
        try:
            path = _state_file()
            data = _load_disk_locked()
            if key in data:
                data.pop(key, None)
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                os.replace(tmp, path)
        except OSError:
            pass


# ── Antigravity OAuth quota ─────────────────────────────────────────────

def record_antigravity_quota(quota: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize and store an Antigravity ``/usage`` quota snapshot."""
    if not isinstance(quota, dict) or not quota.get("ok"):
        return None
    buckets: list[dict[str, Any]] = []
    for raw in quota.get("buckets") or ():
        if not isinstance(raw, dict):
            continue
        pct = _safe_float(raw.get("pct"))
        if pct is None:
            continue
        win = _safe_text(str(raw.get("window") or ""), 24)
        label = "5h" if win == "5h" else ("7d" if win == "weekly" else win or "quota")
        buckets.append({
            "label": label,
            "group": _safe_text(str(raw.get("group") or raw.get("family") or "Models"), 48),
            "family": _safe_text(str(raw.get("family") or ""), 32),
            "remaining_pct": round(max(0.0, min(100.0, pct)), 1),
            "remaining": None,
            "limit": None,
            "unit": "%",
            "reset_time": _safe_text(str(raw.get("reset_time") or ""), 40),
        })
    if not buckets:
        return None
    snapshot = {
        "provider": "antigravity",
        "source": "Google Antigravity OAuth",
        "plan": None,
        "updated_at": _safe_text(str(quota.get("updated_at") or ""), 40) or _utc_now_iso(),
        "model": None,
        "buckets": buckets,
        "credits": None,
        "raw_antigravity": {
            "ok": True,
            "buckets": list(quota.get("buckets") or ()),
            "families": dict(quota.get("families") or {}),
            "min_pct": quota.get("min_pct"),
            "updated_at": quota.get("updated_at"),
        },
    }
    return _save_snapshot("antigravity", snapshot)


# ── ChatGPT / Codex OAuth rate limits ───────────────────────────────────

def _codex_window_bucket(window: Any, *, fallback_label: str, group: str, family: str = "") -> dict[str, Any] | None:
    if not isinstance(window, dict):
        return None
    used = _safe_float(window.get("usedPercent"))
    if used is None:
        return None
    remaining_pct = round(max(0.0, min(100.0, 100.0 - used)), 1)
    mins = window.get("windowDurationMins")
    label = _window_label_from_minutes(mins if isinstance(mins, int) else None, fallback_label)
    resets_at = window.get("resetsAt")
    reset_str = ""
    if isinstance(resets_at, (int, float)) and not isinstance(resets_at, bool) and resets_at > 0:
        try:
            reset_str = dt.datetime.fromtimestamp(resets_at, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OSError, OverflowError, ValueError):
            reset_str = ""
    return {
        "label": label,
        "group": group,
        "family": family,
        "remaining_pct": remaining_pct,
        "remaining": None,
        "limit": None,
        "unit": "%",
        "reset_time": reset_str,
    }


def parse_codex_rate_limits(payload: Any) -> dict[str, Any] | None:
    """Parse Codex app-server ``account/rateLimits/read`` or ``updated`` payload."""
    if not isinstance(payload, dict):
        return None
    root = payload.get("rateLimits") if isinstance(payload.get("rateLimits"), dict) else payload
    if not isinstance(root, dict):
        return None

    plan = _safe_text(root.get("planType"), 40) or None
    buckets: list[dict[str, Any]] = []
    primary = _codex_window_bucket(root.get("primary"), fallback_label="5h", group="ChatGPT", family="primary")
    secondary = _codex_window_bucket(root.get("secondary"), fallback_label="7d", group="ChatGPT", family="primary")
    if primary:
        buckets.append(primary)
    if secondary:
        buckets.append(secondary)

    by_id = payload.get("rateLimitsByLimitId")
    if isinstance(by_id, dict):
        for limit_id, entry in by_id.items():
            if not isinstance(entry, dict):
                continue
            group = _safe_text(entry.get("limitName") or entry.get("normalModelSlug") or str(limit_id), 48)
            fam = _safe_text(entry.get("normalModelSlug") or str(limit_id), 48).lower()
            p = _codex_window_bucket(entry.get("primary"), fallback_label="5h", group=group, family=fam)
            s = _codex_window_bucket(entry.get("secondary"), fallback_label="7d", group=group, family=fam)
            for item in (p, s):
                if item and not any(
                    b["group"] == item["group"] and b["label"] == item["label"] for b in buckets
                ):
                    buckets.append(item)

    credits_info = None
    raw_credits = root.get("credits")
    if isinstance(raw_credits, dict):
        unlimited = bool(raw_credits.get("unlimited"))
        has_credits = bool(raw_credits.get("hasCredits"))
        bal_str = _safe_text(raw_credits.get("balance"), 32)
        bal_num = _safe_float(bal_str.lstrip("$")) if bal_str else None
        if unlimited:
            credits_info = {"label": "Unlimited", "remaining": None, "limit": None, "used": None, "unlimited": True}
        elif has_credits and bal_num is not None:
            credits_info = {"label": f"${bal_num:,.2f}", "remaining": bal_num, "limit": None, "used": None, "unlimited": False}
        elif has_credits and bal_str:
            credits_info = {"label": bal_str, "remaining": None, "limit": None, "used": None, "unlimited": False}

    if not buckets and credits_info is None and plan is None:
        return None
    return {
        "provider": "chatgpt",
        "source": "ChatGPT Codex OAuth",
        "plan": plan,
        "updated_at": _utc_now_iso(),
        "model": None,
        "buckets": buckets,
        "credits": credits_info,
    }


def record_codex_rate_limits(payload: Any) -> dict[str, Any] | None:
    parsed = parse_codex_rate_limits(payload)
    if parsed is None:
        return None
    # Sparse rolling updates may omit plan or credits; preserve previously known fields.
    existing = get_provider_quota("chatgpt")
    if existing:
        if parsed["plan"] is None and existing.get("plan"):
            parsed["plan"] = existing["plan"]
        if parsed["credits"] is None and existing.get("credits"):
            parsed["credits"] = existing["credits"]
        if not parsed["buckets"] and existing.get("buckets"):
            parsed["buckets"] = existing["buckets"]
    return _save_snapshot("chatgpt", parsed)


# ── API-key HTTP rate-limit & quota headers ─────────────────────────────

_HEADER_BUCKETS: tuple[tuple[str, str, str, str, str], ...] = (
    # (label, remaining_hdr, limit_hdr, reset_hdr, unit)
    ("Req/min", "x-ratelimit-remaining-requests-minute", "x-ratelimit-limit-requests-minute", "x-ratelimit-reset-requests-minute", "req"),
    ("Tok/min", "x-ratelimit-remaining-tokens-minute", "x-ratelimit-limit-tokens-minute", "x-ratelimit-reset-tokens-minute", "tok"),
    ("Req/day", "x-ratelimit-remaining-requests-day", "x-ratelimit-limit-requests-day", "x-ratelimit-reset-requests-day", "req"),
    ("Tok/day", "x-ratelimit-remaining-tokens-day", "x-ratelimit-limit-tokens-day", "x-ratelimit-reset-tokens-day", "tok"),
    ("Requests", "x-ratelimit-remaining-requests", "x-ratelimit-limit-requests", "x-ratelimit-reset-requests", "req"),
    ("Tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-limit-tokens", "x-ratelimit-reset-tokens", "tok"),
    ("Requests", "anthropic-ratelimit-requests-remaining", "anthropic-ratelimit-requests-limit", "anthropic-ratelimit-requests-reset", "req"),
    ("Tokens", "anthropic-ratelimit-tokens-remaining", "anthropic-ratelimit-tokens-limit", "anthropic-ratelimit-tokens-reset", "tok"),
    ("In tok", "anthropic-ratelimit-input-tokens-remaining", "anthropic-ratelimit-input-tokens-limit", "anthropic-ratelimit-input-tokens-reset", "tok"),
    ("Out tok", "anthropic-ratelimit-output-tokens-remaining", "anthropic-ratelimit-output-tokens-limit", "anthropic-ratelimit-output-tokens-reset", "tok"),
    ("Quota", "x-quota-remaining", "x-quota-limit", "x-quota-reset", "req"),
    ("Requests", "x-ratelimit-remaining", "x-ratelimit-limit", "x-ratelimit-reset", "req"),
    ("Requests", "ratelimit-remaining", "ratelimit-limit", "ratelimit-reset", "req"),
)


def parse_http_rate_limit_headers(
    headers: Mapping[str, Any] | None,
    *,
    provider: str = "",
    model: str = "",
) -> dict[str, Any] | None:
    """Extract sanitized rate-limit / quota metrics from HTTP response headers."""
    if not headers:
        return None
    low: dict[str, str] = {}
    for k, v in headers.items():
        if isinstance(k, str) and v is not None:
            low[k.strip().casefold()] = str(v).strip()

    buckets: list[dict[str, Any]] = []
    seen_labels: set[str] = set()

    # Unified 5h/7d utilization headers (Anthropic unified headers when present).
    for win_label, util_key, reset_key in (
        ("5h", "anthropic-ratelimit-unified-5h-utilization", "anthropic-ratelimit-unified-5h-reset"),
        ("7d", "anthropic-ratelimit-unified-7d-utilization", "anthropic-ratelimit-unified-7d-reset"),
    ):
        util = _safe_float(low.get(util_key))
        if util is not None:
            pct = round(max(0.0, min(100.0, (1.0 - util) * 100.0 if util <= 1.0 else 100.0 - util)), 1)
            buckets.append({
                "label": win_label,
                "group": "Account",
                "family": "",
                "remaining_pct": pct,
                "remaining": None,
                "limit": None,
                "unit": "%",
                "reset_time": _safe_text(low.get(reset_key, ""), 40),
            })
            seen_labels.add(win_label)

    for label, rem_key, lim_key, rst_key, unit in _HEADER_BUCKETS:
        if label in seen_labels:
            continue
        rem = _safe_float(low.get(rem_key))
        lim = _safe_float(low.get(lim_key))
        if rem is None and lim is None:
            continue
        pct = None
        if rem is not None and lim is not None and lim > 0:
            pct = round(max(0.0, min(100.0, (rem / lim) * 100.0)), 1)
        buckets.append({
            "label": label,
            "group": "Rate limit",
            "family": "",
            "remaining_pct": pct,
            "remaining": rem,
            "limit": lim,
            "unit": unit,
            "reset_time": _safe_text(low.get(rst_key, ""), 40),
        })
        seen_labels.add(label)

    credits_info = None
    rem_cred = _safe_float(
        low.get("x-ratelimit-remaining-credits")
        or low.get("x-credits-remaining")
        or low.get("x-credit-balance")
    )
    lim_cred = _safe_float(low.get("x-ratelimit-limit-credits"))
    if rem_cred is not None or lim_cred is not None:
        if rem_cred is not None and lim_cred is not None and lim_cred > 0:
            credits_info = {
                "label": f"${rem_cred:,.2f} / ${lim_cred:,.2f}",
                "remaining": rem_cred,
                "limit": lim_cred,
                "used": max(0.0, lim_cred - rem_cred),
                "unlimited": False,
            }
        elif rem_cred is not None:
            credits_info = {
                "label": f"${rem_cred:,.2f}",
                "remaining": rem_cred,
                "limit": None,
                "used": None,
                "unlimited": False,
            }

    if not buckets and credits_info is None:
        return None
    return {
        "provider": (provider or "").strip().lower(),
        "source": "HTTP rate-limit headers",
        "plan": None,
        "updated_at": _utc_now_iso(),
        "model": _safe_text(model, 120) or None,
        "buckets": buckets,
        "credits": credits_info,
    }


def record_http_rate_limits(
    provider: str,
    headers: Mapping[str, Any] | None,
    *,
    model: str = "",
) -> dict[str, Any] | None:
    if not provider:
        return None
    parsed = parse_http_rate_limit_headers(headers, provider=provider, model=model)
    if parsed is None:
        return None
    # Do not overwrite rich OAuth or dedicated account credit snapshots if headers only carry partial info;
    # instead merge credits when preserved.
    existing = get_provider_quota(provider)
    if existing and existing.get("source") in {"OpenRouter API key", "DeepSeek API key"}:
        if parsed["credits"] is None and existing.get("credits"):
            parsed["credits"] = existing["credits"]
    return _save_snapshot(provider, parsed)


# ── Dedicated API-key account quota endpoints (OpenRouter / DeepSeek) ───

def parse_openrouter_key_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    limit = _safe_float(data.get("limit"))
    remaining = _safe_float(data.get("limit_remaining"))
    usage = _safe_float(data.get("usage"))
    usage_daily = _safe_float(data.get("usage_daily"))
    usage_weekly = _safe_float(data.get("usage_weekly"))
    is_free = data.get("is_free_tier")

    buckets: list[dict[str, Any]] = []
    credits_info = None
    if limit is not None and limit > 0:
        rem = remaining if remaining is not None else (max(0.0, limit - usage) if usage is not None else None)
        pct = round(max(0.0, min(100.0, (rem / limit) * 100.0)), 1) if rem is not None else None
        buckets.append({
            "label": "Credits",
            "group": "Account",
            "family": "",
            "remaining_pct": pct,
            "remaining": rem,
            "limit": limit,
            "unit": "usd",
            "reset_time": "",
        })
        credits_info = {
            "label": f"${rem:,.2f} / ${limit:,.2f}" if rem is not None else f"${limit:,.2f} limit",
            "remaining": rem,
            "limit": limit,
            "used": usage,
            "unlimited": False,
        }
    elif usage is not None:
        credits_info = {
            "label": f"${usage:,.2f} used",
            "remaining": None,
            "limit": None,
            "used": usage,
            "unlimited": False,
        }
    if usage_daily is not None:
        buckets.append({
            "label": "Today",
            "group": "Usage",
            "family": "",
            "remaining_pct": None,
            "remaining": usage_daily,
            "limit": None,
            "unit": "usd",
            "reset_time": "",
        })
    if usage_weekly is not None:
        buckets.append({
            "label": "7d used",
            "group": "Usage",
            "family": "",
            "remaining_pct": None,
            "remaining": usage_weekly,
            "limit": None,
            "unit": "usd",
            "reset_time": "",
        })

    if not buckets and credits_info is None:
        return None
    return {
        "provider": "openrouter",
        "source": "OpenRouter API key",
        "plan": "free" if is_free is True else ("paid" if is_free is False else None),
        "updated_at": _utc_now_iso(),
        "model": None,
        "buckets": buckets,
        "credits": credits_info,
    }


def fetch_openrouter_quota(api_key: str, base_url: str = "https://openrouter.ai/api/v1", *, timeout_s: float = 10.0) -> dict[str, Any] | None:
    """Query OpenRouter's read-only ``GET /api/v1/key`` endpoint through reviewed egress."""
    if not api_key:
        return None
    from isycode.egress import EgressDenied, open_reviewed, review_destination
    from isycode.providers import _RejectRedirectHandler

    url = base_url.rstrip("/") + "/key"
    try:
        reviewed = review_destination(url)
    except EgressDenied:
        return None
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        opener = open_reviewed(reviewed, _RejectRedirectHandler())
        with opener.open(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read(262_144))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    parsed = parse_openrouter_key_payload(payload)
    return _save_snapshot("openrouter", parsed) if parsed else None


def parse_deepseek_balance_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    infos = payload.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        return None
    buckets: list[dict[str, Any]] = []
    credits_info = None
    for info in infos[:3]:
        if not isinstance(info, dict):
            continue
        currency = _safe_text(str(info.get("currency") or "USD"), 8).upper()
        total = _safe_float(info.get("total_balance"))
        if total is None:
            continue
        sym = "$" if currency == "USD" else (f"{currency} ")
        label_val = f"{sym}{total:,.2f}"
        if credits_info is None:
            credits_info = {
                "label": label_val,
                "remaining": total,
                "limit": None,
                "used": None,
                "unlimited": False,
            }
        buckets.append({
            "label": f"Balance ({currency})",
            "group": "Account",
            "family": "",
            "remaining_pct": None,
            "remaining": total,
            "limit": None,
            "unit": "usd" if currency == "USD" else currency.lower(),
            "reset_time": "",
        })
    if not buckets:
        return None
    return {
        "provider": "deepseek",
        "source": "DeepSeek API key",
        "plan": "available" if payload.get("is_available") else "exhausted",
        "updated_at": _utc_now_iso(),
        "model": None,
        "buckets": buckets,
        "credits": credits_info,
    }


def fetch_deepseek_quota(api_key: str, base_url: str = "https://api.deepseek.com/v1", *, timeout_s: float = 10.0) -> dict[str, Any] | None:
    """Query DeepSeek's read-only ``GET /user/balance`` endpoint through reviewed egress."""
    if not api_key:
        return None
    from isycode.egress import EgressDenied, open_reviewed, review_destination
    from isycode.providers import _RejectRedirectHandler

    parsed_url = urllib.parse.urlsplit(base_url)
    origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
    url = origin + "/user/balance"
    try:
        reviewed = review_destination(url)
    except EgressDenied:
        return None
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        opener = open_reviewed(reviewed, _RejectRedirectHandler())
        with opener.open(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read(262_144))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    parsed = parse_deepseek_balance_payload(payload)
    return _save_snapshot("deepseek", parsed) if parsed else None


# ── Formatting for ModelsScreen detail card ─────────────────────────────

def format_quota_bar(pct: float | None, width: int = 10) -> str:
    if pct is None or not math.isfinite(pct):
        return ""
    clamped = max(0.0, min(100.0, float(pct)))
    filled = int(round((clamped / 100.0) * width))
    return "█" * filled + "░" * (width - filled)


def _tone_for_pct(pct: float | None) -> str:
    if pct is None:
        return "value"
    if pct < 20.0:
        return "low"
    if pct < 50.0:
        return "warn"
    return "ok"


def _format_bucket_row(bucket: dict[str, Any], *, now: dt.datetime | None = None) -> tuple[str, str]:
    label = str(bucket.get("label") or "Quota")
    pct = _safe_float(bucket.get("remaining_pct"))
    rem = _safe_float(bucket.get("remaining"))
    lim = _safe_float(bucket.get("limit"))
    unit = str(bucket.get("unit") or "")
    reset = _format_reset_value(str(bucket.get("reset_time") or ""), now=now)

    pieces = [f"  {label:<7}"]
    if pct is not None:
        pieces.append(f"{format_quota_bar(pct, 10)} {round(pct):>3d}%")
        if rem is not None and lim is not None:
            pieces.append(f"({_format_count(rem, unit)}/{_format_count(lim, unit)})")
    elif rem is not None and lim is not None:
        pieces.append(f"{_format_count(rem, unit)} / {_format_count(lim, unit)}")
    elif rem is not None:
        pieces.append(_format_count(rem, unit))
    if reset:
        pieces.append(f"· {reset}")
    return " ".join(pieces), _tone_for_pct(pct)


def quota_panel_lines(
    provider: str,
    model: str = "",
    *,
    antigravity_quota: dict[str, Any] | None = None,
    loading: bool = False,
    now: dt.datetime | None = None,
) -> list[tuple[str, str]]:
    """Build compact lines ``(text, tone)`` for the model selector detail panel.

    Tones: ``"rule"``, ``"header"``, ``"section"``, ``"ok"``, ``"warn"``,
    ``"low"``, ``"value"``, ``"muted"``.
    """
    key = (provider or "").strip().lower()
    snapshot = get_provider_quota(key)
    if key == "antigravity" and isinstance(antigravity_quota, dict) and antigravity_quota.get("ok"):
        if snapshot is None or snapshot.get("raw_antigravity") != antigravity_quota:
            snapshot = record_antigravity_quota(antigravity_quota) or snapshot

    lines: list[tuple[str, str]] = [
        ("─" * 34, "rule"),
        (tr("Quota"), "header"),
    ]

    if snapshot is None:
        if loading:
            lines.append(("  " + tr("Checking quota…"), "muted"))
        else:
            lines.append(("  " + tr("Not reported yet"), "muted"))
            lines.append(("  " + tr("Shown when this provider exposes quota or rate-limit headers."), "muted"))
        return lines

    plan = snapshot.get("plan")
    if plan:
        lines.append((f"  {tr('Plan')}: {plan}", "value"))

    # Special rich rendering for Google Antigravity: highlighted model family + full account overview.
    raw_ag = snapshot.get("raw_antigravity") if key == "antigravity" else None
    if isinstance(raw_ag, dict) and raw_ag.get("ok"):
        fam = model_to_quota_family(model)
        fam_label = {"gemini": "Gemini", "argon": "Argon", "claude_gpt": "Claude / GPT"}.get(fam, fam)
        five_h, weekly = family_quota_pair(raw_ag, model)
        if five_h or weekly:
            lines.append((f"  {tr('This model')} ({fam_label})", "section"))
            for win_label, bucket in (("5h", five_h), ("7d", weekly)):
                if isinstance(bucket, dict) and _safe_float(bucket.get("pct")) is not None:
                    lines.append(_format_bucket_row({
                        "label": win_label,
                        "remaining_pct": bucket["pct"],
                        "reset_time": bucket.get("reset_time", ""),
                    }, now=now))
        # Account-wide breakdown by group
        grouped: dict[str, list[str]] = {}
        for b in raw_ag.get("buckets") or ():
            if not isinstance(b, dict):
                continue
            gname = str(b.get("group") or b.get("family") or "Models")
            win = "5h" if b.get("window") == "5h" else ("7d" if b.get("window") == "weekly" else str(b.get("window") or ""))
            pct = _safe_float(b.get("pct"))
            if pct is None:
                continue
            cd = _format_reset_value(str(b.get("reset_time") or ""), now=now)
            item = f"{win} {round(pct)}% ({cd})" if cd else f"{win} {round(pct)}%"
            grouped.setdefault(gname, []).append(item)
        if grouped:
            lines.append(("  " + tr("Account"), "section"))
            for gname, pieces in grouped.items():
                lines.append((f"  {gname}: {' · '.join(pieces)}", "muted"))
    else:
        # Generic normalized rendering (ChatGPT Codex OAuth, OpenRouter, DeepSeek, HTTP rate-limit headers)
        credits_info = snapshot.get("credits")
        if isinstance(credits_info, dict) and credits_info.get("label"):
            lines.append((f"  {tr('Credits')}: {credits_info['label']}", "value"))

        buckets = list(snapshot.get("buckets") or ())
        # If Codex reported model-specific rateLimitsByLimitId, surface matching ones first.
        model_low = (model or "").casefold()
        primary_buckets: list[dict[str, Any]] = []
        extra_buckets: list[dict[str, Any]] = []
        for b in buckets:
            if not isinstance(b, dict):
                continue
            fam = str(b.get("family") or "").casefold()
            if key == "chatgpt" and fam and fam != "primary":
                if model_low and (fam in model_low or model_low in fam):
                    primary_buckets.append(b)
                else:
                    extra_buckets.append(b)
            else:
                primary_buckets.append(b)

        for b in primary_buckets[:6]:
            lines.append(_format_bucket_row(b, now=now))

        if extra_buckets:
            lines.append(("  " + tr("Account"), "section"))
            for b in extra_buckets[:4]:
                row_text, _ = _format_bucket_row(b, now=now)
                lines.append((f"  {b.get('group', '')} {row_text.strip()}", "muted"))

    source = _safe_text(str(snapshot.get("source") or ""), 48)
    if source:
        lines.append((f"  {source}", "muted"))
    return lines


__all__ = [
    "LIVE_QUOTA_PROVIDERS",
    "clear_provider_quota",
    "fetch_deepseek_quota",
    "fetch_openrouter_quota",
    "format_quota_bar",
    "get_provider_quota",
    "parse_codex_rate_limits",
    "parse_deepseek_balance_payload",
    "parse_http_rate_limit_headers",
    "parse_openrouter_key_payload",
    "quota_panel_lines",
    "record_antigravity_quota",
    "record_codex_rate_limits",
    "record_http_rate_limits",
]
