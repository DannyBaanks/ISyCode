#!/usr/bin/env python3
"""ISyCode streaming — SSE client for OpenAI-compatible chat completions.

Shows tokens as they arrive so a 10-20s Nemotron round-trip feels alive
instead of frozen. Does NOT modify IsyMotron's Provider; reuses its
config (base_url, api_key, model) for the SSE request.
"""
from __future__ import annotations

import asyncio
import json
import re
import ssl
import time
from urllib.parse import urlparse
import urllib.request
import urllib.error
from typing import Iterator, Callable


class StreamError(Exception):
    pass


def detect_unexecuted_tool_request(text: str) -> str | None:
    """Recognize a provider's plain-text imitation of a shell tool call.

    The chat transport currently sends no tool schemas and has no execution
    dispatcher. A model can still print the JSON shape it has seen elsewhere;
    callers use this detector to avoid presenting or persisting that as an
    executed action.
    """
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", candidate,
                          flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        payload = json.loads(candidate)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    tool = payload.get("tool")
    args = payload.get("args")
    if (isinstance(tool, str) and tool.casefold() in {"bash", "shell", "terminal", "exec"}
            and isinstance(args, list) and len(args) <= 256
            and all(isinstance(arg, str) for arg in args)):
        return tool.casefold()
    return None


def stream_complete(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int = 2000,
    temperature: float = 0.2,
    token_limit_field: str = "max_tokens",
    reasoning_effort: str | None = None,
    temperature_supported: bool = True,
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
        "stream": True,
    }
    body[token_limit_field] = max_tokens
    if temperature_supported:
        body["temperature"] = temperature
    if reasoning_effort is not None:
        body["reasoning_effort"] = reasoning_effort
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


