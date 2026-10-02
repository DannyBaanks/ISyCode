"""IsyMotron-backed planning and execution runtime used by the TUI."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Callable

from isycode.authority import grant_fingerprint, load_workspace_read_grants
from isycode.config import load_api_key, provider_default_model
from isycode.contracts import PlanOutcome
from isycode.action_runtime import ProviderNetworkOwner
from isycode.receipts import IsyMotronReceiptVerifier
from isycode.streaming import stream_complete
from isycode.workspace_authority import WorkspaceAuthority


class AuthorityContextChanged(RuntimeError):
    """The authority used to review a plan no longer matches the runtime."""


class GrantSnapshotChanged(AuthorityContextChanged):
    """The local IsyMotron grant file changed after a plan was created."""


class SecureExecutionUnavailable(RuntimeError):
    """Legacy IsyMotron execution is disabled until native ISyCode owners exist."""


class IsyMotronRuntime:
    """IsyMotron runtime with a safe demo default and optional read-only host."""

    SUBJECT = "isycode-tui"

    def __init__(self, workspace_root: Path) -> None:
        from agents.provider import Provider  # type: ignore[reportMissingImports]
        from relay.loopback import LoopbackRelay  # type: ignore[reportMissingImports]

        self._workspace_root = workspace_root.expanduser().resolve(strict=True)
        provider_name = os.environ.get("ISYMOTRON_PROVIDER", "nebius").casefold()
        self.provider = Provider(
            name=provider_name,
            model=provider_default_model(provider_name),
            api_key=load_api_key(provider_name) or None,
        )
        self.relay = LoopbackRelay()
        mode = os.environ.get("ISYCODE_RUNTIME", "demo").strip().casefold()
        self._grant_snapshot: str | None = None
        if mode == "demo":
            from hosts.simulator.engines import LegacyHost  # type: ignore[reportMissingImports]

            host = LegacyHost(
                fs={"C:/GAMES/DOOM.EXE": "MZ_BINARY",
                    "C:/GAMES/WOLF3D.EXE": "MZ_X",
                    "C:/NEMO/INBOX/.keep": ""},
                granted=["filesystem.read", "filesystem.write", "apps.launch", "system.info"],
                grant_scopes={
                    "filesystem.read": {"roots": ["C:/GAMES"]},
                    "filesystem.write": {"roots": ["C:/NEMO/INBOX"]},
                    "apps.launch": {"allowlist": ["DOOM.EXE"]},
                    "system.info": {},
                },
            )
            self.origin = "demo"
            self.host_name = "win98-retrobox (demo; simulated filesystem)"
        elif mode == "local-readonly":
            from hosts.linux.host import LinuxHost  # type: ignore[reportMissingImports]

            configured, grants = load_workspace_read_grants(workspace_root)
            self._grant_snapshot = grant_fingerprint(configured)
            read_granted = "filesystem.read" in grants.granted
            host = LinuxHost(grants)
            self.origin = "local-read-only"
            self.host_name = (
                f"{configured.display_name} (local; filesystem.read only)"
                if read_granted else
                f"{configured.display_name} (local; no capabilities granted)"
            )
        else:
            raise ValueError(
                "ISYCODE_RUNTIME must be 'demo' or 'local-readonly'.")
        self.host = host
        self.relay.attach(host)
        self.receipt_verifier = IsyMotronReceiptVerifier()

    async def plan(self, intent: str,
                   on_chunk: Callable[[str, str], None] | None = None) -> PlanOutcome:
        from agents.planner import Planner, SYSTEM as PLANNER_SYSTEM  # type: ignore[reportMissingImports]
        from agents.provider import Completion  # type: ignore[reportMissingImports]
        from isymotron.contracts import (  # type: ignore[reportMissingImports]
            CapabilityManifest, HostDescription, HostIdentity,
        )

        descriptions = []
        for host in self.relay.hosts():
            description = self.relay.describe(host["host_id"])
            identity = HostIdentity(**description["identity"])
            capabilities = [CapabilityManifest(
                id=item["id"], version=item["version"], summary=item["summary"],
                scopes=item.get("scopes", {}),
                requires_admin=item.get("requires_admin", False),
                params=tuple(item.get("params", [])),
                returns=tuple(item.get("returns", [])),
            ) for item in description["capabilities"]]
            descriptions.append(HostDescription(
                identity=identity, capabilities=capabilities,
                granted=tuple(description.get("granted", [])),
                bounds=description.get("bounds", {})))

        planner = Planner(self.provider)
        catalog = Planner.catalogue(descriptions)
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": f"CATALOGUE\n{catalog}\n\nREQUEST\n{intent}"},
        ]

        def stream() -> dict:
            return stream_complete(
                self.provider.base_url, self.provider.api_key, self.provider.model,
                messages, max_tokens=None,
                token_limit_field=self.provider.token_limit_field,
                reasoning_effort=self.provider.reasoning_effort,
                temperature_supported=self.provider.temperature_supported,
                on_chunk=on_chunk)

        owner = ProviderNetworkOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root))

        async def send():
            return await asyncio.to_thread(stream)

        result, request_outcome = await owner.execute(
            self.provider,
            {"operation": "isycode.plan", "messages": messages,
             "max_tokens": None, "token_limit_field": self.provider.token_limit_field,
             "reasoning_effort": self.provider.reasoning_effort,
             "temperature_supported": self.provider.temperature_supported},
            send)
        if request_outcome.decision != "ALLOW" or not isinstance(result, dict):
            raise SecureExecutionUnavailable(
                f"Provider planning request {request_outcome.decision.lower()}: "
                f"{request_outcome.reason[:240] or 'no verifiable response'}")
        usage = result.get("usage") or {}
        completion = Completion(
            text=result["text"], model=self.provider.model,
            provider=self.provider.name, latency_s=result["latency_s"],
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            finish_reason=result.get("finish_reason"),
            reasoning=result.get("reasoning", ""))
        plan = Planner.parse(result["text"], descriptions, raw_completion=completion)
        return PlanOutcome(
            plan=plan, model=self.provider.model,
            provider_label=self.provider.label, host_name=self.host_name,
            origin=self.origin)

    def _assert_grants_unchanged(self) -> None:
        if self._grant_snapshot is not None:
            from windows.grants import Grants  # type: ignore[reportMissingImports]

            current = grant_fingerprint(Grants.load())
            if current != self._grant_snapshot:
                raise GrantSnapshotChanged(
                    "IsyMotron grants changed after planning; review a newly generated plan.")

    def _host_description(self) -> dict:
        self._assert_grants_unchanged()
        host_id = self.host.identify().host_id
        return self.relay.describe(host_id)

    def approval_summary(self) -> dict:
        """Return the authority details that the user needs to review."""
        description = self._host_description()
        return {
            "identity": description.get("identity", {}),
            "granted": sorted(description.get("granted", [])),
            "bounds": description.get("bounds", {}),
        }

    def approval_context(self) -> str:
        """Fingerprint the host identity, catalog, grants, and effective scopes."""
        description = self._host_description()
        payload = {
            "origin": self.origin,
            "grant_snapshot": self._grant_snapshot,
            "host": description,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def execute(self, plan, *, expected_context: str):
        """Refuse legacy execution; its grants are not ISyCode authorization."""
        del plan, expected_context
        raise SecureExecutionUnavailable(
            "Plan execution is disabled in ISyCode Secure until every step is routed "
            "through Workspace Authority, ISySentinel, and a native execution owner.")


    def verify_execution(self, execution):
        """Verify every receipt against a claim bundle from its IsyMotron host."""
        results = {}
        for step in execution.steps:
            receipt = step.receipt
            claims = self.host.claim_bundle(receipt.receipt_id)
            results[step.index] = self.receipt_verifier.verify(receipt, claims)
        return results
