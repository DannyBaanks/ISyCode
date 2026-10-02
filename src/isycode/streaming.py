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

DEFAULT_STREAM_TIMEOUT_S = None


class StreamError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status
        self.transport = status is None



async def _upgrade_client_tls(writer: asyncio.StreamWriter, context: ssl.SSLContext,
                              host: str) -> None:
    """Upgrade a CONNECT stream on supported Python 3.10+ runtimes."""
    if callable(getattr(writer, "start_tls", None)):
        await writer.start_tls(context, server_hostname=host)
        return
    # Python 3.10 exposes loop.start_tls but has no StreamWriter upgrade API.
    # Keep this compatibility bridge here; never replace certificate validation.
    await writer.drain()
    protocol = writer._protocol
    transport = await asyncio.get_running_loop().start_tls(
        writer.transport, protocol, context, server_side=False, server_hostname=host)
    if transport is None:
        raise StreamError("provider TLS upgrade failed")
    writer._transport = transport
    protocol._stream_writer = writer
    protocol._transport = transport
    protocol._over_ssl = True

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
    max_tokens: int | None = None,
    temperature: float = 0.2,
    token_limit_field: str = "max_tokens",
    reasoning_effort: str | None = None,
    temperature_supported: bool = True,
    timeout_s: float | None = DEFAULT_STREAM_TIMEOUT_S,
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
    if max_tokens is not None:
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
    max_tokens: int | None = None,
    token_limit_field: str = "max_tokens",
    reasoning_effort: str | None = None,
    temperature_supported: bool = True,
    timeout_s: float | None = DEFAULT_STREAM_TIMEOUT_S,
    on_chunk: Callable[[str, str], None] | None = None,
    tools: list[dict] | None = None,
    include_usage: bool = False,
) -> dict:
    """Stream a completion over an asyncio-owned socket that its task can cancel."""
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise StreamError("provider URL must be an HTTP(S) URL with a host")
    if parsed.username or parsed.password:
        raise StreamError("provider URL must not contain embedded credentials")
    if any(char in api_key for char in "\r\n"):
        raise StreamError("provider credential contains invalid HTTP header characters")
    proxy_url = urllib.request.getproxies().get(parsed.scheme)
    if proxy_url and urllib.request.proxy_bypass(parsed.netloc):
        proxy_url = None

    body = {"model": model, "messages": messages, "stream": True}
    if include_usage:
        body["stream_options"] = {"include_usage": True}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if max_tokens is not None:
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
    async def bounded(awaitable):
        if timeout_s is None:
            return await awaitable
        return await asyncio.wait_for(awaitable, timeout=timeout_s)

    tls = ssl.create_default_context() if parsed.scheme == "https" else None
    if proxy_url:
        proxy = urlparse(proxy_url)
        if proxy.scheme != "http" or not proxy.hostname or proxy.username or proxy.password:
            raise StreamError("streaming requires an HTTP proxy without embedded credentials")
        reader, writer = await bounded(asyncio.open_connection(proxy.hostname, proxy.port or 80))
        if tls:
            # CONNECT carries no provider credential; TLS verification remains enabled.
            tunnel_target = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
            try:
                writer.write((f"CONNECT {tunnel_target} HTTP/1.1\r\n"
                              f"Host: {tunnel_target}\r\n\r\n").encode("ascii"))
                await bounded(writer.drain())
                status_line = await bounded(reader.readline())
                parts = status_line.decode("latin-1").split()
                if len(parts) < 2 or not parts[0].startswith("HTTP/") or not parts[1].isdigit():
                    raise StreamError("proxy returned an invalid HTTP status")
                status = int(parts[1])
                if status != 200:
                    raise StreamError(f"proxy refused provider tunnel (HTTP {status}); no provider request was sent")
                header_bytes = 0
                while True:
                    line = await bounded(reader.readline())
                    header_bytes += len(line)
                    if not line or header_bytes > 64 * 1024:
                        raise StreamError("proxy returned incomplete or oversized headers")
                    if line == b"\r\n":
                        break
                # Stop plaintext reads before TLS takes over. A CONNECT peer may
                # have appended unauthenticated bytes to its headers; those must
                # never enter the authenticated SSE parser after the upgrade.
                writer.transport.pause_reading()
                if reader._buffer:
                    raise StreamError("proxy sent unexpected plaintext after CONNECT headers")
                await bounded(_upgrade_client_tls(writer, tls, host))
            except BaseException:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
                except (asyncio.TimeoutError, OSError):
                    pass
                raise
        else:
            request_path = f"http://{host_header}{request_path}"
    else:
        reader, writer = await bounded(asyncio.open_connection(
            host, port, ssl=tls, server_hostname=host if tls else None))
    content: list[str] = []
    reasoning: list[str] = []
    usage: dict = {}
    tool_calls: dict[int, dict] = {}
    finish_reason = None
    line_buffer = bytearray()
    stream_done = False
    started = time.monotonic()

    def consume_sse_line(raw_line: bytes) -> bool:
        nonlocal finish_reason, usage, stream_done
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            return False
        data = line[5:].strip()
        if data == "[DONE]":
            stream_done = True
            return True
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            return False
        if not isinstance(event, dict):
            return False
        if "error" in event:
            # Providers may fail after sending HTTP 200. Never echo their body:
            # it can contain credentials or private request/transcript data.
            raise StreamError("provider reported a streaming API error")
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
            if (newline < 0 and len(line_buffer) > 1024 * 1024) or newline > 1024 * 1024:
                raise StreamError("provider SSE frame exceeds 1 MiB")
            if newline < 0:
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
            raise StreamError(f"provider returned HTTP {status}", status=status)

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
        if not stream_done and not finish_reason:
            raise StreamError("provider closed an incomplete completion stream")
        return {
            "text": "".join(content), "reasoning": "".join(reasoning),
            "finish_reason": finish_reason, "usage": usage,
            # A syntactically valid prefix is still not a completed tool request.
            "tool_calls": ([] if finish_reason in {"length", "content_filter"} else
                           [tool_calls[index] for index in sorted(tool_calls)]),
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
