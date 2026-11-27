"""AppController: owns the real IsyVM backend components for the UI.

Every component is constructed exactly the way isyvm/agent_cli.py
constructs them (get_components). The controller only exposes read-only
views plus a small number of host actions; it never reimplements a
backend decision.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from core.agent import ProviderRegistry
from core.agent.providers.registry import DEFAULT_MODELS, DEFAULT_ENDPOINTS
from core.policy import PolicyEngine, RuntimeLayer
from core.runtime import RuntimeRegistry
from core.runtime.base import ToolCall, ExecutionResult
from core.secret_broker import SecretBroker
from core.resident import ResidentReader, ResidentRecorder, SelfScanner
from core.plan import PlanStore
from core.mode import ModeController
from core.todo import TodoStore
from core.provider_service import ProviderService
from core.ide_state import project_state
from core.conversations import ConversationStore
from core.tool_execution import ToolExecutionService

from bridge.isyco_reader import list_contracts, read_contract


class AppController:
    """Host-owned wiring between the UI and the IsyVM backend."""

    def __init__(self, working_dir: str | Path | None = None):
        self.working_dir = Path(working_dir or Path.cwd()).resolve()
        self.secret_broker = SecretBroker()
        self.provider_registry = ProviderRegistry(self.secret_broker)
        self.provider_service = ProviderService(self.provider_registry)
        self.policy_engine = PolicyEngine()
        self.runtime_registry = RuntimeRegistry(self.working_dir)
        self.resident_reader = ResidentReader(self.working_dir)
        self.resident_recorder = ResidentRecorder(self.working_dir)
        self.self_scanner = SelfScanner(self.working_dir)
        self.plan_store = PlanStore(self.working_dir)
        self.mode_controller = ModeController(self.working_dir)
        self.todo_store = TodoStore(self.working_dir)
        self.conversations = ConversationStore(self.working_dir)
        self.tool_execution = ToolExecutionService(self.working_dir, self.policy_engine, self.runtime_registry)
        self.tool_settings = self.tool_execution.settings
        self.proposals = self.tool_execution.proposals

    # --- workspace ---------------------------------------------------

    def set_workspace(self, path: str | Path) -> None:
        self.working_dir = Path(path).resolve()
        self.runtime_registry = RuntimeRegistry(self.working_dir)
        self.resident_reader = ResidentReader(self.working_dir)
        self.resident_recorder = ResidentRecorder(self.working_dir)
        self.self_scanner = SelfScanner(self.working_dir)
        self.plan_store = PlanStore(self.working_dir)
        self.mode_controller = ModeController(self.working_dir)
        self.todo_store = TodoStore(self.working_dir)
        self.conversations = ConversationStore(self.working_dir)
        self.tool_execution = ToolExecutionService(self.working_dir, self.policy_engine, self.runtime_registry)
        self.tool_settings = self.tool_execution.settings
        self.proposals = self.tool_execution.proposals

    # --- read-only views ---------------------------------------------

    def providers(self) -> dict:
        return self.provider_registry.list()

    def provider_types(self) -> list[str]:
        return self.provider_registry.list_provider_types()

    def default_models(self) -> dict:
        return dict(DEFAULT_MODELS)

    def default_endpoints(self) -> dict:
        return dict(DEFAULT_ENDPOINTS)

    def policy_rules(self) -> list[dict]:
        return self.policy_engine.get_rules_summary()

    def runtime_status(self) -> dict:
        return {
            layer.value: self.runtime_registry.is_available(layer)
            for layer in RuntimeLayer
        }

    def resident_status(self) -> dict:
        return self.resident_reader.status()

    def mode(self) -> str:
        return self.mode_controller.current()

    def set_mode(self, mode: str) -> str:
        return self.mode_controller.set(mode)

    def toggle_mode(self) -> str:
        return self.mode_controller.toggle()

    def plan_context(self) -> dict:
        return self.plan_store.context()

    def plans(self) -> list[str]:
        return self.plan_store.ids()

    def plan_records(self, plan_id: str | None = None) -> list[dict]:
        return self.plan_store.records(plan_id)

    def sessions(self) -> list[dict]:
        sessions_dir = project_state(self.working_dir) / "resident" / "sessions"
        if not sessions_dir.is_dir():
            return []
        out = []
        for path in sorted(sessions_dir.glob("*.jsonl")):
            out.append({
                "id": path.stem,
                "path": str(path),
                "size": path.stat().st_size,
            })
        return out

    def session_events(self, session_id: str) -> list[dict]:
        from core.resident.store import read_jsonl
        path = project_state(self.working_dir) / "resident" / "sessions" / f"{session_id}.jsonl"
        return read_jsonl(path) if path.is_file() else []

    # --- host actions (delegate to the real backend) -----------------

    def execute_tool(self, name: str, arguments: dict,
                     timeout: float = 30.0) -> ExecutionResult:
        """Explicit editor actions share policy and proposal checks with the agent.

        Agent switches affect agent calls. Saving in the editor is explicit
        human consent, and still checks policy, paths and the original hash.
        """
        tool_call = ToolCall(name=name, arguments=arguments, id=f"ui:{uuid.uuid4().hex}")
        return asyncio.run(asyncio.wait_for(self.tool_execution.execute(
            tool_call, mode=self.mode(), actor="HOST"), timeout))

    def verify_contracts(self) -> dict:
        """Run the real multi-target contract verifier and regenerate the
        evidence report (same flow as engine/bootstrap.py verify)."""
        from verifier.contract_verifier import run_all_checks, write_report
        results = run_all_checks(target_name="all")
        write_report(results)
        summary = {}
        for target, checks in results.items():
            summary[target] = {
                "passed": sum(1 for c in checks if c.result == "PASS"),
                "total": len(checks),
                "checks": [
                    {"law": c.law, "result": c.result, "detail": c.detail}
                    for c in checks
                ],
            }
        return summary

    def resident_query(self, intent: str, category: str = "general") -> dict:
        return self.resident_reader.query(intent, category=category)

    def resident_scan(self) -> dict:
        return self.self_scanner.scan()

    def bridge_contracts(self, root_subdir: str = "bridge_core/contracts") -> list[str]:
        return list_contracts(root_subdir=root_subdir)

    def bridge_read_contract(self, name: str,
                             root_subdir: str = "bridge_core/contracts") -> str:
        return read_contract(name, root_subdir=root_subdir)

    def has_key(self, provider: str) -> bool:
        return self.secret_broker.has_key(provider)

    def set_key(self, provider: str, key: str) -> str:
        return self.secret_broker.set(provider, key)

    def import_opencode_keys(self, path: str | Path | None = None) -> dict:
        return self.secret_broker.import_from_opencode(Path(path) if path else None)

    def add_provider(self, name: str, provider_type: str, model: str,
                     endpoint: str | None = None, api_key: str | None = None,
                     **kwargs) -> str:
        return self.provider_service.save(
            name, provider_type, model,
            endpoint=endpoint, api_key=api_key, **kwargs,
        )

    def remove_provider(self, name: str) -> bool:
        return self.provider_registry.remove(name)

    # --- state helpers -----------------------------------------------

    def snapshot(self) -> dict:
        """Compact host state for status panels and acceptance tooling."""
        return {
            "working_dir": str(self.working_dir),
            "mode": self.mode(),
            "providers": self.providers(),
            "runtime": self.runtime_status(),
            "policy": self.policy_rules(),
            "resident": self.resident_status(),
        }
