"""Non-interactive mode: ``isycode -p "prompt"`` answers once and exits.

It uses the same owners as the TUI: every model call goes through
ProviderNetworkOwner, every tool through its execution owner, and all of them
are decided by Workspace Authority and IsySentinel and journaled. With no
person present nothing can be approved, so only tools that never need an
approval are offered: workspace list/read/search/grep and git status/diff.
Edits, commands, commits and anything else stay unavailable.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, TextIO

from isycode.action_runtime import (
    CHAT_WORKSPACE_TOOLS, TOOL_ACTIONS, LocalWorkspaceReadOwner, ProviderNetworkOwner,
)
from isycode.agent_loop import AgentLimits, compact_turn
from isycode.authority_view import displayed_on
from isycode.config import discover_workspace_identity, provider_default_model
from isycode.git_owner import GIT_TOOLS, GitOwner, git_executable
from isycode.providers import Provider, ProviderError, load_provider_key, selected_provider_name
from isycode.streaming import StreamError, async_stream_complete
from isycode.workspace_authority import WorkspaceAuthority, WorkspaceAuthorityError

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_DENIED = 3

Transport = Callable[[list[dict], list[dict] | None, Callable[[str, str], None]], Awaitable[dict]]


def _grants(authority: WorkspaceAuthority) -> dict[str, Any]:
    try:
        return authority.effective_policy().get("grants", {})
    except (WorkspaceAuthorityError, OSError, ValueError):
        return {}


def available_tools(root: Path, authority: WorkspaceAuthority) -> list[dict]:
    """Approval-free tools whose grants are effective for this workspace."""
    grants = _grants(authority)
    reads = all(displayed_on(action, grants.get(action, {}),
                             str(root) in grants.get(action, {}).get("path_prefixes", []))
                for action in ("workspace.files.list", "workspace.files.read",
                               "workspace.files.search"))
    if not reads:
        return []
    tools = list(CHAT_WORKSPACE_TOOLS)
    if (git_executable() and (root / ".git").is_dir()
            and all(displayed_on(action, grants.get(action, {}))
                    for action in ("git.status", "git.diff"))):
        tools += GIT_TOOLS
    return tools


def _register_saved_key_reader(root: Path) -> None:
    from isycode.credential_owner import CredentialUseOwner
    from isycode.credentials import set_saved_secret_reader

    try:
        owner = CredentialUseOwner(root, WorkspaceAuthority(root))
    except Exception:  # noqa: BLE001 - any failure means no saved keys are read
        set_saved_secret_reader(None)
        return
    set_saved_secret_reader(lambda service, consumer: owner.secret_for(service, consumer)[1])


def _dispatch(root: Path, authority: WorkspaceAuthority, call: dict, log: TextIO) -> tuple[str, str]:
    function = call.get("function") if isinstance(call, dict) else None
    name = function.get("name") if isinstance(function, dict) else None
    call_id = call.get("id") or "call_headless"
    try:
        arguments = json.loads(function.get("arguments") or "{}") if isinstance(function, dict) else None
    except (json.JSONDecodeError, TypeError):
        arguments = None
    if not isinstance(arguments, dict):
        return call_id, json.dumps({"error": "tool arguments must be a JSON object"})
    if name in TOOL_ACTIONS:
        outcome = LocalWorkspaceReadOwner(root, authority).execute(TOOL_ACTIONS[name], arguments)
    elif name == "git_status":
        outcome = GitOwner(root, authority).status()
    elif name == "git_diff":
        path, staged = arguments.get("path", "."), arguments.get("staged", False)
        if not isinstance(path, str) or not isinstance(staged, bool):
            return call_id, json.dumps({"error": "path must be a string and staged a boolean"})
        outcome = GitOwner(root, authority).diff(path, staged)
    else:
        print(f"isycode: tool {name!r} is not available without a person to approve it",
              file=log)
        return call_id, json.dumps({"error": "this tool is not available in non-interactive mode"})
    if outcome.decision != "ALLOW" or outcome.receipt is None:
        print(f"isycode: {name} {outcome.decision} · {outcome.reason[:200]}", file=log)
        return call_id, json.dumps({"error": "ISyCode denied the action", "reason": outcome.reason[:300]})
    print(f"isycode: {name} ALLOW · receipt {outcome.receipt.receipt_id}", file=log)
    return call_id, outcome.text


async def run_headless(prompt: str, *, root: Path | None = None, out: TextIO = sys.stdout,
                       log: TextIO = sys.stderr, json_output: bool = False,
                       transport: Transport | None = None) -> int:
    """Answer one prompt. Returns a process exit code."""
    root = (root or discover_workspace_identity(Path.cwd()).workspace_root).resolve()
    authority = WorkspaceAuthority(root)
    _register_saved_key_reader(root)
    try:
        from isycode.user_defaults import UserDefaultsStore
        limits = AgentLimits.from_defaults(UserDefaultsStore().load())
    except (OSError, ValueError):
        limits = AgentLimits()
    try:
        name = selected_provider_name()
        provider = Provider(name=name, model=provider_default_model(name),
                            api_key=load_provider_key(name) or None)
    except ProviderError as exc:
        print(f"isycode: provider unavailable · {exc}", file=log)
        return EXIT_FAILED
    tools = available_tools(root, authority) if provider.supports_tools else []
    messages: list[dict] = [
        {"role": "system", "content": (
            f"You are ISyCode running non-interactively in the workspace {root}. Nobody can "
            "approve actions in this mode: you cannot edit files, run commands or commit. "
            + ("Read-only workspace tools are available; use them to inspect the repository. "
               if tools else "No workspace tools are enabled; answer from the prompt alone. ")
            + "Never claim to have inspected or changed anything you did not. Answer concisely.")},
        {"role": "user", "content": prompt},
    ]
    owner = ProviderNetworkOwner(root, authority)
    streamed: list[str] = []

    def on_chunk(kind: str, chunk: str) -> None:
        if kind == "content":
            streamed.append(chunk)
            if not json_output:
                out.write(chunk)
                out.flush()

    async def default_transport(request_messages, request_tools, callback):
        return await async_stream_complete(
            provider.base_url, provider.api_key, provider.model, request_messages,
            max_tokens=limits.answer_tokens, token_limit_field=provider.token_limit_field,
            reasoning_effort=provider.reasoning_effort,
            temperature_supported=provider.temperature_supported,
            on_chunk=callback, tools=request_tools)

    send = transport or default_transport
    receipts: list[str] = []
    tool_calls = 0
    answer = ""
    try:
        for step in range(limits.max_steps):
            messages[:], _ = compact_turn(messages)
            streamed.clear()
            material = {"operation": "chat.completions", "messages": messages,
                        "max_tokens": limits.answer_tokens,
                        "token_limit_field": provider.token_limit_field,
                        "reasoning_effort": provider.reasoning_effort,
                        "temperature_supported": provider.temperature_supported,
                        "tools": tools or None}
            response, outcome = await owner.execute(
                provider, material, lambda: send(messages, tools or None, on_chunk))
            if outcome.decision != "ALLOW" or not isinstance(response, dict):
                print(f"isycode: provider request {outcome.decision} · {outcome.reason[:240]}",
                      file=log)
                return EXIT_DENIED
            receipts.append(outcome.receipt.receipt_id)
            answer = response.get("text") or "".join(streamed)
            calls = response.get("tool_calls") or []
            if not calls:
                break
            messages.append({"role": "assistant", "content": response.get("text") or None,
                             "tool_calls": calls})
            for index, call in enumerate(calls):
                if index >= limits.max_tool_calls:
                    call_id = call.get("id") or "call_headless"
                    result = json.dumps({"error": "per-response tool call limit reached"})
                else:
                    call_id, result = await asyncio.to_thread(_dispatch, root, authority, call, log)
                    tool_calls += 1
                messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
            if not json_output and streamed:
                out.write("\n")
        else:
            print(f"isycode: step limit reached ({limits.max_steps}); the answer may be incomplete",
                  file=log)
    except (ProviderError, StreamError, OSError) as exc:
        print(f"isycode: request failed · {type(exc).__name__}: {str(exc)[:200]}", file=log)
        return EXIT_FAILED
    if json_output:
        out.write(json.dumps({"answer": answer, "workspace": str(root), "tool_calls": tool_calls,
                              "provider_receipts": receipts}, ensure_ascii=False) + "\n")
    elif not answer.endswith("\n"):
        out.write("\n")
    return EXIT_OK


def main(arguments: list[str], stdin: TextIO = sys.stdin) -> int:
    """``isycode -p [PROMPT|-] [--json]``: PROMPT or stdin when omitted or "-"."""
    json_output = "--json" in arguments
    rest = [item for item in arguments if item != "--json"]
    if not rest or rest[0] not in {"-p", "--print"}:
        print("usage: isycode -p [PROMPT|-] [--json]", file=sys.stderr)
        return EXIT_USAGE
    prompt = " ".join(rest[1:]).strip()
    if not prompt or prompt == "-":
        prompt = stdin.read(256 * 1024).strip()
    if not prompt:
        print("isycode: empty prompt", file=sys.stderr)
        return EXIT_USAGE
    return asyncio.run(run_headless(prompt, json_output=json_output))


__all__ = ["EXIT_DENIED", "EXIT_FAILED", "EXIT_OK", "EXIT_USAGE", "available_tools", "main",
           "run_headless"]
