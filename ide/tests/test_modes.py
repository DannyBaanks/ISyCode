import asyncio

from core.agent.providers import ProviderConfig
from core.agent.providers.base import BaseProvider
from core.agent.run import Agent, AgentContext
from core.mode import CODER, PLAN, ModeController
from core.plan import PlanStore
from core.resident import SelfScanner
from core.policy import PolicyEngine
from core.runtime import RuntimeRegistry, ToolCall
from core.secret_broker import SecretBroker


class NoopProvider(BaseProvider):
    async def complete(self, messages, tools=None):
        raise AssertionError("provider is not needed for direct mode tests")

    async def stream(self, messages, tools=None):
        yield ""


def make_agent(root, mode):
    from core.agent.providers import ProviderRegistry
    registry = ProviderRegistry(SecretBroker(), config_path=root / "config.yaml")
    registry.add("mock", "openai", "model")
    provider = NoopProvider(
        ProviderConfig("mock", "openai", "model", "http://mock"), registry.secret_broker
    )
    registry.from_config = lambda config: provider
    return Agent(
        AgentContext("mock", "model", "test", str(root), mode=mode),
        registry, PolicyEngine(), RuntimeRegistry(root), registry.secret_broker, on_approval=lambda call: asyncio.sleep(0, result=True),
    )


def test_plan_mode_denies_write_and_coder_mode_allows_it(tmp_path):
    agent = make_agent(tmp_path, PLAN)
    assert {tool["function"]["name"] for tool in agent._available_tools()} == {
        "read", "glob", "grep", "project_tree", "verify", "resident_query", "resident_scan",
        "isycode_git_status", "isycode_git_diff", "isycode_git_log",
        "isycode_worktrees", "isycode_isymem_recall", "isycode_mcp_servers",
    }
    denied = asyncio.run(agent._execute_tool(ToolCall("write", {"path": "x.py", "content": "x"}, "plan-write")))
    assert not denied.success
    assert denied.error_code == "PLAN_MODE_WRITE_DENIED"
    assert not (tmp_path / "x.py").exists()

    agent.ctx.mode = CODER
    allowed = asyncio.run(agent._execute_tool(ToolCall("write", {"path": "x.py", "content": "x"}, "coder-write")))
    assert allowed.success
    assert (tmp_path / "x.py").read_text(encoding="utf-8") == "x"


def test_plan_artifact_persists_and_reloads(tmp_path):
    controller = ModeController(tmp_path)
    assert controller.set(PLAN) == PLAN
    plans = PlanStore(tmp_path)
    plan_id = plans.create("add resident guidance")
    plans.append(plan_id, "modify", path="core/agent/run.py", reason="preserve tool protocol")
    controller.set(CODER)
    plans.append(plan_id, "approval", status="approved", actor="USER")
    context = PlanStore(tmp_path).context()
    assert context["plan_id"] == plan_id
    assert {item["type"] for item in context["records"]} == {"plan", "modify", "approval"}


def test_protected_zone_requires_approved_plan_item(tmp_path):
    (tmp_path / "core" / "runtime").mkdir(parents=True)
    (tmp_path / "core" / "runtime" / "base.py").write_text("protected\n", encoding="utf-8")
    SelfScanner(tmp_path).scan()
    agent = make_agent(tmp_path, CODER)
    denied = asyncio.run(agent._execute_tool(ToolCall("write", {"path": "core/runtime/base.py", "content": "x"}, "protected")))
    assert not denied.success
    assert denied.error_code == "PROTECTED_ZONE_REQUIRES_APPROVAL"

    plans = PlanStore(tmp_path)
    plan_id = plans.create("modify protected runtime")
    plans.append(plan_id, "modify", path="core/runtime/base.py", reason="approved maintenance")
    plans.append(plan_id, "approval", status="approved", actor="USER")
    agent.ctx.plan_context = plans.context()
    allowed = asyncio.run(agent._execute_tool(ToolCall("write", {"path": "core/runtime/base.py", "content": "approved"}, "approved")))
    assert allowed.success
