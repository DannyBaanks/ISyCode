#!/usr/bin/env python3
"""ISyCode streaming — SSE client for OpenAI-compatible chat completions.

Shows tokens as they arrive so a 10-20s Nemotron round-trip feels alive
instead of frozen. Does NOT modify IsyMotron's Provider; reuses its
config (base_url, api_key, model) for the SSE request.
"""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from typing import Iterator, Callable


class StreamError(Exception):
    pass


def stream_complete(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int = 2000,
    temperature: float = 0.2,
    timeout_s: float = 120.0,
    on_chunk: Callable[[str, str], None] | None = None,
) -> dict:
    """Stream a chat completion. Returns collected result.

    on_chunk(kind, text) is called per delta, kind is 'content' or
    'reasoning'. Returns dict with full text, reasoning, token counts,
    finish_reason, latency.
    """
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json",
                 "Accept": "text/event-stream"},
    )
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason: str | None = None
    usage: dict = {}
    t0 = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout_s)
    except urllib.error.HTTPError as e:
        raise StreamError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
    except (urllib.error.URLError, OSError) as e:
        raise StreamError(f"stream unreachable: {e}")
    try:
        for raw_line in resp:
            line = raw_line.decode(errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                evt = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = evt.get("choices") or []
            if not choices:
                if "usage" in evt:
                    usage = evt["usage"]
                continue
            delta = choices[0].get("delta") or {}
            if choices[0].get("finish_reason"):
                finish_reason = choices[0]["finish_reason"]
            c = delta.get("content")
            if c:
                content_parts.append(c)
                if on_chunk:
                    on_chunk("content", c)
            r = delta.get("reasoning_content")
            if r:
                reasoning_parts.append(r)
                if on_chunk:
                    on_chunk("reasoning", r)
    finally:
        resp.close()
    return {
        "text": "".join(content_parts),
        "reasoning": "".join(reasoning_parts),
        "finish_reason": finish_reason,
        "usage": usage,
        "latency_s": time.time() - t0,
    }
