"""Tailscale, Mobile Host, bridge, Gateway, broker, and LSP.

Moved verbatim from tui.py. TUIApp inherits this mixin.
"""
from __future__ import annotations

import sys
import os
import asyncio
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse
from isycode.config import gateway_workspace_id
from isycode.decision_view import verified_receipt_line
from isycode.workspace_authority import WorkspaceAuthority, WorkspaceAuthorityError
from isycode.action_runtime import GatewayMCPInvocationOwner, GatewaySemanticOwner, LPSSymbolOwner
from isycode.authority_view import (
    MOBILE_HOST_ADDRESS,
    MOBILE_PAIR_ACTIONS,
    MOBILE_PAIR_TARGET,
    displayed_on,
    mobile_host_enabled,
)
from isycode.broker import BrokerManagementOwner
from isycode.security import ActionRequest
from textual.widgets import Static
from rich.text import Text
from isycode.gateway_client import GatewayClient
from isycode.gateway_mcp import tool_schema_digest
from isycode.mobile_host import MobileHostOwner
from isycode.tailscale import LINUX_OPERATOR_HINT, TailscaleAdapter, TailscaleSnapshot
from isycode.tailscale_read import TailscaleReadOwner
from isycode.tailscale_login import TailscaleLoginOwner
from isycode.tailscale_install import TailscalePackageInstallOwner
from isycode.tailscale_serve import MOBILE_HOST_ROUTE_ID, TailscaleServeOwner, route_url
from isycode.private_access import PrivateAccessStateStore
from isycode.localization import tr
from isycode.tui_theme import status_chip, TEXT, MUTED, GREEN, YELLOW, RED, CYAN
from isycode.tui_widgets import ChatArea
from isycode.tui_screens_approval import TailscaleConfirmScreen
from isycode.tui_screens_grants import GrantLSPProcessScreen
from isycode.tui_screens_mcp import (
    MCPArgumentsScreen,
    MCPInvocationConfirmScreen,
    GatewaySemanticQueryScreen,
    GatewaySemanticConfirmScreen,
    LSPQueryScreen,
    LSPConfirmScreen,
    BrokerManagementScreen,
    BrokerOperationConfirmScreen,
)


