"""Role and semantic navigation data owned by ISyCode."""
from __future__ import annotations


ISYCODE_AGENTS = [
    {
        "name": "Build",
        "kind": "Agent",
        "color": "#5fb3ff",
        "description": "General implementation guidance for the active ISyCode workspace.",
        "engine": "ISyCode selected provider and model",
    },
    {
        "name": "Plan",
        "kind": "Agent",
        "color": "#c792ea",
        "description": "Plan-mode guidance for the active ISyCode workspace.",
        "engine": "ISyCode selected provider and model",
    },
]

ISYCODE_SUBAGENTS = [
    {
        "name": name,
        "kind": "Specialist",
        "description": description,
        "engine": "ISyCode selected provider and model",
        "color": color,
    }
    for name, description, color in [
        ("General", "General-purpose help grounded in the active ISyCode workspace.", "#9cdcfe"),
        ("Explore", "Read-only exploration of the active ISyCode workspace; report paths and evidence.", "#b5e890"),
        ("Scout", "Fast, focused search in the active ISyCode workspace; return exact matches and locations.", "#f78c6c"),
    ]
]

# These contracts are integrated into ISyCode from the project's role catalog. Keep each engine
# (workflow), capability boundary, and CLI surface together so the UI cannot
# accidentally present a role as a generic chat prompt.
ISYCO_MOTORS = [
    {
        "name": "coder",
        "kind": "ISyCo motor",
        "color": "#4fd6a3",
        "description": "Implementation and software repair.",
        "engine": "INSPECT → PLAN → MODIFY → TEST → VERIFY → REPORT",
        "commands": ["isyco coder pre [--strict]", "isyco coder post -- <cmd>"],
        "owns": ["software.implementation", "software.bugfix", "software.refactor", "tests.product"],
    },
    {
        "name": "researcher",
        "kind": "ISyCo motor",
        "color": "#ffb86c",
        "description": "Hypotheses, experiments, and measured evidence.",
        "engine": "QUESTION → PRIOR_EVIDENCE → HYPOTHESIS → METRIC → EXPERIMENT → MEASURE → VERIFY → CONCLUDE",
        "commands": ["isyco researcher pack build ...", "isyco researcher pack verify DIR"],
        "owns": ["experiment.design", "experiment.execution", "evidence.measurement", "hypothesis.falsification"],
    },
    {
        "name": "planner",
        "kind": "ISyCo motor",
        "color": "#8fa8ff",
        "description": "Milestone plans with dependencies, risks, and a coder handoff.",
        "engine": "INTAKE → DISCOVER → CONSTRAINTS → MILESTONES → DEPENDENCIES → RISKS → WRITE_MD → VERIFY_MD → HANDOFF_CODER",
        "commands": ["isyco planner new --slug S --goal G", "isyco planner verify FILE", "isyco planner list"],
        "owns": ["planning.milestones", "planning.implementation-handoff"],
        "rule": "Only writes plans under .opencode/plans/*.md.",
    },
    {
        "name": "librarian",
        "kind": "ISyCo motor",
        "color": "#e6c07b",
        "description": "Knowledge inventory, documentation reconciliation, and provenance.",
        "engine": "FIND → READ → MAP → CROSS_CHECK → ORGANIZE → REPORT",
        "commands": ["isyco librarian check FILE"],
        "owns": ["knowledge.inventory", "documentation.provenance", "documentation.reconciliation", "claims.registry"],
    },
    {
        "name": "maintainer",
        "kind": "ISyCo motor",
        "color": "#a3b8cc",
        "description": "Platform, plugins, MCP, brokers, and daemon integration.",
        "engine": "BRIDGE_PR_INBOX → DISCOVER → CLASSIFY → CHECK → DIFF → SNAPSHOT → INTEGRATE → STARTUP_TEST → FAILURE_TEST → DOCUMENT → REPORT",
        "commands": ["isyco maintainer check", "isyco maintainer fix --yes", "isyco maintainer sticky <sub>"],
        "owns": ["isycode.platform.configuration", "isycode.platform.plugins", "isycode.platform.mcp", "isycode.platform.brokers", "isycode.platform.daemons", "isycode.roles.governance"],
        "rule": "Repair mode requires explicit --yes; run check and inspect the diff first.",
    },
    {
        "name": "devils-advocate",
        "kind": "ISyCo motor",
        "color": "#ff6ac1",
        "description": "Adversarial review, counterexamples, and risk challenges.",
        "engine": "DISCOVER → STEELMAN → ATTACK → TRACE → FALSIFY → MITIGATE → VERDICT → REPORT",
        "commands": ["isyco devils-advocate verdicts [--keyword K] [--verdict V]", "isyco devils-advocate tally"],
        "owns": ["governance.adversarial-review", "governance.counterexample-analysis", "governance.risk-challenge", "governance.precanonical-verdict"],
        "verdicts": ["PASS", "CONDITIONAL_PASS", "FAIL", "NOT_DEMONSTRATED"],
    },
    {
        "name": "historian",
        "kind": "ISyCo motor",
        "color": "#d19a66",
        "description": "Tracks staleness and records the verified project timeline.",
        "engine": "PROBE → GATHER → TRACE → CROSSCHECK → CHRONICLE → STATE → VERIFY → REGISTER",
        "commands": ["isyco historian status", "isyco historian register", "isyco historian show", "isyco historian chronicle"],
        "owns": ["history.daily-chronicle", "history.change-forensics", "history.state-registry", "history.timeline"],
        "rule": "This motor does not converse; user input runs the staleness workflow.",
    },
    {
        "name": "orchestrator",
        "kind": "ISyCo motor",
        "color": "#ffe066",
        "description": "Supervises Bridge leases, agent health, dispatch, and escalation.",
        "engine": "RECEIVE_ORDER → SNAPSHOT → READ_REGISTRY → DETECT → DECIDE → WAKE → VERIFY → ESCALATE → REPORT",
        "commands": ["isyco orchestrator watch", "isyco orchestrator sweep-leases [--apply]", "isyco orchestrator sweep-dormant [--apply]", "isyco orchestrator sweep-ghosts [--apply]", "isyco orchestrator sweep-testagents [--apply]"],
        "owns": ["coordination.lease-watch", "coordination.agent-health", "coordination.agent-wake", "coordination.task-dispatch"],
        "rule": "Sweeps are dry-run unless --apply is explicitly supplied.",
    },
]