async def async_stream_complete(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    max_tokens: int = 1200,
    token_limit_field: str = "max_tokens",
    reasoning_effort: str | None = None,
    temperature_supported: bool = True,
    timeout_s: float = 120.0,
    on_chunk: Callable[[str, str], None] | None = None,
    tools: list[dict] | None = None,
) -> dict:
    """Stream a completion over an asyncio-owned socket that its task can cancel."""
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise StreamError("provider URL must be an HTTP(S) URL with a host")
    if parsed.username or parsed.password:
        raise StreamError("provider URL must not contain embedded credentials")
    if any(char in api_key for char in "\r\n"):
        raise StreamError("provider credential contains invalid HTTP header characters")
    if urllib.request.getproxies().get(parsed.scheme):
        raise StreamError(
            "Cancellable async transport does not support the configured proxy; no request was sent")

    body = {"model": model, "messages": messages, "stream": True}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    body[token_limit_field] = max_tokens
    if temperature_supported:
        body["temperature"] = 0.2
    if reasoning_effort is not None:
        body["reasoning_effort"] = reasoning_effort
    payload = json.dumps(body).encode("utf-8")
    host = parsed.hostname.encode("idna").decode("ascii")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    host_header = f"[{host}]" if ":" in host else host
    if parsed.port:
        host_header = f"{host_header}:{port}"
    request_path = parsed.path.rstrip("/") + "/chat/completions"
    if parsed.query:
        request_path += "?" + parsed.query
    if any(char in request_path for char in "\r\n "):
        raise StreamError("provider URL contains invalid request-target characters")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    async def bounded(awaitable):
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        return await asyncio.wait_for(awaitable, timeout=remaining)

    tls = ssl.create_default_context() if parsed.scheme == "https" else None
    reader, writer = await bounded(asyncio.open_connection(
        host, port, ssl=tls, server_hostname=host if tls else None))
    content: list[str] = []
    reasoning: list[str] = []
    usage: dict = {}
    tool_calls: dict[int, dict] = {}
    finish_reason = None
    line_buffer = bytearray()
    started = time.monotonic()

    def consume_sse_line(raw_line: bytes) -> bool:
        nonlocal finish_reason, usage
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            return False
        data = line[5:].strip()
        if data == "[DONE]":
            return True
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            return False
        if not isinstance(event, dict):
            return False
        choices = event.get("choices") or []
        if not choices:
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            return False
        choice = choices[0]
        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]
        delta = choice.get("delta") or {}
        if isinstance(delta.get("content"), str):
            content.append(delta["content"])
            if on_chunk:
                on_chunk("content", delta["content"])
        if isinstance(delta.get("reasoning_content"), str):
            reasoning.append(delta["reasoning_content"])
            if on_chunk:
                on_chunk("reasoning", delta["reasoning_content"])
        for item in delta.get("tool_calls", []) or []:
            if not isinstance(item, dict) or not isinstance(item.get("index"), int):
                continue
            index = item["index"]
            call = tool_calls.setdefault(index, {
                "id": "", "type": "function", "function": {"name": "", "arguments": ""},
            })
            if isinstance(item.get("id"), str):
                call["id"] = item["id"][:160]
            function = item.get("function") or {}
            if not isinstance(function, dict):
                continue
            if isinstance(function.get("name"), str):
                call["function"]["name"] += function["name"]
            if isinstance(function.get("arguments"), str):
                call["function"]["arguments"] += function["arguments"]
                if len(call["function"]["arguments"]) > 64 * 1024:
                    raise StreamError("provider tool arguments exceed 64 KiB")
        return False

    async def consume_bytes(data: bytes) -> bool:
        line_buffer.extend(data)
        while True:
            newline = line_buffer.find(b"\n")
            if newline < 0:
                if len(line_buffer) > 1_000_000:
                    raise StreamError("provider sent an oversized streaming event")
                return False
            raw_line = bytes(line_buffer[:newline])
            del line_buffer[:newline + 1]
            if consume_sse_line(raw_line):
                return True

    try:
        writer.write(
            f"POST {request_path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            f"Authorization: Bearer {api_key}\r\n"
            "Content-Type: application/json\r\n"
            "Accept: text/event-stream\r\n"
            "Accept-Encoding: identity\r\n"
            "Connection: close\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
        await bounded(writer.drain())
        status_line = await bounded(reader.readline())
        try:
            status_parts = status_line.decode("latin-1").strip().split(" ", 2)
            version, status_text = status_parts[:2]
            status = int(status_text)
        except (ValueError, TypeError):
            raise StreamError("provider returned an invalid HTTP status line")
        if not version.startswith("HTTP/"):
            raise StreamError("provider returned an invalid HTTP status line")
        headers: dict[str, str] = {}
        header_bytes = 0
        while True:
            header_line = await bounded(reader.readline())
            header_bytes += len(header_line)
            if header_bytes > 65536:
                raise StreamError("provider response headers are too large")
            if header_line in {b"\r\n", b"\n", b""}:
                break
            if b":" in header_line:
                key, value = header_line.decode("latin-1").split(":", 1)
                headers[key.strip().casefold()] = value.strip()
        if status != 200:
            raise StreamError(f"provider returned HTTP {status}")

        async def read_chunked() -> None:
            while True:
                size_line = await bounded(reader.readline())
                try:
                    size = int(size_line.split(b";", 1)[0].strip(), 16)
                except ValueError as error:
                    raise StreamError("provider returned an invalid chunked stream") from error
                if size == 0:
                    while await bounded(reader.readline()) not in {b"\r\n", b"\n", b""}:
                        pass
                    return
                remaining = size
                while remaining:
                    data = await bounded(reader.read(min(65536, remaining)))
                    if not data:
                        raise StreamError("provider closed a truncated chunked stream")
                    remaining -= len(data)
                    if await consume_bytes(data):
                        return
                await bounded(reader.readexactly(2))

        transfer_encoding = headers.get("transfer-encoding", "").casefold()
        if "chunked" in transfer_encoding:
            await read_chunked()
        elif "content-length" in headers:
            try:
                remaining = int(headers["content-length"])
            except ValueError as error:
                raise StreamError("provider returned an invalid content length") from error
            while remaining:
                data = await bounded(reader.read(min(65536, remaining)))
                if not data:
                    raise StreamError("provider closed a truncated response")
                remaining -= len(data)
                if await consume_bytes(data):
                    break
        else:
            while True:
                data = await bounded(reader.read(65536))
                if not data or await consume_bytes(data):
                    break
        return {
            "text": "".join(content), "reasoning": "".join(reasoning),
            "finish_reason": finish_reason, "usage": usage,
            "tool_calls": [tool_calls[index] for index in sorted(tool_calls)],
            "latency_s": time.monotonic() - started,
        }
    except asyncio.TimeoutError as error:
        raise StreamError("provider request timed out") from error
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
        except (asyncio.TimeoutError, OSError):
            pass