class RemoteMixin:
    async def _start_mobile_host(self) -> None:
        authority = WorkspaceAuthority(self._workspace_root)
        owner = MobileHostOwner(self._workspace_root, authority, self._action_approvals,
                                host=self._mobile_host)
        self._mobile_host_owner = owner
        try:
            grants = authority.policy().get("grants", {})
            if not mobile_host_enabled(grants):
                if not await self._grant_mobile_host(authority):
                    self._append("  " + tr("Mobile Host grant cancelled; no listener started."), MUTED)
                    return
            request = owner.start_request()
            try:
                routed = next((route for route in PrivateAccessStateStore().load().owned_routes
                               if route.route_id == MOBILE_HOST_ROUTE_ID), None)
            except (OSError, ValueError):
                routed = None
            exposure = ("It does not change Tailscale Serve. Your saved private route "
                        f"{route_url(routed)} already points here, so devices in your tailnet can "
                        "reach this host through it while it runs." if routed is not None else
                        "It does not change Tailscale Serve or expose a remote route.")
            if not await self._await_screen(TailscaleConfirmScreen(
                    "Start Mobile Host", tr("Start the ISyCode Mobile Host on loopback only: http://127.0.0.1:8765. This enables the temporary pairing PIN shown in Settings. {exposure}", exposure=exposure), "Start host")):
                self._append("  " + tr("Mobile Host start cancelled; no listener started."), MUTED)
                return
            approval = self._action_approvals.issue(request, ttl_seconds=30)
            allowed, reason = await owner.authorize_and_launch(approval)
            if not allowed:
                self._append("  " + tr("Mobile Host start denied · {value}", value=reason[:180]), YELLOW)
            else:
                code = self._mobile_host.pairing_code_for_local_settings() or "unavailable"
                self._append("  " + tr("Mobile Host started at http://127.0.0.1:8765 · pairing PIN {code} (expires in 5 minutes).", code=code), GREEN)
            self._refresh_mobile_host_status()
            self._render_mobile_host_status()
        except (OSError, RuntimeError, TypeError, ValueError, WorkspaceAuthorityError) as exc:
            self._append("  " + tr("Mobile Host could not start ({name}).", name=type(exc).__name__), RED)

    def _refresh_mobile_host_status(self) -> None:
        status = self._mobile_host.status()
        if not self.is_mounted:
            return
        if status.alive:
            scheme = "https" if status.secure_transport else "http"
            transport = "TLS" if status.secure_transport else "Loopback Only"
            self.query_one("#mobile-host-status", Static).update(Text(
                tr("Alive · {scheme}://{address}:{port} · {transport}", scheme=scheme, address=status.address, port=status.port, transport=transport)))
        elif status.state == "error":
            self.query_one("#mobile-host-status", Static).update(Text(
                tr("Unavailable · {value}", value=status.error or tr("startup failed"))))
        else:
            self.query_one("#mobile-host-status", Static).update(Text(tr("Stopped")))
        clients = status.clients
        if not clients:
            client_text = "No mobile clients connected."
        else:
            lines = [f"{len(clients)} connected mobile client(s):"]
            lines.extend(
                f"• {client['device_name']} · Connected"
                for client in clients[:4]
            )
            if len(clients) > 4:
                lines.append(f"…and {len(clients) - 4} more")
            client_text = "\n".join(lines)
        self.query_one("#mobile-client-status", Static).update(Text(client_text))

    def _open_private_access_menu(self) -> None:
        if self._menu_mode != "private_access":
            self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("private_access", "Settings · Private access", [
            self._entry("Checking local Tailscale status…", "info"),
            self._entry("Permissions and authority…", "tailscale_permissions", ""),
            self._entry("Refresh status", "tailscale_refresh", ""),
            self._entry("Manual setup steps", "tailscale_manual", ""),
            self._entry(tr("Back to Settings"), "settings_back", ""),
        ])
        self.run_worker(self._refresh_private_access(), exclusive=True,
                        group="tailscale-status")

    async def _refresh_private_access(self) -> None:
        owner = TailscaleReadOwner(
            self._workspace_root, WorkspaceAuthority(self._workspace_root),
            self._action_approvals, adapter=self._tailscale_adapter)
        try:
            snapshot, outcome = await asyncio.to_thread(owner.inspect)
        except (OSError, RuntimeError, TypeError, ValueError, WorkspaceAuthorityError):
            snapshot = TailscaleSnapshot("unavailable")
            outcome = None
        self._tailscale_snapshot = snapshot
        status = {"missing_cli": "Missing CLI", "unavailable": "Unavailable", "signed_in": "Signed in",
                  "signed_out": "Signed out", "not_authorized": "Not authorized",
                  }.get(snapshot.state, snapshot.state.replace("_", " ").title())
        if outcome is not None and outcome.decision == "DENY":
            status = "Detected · read-only status grant required"
        if snapshot.serve_state == "conflict":
            status = "Serve conflict · no change allowed"
        elif snapshot.serve_state == "unavailable" and snapshot.state == "signed_in":
            status = "Verification unavailable · no change allowed"
        try:
            owned_route = next((route for route in PrivateAccessStateStore().load().owned_routes
                                if route.route_id == MOBILE_HOST_ROUTE_ID), None)
        except (OSError, ValueError):
            owned_route = None
        if owned_route is not None:
            live_route = next((route for route in snapshot.routes
                               if (route.host, route.path, route.target) ==
                               (owned_route.host, owned_route.path, owned_route.target)), None)
            if live_route is not None:
                status = "Private route recorded · Mobile Host health rechecked before changes"
        else:
            live_route = None
        entries = [self._entry(tr("Tailscale · {status}", status=tr(status)), "info", "",
                               tr("Installed CLI: {value}\nTailnet identity: {value2}\nServe inventory: {serve_state}\nGateway: {value3} · {value4}\nTailnet login, Serve reachability, Gateway API keys, and workspace grants are separate.", value=snapshot.executable or tr("not detected"), value2=snapshot.dns_name or tr("not verified"), serve_state=tr(snapshot.serve_state), value3=snapshot.gateway_url or tr("not configured"), value4=tr("healthy") if snapshot.gateway_healthy else tr("not verified")),
                               translate=False)]
        if live_route is not None:
            entries.append(self._entry(
                tr("Route stays on after ISyCode exits · {url}", url=route_url(live_route)), "info", "",
                tr("Tailscale Serve keeps this private route until you disable it here; ISyCode does not remove it on exit because removal is itself an approved change. While Mobile Host is stopped, whatever listens on {target} is reachable from your tailnet at this path. Disable the route when you are not using it.", target=live_route.target),
                translate=False))
        if snapshot.state == "not_authorized":
            entries.append(self._entry("Grant read-only Tailscale inventory", "tailscale_permissions", ""))
        elif snapshot.state == "missing_cli":
            try:
                TailscalePackageInstallOwner(
                    self._workspace_root, WorkspaceAuthority(self._workspace_root),
                    self._action_approvals).plan()
                entries.append(self._entry(
                    "Install Tailscale · supported Ubuntu/Debian · three approvals",
                    "tailscale_install", ""))
            except (OSError, RuntimeError, TypeError, ValueError):
                entries.append(self._entry(
                    "Automated installation unavailable on this system", "info", "",
                    "Use the official manual instructions; ISyCode will not run an unverified installer."))
            entries.append(self._entry("Manual installation steps", "tailscale_manual", ""))
        elif snapshot.state == "unsupported_os":
            entries.append(self._entry(
                "Automated installation unavailable on this system", "info", "",
                "ISyCode automates only the reviewed Ubuntu/Debian package transaction."))
            entries.append(self._entry("Manual installation steps", "tailscale_manual", ""))
        elif snapshot.state == "signed_out":
            entries.append(self._entry("Log in to this tailnet…", "tailscale_login", ""))
            if self._tailscale_login_owner and self._tailscale_login_attempt:
                entries.extend([
                    self._entry("Check browser login status", "tailscale_login_check", ""),
                    self._entry("Cancel local login process", "tailscale_login_cancel", ""),
                ])
        elif snapshot.state == "signed_in":
            try:
                owned = any(route.route_id == MOBILE_HOST_ROUTE_ID
                            for route in PrivateAccessStateStore().load().owned_routes)
            except (OSError, ValueError):
                owned = False
            if owned:
                entries.append(self._entry("Disable ISyCode Mobile Host route…",
                                           "tailscale_serve_disable", ""))
            elif snapshot.serve_state in {"empty", "existing"}:
                entries.append(self._entry("Enable private Mobile Host route…",
                                           "tailscale_serve_enable", ""))
            else:
                entries.append(self._entry("Serve inventory is unavailable or conflicting",
                                           "info", "",
                                           "ISyCode will not change unknown or conflicting Serve configuration."))
        entries.extend([
            self._entry("Permissions and authority…", "tailscale_permissions", ""),
            self._entry("Refresh status", "tailscale_refresh", ""),
            self._entry("Manual setup steps", "tailscale_manual", ""),
            self._entry(tr("Back to Settings"), "settings_back", ""),
        ])
        self._render_menu("private_access", "Settings · Private access", entries)

    def _open_tailscale_permissions(self) -> None:
        if self._menu_mode != "tailscale_permissions" and self._menu_mode:
            self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        try:
            cli = self._tailscale_adapter.resolve_executable()
        except (OSError, RuntimeError, ValueError):
            cli = None
        apt = shutil.which("apt-get")
        apt_executable = str(Path(apt).resolve(strict=True)) if apt else None
        scopes = []
        if cli:
            scopes.extend(("tailscale.inspect", "tailscale.login",
                           "tailscale.serve.enable", "tailscale.serve.disable"))
        if apt:
            scopes.extend(("tailscale.install.prepare", "tailscale.install.stage",
                           "tailscale.install"))
        entries = []
        try:
            grants = WorkspaceAuthority(self._workspace_root).policy().get("grants", {})
            for action in scopes:
                executable = cli if action in {
                    "tailscale.inspect", "tailscale.login", "tailscale.serve.enable",
                    "tailscale.serve.disable"} else apt_executable
                if executable is None:
                    continue
                grant = grants.get(action, {})
                enabled = displayed_on(action, grant,
                                       executable in grant.get("executables", []))
                payload = json.dumps({"action": action, "executable": executable,
                                      "enabled": enabled})
                entries.append(self._entry(
                    tr("{verb} {action} · {executable}",
                       verb=tr("Revoke") if enabled else tr("Grant"),
                       action=action, executable=executable),
                    "tailscale_grant", payload,
                    tr("This permission is scoped to this workspace and exact executable. Mutations still need a fresh approval."),
                    translate=False))
        except (OSError, ValueError, WorkspaceAuthorityError):
            entries.append(self._entry("Authority policy unavailable · all actions deny", "info"))
        if not entries:
            entries.append(self._entry("No supported Tailscale CLI or apt-get was found.", "info"))
        entries.append(self._entry("Back", "private_access_back", ""))
        self._render_menu("tailscale_permissions", "Private access · Authority grants", entries)

    async def _change_tailscale_grant(self, payload: str) -> None:
        try:
            data = json.loads(payload)
            action = data["action"]
            executable = data["executable"]
            enabled = not data["enabled"]
            accepted = await self._await_screen(TailscaleConfirmScreen(
                "Workspace Authority · Tailscale",
                tr("{value} `{action}` for this workspace?\n\nExact executable: {executable}\n\nA grant permits only this owner and executable to request the action. It does not log in, install packages, expose the Gateway, or bypass IsySentinel. Every mutation still needs its own one-use approval.", value=tr("Grant") if enabled else tr("Revoke"), action=action, executable=executable),
                "Save grant" if enabled else "Revoke grant"))
            if not accepted:
                self._append("  " + tr("Tailscale authority change cancelled; no grant changed."), MUTED)
                return
            WorkspaceAuthority(self._workspace_root).set_grant(
                action, enabled=enabled, executables=[executable])
            self._append("  " + tr("Workspace grant {value} · {action}.", value=tr("saved") if enabled else tr("revoked"), action=action), GREEN)
            self._open_tailscale_permissions()
        except (KeyError, json.JSONDecodeError, OSError, ValueError,
                WorkspaceAuthorityError) as exc:
            self._append("  " + tr("Tailscale grant was not changed ({name}).", name=type(exc).__name__), RED)

    async def _run_tailscale_install(self) -> None:
        try:
            owner = TailscalePackageInstallOwner(
                self._workspace_root, WorkspaceAuthority(self._workspace_root),
                self._action_approvals)
            plan = owner.plan()
            for action_id, request, details, operation in (
                ("tailscale.install.prepare", plan.prepare_request(self._workspace_root),
                 plan.prepare_preview(), owner.prepare),
            ):
                if not self._tailscale_grant_exists(action_id, plan.apt_executable):
                    self._append("  " + tr("Installation blocked · explicitly grant this exact action in Settings → Private access → Permissions."), YELLOW)
                    self._open_tailscale_permissions()
                    return
                accepted = await self._await_screen(TailscaleConfirmScreen(
                    "Prepare official Tailscale package", details,
                    "Download and verify"))
                if not accepted:
                    self._append("  " + tr("Package preparation cancelled; no package transaction ran."), MUTED)
                    return
                approval = self._action_approvals.issue(request, ttl_seconds=30)
                outcome = await asyncio.to_thread(operation, request, approval)
                if outcome.decision != "ALLOW":
                    self._append("  " + tr("Package preparation {decision} · {value}", decision=outcome.decision, value=outcome.reason[:180]), YELLOW)
                    return
            transaction = await asyncio.to_thread(owner.simulate)
            for action_id, request, details, operation in (
                ("tailscale.install.stage", transaction.stage_request(self._workspace_root),
                 transaction.stage_preview(), owner.stage),
                ("tailscale.install", transaction.request(self._workspace_root),
                 transaction.preview(), owner.install),
            ):
                if not self._tailscale_grant_exists(action_id, transaction.plan.apt_executable):
                    self._append("  " + tr("Installation blocked · explicitly grant this exact action in Settings → Private access → Permissions."), YELLOW)
                    self._open_tailscale_permissions()
                    return
                accepted = await self._await_screen(TailscaleConfirmScreen(
                    "Stage verified package as root" if action_id.endswith("stage")
                    else "Install exact Tailscale package", details,
                    "Approve this step"))
                if not accepted:
                    self._append("  " + tr("Installation cancelled before this step; no later step ran."), MUTED)
                    return
                approval = self._action_approvals.issue(request, ttl_seconds=30)
                outcome = await asyncio.to_thread(operation, request, approval)
                if outcome.decision != "ALLOW":
                    self._append("  " + tr("Tailscale install {decision} · {value}", decision=outcome.decision, value=outcome.reason[:180]), YELLOW)
                    return
                self._append("  " + tr("Tailscale step complete · {action_id} · receipt verified.", action_id=action_id), GREEN)
            await self._refresh_private_access()
        except (OSError, RuntimeError, TypeError, ValueError,
                WorkspaceAuthorityError) as exc:
            self._append("  " + tr("Automated Tailscale install unavailable ({name}). Use the official manual instructions.", name=type(exc).__name__), YELLOW)

    def _tailscale_grant_exists(self, action_id: str, executable: str) -> bool:
        try:
            grant = WorkspaceAuthority(self._workspace_root).policy()["grants"].get(action_id, {})
            return (grant.get("enabled") is True
                    and str(Path(executable).resolve(strict=True)) in grant.get("executables", []))
        except (OSError, RuntimeError, ValueError, WorkspaceAuthorityError):
            return False

    async def _run_tailscale_login(self) -> None:
        owner = TailscaleLoginOwner(
            self._workspace_root, WorkspaceAuthority(self._workspace_root),
            self._action_approvals, adapter=self._tailscale_adapter)
        try:
            executable = self._tailscale_adapter.resolve_executable()
            if not executable or not self._tailscale_grant_exists("tailscale.inspect", executable):
                self._append("  " + tr("Login status check blocked · grant read-only inventory first."), YELLOW)
                self._open_tailscale_permissions()
                return
            request = owner.login_request()
            if not self._tailscale_grant_exists("tailscale.login", request.parameters["executable"]):
                self._append("  " + tr("Login blocked · grant this exact Tailscale executable in Settings → Private access → Permissions."), YELLOW)
                self._open_tailscale_permissions()
                return
            details = owner.preview(request)
            if not await self._await_screen(TailscaleConfirmScreen(
                    "Sign in to Tailscale", details, "Start browser login")):
                self._append("  " + tr("Tailscale login cancelled; no process started."), MUTED)
                return
            approval = self._action_approvals.issue(request, ttl_seconds=30)
            outcome = await asyncio.to_thread(owner.begin_login, request, approval)
            if outcome.decision != "ALLOW":
                self._append("  " + tr("Tailscale login {decision} · {value}", decision=outcome.decision, value=outcome.reason[:180]), YELLOW)
                return
            self._tailscale_login_owner = owner
            self._tailscale_login_attempt = outcome.text.split(": ", 1)[-1]
            status = await asyncio.to_thread(owner.poll, self._tailscale_login_attempt)
            if status.login_url:
                self._append("  " + tr("Open this official login link in your browser: {login_url}", login_url=status.login_url), CYAN)
            self._append("  " + tr("Tailscale login · {state} · {reason}", state=status.state, reason=status.reason), YELLOW)
            self._open_private_access_menu()
        except (OSError, RuntimeError, TypeError, ValueError,
                WorkspaceAuthorityError) as exc:
            self._append("  " + tr("Tailscale login could not start ({name}).", name=type(exc).__name__), RED)

    async def _check_tailscale_login(self, cancel: bool = False) -> None:
        owner = self._tailscale_login_owner
        attempt = self._tailscale_login_attempt
        if owner is None or attempt is None:
            self._append("  " + tr("No active Tailscale login attempt in this process."), MUTED)
            return
        status = await asyncio.to_thread(owner.cancel if cancel else owner.poll, attempt)
        if status.login_url:
            self._append("  " + tr("Official Tailscale login link: {login_url}", login_url=status.login_url), CYAN)
        self._append("  " + tr("Tailscale login · {state} · {reason}", state=status.state, reason=status.reason),
                     GREEN if status.state == "signed_in" else YELLOW)
        if status.state == "failed" and sys.platform == "linux":
            self._append(f"  {LINUX_OPERATOR_HINT}", MUTED)
        if status.state != "pending":
            self._tailscale_login_owner = None
            self._tailscale_login_attempt = None
        self._open_private_access_menu()

    async def _run_tailscale_serve(self, enabling: bool) -> None:
        mobile_serve_adapter = TailscaleAdapter(
            gateway_url="http://127.0.0.1:8765", gateway_port=8765,
            gateway_health_path="/isycode/v1/health")
        owner = TailscaleServeOwner(
            self._workspace_root, WorkspaceAuthority(self._workspace_root),
            self._action_approvals, adapter=mobile_serve_adapter,
            gateway_port=8765, route_id=MOBILE_HOST_ROUTE_ID,
            service_label="Mobile Host")
        action_id = "tailscale.serve.enable" if enabling else "tailscale.serve.disable"
        try:
            executable = self._tailscale_adapter.resolve_executable()
            if not executable or not self._tailscale_grant_exists("tailscale.inspect", executable):
                self._append("  " + tr("Serve inventory blocked · grant read-only Tailscale status first."), YELLOW)
                self._open_tailscale_permissions()
                return
            preview = owner.preview_enable() if enabling else owner.preview_disable()
            executable = preview.request.parameters["executable"]
            if not self._tailscale_grant_exists(action_id, executable):
                self._append("  " + tr("Serve change blocked · grant this exact Tailscale executable in Settings → Private access → Permissions."), YELLOW)
                self._open_tailscale_permissions()
                return
            label = "Enable private route" if enabling else "Disable owned private route"
            if not await self._await_screen(TailscaleConfirmScreen(
                    "Private Tailscale Serve", preview.description, label)):
                self._append("  " + tr("Tailscale Serve change cancelled; no command ran."), MUTED)
                return
            approval = self._action_approvals.issue(preview.request, ttl_seconds=30)
            operation = owner.enable if enabling else owner.disable
            outcome = await asyncio.to_thread(operation, preview, approval)
            self._append("  " + tr("Tailscale Serve · {decision} · {text}", decision=outcome.decision, text=outcome.text),
                         GREEN if outcome.decision == "ALLOW" else YELLOW)
            if outcome.decision in {"ERROR", "NOT_VERIFIABLE"} and sys.platform == "linux":
                self._append(f"  {LINUX_OPERATOR_HINT}", MUTED)
            if outcome.receipt:
                self._append("  " + tr("Receipt · {receipt_id}", receipt_id=outcome.receipt.receipt_id), MUTED)
            self._open_private_access_menu()
        except (OSError, RuntimeError, TypeError, ValueError,
                WorkspaceAuthorityError) as exc:
            # Only surface the owner’s fixed validation messages; operating-system
            # and subprocess exceptions can contain local paths or command details.
            reason = str(exc)[:180] if isinstance(exc, ValueError) else type(exc).__name__
            self._append("  " + tr("Private Serve blocked · {reason}. No route change was approved.", reason=reason),
                         YELLOW)

    async def _show_tailscale_manual_steps(self) -> None:
        details = (
            "1. Install Tailscale using the official Linux guide: "
            "https://tailscale.com/docs/install/linux\n"
            "2. Return here and grant read-only local Tailscale inventory.\n"
            "3. Sign in from the Tailscale browser login flow.\n"
            "4. Grant `tailscale.serve.enable`, then review the exact `/isycode` route before enabling it.\n\n"
            "ISyCode's automated installer supports only the verified Ubuntu/Debian package recipe. "
            "Manual installation does not grant permissions, sign in, change Serve, or install a daemon "
            "through this TUI. Tailscale Serve is private to the tailnet; Gateway keys/scopes and "
            "workspace filesystem grants remain separate.")
        await self._await_screen(TailscaleConfirmScreen(
            "Manual private-access setup", details, "Done"))
        self._open_private_access_menu()

    def _open_bridge_settings(self) -> None:
        entries = [self._entry(
            "Blocked · no registered action owner",
            "info", "", "Bridge leases are coordination signals, never Workspace Authority grants. "
            "Secure does not run hello, heartbeat, peek, send, lease, or wake until each path has an owner and gate."),
            self._entry(tr("Back to Settings"), "settings_back", "")]
        if self._menu_mode != "bridge_settings":
            self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("bridge_settings", "Settings · Bridge coordination", entries)

    async def _set_bridge_enabled(self, enabled: bool) -> None:
        # There is deliberately no Bridge execution owner in Secure yet.
        # Persisted opt-in and a Bridge lease are not product authorization.
        del enabled
        self._bridge_enabled = False
        self._set_activity(tr("Bridge is blocked in Secure · execution owner not connected"), YELLOW)
        self._refresh_bridge_status_text()
        self._open_bridge_settings()

    async def _enable_bridge(self, startup: bool = False) -> None:
        del startup
        self._bridge_enabled = False
        self._set_activity(tr("Bridge startup blocked in Secure · no execution owner is connected"), YELLOW)
        self._refresh_bridge_status_text()

    async def _bridge_tick(self, force: bool = False) -> None:
        del force
        # No direct Bridge subprocess calls are reachable from Secure.
        self._bridge_enabled = False
        self._refresh_bridge_status_text()

    def _refresh_bridge_status_text(self) -> None:
        if not self.is_mounted:
            return
        text = status_chip("Blocked in Secure · no Bridge owner")
        self.query_one("#bridge-status", Static).update(text)

    async def _issue_pairing_pin(self) -> None:
        """Replace the pairing PIN only through the Mobile Host owner's gate."""
        owner = self._mobile_host_owner
        if owner is None or not self._mobile_host.status().alive:
            self._append("  " + tr("Start Mobile Host first; no PIN was issued."), YELLOW)
            return
        try:
            authority = WorkspaceAuthority(self._workspace_root)
            if (not mobile_host_enabled(authority.policy().get("grants", {}))
                    and not await self._grant_mobile_host(authority)):
                self._append("  " + tr("Mobile Host grant cancelled; no PIN was issued."), MUTED)
                return
            request = owner.pin_request()
        except (WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append("  " + tr("New PIN unavailable ({name}); nothing changed.", name=type(exc).__name__), RED)
            return
        if not await self._await_screen(TailscaleConfirmScreen(
                "Issue a new pairing PIN",
                "Replace the current Mobile Host PIN, if any, and clear failed pairing attempts. "
                "The new PIN works once, for 5 minutes, from any device that can reach this host, "
                "including your tailnet through a saved private route.",
                "Issue PIN")):
            self._append("  " + tr("New PIN cancelled; the current PIN is unchanged."), MUTED)
            return
        approval = self._action_approvals.issue(request, ttl_seconds=30)
        issued, reason, pin = await asyncio.to_thread(owner.issue_pairing_pin, request, approval)
        if issued and pin:
            self._append("  " + tr("New pairing PIN {pin} (expires in 5 minutes, one device).", pin=pin), GREEN)
        else:
            self._append("  " + tr("New PIN denied · {value}", value=reason[:180]), YELLOW)
        self._render_mobile_host_status()

    async def _grant_mobile_host(self, authority: WorkspaceAuthority) -> bool:
        """Ask once, then save exactly the scoped Mobile Host grants."""
        accepted = await self._await_screen(TailscaleConfirmScreen(
            "Grant Mobile Host for this workspace",
            tr("Allow `mobile.host.start` only at {mobile_host_address}, `mobile.pair` only for the one-use Mobile Host pairing challenge, and `mobile.pair.issue` to replace that PIN (each new PIN still asks first). The listener binds loopback only; if a private Tailscale route to it is enabled, tailnet devices can reach it through that route. Pair-issued tokens can read the runtime inventory, request runtime selection, and send heartbeats; they cannot read files, execute runtimes, or access sessions.", mobile_host_address=MOBILE_HOST_ADDRESS),
            "Grant these actions"))
        if not accepted:
            return False
        authority.set_grant("mobile.host.start", enabled=True,
                            network_hosts=[MOBILE_HOST_ADDRESS])
        for action in MOBILE_PAIR_ACTIONS:
            authority.set_grant(action, enabled=True, targets=[MOBILE_PAIR_TARGET])
        return True

    def _render_mobile_host_status(self) -> None:
        status = self._mobile_host.status()
        entries: list[dict[str, str]] = []
        if status.alive:
            pin = self._mobile_host.pairing_code_for_local_settings()
            try:
                routed = next((route for route in PrivateAccessStateStore().load().owned_routes
                               if route.route_id == MOBILE_HOST_ROUTE_ID), None)
            except (OSError, ValueError):
                routed = None
            entries.append(self._entry(
                tr("Host alive · http://{address}:{port}",
                   address=status.address, port=status.port), "info", "",
                tr("Bound to loopback. {value}", value=(tr("Your saved private route {route} makes it reachable from your tailnet while it runs.", route=route_url(routed)) if routed is not None else tr("No saved private Tailscale route points here."))),
                translate=False))
            if pin:
                entries.append(self._entry(
                    tr("Pairing PIN · {pin} · expires in 5 minutes", pin=pin),
                    "info", "", tr("One device exchange; token expires in one hour."),
                    translate=False))
            entries.append(self._entry(
                "New pairing PIN · asks first", "mobile_host_new_pin", "",
                "Replaces the current PIN and clears failed attempts. Needs the Mobile Host grant."))
            entries.append(self._entry("Refresh host status", "mobile_host_status_refresh", ""))
        else:
            entries.append(self._entry("Start Mobile Host · local approval required",
                                       "mobile_host_start", ""))
            entries.append(self._entry("Listener stopped · no pairing credentials issued", "info"))
        entries.append(self._entry(tr("Back to Settings"), "settings_back", ""))
        self._render_menu("mobile_host_status", "Settings · Mobile host", entries)

    async def _open_gateway_mcp_tool(self, name: str) -> None:
        tool = next((item for item in self._gateway_mcp_snapshot.items
                     if item.get("name") == name), None)
        if self._gateway_mcp_snapshot.state != "ready" or tool is None:
            self._append("  " + tr("MCP catalog changed or is unavailable; refresh it before calling a tool."), YELLOW)
            return
        arguments = await self._await_screen(MCPArgumentsScreen(tool))
        if arguments is None:
            return
        endpoint = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8787").rstrip("/")
        try:
            GatewayClient._validate_base_url(endpoint)
            parsed_endpoint = urlparse(endpoint)
            if parsed_endpoint.path not in {"", "/"} or parsed_endpoint.query or parsed_endpoint.fragment:
                raise ValueError("Gateway endpoint must be an origin without a path")
        except ValueError:
            self._append("  " + tr("Gateway URL is invalid; no MCP request was sent."), RED)
            return
        accepted = await self._await_screen(
            MCPInvocationConfirmScreen(
                name, str(tool.get("description", "")), arguments, endpoint))
        if not accepted:
            self._append("  " + tr("MCP call cancelled; no tool was invoked."), MUTED)
            return
        try:
            request = ActionRequest(
                "mcp.invoke", self._workspace_root, GatewayMCPInvocationOwner.target_for(endpoint),
                {"server": GatewayMCPInvocationOwner.SERVER_ID, "tool": name,
                 "arguments": arguments, "url": endpoint,
                 "schema_digest": tool_schema_digest(tool)}, execution_owner="gateway_mcp")
            approval = self._action_approvals.issue(request, ttl_seconds=30)
            owner = GatewayMCPInvocationOwner(
                self._workspace_root, WorkspaceAuthority(self._workspace_root),
                self._action_approvals)
            self._set_activity(tr("MCP · awaiting local grant for {name}", name=name), YELLOW)
            outcome = await owner.invoke(
                name, arguments, endpoint, tool_schema_digest(tool),
                list(self._gateway_mcp_snapshot.items), approval)
        except (WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append("  " + tr("MCP call denied before dispatch ({name}).", name=type(exc).__name__), RED)
            return
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            self._append("  " + tr("MCP call {decision} · {value}", decision=outcome.decision, value=outcome.reason[:240]), YELLOW)
            if outcome.text and outcome.decision == "ERROR":
                self.query_one(ChatArea).mount(Static(Text(outcome.text, style=YELLOW)))
            self._set_activity(tr("MCP call blocked · {name}", name=name), YELLOW)
            return
        self._append("  " + tr("MCP {name} · Gateway returned a result", name=name), CYAN)
        self.query_one(ChatArea).mount(Static(Text(outcome.text, style=TEXT)))
        self._append(
            f"  {verified_receipt_line(outcome.receipt.receipt_id)}",
            GREEN)
        self._set_activity(tr("MCP tool completed · {name}", name=name), GREEN)

    async def _open_gateway_semantic_search(self) -> None:
        endpoint = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8787").rstrip("/")
        try:
            workspace_id = gateway_workspace_id(self._workspace_root)
        except (OSError, RuntimeError, ValueError):
            self._append("  " + tr("Workspace root could not be resolved; no Gateway request was sent."), RED)
            return
        try:
            GatewayClient._validate_base_url(endpoint)
        except ValueError:
            self._append("  " + tr("Gateway URL is invalid; no semantic request was sent."), RED)
            return
        selected = await self._await_screen(GatewaySemanticQueryScreen(endpoint, workspace_id))
        if not selected:
            return
        operation, payload = selected
        accepted = await self._await_screen(
            GatewaySemanticConfirmScreen(endpoint, operation, payload, workspace_id))
        if not accepted:
            self._append("  " + tr("Semantic search cancelled; no Gateway request was sent."), MUTED)
            return
        try:
            target = GatewayMCPInvocationOwner.target_for(endpoint).split("@", 1)[1]
            request = ActionRequest(
                "gateway.semantic.read", self._workspace_root, target,
                {"url": endpoint, "operation": operation, "payload": payload,
                 "workspace_id": workspace_id}, execution_owner="gateway_semantic")
            approval = self._action_approvals.issue(request, ttl_seconds=30)
            owner = GatewaySemanticOwner(
                self._workspace_root, WorkspaceAuthority(self._workspace_root),
                self._action_approvals)
            self._set_activity(tr("Gateway {operation} · awaiting local grant and remote scope", operation=operation), YELLOW)
            outcome = await asyncio.to_thread(
                owner.invoke, operation, payload, endpoint, workspace_id, approval)
        except (WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append("  " + tr("Semantic request denied before dispatch ({name}).", name=type(exc).__name__), RED)
            return
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            self._append("  " + tr("Gateway {operation} {decision} · {value}", operation=operation, decision=outcome.decision, value=outcome.reason[:240]), YELLOW)
            if outcome.text and outcome.decision == "ERROR":
                self.query_one(ChatArea).mount(Static(Text(outcome.text, style=YELLOW)))
            self._set_activity(tr("Gateway {operation} blocked · check workspace binding, host grant, and isyco.semantic key scope", operation=operation), YELLOW)
            return
        self._append("  " + tr("Gateway semantic {operation} · response from configured workspace", operation=operation), CYAN)
        self.query_one(ChatArea).mount(Static(Text(outcome.text, style=TEXT)))
        self._append(
            "  " + tr("{verified_receipt_line} · configured workspace IDs matched", verified_receipt_line=verified_receipt_line(outcome.receipt.receipt_id)),
            GREEN)
        self._set_activity(tr("Native Gateway {operation} completed", operation=operation), GREEN)

    async def _open_broker_preview(self) -> None:
        self._set_activity(
            tr("Broker preview blocked · desktop.file_picker has no registered action owner"), YELLOW)

    async def _provision_broker(self) -> None:
        self._set_activity(
            tr("Broker provisioning blocked · desktop.file_picker has no registered action owner"), YELLOW)

    async def _manage_broker(self, project: Path) -> None:
        try:
            authority = WorkspaceAuthority(self._workspace_root)
            owner = BrokerManagementOwner(
                self._workspace_root, authority, self._action_approvals)
            item = owner.registry.get(self._workspace_root, project)
            if item is None:
                raise FileNotFoundError("registered broker not found")
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError,
                WorkspaceAuthorityError) as exc:
            self._append("  " + tr("Managed broker unavailable ({name}); no Docker action ran.", name=type(exc).__name__), YELLOW)
            return
        operation = await self._await_screen(BrokerManagementScreen(project, item))
        if operation is None:
            return
        if operation in {"logs", "start", "stop", "remove"}:
            accepted = await self._await_screen(
                BrokerOperationConfirmScreen(operation, project, item["container"]))
            if not accepted:
                self._append("  " + tr("Broker {operation} cancelled; no Docker action ran.", operation=operation), MUTED)
                return
        action_id = {"health": "broker.health", "logs": "broker.logs",
                     "start": "broker.start", "stop": "broker.stop",
                     "remove": "broker.remove"}[operation]
        try:
            request, _ = owner.request_for(project, operation)
            if operation in {"start", "stop"}:
                authority.set_grant(action_id, enabled=True, executables=[owner.docker])
            elif operation == "remove":
                authority.set_grant(action_id, enabled=True, targets=[request.target])
            else:
                authority.set_grant(action_id, enabled=True)
            approval = (self._action_approvals.issue(request, ttl_seconds=30)
                        if operation in {"logs", "start", "stop", "remove"} else None)
            self._set_activity(tr("Semantic broker · {operation} · checking exact registry identity", operation=operation), YELLOW)
            outcome = await asyncio.to_thread(owner.perform, project, operation, approval)
        except (OSError, RuntimeError, TypeError, ValueError, WorkspaceAuthorityError) as exc:
            self._append("  " + tr("Broker {operation} failed ({name}); review registry and Docker state.", operation=operation, name=type(exc).__name__), RED)
            return
        finally:
            try:
                if operation in {"start", "stop"}:
                    authority.set_grant(action_id, enabled=False, executables=[])
                elif operation == "remove":
                    authority.set_grant(action_id, enabled=False, targets=[])
                else:
                    authority.set_grant(action_id, enabled=False)
            except (WorkspaceAuthorityError, OSError, ValueError):
                pass
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            self._append("  " + tr("Broker {operation} {decision} · {value}", operation=operation, decision=outcome.decision, value=outcome.reason[:300]), YELLOW)
            self._set_activity(tr("Broker {operation} not verified", operation=operation), YELLOW)
            return
        self.query_one(ChatArea).mount(Static(Text(
            tr("Semantic broker · {operation}\n{text}", operation=operation, text=outcome.text), style=TEXT)))
        self._append(f"  {verified_receipt_line(outcome.receipt.receipt_id, local=False)}", GREEN)
        self._set_activity(tr("Semantic broker {operation} completed · local receipt verified", operation=operation), GREEN)

    async def _open_lsp_server(self, server_id: str) -> None:
        self._refresh_lsp_status()
        server = next((item for item in self._lsp_inventory
                       if item.get("id") == server_id), None)
        if server is None or server.get("state") != "sandbox_ready":
            self._append("  " + tr("This LSP adapter is not available in a supported sandbox."), YELLOW)
            return
        try:
            authority = WorkspaceAuthority(self._workspace_root)
            grant = authority.policy().get("grants", {}).get("lsp.start", {})
            lsp_sandbox = server["sandbox_executable"]
            has_grant = (bool(grant.get("enabled"))
                         and lsp_sandbox in grant.get("executables", []))
        except (WorkspaceAuthorityError, OSError, ValueError):
            self._append("  " + tr("Workspace Authority is unavailable; LSP process is denied."), RED)
            return
        if not has_grant:
            accepted = await self._await_screen(GrantLSPProcessScreen(
                self._workspace_root, lsp_sandbox))
            if not accepted:
                self._append("  " + tr("LSP process grant declined; no language server was started."), MUTED)
                return
            try:
                executables = set(grant.get("executables", []))
                executables.add(lsp_sandbox)
                authority.set_grant("lsp.start", enabled=True, executables=sorted(executables))
            except (WorkspaceAuthorityError, OSError, ValueError):
                self._append("  " + tr("LSP process grant could not be saved; the server remains denied."), RED)
                return
        query = await self._await_screen(LSPQueryScreen(self._workspace_root, server["label"]))
        if query is None:
            return
        accepted = await self._await_screen(LSPConfirmScreen(self._workspace_root, query, server["label"]))
        if not accepted:
            self._append("  " + tr("LSP request cancelled; no language server was started."), MUTED)
            return
        try:
            request = ActionRequest(
                "lsp.start", self._workspace_root, server_id,
                {"operation": "workspace/symbol", "server_id": server_id,
                 "query": query, "workspace_root": str(self._workspace_root),
                 "executable": server["sandbox_executable"],
                 "server_executable": server["server_executable"],
                 "node_executable": server["node_executable"],
                 **({"runtime_executable": server["runtime_executable"]} if server.get("runtime_executable") else {})},
                execution_owner="lsp_symbols")
            approval = self._action_approvals.issue(request, ttl_seconds=30)
            owner = LPSSymbolOwner(
                self._workspace_root, authority,
                self._action_approvals)
            self._set_activity(tr("LSP · awaiting local grant and starting sandbox"), YELLOW)
            outcome = await owner.search(
                server_id, query, approval, list(self._lsp_inventory))
        except (WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append("  " + tr("LSP request denied before start ({name}).", name=type(exc).__name__), RED)
            return
        if outcome.decision != "ALLOW" or outcome.receipt is None:
            self._append("  " + tr("LSP request {decision} · {value}", decision=outcome.decision, value=outcome.reason[:240]), YELLOW)
            self._set_activity(tr("LSP request blocked · grant sandbox in Authority settings"), YELLOW)
            return
        self._append("  " + tr("{label} LSP · {query} · verified workspace/symbol response", label=server['label'], query=query), CYAN)
        self.query_one(ChatArea).mount(Static(Text(outcome.text, style=TEXT)))
        self._append(
            f"  {verified_receipt_line(outcome.receipt.receipt_id)}",
            GREEN)
        self._set_activity(tr("LSP request completed · sandbox closed"), GREEN)

    async def _change_mobile_host_grant(self, enabled: bool) -> None:
        try:
            authority = WorkspaceAuthority(self._workspace_root)
            if enabled:
                if await self._grant_mobile_host(authority):
                    self._append("  " + tr("Mobile Host granted for this workspace. Starting it still asks first."), GREEN)
                else:
                    self._append("  " + tr("Mobile Host grant cancelled; nothing changed."), MUTED)
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
                self._append("  " + tr("Mobile Host grants revoked for this workspace."), GREEN)
            else:
                self._append("  " + tr("Mobile Host grants unchanged."), MUTED)
        except (WorkspaceAuthorityError, OSError, ValueError):
            self._append("  " + tr("Mobile Host grants could not be changed; starts and pairing stay denied unless a valid saved grant remains."), RED)
        self._open_authority_menu()