# Shift+Tab in the composer walks this order, then back to no role (opencode's
# agent switch). Specialists stay in the Role menu: they are not primary roles.
ROLE_CYCLE = tuple(ISYCODE_AGENTS + ISYCO_MOTORS)


def role_color(name: str | None) -> str | None:
    """The identifying color of a role, or None for no role or an unknown name."""
    if not name:
        return None
    for role in ISYCODE_AGENTS + ISYCODE_SUBAGENTS + ISYCO_MOTORS:
        if role["name"] == name:
            return role.get("color")
    return None


ROLE_KERNEL = (
    "Shared role kernel: follow the Bridge coordination contract; preserve each role's "
    "scope and workflow; commit requirements apply before release. ISySentinel and "
    "Workspace Authority decide ISyCode actions; Bridge leases coordinate peers only. "
    "IsyMotron is an optional runtime adapter."
)

SEMANTIC_BRANCHES = [
    ("Skills", "Guidance available to ISyCode"),
    ("Models", "Current and available model IDs"),
    ("MCP", "Connected tool services and their status"),
    ("LSP", "Language server status"),
    ("Files", "Workspace files and directories"),
    ("Roles", "ISyCode agents and ISyCo motors"),
    ("Providers", "Provider catalog and credentials"),
    ("Session", "Session actions and current state"),
    ("Workspace", "Workspace root and navigation"),
    ("Commands", "Slash commands and keyboard shortcuts"),
]
