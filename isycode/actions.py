"""Registry of semantic actions known to the ISyCode security boundary."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionSpec:
    id: str
    group: str
    label: str
    effect: str = "read"
    approval_required: bool = False
    description: str = ""


_ENTRIES = [
    ("workspace.files.list", "Files", "List files", "read", False),
    ("workspace.files.read", "Files", "Read file contents", "read", False),
    ("workspace.files.search", "Files", "Search file names", "read", False),
    ("workspace.context.inject", "Files", "Inject AGENTS.md context", "read", False),
    ("workspace.files.write", "Files", "Create or edit files", "write", True),
    ("workspace.files.move", "Files", "Move or rename files", "write", True),
    ("workspace.files.delete", "Files", "Delete files", "destructive", True),
    ("workspace.files.read_sensitive", "Files", "Read sensitive files", "sensitive", True),
    ("provider.request", "Network", "Send prompts to the selected model provider", "network", False),
    ("catalog.external.read", "Network", "Read an external integration catalog", "network-read", False),
    ("gateway.semantic.read", "Network", "Use ISyCo semantic analysis", "network-read", True),
    ("gateway.files.read", "Network", "Read files through ISyCo Gateway", "network-read", False),
    ("gateway.files.write", "Network", "Write files through ISyCo Gateway", "network-write", True),
    ("oauth.authorize", "Credentials", "Start a provider OAuth flow", "credential", True),
    ("credentials.add", "Credentials", "Save a named API key", "credential", True),
    ("credentials.use", "Credentials", "Use a saved API key", "credential", False),
    ("credentials.revoke", "Credentials", "Revoke a saved API key", "destructive", True),
    ("mcp.discover", "MCP", "Discover MCP servers and tools", "network-read", False),
    ("mcp.invoke", "MCP", "Invoke an MCP tool", "external", True),
    ("lsp.discover", "LSP", "Discover installed language servers", "read", False),
    ("lsp.start", "LSP", "Start a language server", "process", True),
    ("lsp.stop", "LSP", "Stop a language server", "process", False),
    ("broker.preview", "Semantic broker", "Preview a broker recipe", "read", False),
    ("broker.build", "Semantic broker", "Build a semantic broker image", "process", True),
    ("broker.start", "Semantic broker", "Start a semantic broker", "process", True),
    ("broker.health", "Semantic broker", "Read broker health and status", "read", False),
    ("broker.logs", "Semantic broker", "Read broker logs", "read", True),
    ("broker.stop", "Semantic broker", "Stop a semantic broker", "process", True),
    ("broker.remove", "Semantic broker", "Remove a broker container/image", "destructive", True),
    ("mobile.host.start", "Mobile Host", "Start the local Mobile Host", "network", True),
    ("mobile.host.stop", "Mobile Host", "Stop the local Mobile Host", "process", False),
    ("mobile.pair", "Mobile Host", "Pair a mobile device", "credential", True),
    ("mobile.session.read", "Mobile Host", "Read a remote session", "read", False),
    ("mobile.session.create", "Mobile Host", "Create a remote session", "external", True),
    ("mobile.session.cancel", "Mobile Host", "Cancel a remote turn", "external", True),
    ("mobile.approval.respond", "Mobile Host", "Respond to a remote approval", "external", True),
    ("bridge.connect", "Bridge", "Connect to the optional Bridge", "network", True),
    ("bridge.peek", "Bridge", "Read Bridge messages", "read", False),
    ("bridge.send", "Bridge", "Send a Bridge message", "external", True),
    ("bridge.lease.claim", "Bridge", "Claim a coordination lease", "coordination", True),
    ("bridge.lease.release", "Bridge", "Release a coordination lease", "coordination", False),
    ("bridge.wake", "Bridge", "Wake another registered agent", "external", True),
    ("l1.create", "L1 tools", "Create a staged L1 tool", "write", True),
    ("l1.validate", "L1 tools", "Validate a staged L1 tool", "process", True),
    ("l1.test", "L1 tools", "Run L1 tool tests and probe", "process", True),
    ("l1.activate", "L1 tools", "Activate an L1 tool", "write", True),
    ("l1.disable", "L1 tools", "Disable an L1 tool", "write", True),
    ("l1.rollback", "L1 tools", "Roll back an L1 tool generation", "write", True),
    ("session.create", "Sessions", "Create a persistent conversation", "write", False),
    ("session.resume", "Sessions", "Resume a persistent conversation", "read", False),
    ("session.delete", "Sessions", "Delete a persistent conversation", "destructive", True),
    ("clipboard.copy", "Desktop", "Copy a path or text to clipboard", "external", True),
    ("desktop.file_picker", "Desktop", "Open the native file picker", "process", True),
    ("tailscale.inspect", "Private access", "Inspect local Tailscale status", "read", False),
    ("tailscale.install.prepare", "Private access", "Prepare an isolated signed Tailscale package", "process", True),
    ("tailscale.install.stage", "Private access", "Stage verified Tailscale package as root", "process", True),
    ("tailscale.install", "Private access", "Install the official Tailscale package", "process", True),
    ("tailscale.login", "Private access", "Start Tailscale browser login", "process", True),
    ("tailscale.serve.enable", "Private access", "Enable private Gateway Serve route", "process", True),
    ("tailscale.serve.disable", "Private access", "Disable owned private Gateway Serve route", "process", True),
    ("role.select", "Roles", "Select conversational guidance", "read", False),
]

ACTION_CATALOG: tuple[ActionSpec, ...] = tuple(ActionSpec(*entry) for entry in _ENTRIES)
ACTION_BY_ID = {item.id: item for item in ACTION_CATALOG}

if len(ACTION_BY_ID) != len(ACTION_CATALOG):
    raise RuntimeError("ISyCode action registry contains duplicate identifiers.")

__all__ = ["ACTION_BY_ID", "ACTION_CATALOG", "ActionSpec"]
