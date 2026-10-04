"""Authority menu and workspace grant methods for the ISyCode TUI.

Moved verbatim from tui.py. TUIApp inherits AuthorityMixin.
"""
from __future__ import annotations

import json
import os
import time as _time
from typing import Any
from urllib.parse import urlparse

from isycode.action_audit import ActionAuditJournal
from isycode.action_runtime import GatewayMCPInvocationOwner
from isycode.actions import ACTION_BY_ID
from isycode.authority_view import (
    MOBILE_HOST_ADDRESS,
    MOBILE_PAIR_ACTIONS,
    displayed_on,
    mobile_host_enabled,
    mobile_host_saved,
    other_saved_grants,
)
from isycode.clipboard_owner import CLIPBOARD_TARGET
from isycode.command_runner import sandbox_executable
from isycode.gateway_client import GatewayClient
from isycode.git_owner import git_executable, git_repository_available
from isycode.providers import PRESETS, selected_provider_name
from isycode.tui_screens_approval import TailscaleConfirmScreen
from isycode.tui_screens_grants import (
    GrantLSPProcessScreen,
    GrantMCPInvocationScreen,
    GrantProviderNetworkScreen,
    GrantWorkspaceReadScreen,
)
from isycode.tui_theme import GREEN, MUTED, RED, YELLOW
from isycode.workspace_authority import WorkspaceAuthority, WorkspaceAuthorityError


FILE_CHANGE_GRANTS = ("workspace.files.write", "workspace.files.restore",
                      "workspace.files.delete", "workspace.files.move")


