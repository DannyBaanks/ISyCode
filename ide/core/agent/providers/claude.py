"""Claude Code provider - uses the official Claude Code CLI in headless mode.

This wraps `claude -p` (the official Agent SDK CLI) so the ISYCO TUI acts as a
frontend for Claude Code. Claude Code runs its own agent loop, tools, MCP and
hooks. Keys are injected only via environment variables inside the subprocess:

- Direct Anthropic key  -> ANTHROPIC_API_KEY
- Routed (OpenRouter, NVIDIA, claude-code-router) -> ANTHROPIC_BASE_URL +
  ANTHROPIC_AUTH_TOKEN  (the officially documented way to use Claude Code
  with other providers)
"""

from __future__ import annotations
import asyncio
import json
import os
import shutil
import subprocess
from typing import AsyncIterator, Optional

from .base import BaseProvider, ProviderConfig, CompletionResponse, ToolCall


DEFAULT_ANTHROPIC_ENDPOINT = "https://api.anthropic.com"


class ClaudeCodeProvider(BaseProvider):
    """Runs `claude -p` in headless mode with stream-json output."""

    def __init__(self, config: ProviderConfig, secret_broker):
        super().__init__(config, secret_broker)
        self._claude_bin: Optional[str] = None

    @property
    def claude_bin(self) -> str:
        if self._claude_bin is None:
            self._claude_bin = shutil.which("claude")
            if not self._claude_bin:
                raise RuntimeError(
                    "Claude Code CLI not found. Install it with: "
                    "npm install -g @anthropic-ai/claude-code"
                )
        return self._claude_bin

    # ------------------------------------------------------------------
    # Environment / key handling (never printed, only in subprocess env)
    # ------------------------------------------------------------------
    def _env_has_key(self) -> bool:
        """True if we're injecting a key via env (requires --bare)."""
        return bool(self._resolve_key())

    def _resolve_key(self) -> Optional[str]:
        """Look up the API key: own slot, then the generic 'anthropic' slot."""
        key = self.secret_broker.get(self.config.name)
        if not key and self.config.name != "anthropic":
            key = self.secret_broker.get("anthropic")
        return key

    def _build_env(self) -> dict:
        env = dict(os.environ)
        env.setdefault("NO_COLOR", "1")
        key = self._resolve_key()

        endpoint = (self.config.endpoint or "").rstrip("/")
        is_direct = (
            not endpoint
            or endpoint.rstrip("/v1") == DEFAULT_ANTHROPIC_ENDPOINT
        )

        if key:
            if is_direct:
                env["ANTHROPIC_API_KEY"] = key
                env.pop("ANTHROPIC_AUTH_TOKEN", None)
            else:
                env["ANTHROPIC_AUTH_TOKEN"] = key
                env["ANTHROPIC_BASE_URL"] = endpoint
                env.pop("ANTHROPIC_API_KEY", None)
        elif not is_direct:
            # Routed endpoint with key provided another way (ccr, etc.)
            env["ANTHROPIC_BASE_URL"] = endpoint

        if self.config.model:
            env["ANTHROPIC_MODEL"] = self.config.model
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = self.config.model
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = self.config.model
            env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = self.config.model
        return env

    def _build_command(self, prompt: str, streaming: bool) -> list[str]:
        env_key = self._env_has_key()
        cmd = [self.claude_bin]
        if env_key:
            # --bare skips OAuth login and uses ANTHROPIC_API_KEY/AUTH_TOKEN
            cmd.append("--bare")
        # Prompt is piped via stdin (robust with multiline: no shell quoting
        # issues through .cmd shims on Windows).
        cmd += ["-p", "--output-format",
                "stream-json" if streaming else "json"]
        if streaming:
            cmd.append("--verbose")
        if self.config.model:
            cmd += ["--model", self.config.model]
        # Headless means no human to approve: fail closed.
        cmd += [
            "--permission-mode", "default",
            "--allowedTools", "Read,Grep,Glob,List,WebFetch",
        ]
        return cmd

    @staticmethod
    def _messages_to_prompt(messages: list[dict]) -> str:
        parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content") or ""
            if role == "system":
                continue  # handled via --append-system-prompt
            if role == "tool":
                parts.append(f"[TOOL RESULT]\n{content}")
            else:
                parts.append(f"[{role.upper()}]\n{content}")
        return "\n\n".join(parts)

    @staticmethod
    def _extract_system_prompt(messages: list[dict]) -> str:
        return "\n\n".join(
            m.get("content", "") for m in messages if m.get("role") == "system"
        )

    # ------------------------------------------------------------------
    # API (used by the ISYCO agent loop)
    # ------------------------------------------------------------------
    async def complete(self, messages: list[dict],
                       tools: list = None) -> CompletionResponse:
        prompt = self._messages_to_prompt(messages)
        system_prompt = self._extract_system_prompt(messages)
        cmd = self._build_command(prompt, streaming=False)
        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]

        env = self._build_env()
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=prompt.encode("utf-8"))
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            return CompletionResponse(
                content="",
                finish_reason="error",
                usage={"error": err or f"claude exited {proc.returncode}"},
            )
        try:
            data = json.loads(stdout.decode(errors="replace"))
        except json.JSONDecodeError:
            return CompletionResponse(
                content=stdout.decode(errors="replace").strip(),
                finish_reason="stop",
            )
        result = data.get("result") or ""
        is_error = data.get("is_error", False)
        return CompletionResponse(
            content=result,
            finish_reason="error" if is_error else "stop",
            usage={"is_error": is_error},
        )

    async def stream(self, messages: list[dict],
                     tools: list = None) -> AsyncIterator[str]:
        """Yield text deltas from stream-json (also marks tool usage)."""
        prompt = self._messages_to_prompt(messages)
        system_prompt = self._extract_system_prompt(messages)
        cmd = self._build_command(prompt, streaming=True)
        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]
        env = self._build_env()

        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdout is not None
        assert proc.stdin is not None
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                line = line.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                if etype == "stream_event":
                    ev = event.get("event", {})
                    if ev.get("type") == "content_block_delta":
                        delta = ev.get("delta", {})
                        text = delta.get("text")
                        if text:
                            yield text
                        if delta.get("type") == "input_json_delta":
                            pass
                    elif ev.get("type") == "content_block_start":
                        cb = ev.get("content_block", {})
                        if cb.get("type") == "tool_use":
                            yield f"\n[TOOL] {cb.get('name', 'tool')}\n"
                elif etype == "assistant":
                    msg = event.get("message", {})
                    for cb in msg.get("content", []):
                        if cb.get("type") == "text" and cb.get("text"):
                            yield cb["text"]
                        if cb.get("type") == "tool_use":
                            yield f"\n[TOOL] {cb.get('name', 'tool')}\n"
                elif etype == "result":
                    yield "\n" + (event.get("result") or "")
                    break
        finally:
            if proc.returncode is None:
                proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass

    async def close(self):
        pass