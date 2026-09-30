"""Narrow, approved Tailscale Serve mapping for the local ISyCode Gateway."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from isycode.action_runtime import (
    ActionOutcome, ActionReceipt, ProductActionGate, TailscaleAuthorityFacts,
    tailscale_serve_delta_digest,
)
from isycode.approvals import ActionApproval, ActionApprovalStore
from isycode.private_access import OwnedServeRoute, PrivateAccessStateStore
from isycode.security import ActionRequest
from isycode.tailscale import (
    DEFAULT_GATEWAY_PORT, TailscaleAdapter, TailscaleCommandResult,
    TailscaleSnapshot, ServeRoute, _bounded_run,
)
from isycode.tailscale_read import TailscaleReadOwner
from isycode.workspace_authority import WorkspaceAuthority


ROUTE_ID = "isycode-gateway"
MOBILE_HOST_ROUTE_ID = "isycode-mobile-host"
ROUTE_PATH = "/isycode"
HTTPS_PORT = 443
COMMAND_TIMEOUT = 15.0
MAX_OUTPUT = 64 * 1024
HOST_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.ts\.net")


def serve_host_port(dns_name: str, port: int = HTTPS_PORT) -> str:
    """Return the key Tailscale uses for Serve `Web` and `AllowFunnel` entries.

    `tailscale serve status --json` keys both maps by ipn.HostPort
    ("$DNS:$PORT"), which the read adapter preserves as `ServeRoute.host`.
    Owned-route identity must use the same key or the owner cannot see its
    own route, nor an unowned route it must refuse to replace.
    """
    return f"{dns_name.rstrip('.')}:{port}"


def route_url(route: ServeRoute) -> str:
    """Browser URL for a HostPort-keyed route; 443 is implicit for https."""
    return f"https://{route.host.removesuffix(f':{HTTPS_PORT}')}{route.path}"


@dataclass(frozen=True)
class ServePreview:
    action_id: str
    request: ActionRequest
    route: ServeRoute
    argv: tuple[str, ...]
    description: str
    already_applied: bool = False


class TailscaleServeOwner:
    """Add/remove one private path, never resetting or replacing Serve config."""

    def __init__(self, root: Path, authority: WorkspaceAuthority,
                 approvals: ActionApprovalStore, *, adapter: Any | None = None,
                 state_store: PrivateAccessStateStore | None = None,
                 runner: Callable = _bounded_run,
                 gateway_port: int = DEFAULT_GATEWAY_PORT,
                 route_id: str = ROUTE_ID,
                 service_label: str = "Gateway"):
        self.root = root.resolve(strict=True)
        self.authority = authority
        self.approvals = approvals
        self.adapter = adapter or TailscaleAdapter(gateway_port=gateway_port)
        self._inventory = TailscaleReadOwner(self.root, authority, approvals,
                                             adapter=self.adapter, gateway_port=gateway_port)
        self.state_store = state_store or PrivateAccessStateStore()
        self.runner = runner
        self.gateway_port = gateway_port
        self.route_id = route_id
        self.service_label = service_label

    def _prepare(self, action_id: str) -> tuple[ServePreview, TailscaleAuthorityFacts]:
        if action_id not in {"tailscale.serve.enable", "tailscale.serve.disable"}:
            raise ValueError("unsupported Tailscale Serve action")
        snapshot = self._inventory.authorized_snapshot()
        if not isinstance(snapshot, TailscaleSnapshot) or snapshot.state != "signed_in":
            raise ValueError("Tailscale must be signed in before configuring private Serve")
        if snapshot.serve_state not in {"empty", "existing"} or not isinstance(snapshot.serve_digest, str):
            raise ValueError("complete, supported Serve inventory is unavailable")
        executable = snapshot.executable
        if not isinstance(executable, str) or not Path(executable).is_absolute():
            raise ValueError("canonical Tailscale executable is unavailable")
        executable_path = Path(executable).resolve(strict=True)
        if (str(executable_path) != executable or executable_path.name != "tailscale"
                or not executable_path.is_file() or not executable_path.stat().st_mode & 0o111):
            raise ValueError("canonical Tailscale executable is unavailable")
        host = snapshot.dns_name
        if not isinstance(host, str) or HOST_RE.fullmatch(host.rstrip(".")) is None:
            raise ValueError("a verified Tailscale DNS name is required for private Serve")
        # Owned identity uses the same HostPort key as the live inventory.
        host = serve_host_port(host)
        state = self.state_store.load()
        saved = tuple(route for route in state.owned_routes if route.route_id == self.route_id)
        if len(saved) > 1:
            raise ValueError("private route ownership state is ambiguous")

        if action_id == "tailscale.serve.enable":
            gateway_url = snapshot.gateway_url
            if (not isinstance(gateway_url, str)
                    or gateway_url != f"http://127.0.0.1:{self.gateway_port}"):
                raise ValueError(f"the configured loopback {self.service_label} endpoint is unavailable")
            if snapshot.gateway_healthy is not True:
                if self.service_label == "Mobile Host":
                    raise ValueError(
                        "Mobile Host health is not reachable at 127.0.0.1:8765. "
                        "Start it from Settings → Mobile host status, then retry."
                    )
                raise ValueError(f"the configured loopback {self.service_label} health check must pass")
            gateway_port = self.gateway_port
            route = ServeRoute(host, ROUTE_PATH, gateway_url, True)
            matches = tuple(item for item in snapshot.routes
                            if (item.host, item.path) == (route.host, route.path))
            already = False
            owned = None
            if saved:
                record = saved[0]
                if (record.host, record.path, record.target) != (
                        route.host, route.path, route.target):
                    raise ValueError("saved private route ownership conflicts with this host")
                if matches != (route,):
                    raise ValueError("saved route is not independently verified in live Serve state")
                owned = record
                already = True
            elif matches:
                raise ValueError("the /isycode route is already configured without ISyCode ownership")
            operation = (executable, "serve", f"--https={HTTPS_PORT}",
                         f"--set-path={ROUTE_PATH}", "--bg", gateway_url)
            description = (
                f"Add only {route_url(route)} -> {route.target} ({self.service_label}) via private Tailscale Serve.\n"
                f"Exact command: {' '.join(operation)}\n"
                "The local service stays bound to loopback. Funnel/public access is disabled. "
                "Other Serve routes must remain unchanged.\n")
        else:
            if not saved:
                raise ValueError("there is no ISyCode-owned route to disable")
            record = saved[0]
            if record.host != host:
                raise ValueError("current Tailscale name differs from the saved owned route")
            gateway_url = record.target
            parsed_gateway = urlsplit(gateway_url)
            gateway_port = parsed_gateway.port
            if (parsed_gateway.scheme != "http" or parsed_gateway.hostname != "127.0.0.1"
                    or gateway_port is None):
                raise ValueError("saved Gateway route target is invalid")
            route = ServeRoute(record.host, record.path, record.target, True)
            matches = tuple(item for item in snapshot.routes
                            if (item.host, item.path) == (route.host, route.path))
            if matches and matches != (route,):
                raise ValueError("live route differs from the saved ISyCode-owned route")
            owned = record
            already = not matches
            operation = (executable, "serve", f"--https={HTTPS_PORT}",
                         f"--set-path={ROUTE_PATH}", "--bg", gateway_url, "off")
            description = (
                f"Remove only the owned private mapping {route_url(route)} "
                f"-> {route.target}.\nExact command: {' '.join(operation)}\n"
                "Other Serve routes remain in place. No global reset is used.\n")

        facts = TailscaleAuthorityFacts(
            cli_executable=executable, gateway_url=gateway_url,
            gateway_port=gateway_port, route_id=self.route_id,
            proposed_route=route, live_routes=snapshot.routes,
            serve_inventory_complete=True, owned_route=owned,
            serve_digest=snapshot.serve_digest,
        )
        delta = tailscale_serve_delta_digest(action_id, snapshot.serve_digest,
                                             route, operation)
        request = ActionRequest(action_id, self.root, "tailscale", {
            "executable": executable, "gateway_url": gateway_url,
            "gateway_port": gateway_port, "route_id": self.route_id,
            "route_host": route.host, "route_path": route.path,
            "route_target": route.target, "serve_digest": snapshot.serve_digest,
            "serve_argv": operation, "serve_delta_digest": delta,
            "mode": "private", "funnel": False,
        }, execution_owner="tailscale_serve")
        return ServePreview(action_id, request, route, operation, description, already), facts

    def preview_enable(self) -> ServePreview:
        return self._prepare("tailscale.serve.enable")[0]

    def preview_disable(self) -> ServePreview:
        return self._prepare("tailscale.serve.disable")[0]

    def _gate(self, facts: TailscaleAuthorityFacts) -> ProductActionGate:
        return ProductActionGate(self.root, self.authority, owner_id="tailscale_serve",
                                 tailscale_facts=facts)

    @staticmethod
    def _receipt(gate: ProductActionGate, request: ActionRequest,
                 outcome: str, event: str) -> ActionReceipt | None:
        digest = hashlib.sha256(f"{outcome}:{event}".encode()).hexdigest()
        receipt = ActionReceipt("rcpt_" + secrets.token_hex(8), request.action_id,
                                request.digest, "ALLOW", outcome, digest)
        return receipt if gate.persist_receipt(request, receipt) else None

    def _run(self, argv: tuple[str, ...]) -> TailscaleCommandResult:
        result = self.runner(argv, env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
                             timeout=COMMAND_TIMEOUT, max_output=MAX_OUTPUT)
        if (not isinstance(result, TailscaleCommandResult)
                or len(result.stdout.encode()) + len(result.stderr.encode()) > MAX_OUTPUT):
            raise ValueError("Tailscale Serve returned invalid or oversized output")
        return result

    @staticmethod
    def _same_routes(left: tuple[ServeRoute, ...], right: tuple[ServeRoute, ...]) -> bool:
        return Counter(left) == Counter(right)

    @staticmethod
    def _unrelated_config(snapshot: TailscaleSnapshot, route: ServeRoute) -> tuple[str, str]:
        """Canonical config after removing only our exact Web path.

        This also covers TCP listeners, Tailscale Services, Funnel flags, and
        other node routes that are not represented by the simplified route list.
        """
        if not isinstance(snapshot.serve_node_config, str) or not isinstance(
                snapshot.serve_services_config, str):
            raise ValueError("complete raw Serve configuration is unavailable")
        node = json.loads(snapshot.serve_node_config)
        services = json.loads(snapshot.serve_services_config)
        if not isinstance(node, dict) or not isinstance(services, dict):
            raise ValueError("Serve configuration is malformed")
        web = node.get("Web", {})
        funnel = node.get("AllowFunnel", {})
        if not isinstance(web, dict) or not isinstance(funnel, dict):
            raise ValueError("Serve configuration cannot be safely projected")
        host_service = web.get(route.host)
        if host_service is not None:
            if not isinstance(host_service, dict):
                raise ValueError("Serve route host configuration is malformed")
            handlers = host_service.get("Handlers", {})
            if not isinstance(handlers, dict):
                raise ValueError("Serve route handlers are malformed")
            handlers.pop(route.path, None)
            if not handlers:
                web.pop(route.host, None)
        if funnel.get(route.host) is True:
            raise ValueError("the ISyCode route is configured for public Funnel access")
        funnel.pop(route.host, None)
        if not funnel:
            node.pop("AllowFunnel", None)
        if not web:
            node.pop("Web", None)
        # `serve --https=443` creates the HTTPS listener with the first web
        # handler on :443 and removes it with the last one. Project it out only
        # in exactly that shape, so any other listener change stays visible.
        tcp = node.get("TCP", {})
        if not isinstance(tcp, dict):
            raise ValueError("Serve TCP listeners cannot be safely projected")
        suffix = f":{HTTPS_PORT}"
        if (tcp.get(str(HTTPS_PORT)) == {"HTTPS": True}
                and not any(key.endswith(suffix) for key in web)):
            tcp.pop(str(HTTPS_PORT))
        if not tcp:
            node.pop("TCP", None)
        if node.get("Foreground") is False:
            node.pop("Foreground", None)
        return (json.dumps(node, sort_keys=True, separators=(",", ":")),
                json.dumps(services, sort_keys=True, separators=(",", ":")))

    def _perform(self, preview: ServePreview, approval: ActionApproval | None,
                 *, enabling: bool) -> ActionOutcome:
        expected_action = "tailscale.serve.enable" if enabling else "tailscale.serve.disable"
        if not isinstance(preview, ServePreview) or preview.action_id != expected_action:
            return ActionOutcome("Tailscale Serve action denied.", "DENY", None,
                                 "action preview has the wrong identity")
        try:
            fresh, facts = self._prepare(expected_action)
            if fresh != preview:
                return ActionOutcome("Tailscale Serve action denied.", "DENY", None,
                                     "live route or exact operation changed; create a new preview")
            gate = self._gate(facts)
            _, decision = gate.authorize(preview.request, approvals=self.approvals,
                                         approval=approval)
            if not decision.allowed:
                return ActionOutcome("Tailscale Serve action denied.", "DENY", None,
                                     "Workspace Authority, IsySentinel, approval, or journal denied")
        except (OSError, RuntimeError, TypeError, ValueError):
            return ActionOutcome("Tailscale Serve action denied.", "DENY", None,
                                 "fresh Tailscale inventory or private state is unavailable")

        # Re-check after the approval dialog and gate journal write. The CLI can
        # change the exact path only if this still matches the approved snapshot.
        try:
            current, _ = self._prepare(expected_action)
            if current != preview:
                receipt = self._receipt(gate, preview.request, "FAILURE", "serve_state_drift")
                if receipt is None:
                    return ActionOutcome("Tailscale Serve result is not verifiable.",
                                         "NOT_VERIFIABLE", None, "durable receipt unavailable")
                return ActionOutcome("Tailscale Serve state changed before execution.",
                                     "DENY", receipt, "no Serve command was issued")
        except (OSError, RuntimeError, TypeError, ValueError):
            receipt = self._receipt(gate, preview.request, "FAILURE", "pre_execution_unavailable")
            return ActionOutcome("Tailscale Serve result is not verifiable.",
                                 "NOT_VERIFIABLE", receipt, "no Serve command was issued")

        if preview.already_applied:
            if not enabling:
                try:
                    self.state_store.clear_owned_route(self.route_id)
                except (OSError, ValueError):
                    receipt = self._receipt(gate, preview.request, "FAILURE", "state_clear_failed")
                    return ActionOutcome("The stale route record could not be cleared.",
                                         "ERROR", receipt, "Serve was already disabled")
            receipt = self._receipt(gate, preview.request, "SUCCESS", "already_applied")
            if receipt is None:
                return ActionOutcome("Tailscale Serve result is not verifiable.",
                                     "NOT_VERIFIABLE", None, "durable receipt unavailable")
            return ActionOutcome("Private Tailscale route is already in the requested state.",
                                 "ALLOW", receipt, "verified idempotent operation")

        try:
            before = self.adapter.inspect()
            if not isinstance(before, TailscaleSnapshot) or before.serve_digest != facts.serve_digest:
                raise ValueError("Serve inventory changed before the command")
            try:
                self._run(preview.argv)
            except (OSError, RuntimeError, TypeError, ValueError, subprocess.TimeoutExpired):
                # A client timeout or output error does not prove the daemon
                # rejected the operation. Always inspect the live config before
                # deciding whether a route exists or ownership can be recorded.
                pass
            after = self.adapter.inspect()
            if not isinstance(after, TailscaleSnapshot):
                raise ValueError("post-operation Serve inventory is unavailable")
            target_matches = tuple(item for item in after.routes
                                   if (item.host, item.path) ==
                                   (preview.route.host, preview.route.path))
            if enabling:
                route_present = (target_matches == (preview.route,)
                                 and after.state == "signed_in"
                                 and after.serve_state == "existing")
                gateway_healthy = after.gateway_healthy is True
                expected_routes = Counter(before.routes)
                expected_routes[preview.route] += 1
                preserved = Counter(after.routes) == expected_routes
                config_preserved = (self._unrelated_config(before, preview.route)
                                    == self._unrelated_config(after, preview.route))
                if route_present:
                    owned = OwnedServeRoute(
                        self.route_id, preview.route.host, preview.route.path,
                        preview.route.target,
                        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "online" if gateway_healthy else "offline")
                    try:
                        self.state_store.record_owned_route(owned)
                    except (OSError, ValueError):
                        receipt = self._receipt(gate, preview.request, "FAILURE",
                                                "owned_route_state_write_failed")
                        return ActionOutcome(
                            "The private route is live, but ISyCode could not save its ownership record.",
                            "NOT_VERIFIABLE", receipt,
                            "the live route is shown; no automatic rollback was attempted")
                if not route_present or not gateway_healthy or not preserved or not config_preserved:
                    receipt = self._receipt(gate, preview.request, "FAILURE",
                                            "route_verification_or_preservation_failed")
                    return ActionOutcome(
                        "Tailscale Serve could not verify the exact private route and unchanged unrelated routes.",
                        "NOT_VERIFIABLE", receipt,
                        "any exact route observed is recorded only as an ownership hint")
                event = "private_route_enabled_and_verified"
            else:
                route_absent = not target_matches
                expected_routes = Counter(before.routes)
                expected_routes[preview.route] -= 1
                if expected_routes[preview.route] <= 0:
                    del expected_routes[preview.route]
                preserved = Counter(after.routes) == expected_routes
                config_preserved = (self._unrelated_config(before, preview.route)
                                    == self._unrelated_config(after, preview.route))
                if route_absent:
                    self.state_store.clear_owned_route(self.route_id)
                if not route_absent or not preserved or not config_preserved:
                    receipt = self._receipt(gate, preview.request, "FAILURE",
                                            "route_removal_or_preservation_failed")
                    return ActionOutcome(
                        "Tailscale Serve removal or preservation could not be verified.",
                        "NOT_VERIFIABLE", receipt,
                        "the live route and saved ownership are reported separately")
                event = "private_route_disabled_and_verified"
        except (OSError, RuntimeError, TypeError, ValueError, subprocess.TimeoutExpired):
            receipt = self._receipt(gate, preview.request, "FAILURE", "serve_operation_failed")
            if receipt is None:
                return ActionOutcome("Tailscale Serve result is not verifiable.",
                                     "NOT_VERIFIABLE", None, "durable receipt unavailable")
            return ActionOutcome("Tailscale Serve operation failed closed.", "ERROR", receipt,
                                 "no raw Tailscale output was retained")

        receipt = self._receipt(gate, preview.request, "SUCCESS", event)
        if receipt is None:
            return ActionOutcome("Tailscale Serve result is not verifiable.",
                                 "NOT_VERIFIABLE", None, "durable receipt unavailable")
        message = (f"Private {self.service_label} route enabled: {route_url(preview.route)}"
                   if enabling else f"ISyCode-owned private {self.service_label} route disabled.")
        return ActionOutcome(message, "ALLOW", receipt, event)

    def enable(self, preview: ServePreview,
               approval: ActionApproval | None) -> ActionOutcome:
        return self._perform(preview, approval, enabling=True)

    def disable(self, preview: ServePreview,
                approval: ActionApproval | None) -> ActionOutcome:
        return self._perform(preview, approval, enabling=False)


__all__ = ["ServePreview", "TailscaleServeOwner", "route_url", "serve_host_port"]