class AuthorityMixin:
    """Authority menu, quiet Classic trust, and saved grants."""

    def _workspace_mode(self) -> str:
        try:
            return WorkspaceAuthority(self._workspace_root).mode() or "security"
        except (WorkspaceAuthorityError, OSError, ValueError):
            return "security"

    def _request_is_quiet(self, request) -> bool:
        """Trusted Classic covers this request, so the per-action modal stays closed."""
        try:
            from isycode.workspace_trust import quiet_classic
            return bool(quiet_classic(WorkspaceAuthority(request.workspace_root), request))
        except Exception:
            return False

    async def _offer_quiet_trust(self, authority, *, again: bool = False) -> None:
        """Human confirmation only. A decline is remembered; Security never reaches here."""
        from isycode.workspace_setup import broad_workspace_reason
        from isycode.workspace_trust import (
            ACCEPT_PHRASE, WorkspaceTrust, onboarding_brief,
        )

        try:
            trust = WorkspaceTrust()
            if authority.mode() != "classic":
                return
            if broad_workspace_reason(authority.root):
                self._append("  This folder is too broad for the quiet Classic profile. "
                             "Each edit and command still asks.", YELLOW)
                return
            if trust.trusted(authority):
                return
            if not again and not trust.needs_onboarding(authority):
                return
            brief = onboarding_brief(
                root=authority.root, mode="Classic", provider=selected_provider_name(),
                sends_workspace_context=True)
            confirmed = await self._await_screen(TailscaleConfirmScreen(
                "Trust this folder?", brief, "Trust this folder"))
            if confirmed:
                trust.accept(authority, ACCEPT_PHRASE)
                self._append("  Quiet Classic is on for ordinary edits and sandboxed tests. "
                             "Commits, secrets and authority changes still ask.", GREEN)
            else:
                trust.decline(authority)
                self._append("  Quiet Classic stays off. Each edit and command still asks.", MUTED)
        except (OSError, ValueError, WorkspaceAuthorityError):
            self._append("  Trust was not saved. Each edit and command still asks.", YELLOW)

    async def _change_workspace_mode(self, mode: str) -> None:
        classic = mode == "classic"
        if not await self._await_screen(TailscaleConfirmScreen(
                "Switch this workspace to Classic?" if classic else "Switch this workspace to Security?",
                ("Reading/searching, edit proposals, chat, sessions and Git review work without "
                 "granting each capability. Sandbox commands are ready when supported. "
                 "The next screen can trust this folder for ordinary edits and isolated tests. "
                 "Until then, edits, delete/move, commands and commits still ask. "
                 "Commits, secrets and authority changes keep asking. "
                 "Integrations still need explicit permission; free shell and sensitive files "
                 "stay unavailable." if classic else
                 "Everything starts off; you allow each capability in Settings → Authority. "
                 "Permissions you granted explicitly stay as they are."),
                "Use Classic" if classic else "Use Security")):
            self._open_authority_menu()
            return
        try:
            authority = WorkspaceAuthority(self._workspace_root)
            authority.set_mode(mode)
            self._append(f"  This workspace now uses {'Classic' if classic else 'Security'} mode.", GREEN)
            if classic:
                await self._offer_quiet_trust(authority, again=True)
        except (WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append(f"  Mode could not be changed ({type(exc).__name__}).", RED)
        self._update_workspace_identity_ui()
        self._open_authority_menu()

    def _open_authority_menu(self) -> None:
        entries: list[dict] = [self._entry(
            "Choose what ISyCode can do in this workspace. Everything else stays off.", "info"),
            self._entry(
                "Some actions ask again before they run, even when turned on. "
                "Press ? on any option to see what it does.", "info")]
        try:
            authority = WorkspaceAuthority(self._workspace_root)
            policy = authority.effective_policy()
            grants = policy.get("grants", {})
            classic = authority.mode() == "classic"
            entries.append(self._entry(
                ("Mode · Classic · ready to use; switch to Security…" if classic
                 else "Mode · Security · nothing runs until you allow it; switch to Classic…"),
                "workspace_mode", "security" if classic else "classic",
                "Classic is ready for the local coding loop: read/edit, chat, sessions, Git review, "
                "and sandboxed commands where supported. Each edit, delete/move, command and commit "
                "still asks first. Security starts with grants off; use individual grants or the reviewed coding-tool bundle. Both keep Sentinel and the journal."))
            entries.append(self._entry(
                "Turn on all coding tools…", "coding_toolkit", "",
                "One step for read, search, edit, move, delete, undo, sandboxed commands, git and "
                "Python checks (whatever this computer supports). Each change, command and commit "
                "still asks you first, and IsySentinel still checks every action."))
            readonly_ids = {"workspace.files.list", "workspace.files.read", "workspace.files.search",
                            "workspace.context.inject"}
            read_enabled = all(displayed_on(
                action, grants.get(action, {}),
                str(self._workspace_root) in grants.get(action, {}).get("path_prefixes", []))
                for action in readonly_ids)
            entries.append(self._capability_entry(
                "Read and search workspace files", "workspace_read", read_enabled,
                "Lets ISyCode list, read, and find files here. It cannot change or delete them."))
            if self._chat_session_owner is not None:
                entries.append(self._capability_entry(
                    "Save conversations in this workspace", "sessions",
                    all(displayed_on(action, grants.get(action, {}))
                        for action in ("session.create", "session.resume")),
                    "Keeps this workspace's chats in your private ISyCode state folder, outside the "
                    "project, so you can resume them. Common secrets are redacted before saving."))
                if self._active_chat_session_id:
                    entries.append(self._capability_entry(
                        "Delete current conversation · asks every time", "session_delete",
                        displayed_on("session.delete", grants.get("session.delete", {}),
                                     self._active_chat_session_id in grants.get("session.delete", {}).get("targets", [])),
                        "Lets you delete the saved conversation that is open right now. The "
                        "permission covers only that conversation, and each deletion still asks you."))
                else:
                    entries.append(self._entry(
                        "Delete a conversation · open a saved one first", "info", "",
                        "Deleting works one conversation at a time. Open a saved conversation from "
                        "Sessions, then come back here to allow deleting that one."))
            else:
                entries.append(self._entry(
                    "Save conversations · recurring workspaces only", "info", "",
                    "Temporary runs never keep chat history."))
            write_grant = grants.get("workspace.files.write", {})
            entries.append(self._capability_entry(
                "Edit workspace files · folder approval settings apply", "workspace_write",
                displayed_on("workspace.files.write", write_grant,
                             str(self._workspace_root) in write_grant.get("path_prefixes", [])),
                "The assistant can propose creating, changing, moving and deleting files here. You see "
                "the diff unless this folder is trusted for quiet Classic, or automatic edits are on. "
                "A trusted folder still stays inside the effect budget. /undo reverts the last change. Sensitive "
                "files stay off-limits."))
            if git_executable() and git_repository_available(self._workspace_root):
                entries.append(self._capability_entry(
                    "See git status and diffs", "git_read",
                    all(displayed_on(action, grants.get(action, {}))
                        for action in ("git.status", "git.diff")),
                    "Lets the assistant see the branch, changed files and diffs. Sensitive files "
                    "stay hidden, and repositories that configure their own programs are refused."))
                entries.append(self._capability_entry(
                    "Create git commits · asks before every commit", "git_commit",
                    displayed_on("git.commit", grants.get("git.commit", {})),
                    "The assistant can propose a commit. You review the exact files, message and "
                    "diff. Hooks never run and nothing is pushed."))
            clipboard_grant = grants.get("clipboard.copy", {})
            entries.append(self._capability_entry(
                "Copy selected text to the clipboard", "clipboard",
                displayed_on("clipboard.copy", clipboard_grant,
                             CLIPBOARD_TARGET in clipboard_grant.get("targets", [])),
                "Selecting text with the mouse (or Ctrl+C on a selection, or Copy path) copies "
                "it. Only your own gesture copies; the assistant cannot. The journal records the "
                "size, never the text. API keys are never copied."))
            command_sandbox = sandbox_executable()
            if command_sandbox:
                command_grant = grants.get("workspace.command.run", {})
                entries.append(self._capability_entry(
                    "Run commands in a sandbox", "workspace_command",
                    displayed_on("workspace.command.run", command_grant,
                                 command_sandbox in command_grant.get("executables", [])),
                    "The assistant can propose programs like tests or a build. Each exact command "
                    "asks unless this folder is trusted for quiet Classic. It runs without network, "
                    "with sensitive files hidden, and can only change files inside this workspace. "
                    "There is no unsandboxed fallback."))
            else:
                entries.append(self._entry(
                    "Run commands · sandbox not available on this computer", "info", "",
                    "Needs bubblewrap, libseccomp and python3 on Linux. Commands stay off. "
                    "There is no unsandboxed fallback."))
            selected_name = selected_provider_name()
            selected_preset = PRESETS.get(selected_name, {})
            selected_url_text = (os.environ.get("ISYCODE_BASE_URL")
                                 or os.environ.get("ISYMOTRON_BASE_URL")
                                 or selected_preset.get("base_url", ""))
            selected_url = urlparse(selected_url_text)
            provider_host = (selected_url.hostname or "").casefold().rstrip(".")
            try:
                if selected_url.port:
                    provider_host += f":{selected_url.port}"
            except ValueError:
                provider_host = "invalid endpoint"
            network_grant = grants.get("provider.request", {})
            provider_network_enabled = displayed_on(
                "provider.request", network_grant,
                provider_host in network_grant.get("network_hosts", []))
            if provider_host and provider_host != "invalid endpoint":
                entries.append(self._capability_entry(
                    "Connect to the selected AI model", "provider", provider_network_enabled,
                    "Sends your messages to the model you chose. A saved API key is kept separately."))
            else:
                entries.append(self._entry("Model connection · not ready yet", "info", "",
                                           "Choose a model provider in Settings first."))
            gateway_url = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8787")
            self._append_network_grant_entry(
                entries, grants, "gateway.files.read", "Check ISyCo Gateway", gateway_url,
                "Checks whether your local ISyCo Gateway is available." )
            self._append_network_grant_entry(
                entries, grants, "mcp.discover", "Find Gateway tools", gateway_url,
                "Shows which extra tools the Gateway offers. Finding a tool does not run it.")
            self._append_network_grant_entry(
                entries, grants, "gateway.semantic.read", "Search and understand code with Gateway",
                gateway_url,
                "Sends a search you review first. Each search asks for approval before it runs.")
            try:
                invoke_target = GatewayMCPInvocationOwner.target_for(gateway_url)
                mcp_grant = grants.get("mcp.invoke", {})
                invoke_enabled = displayed_on("mcp.invoke", mcp_grant,
                                              invoke_target in mcp_grant.get("targets", []))
                entries.append(self._capability_entry(
                    "Run a Gateway tool", "gateway_invoke", invoke_enabled,
                    "You will review the tool and its details, then approve each run separately."))
            except ValueError:
                entries.append(self._entry("Gateway tools · not ready yet", "info", "",
                                           "Finish setting up the local Gateway connection first."))
            lsp_server = next((item for item in self._lsp_inventory
                               if item.get("id") == "pyright"), None)
            if lsp_server and lsp_server.get("state") == "sandbox_ready":
                lsp_grant = grants.get("lsp.start", {})
                lsp_sandbox = lsp_server["sandbox_executable"]
                lsp_enabled = displayed_on("lsp.start", lsp_grant,
                                           lsp_sandbox in lsp_grant.get("executables", []))
                entries.append(self._capability_entry(
                    "Local code help", "lsp", lsp_enabled,
                    "Uses the protected language helper to find code symbols on this computer."))
                diagnostics_grant = grants.get("lsp.diagnostics", {})
                entries.append(self._capability_entry(
                    "Check Python files after edits", "lsp_diagnostics",
                    displayed_on("lsp.diagnostics", diagnostics_grant,
                                 lsp_sandbox in diagnostics_grant.get("executables", [])),
                    "After you apply a change to a .py file, the protected Pyright helper reports "
                    "errors and warnings to you and to the assistant. It cannot change files."))
            elif lsp_server:
                entries.append(self._entry(
                    "Local code help · not ready yet", "info", "",
                    "ISyCode will show this as an option when its protected helper is ready."))
            if not (lsp_server and lsp_server.get("state") == "sandbox_ready"):
                other_lsp = next((item for item in self._lsp_inventory if item.get("state") == "sandbox_ready"), None)
                if other_lsp:
                    sandbox = other_lsp["sandbox_executable"]
                    grant = grants.get("lsp.start", {})
                    entries.append(self._capability_entry("Local code help", "lsp",
                        displayed_on("lsp.start", grant, sandbox in grant.get("executables", [])),
                        "Read-only local symbols; each request is reviewed before its protected process starts."))
            web_hosts = grants.get("web.fetch", {}).get("network_hosts", [])
            for host in web_hosts:
                self._append_network_grant_entry(entries, grants, "web.fetch", "Read public web pages", "https://" + host, "Read-only HTTPS; no credentials, private hosts or redirects. Each new host asks first.")
            if not web_hosts:
                entries.append(self._entry("Web pages · asks for each new host", "info", "", "The webfetch tool requests a separate bounded host grant before reading a public HTTPS page."))
            external_catalog_url = os.environ.get("OPENISY_API_URL", "").strip()
            if external_catalog_url:
                self._append_network_grant_entry(
                    entries, grants, "catalog.external.read", "Browse optional integrations",
                    external_catalog_url,
                    "Reads the optional integrations list. It does not enable their tools.")
            else:
                entries.append(self._entry(
                    "Optional integrations · not set up", "info", "",
                    "You can connect these later from Settings."))
            mobile_on = mobile_host_enabled(grants)
            partial = not mobile_on and mobile_host_saved(grants)
            entries.append(self._capability_entry(
                "Mobile Host on this computer" + (" · partial saved grant" if partial else ""),
                "mobile_host", mobile_on,
                f"Lets ISyCode start the loopback Mobile Host at {MOBILE_HOST_ADDRESS} and accept "
                "one-use PIN pairing. Paired devices can read the runtime list and send heartbeats; "
                "they cannot read files, run tools, or open sessions. Starting still asks first."))
            saved = other_saved_grants(grants)
            if saved:
                entries.append(self._entry("— Other saved permissions —", "info", "",
                                           "Every other permission saved for this workspace."))
            for row in saved:
                if row.state == "on":
                    state = "ON · asks before each use" if row.approval_required else "ON"
                else:
                    state = "blocked · no Secure owner · saved grant ignored"
                entries.append(self._entry(
                    f"{row.label} · {state}", "authority_saved_grant", row.action_id,
                    f"Scope: {row.scope}. Select to remove this saved permission."))
        except (WorkspaceAuthorityError, OSError, ValueError):
            entries.append(self._entry(
                "Protection settings are unavailable · everything stays off", "info"))
        entries.append(self._entry(
            "Protection is always on", "info", "",
            "ISyCode checks every action before it runs. Turning an option on never gives access beyond this workspace, "
            "and sensitive actions still ask you first."))
        entries.append(self._entry(
            "File edits follow folder approval settings; other changes always ask.",
            "info", "", "Turning a permission on lets the assistant propose that kind of action. "
            "Files → Folders controls automatic file edits. Commands, moves, deletes and commits still require approval."))
        entries.append(self._entry("Back to Settings", "settings_back", ""))
        if self._menu_mode != "authority_settings":
            self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("authority_settings", "Settings · Authority & Security", entries)

    def _append_network_grant_entry(self, entries: list[dict], grants: dict,
                                    action_id: str, label: str, url: str,
                                    detail: str = "") -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        try:
            if parsed.port:
                host += f":{parsed.port}"
        except ValueError:
            host = "invalid endpoint"
        if not host or host == "invalid endpoint":
            entries.append(self._entry(f"{label} · not ready yet", "info"))
            return
        grant = grants.get(action_id, {})
        enabled = displayed_on(action_id, grant, host in grant.get("network_hosts", []))
        payload = json.dumps({"action_id": action_id, "label": label, "url": url})
        entries.append(self._capability_entry(label, f"network:{payload}", enabled, detail))

    async def _grant_workspace_read(self) -> None:
        await self._change_workspace_read_grant(True)

    async def _revoke_workspace_read(self) -> None:
        await self._change_workspace_read_grant(False)

    async def _change_provider_network_grant(self, enabled: bool) -> None:
        selected_name = selected_provider_name()
        preset = PRESETS.get(selected_name)
        if preset is None:
            self._append("  Selected provider is unknown; no network grant was changed.", RED)
            self._open_authority_menu()
            return
        from isycode.grok_session import session_transport
        base_url = (os.environ.get("ISYCODE_BASE_URL")
                    or os.environ.get("ISYMOTRON_BASE_URL")
                    or (session_transport() if selected_name == "xai" else None)
                    or preset["base_url"])
        parsed = urlparse(base_url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        try:
            if parsed.port:
                host += f":{parsed.port}"
        except ValueError:
            self._append("  Provider endpoint is invalid; no network grant was changed.", RED)
            self._open_authority_menu()
            return
        accepted = await self._await_screen(GrantProviderNetworkScreen(
            preset["label"], host, revoke=not enabled))
        if accepted:
            try:
                authority = WorkspaceAuthority(self._workspace_root)
                grant = authority.policy().get("grants", {}).get("provider.request", {})
                hosts = set(grant.get("network_hosts", []))
                if enabled:
                    hosts.add(host)
                else:
                    hosts.discard(host)
                authority.set_grant(
                    "provider.request", enabled=bool(hosts), network_hosts=sorted(hosts))
                self._append(
                    f"  Provider network {'granted' if enabled else 'revoked'} for {host}. "
                    "Credential and tool permissions remain separate.", GREEN)
            except (WorkspaceAuthorityError, OSError, ValueError):
                self._append("  Provider network policy could not be saved; requests remain denied.", RED)
        self._open_authority_menu()

    async def _change_network_action_grant(self, payload: str, enabled: bool) -> None:
        try:
            value = json.loads(payload)
            action_id, label, url = value["action_id"], value["label"], value["url"]
            if action_id not in {"gateway.files.read", "gateway.semantic.read",
                                 "mcp.discover", "catalog.external.read", "web.fetch"}:
                raise ValueError("unsupported network action")
            parsed = urlparse(url)
            host = (parsed.hostname or "").casefold().rstrip(".")
            if parsed.port:
                host += f":{parsed.port}"
            if not host:
                raise ValueError("endpoint host is missing")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._append("  Invalid network grant request; no permission changed.", RED)
            self._open_authority_menu()
            return
        accepted = await self._await_screen(GrantProviderNetworkScreen(
            label, host, revoke=not enabled))
        if accepted:
            try:
                authority = WorkspaceAuthority(self._workspace_root)
                grant = authority.policy().get("grants", {}).get(action_id, {})
                hosts = set(grant.get("network_hosts", []))
                if enabled:
                    hosts.add(host)
                else:
                    hosts.discard(host)
                authority.set_grant(action_id, enabled=bool(hosts), network_hosts=sorted(hosts))
                self._append(
                    f"  {'Granted' if enabled else 'Revoked'} {label} access for {host}.", GREEN)
            except (WorkspaceAuthorityError, OSError, ValueError):
                self._append("  Network grant could not be saved; access remains denied.", RED)
        self._open_authority_menu()

    async def _change_session_grant(self, enabled: bool) -> None:
        accepted = await self._await_screen(TailscaleConfirmScreen(
            "Save conversations in this workspace?" if enabled else "Stop saving conversations?",
            ("New messages in this workspace are saved to your private ISyCode state folder, "
             "outside the project, and can be resumed from Sessions. API keys, bearer tokens and "
             "similar secrets are redacted before saving." if enabled else
             "New messages stay in memory only. Conversations already saved are kept; deleting "
             "them is not available yet."),
            "Save conversations" if enabled else "Stop saving"))
        if accepted:
            try:
                authority = WorkspaceAuthority(self._workspace_root)
                for action in ("session.create", "session.resume"):
                    authority.set_grant(action, enabled=enabled)
                self._append("  Conversations will be saved for this workspace." if enabled
                             else "  Conversations are no longer saved for this workspace.", GREEN)
            except (WorkspaceAuthorityError, OSError, ValueError) as exc:
                self._append(f"  Session permission could not be saved ({type(exc).__name__}).", RED)
        self._open_authority_menu()

    async def _change_session_delete_grant(self, enabled: bool) -> None:
        session_id = self._active_chat_session_id
        if enabled and not session_id:
            self._append("  Open a saved conversation before granting its deletion.", YELLOW)
            self._open_authority_menu()
            return
        accepted = await self._await_screen(TailscaleConfirmScreen(
            "Allow conversation deletion?" if enabled else "Disable conversation deletion?",
            f"This permission applies only to conversation {session_id or 'previously selected'} in this workspace. "
            "Every deletion still requires reviewing the exact conversation and confirming it.",
            "Allow deletion" if enabled else "Disable deletion"))
        if accepted:
            authority = WorkspaceAuthority(self._workspace_root)
            targets = authority.policy().get("grants", {}).get("session.delete", {}).get("targets", [])
            authority.set_grant("session.delete", enabled=enabled,
                                targets=sorted(set(targets + ([session_id] if enabled else []))))
        self._open_authority_menu()

    async def _change_workspace_write_grant(self, enabled: bool) -> None:
        if enabled and not self._workspace_chat_tools_enabled():
            self._append("  Turn on reading workspace files first; editing builds on it.", YELLOW)
            self._open_authority_menu()
            return
        accepted = await self._await_screen(TailscaleConfirmScreen(
            "Allow file edits in this workspace?" if enabled else "Turn off file edits?",
            (f"The assistant may propose creating, changing, moving and deleting files inside "
             f"{self._workspace_root}. File edits follow your per-folder approval setting; other changes "
             "ask first. A file that changed after review is never touched, and /undo reverts the "
             "last change. Sensitive files and .isyroot stay off-limits." if enabled else
             "The assistant can no longer propose file changes in this workspace. Files already "
             "changed stay as they are."),
            "Allow edits" if enabled else "Turn off edits"))
        if accepted:
            try:
                authority = WorkspaceAuthority(self._workspace_root)
                for action in FILE_CHANGE_GRANTS:
                    authority.set_grant(action, enabled=enabled,
                                        path_prefixes=[self._workspace_root] if enabled else [])
                self._append("  File edits allowed; folder approval settings still apply." if enabled
                             else "  File edits turned off for this workspace.", GREEN)
            except (WorkspaceAuthorityError, OSError, ValueError) as exc:
                self._append(f"  Edit permission could not be saved ({type(exc).__name__}).", RED)
        self._open_authority_menu()

    async def _change_lsp_diagnostics_grant(self, enabled: bool) -> None:
        server = next((item for item in self._lsp_inventory
                       if item.get("id") == "pyright" and item.get("state") == "sandbox_ready"), None)
        if server is None:
            self._append("  Local code help is not ready yet; nothing changed.", YELLOW)
            self._open_authority_menu()
            return
        if not await self._await_screen(TailscaleConfirmScreen(
                "Check Python files after edits?" if enabled else "Stop checking Python files?",
                ("After each change you apply to a .py file, Pyright runs in its read-only, "
                 "network-blocked sandbox and reports problems. It needs read access to the "
                 "workspace and never changes files." if enabled else
                 "Edits are no longer checked by Pyright in this workspace."),
                "Allow checks" if enabled else "Turn off checks")):
            self._open_authority_menu()
            return
        try:
            WorkspaceAuthority(self._workspace_root).set_grant(
                "lsp.diagnostics", enabled=enabled,
                executables=[server["sandbox_executable"]] if enabled else [])
            self._append("  Python checks after edits "
                         f"{'allowed' if enabled else 'turned off'}.", GREEN)
        except (WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append(f"  Check permission could not be saved ({type(exc).__name__}).", RED)
        self._open_authority_menu()

    async def _change_git_grant(self, commit: bool, enabled: bool) -> None:
        actions = ("git.commit",) if commit else ("git.status", "git.diff")
        if commit:
            title = "Allow git commits in this workspace?" if enabled else "Turn off git commits?"
            body = ("The assistant may propose commits. Each one shows its files, message and diff "
                    "and is created only if you approve it. Hooks never run and nothing is pushed."
                    if enabled else "No commit can be created from ISyCode in this workspace.")
        else:
            title = "Let ISyCode see git status and diffs?" if enabled else "Hide git status and diffs?"
            body = ("The assistant may read the branch, changed files and diffs. Sensitive files "
                    "stay hidden." if enabled else "The assistant can no longer read git state here.")
        if not await self._await_screen(TailscaleConfirmScreen(
                title, body, ("Allow" if enabled else "Turn off"))):
            self._open_authority_menu()
            return
        try:
            authority = WorkspaceAuthority(self._workspace_root)
            for action in actions:
                authority.set_grant(action, enabled=enabled)
            self._append(f"  Git {'commits' if commit else 'status and diffs'} "
                         f"{'allowed' if enabled else 'turned off'} for this workspace.", GREEN)
        except (WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append(f"  Git permission could not be saved ({type(exc).__name__}).", RED)
        self._open_authority_menu()

    async def _change_clipboard_grant(self, enabled: bool) -> None:
        try:
            WorkspaceAuthority(self._workspace_root).set_grant(
                "clipboard.copy", enabled=enabled, targets=[CLIPBOARD_TARGET] if enabled else [])
            self._append("  Copy on select is on; select text with the mouse to copy it."
                         if enabled else "  Copy on select is off for this workspace.", GREEN)
        except (WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append(f"  Clipboard permission could not be saved ({type(exc).__name__}).", RED)
        self._open_authority_menu()

    async def _change_command_grant(self, enabled: bool) -> None:
        sandbox = sandbox_executable()
        if enabled and sandbox is None:
            self._append("  The command sandbox is not available here; commands stay off.", YELLOW)
            self._open_authority_menu()
            return
        accepted = await self._await_screen(TailscaleConfirmScreen(
            "Allow sandboxed commands in this workspace?" if enabled else "Turn off commands?",
            (f"The assistant may propose programs to run inside {self._workspace_root}. Each exact "
             "command is shown and runs only if you approve it, through bubblewrap with the network "
             "blocked, sensitive files hidden and only this workspace writable. Classic includes "
             "this sandbox when available; Security requires an explicit grant." if enabled else
             "No command can run in this workspace. Nothing already changed is undone."),
            "Allow commands" if enabled else "Turn off commands"))
        if accepted:
            try:
                authority = WorkspaceAuthority(self._workspace_root)
                authority.set_grant("workspace.command.run", enabled=enabled,
                                    executables=[sandbox] if enabled else [])
                self._append("  Sandboxed commands allowed; each one still asks first." if enabled
                             else "  Commands turned off for this workspace.", GREEN)
            except (WorkspaceAuthorityError, OSError, ValueError) as exc:
                self._append(f"  Command permission could not be saved ({type(exc).__name__}).", RED)
        self._open_authority_menu()

    async def _change_mobile_host_grant(self, enabled: bool) -> None:
        try:
            authority = WorkspaceAuthority(self._workspace_root)
            if enabled:
                if await self._grant_mobile_host(authority):
                    self._append("  Mobile Host granted for this workspace. Starting it still asks first.", GREEN)
                else:
                    self._append("  Mobile Host grant cancelled; nothing changed.", MUTED)
            elif await self._await_screen(TailscaleConfirmScreen(
                    "Revoke Mobile Host for this workspace",
                    "Remove the saved `mobile.host.start`, `mobile.pair` and `mobile.pair.issue` "
                    "grants. New starts, new PINs and new pairing are denied. A host already "
                    "running keeps serving devices paired earlier until ISyCode exits; their "
                    "tokens still expire within an hour.",
                    "Revoke Mobile Host grants")):
                authority.set_grant("mobile.host.start", enabled=False, network_hosts=[])
                for action in MOBILE_PAIR_ACTIONS:
                    authority.set_grant(action, enabled=False, targets=[])
                self._append("  Mobile Host grants revoked for this workspace.", GREEN)
            else:
                self._append("  Mobile Host grants unchanged.", MUTED)
        except (WorkspaceAuthorityError, OSError, ValueError):
            self._append("  Mobile Host grants could not be changed; starts and pairing stay denied "
                         "unless a valid saved grant remains.", RED)
        self._open_authority_menu()

    async def _remove_saved_grant(self, action_id: str) -> None:
        if action_id not in ACTION_BY_ID:
            self._append("  Unknown permission; nothing changed.", YELLOW)
            return
        action = ACTION_BY_ID[action_id]
        if await self._await_screen(TailscaleConfirmScreen(
                "Remove saved permission",
                f"Remove the saved permission for {action.group} · {action.label} "
                f"(`{action_id}`) in this workspace, including its saved scope?",
                "Remove permission")):
            try:
                WorkspaceAuthority(self._workspace_root).set_grant(
                    action_id, enabled=False, path_prefixes=[], network_hosts=[],
                    executables=[], targets=[])
                self._append(f"  Saved permission removed · {action_id}.", GREEN)
            except (WorkspaceAuthorityError, OSError, ValueError):
                self._append("  Saved permission could not be removed.", RED)
        self._open_authority_menu()

    async def _change_mcp_invocation_grant(self, enabled: bool) -> None:
        endpoint = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8787").rstrip("/")
        try:
            target = GatewayMCPInvocationOwner.target_for(endpoint)
            GatewayClient._validate_base_url(endpoint)
        except ValueError:
            self._append("  Gateway URL is invalid; no MCP grant was changed.", RED)
            self._open_authority_menu()
            return
        accepted = await self._await_screen(GrantMCPInvocationScreen(
            target.split("@", 1)[-1], revoke=not enabled))
        if accepted:
            try:
                authority = WorkspaceAuthority(self._workspace_root)
                grant = authority.policy().get("grants", {}).get("mcp.invoke", {})
                targets = set(grant.get("targets", []))
                if enabled:
                    targets.add(target)
                else:
                    targets.discard(target)
                authority.set_grant("mcp.invoke", enabled=bool(targets), targets=sorted(targets))
                self._append(
                    f"  Gateway MCP invocation {'granted' if enabled else 'revoked'} for this workspace. "
                    "Each tool call still needs an explicit one-use approval.", GREEN)
            except (WorkspaceAuthorityError, OSError, ValueError):
                self._append("  MCP invocation grant could not be saved; calls remain denied.", RED)
        self._open_authority_menu()

    async def _change_lsp_process_grant(self, executable: str, enabled: bool) -> None:
        server = next((item for item in self._lsp_inventory
                       if item.get("sandbox_executable") == executable
                       and item.get("state") == "sandbox_ready"), None)
        if server is None:
            self._append("  LSP sandbox changed or is unavailable; no process grant was changed.", RED)
            self._open_authority_menu()
            return
        accepted = await self._await_screen(GrantLSPProcessScreen(
            self._workspace_root, executable, revoke=not enabled))
        if accepted:
            try:
                authority = WorkspaceAuthority(self._workspace_root)
                grant = authority.policy().get("grants", {}).get("lsp.start", {})
                executables = set(grant.get("executables", []))
                if enabled:
                    executables.add(executable)
                else:
                    executables.discard(executable)
                authority.set_grant(
                    "lsp.start", enabled=bool(executables), executables=sorted(executables))
                self._append(
                    f"  Sandboxed LSP process {'granted' if enabled else 'revoked'} for this workspace.",
                    GREEN)
            except (WorkspaceAuthorityError, OSError, ValueError):
                self._append("  LSP process grant could not be saved; the server remains denied.", RED)
        self._open_authority_menu()

    def _coding_toolkit_grants(self) -> list[tuple[str, dict[str, Any], str]]:
        """(action, grant scope, label) for every coding tool this computer can offer."""
        root = [self._workspace_root]
        grants: list[tuple[str, dict[str, Any], str]] = [
            (action, {"path_prefixes": root}, "read and search files")
            for action in ("workspace.files.list", "workspace.files.read",
                           "workspace.files.search", "workspace.context.inject")]
        grants += [(action, {"path_prefixes": root}, "edit, move, delete and undo files")
                   for action in FILE_CHANGE_GRANTS]
        grants.append(("clipboard.copy", {"targets": [CLIPBOARD_TARGET]},
                       "copy selected text to the clipboard"))
        sandbox = sandbox_executable()
        if sandbox:
            grants.append(("workspace.command.run", {"executables": [sandbox]},
                           "run approved commands in the sandbox"))
        if git_executable() and git_repository_available(self._workspace_root):
            grants += [(action, {}, "git status, diffs and approved commits")
                       for action in ("git.status", "git.diff", "git.commit")]
        pyright = next((item for item in self._lsp_inventory
                        if item.get("id") == "pyright" and item.get("state") == "sandbox_ready"), None)
        if pyright:
            grants.append(("lsp.diagnostics", {"executables": [pyright["sandbox_executable"]]},
                           "check Python files after edits"))
        return grants

    async def _enable_coding_toolkit(self) -> None:
        grants = self._coding_toolkit_grants()
        labels = list(dict.fromkeys(label for _, _, label in grants))
        missing = []
        if not sandbox_executable():
            missing.append("commands (needs bubblewrap on Linux)")
        if not (git_executable() and git_repository_available(self._workspace_root)):
            missing.append("git (no repository here)")
        body = (f"Saves grants in {self._workspace_root} for: " + "; ".join(labels) + ". "
                "File edits follow your folder approval settings; commands, deletes, moves and commits ask "
                "first. IsySentinel checks every action and the journal records it. You can turn "
                "each one off in this menu." + (" Not available here: " + "; ".join(missing) + "."
                                                 if missing else ""))
        if not await self._await_screen(TailscaleConfirmScreen(
                "Turn on all coding tools?", body, "Turn on coding tools")):
            self._open_authority_menu()
            return
        try:
            authority = WorkspaceAuthority(self._workspace_root)
            for action, scope, _ in grants:
                authority.set_grant(action, enabled=True, **scope)
            self._append(f"  Coding tools on · {len(grants)} permissions saved; changes, commands "
                         "and commits follow their approval settings.", GREEN)
        except (WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append(f"  Coding tools could not be saved ({type(exc).__name__}).", RED)
        self._open_authority_menu()

    async def _change_workspace_read_grant(self, enabled: bool) -> None:
        accepted = await self._await_screen(
            GrantWorkspaceReadScreen(self._workspace_root, revoke=not enabled))
        if accepted:
            try:
                authority = WorkspaceAuthority(self._workspace_root)
                for action_id in (
                    "workspace.files.list", "workspace.files.read", "workspace.files.search",
                    "workspace.context.inject",
                ):
                    authority.set_grant(
                        action_id, enabled=enabled,
                        path_prefixes=[self._workspace_root] if enabled else None)
                self._append("  Read-only workspace grant saved. Writes and shell remain denied."
                             if enabled else "  Read-only workspace tools revoked for this workspace.",
                             GREEN)
            except (WorkspaceAuthorityError, OSError, ValueError) as exc:
                self._append(f"  Workspace grant could not be saved ({type(exc).__name__}).", RED)
        self._open_authority_menu()

    def _open_action_journal(self) -> None:
        try:
            report = ActionAuditJournal.for_read_only_inspection(
                self._workspace_root).verify()
        except (OSError, RuntimeError, ValueError):
            report = None
        if report is None:
            entries = [self._entry("JOURNAL_INVALID · verifier unavailable", "info")]
        else:
            entries = [self._entry(
                f"Integrity · {report.status} · {report.records} records · {report.decisions} decisions · {report.receipts} receipts",
                "info", "", report.reason or
                "Read-only verification. No repair is attempted. Request digests cannot be recomputed because request bodies are not stored.")]
            if report.unverifiable:
                entries.append(self._entry(
                    f"NOT_VERIFIABLE · {report.unverifiable} records lack an owner identity", "info"))
            paired_receipts = {item["request_digest"]: item for item in report.recent
                               if item["kind"] == "receipt"}
            for item in reversed(report.recent):
                if item["kind"] != "decision":
                    continue
                digest = item["request_digest"]
                receipt = paired_receipts.get(digest)
                authority = "ALLOW" if item["authority"] else "DENY"
                result_state = ("receipt metadata recorded" if receipt
                                else "execution/result not demonstrated")
                checks = ", ".join(
                    f"{check['name']} {'PASS' if check['passed'] else 'FAIL'}"
                    for check in item.get("checks", [])) or "not recorded"
                entries.append(self._entry(
                    f"{item['sentinel']} · {item['action']} · {item['owner'] or 'owner unknown'} · {result_state}",
                    "info", "", f"Time: {_time.strftime('%Y-%m-%d %H:%M:%S', _time.localtime(item['time']))}\n"
                    f"Request: {digest[:12]}… · Authority: {authority}\n"
                    f"Systembilities: {checks}\n"
                    f"Failed checks: {', '.join(item['failed_checks']) or 'none'}\n"
                    "Receipt binds a request digest and result digest, but the request/result payload is not retained. "
                    "Target and successful Systembility details are not persisted; no secret or prompt is shown."))
            if not report.recent:
                entries.append(self._entry("No durable decisions recorded for this workspace", "info"))
        entries.append(self._entry("Back to Settings", "settings_back", ""))
        self._render_menu("security_journal", "Security · Action journal (read-only)", entries)
