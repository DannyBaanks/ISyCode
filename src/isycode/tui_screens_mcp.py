"""MCP, Gateway, LSP, and broker modals.

Moved verbatim from tui.py. isycode.tui re-exports these names.
"""
from __future__ import annotations

from typing import Any
from textual.binding import Binding
from textual.widgets import (
    Button,
    Input,
    Select,
    Static,
    TextArea,
)
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from pathlib import Path
import json
from isycode.tui_screens_approval import ApprovalScreen
from isycode.localization import tr



class MCPArgumentsScreen(ModalScreen[dict | None]):
    """Edit JSON arguments against a visible discovered tool schema."""

    CSS = """
    MCPArgumentsScreen { align: center middle; background: #000000 58%; }
    #mcp-arguments-card { width: 92; max-width: 96%; height: 85%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #mcp-arguments-title { height: 2; color: #bb8cff; text-style: bold; }
    #mcp-arguments-description { height: 3; color: #c0c0c4; }
    #mcp-arguments-schema { height: 8; border: none; background: #242529; padding: 0 1; overflow-y: auto; }
    #mcp-arguments-input { height: 1fr; margin-top: 1; }
    #mcp-arguments-error { height: 2; color: #f87171; }
    #mcp-arguments-actions { height: 3; align-horizontal: right; }
    #mcp-arguments-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, tool: dict) -> None:
        super().__init__()
        self.tool = tool

    def compose(self) -> ComposeResult:
        name = str(self.tool.get("name", "Unknown tool"))[:160]
        description = str(self.tool.get("description", "No description supplied."))[:1500]
        schema = self.tool.get("inputSchema", {})
        try:
            schema_text = json.dumps(schema, ensure_ascii=False, indent=2)[:12_000]
        except (TypeError, ValueError):
            schema_text = "Schema unavailable"
        if isinstance(schema, dict) and len(json.dumps(schema, ensure_ascii=False)) > 12_000:
            schema_text += "\n… schema display truncated …"
        with Vertical(id="mcp-arguments-card"):
            yield Static(f"Gateway MCP · {name}", id="mcp-arguments-title")
            yield Static(description, id="mcp-arguments-description")
            yield Static(tr("Discovered input schema\n") + schema_text, id="mcp-arguments-schema")
            yield TextArea("{}", id="mcp-arguments-input", soft_wrap=True)
            yield Static(tr("Enter a JSON object; arguments are not sent until the next confirmation."), id="mcp-arguments-error")
            with Horizontal(id="mcp-arguments-actions"):
                yield Button(tr("Cancel"), id="mcp-arguments-cancel")
                yield Button(tr("Review call…"), id="mcp-arguments-review", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#mcp-arguments-input", TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "mcp-arguments-review":
            self.dismiss(None)
            return
        value = self.query_one("#mcp-arguments-input", TextArea).text
        try:
            parsed = json.loads(value)
            encoded = json.dumps(parsed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if not isinstance(parsed, dict):
                raise ValueError("Arguments must be a JSON object.")
            if len(encoded) > 64 * 1024:
                raise ValueError("Arguments exceed 64 KiB.")
        except (json.JSONDecodeError, UnicodeEncodeError, ValueError) as exc:
            self.query_one("#mcp-arguments-error", Static).update(str(exc))
            return
        self.dismiss(parsed)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MCPInvocationConfirmScreen(ApprovalScreen):
    """Display the exact tool call and arguments before one-use approval."""

    CSS = """
    MCPInvocationConfirmScreen { align: center middle; background: #000000 58%; }
    #mcp-confirm-card { width: 88; max-width: 94%; height: 75%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #mcp-confirm-title { height: 2; color: #fbbf24; text-style: bold; }
    #mcp-confirm-warning { height: 3; color: #c0c0c4; }
    #mcp-confirm-payload { height: 1fr; border: none; background: #242529; padding: 1; overflow-y: auto; }
    #mcp-confirm-actions { height: 3; align-horizontal: right; }
    #mcp-confirm-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, name: str, description: str, arguments: dict, endpoint: str) -> None:
        super().__init__()
        self.tool_name = name
        self.description = description
        self.arguments = arguments
        self.endpoint = endpoint

    def compose(self) -> ComposeResult:
        payload = json.dumps(self.arguments, ensure_ascii=False, indent=2)
        with Vertical(id="mcp-confirm-card"):
            yield Static(f"Confirm Gateway MCP call · {self.tool_name}", id="mcp-confirm-title")
            yield Static(
                f"{self.description[:800]}\nEndpoint: {self.endpoint}\nThis sends the exact arguments below to the Gateway MCP. "
                "A one-use approval is required; the remote Gateway validates its own key and operation policy.",
                id="mcp-confirm-warning")
            with VerticalScroll(id="mcp-confirm-payload"):
                yield Static(payload)
            with Horizontal(id="mcp-confirm-actions"):
                yield Button(tr("Cancel · n"), id="mcp-confirm-cancel")
                yield Button(tr("Approve once and invoke · y"), id="mcp-confirm-approve", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "mcp-confirm-approve")

    def action_cancel(self) -> None:
        self.dismiss(False)


class GatewaySemanticQueryScreen(ModalScreen[tuple[str, dict] | None]):
    """Capture one operation and its typed JSON payload for Gateway HTTP."""

    CSS = """
    GatewaySemanticQueryScreen { align: center middle; background: #000000 58%; }
    #semantic-query-card { width: 92; max-width: 96%; height: 80%; max-height: 36; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #semantic-query-title { height: 2; color: #bb8cff; text-style: bold; }
    #semantic-query-copy { height: auto; margin-bottom: 1; }
    #semantic-operation { margin-bottom: 1; }
    #semantic-payload-label { height: 1; color: #b8b9c1; }
    #semantic-payload { height: 1fr; min-height: 8; margin-bottom: 1; }
    #semantic-query-error { height: 2; color: #fbbf24; }
    #semantic-query-actions { height: 3; align-horizontal: right; }
    #semantic-query-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    OPERATIONS = (
        "context", "symbols/search", "document-symbols", "definition", "references",
        "hover", "diagnostics", "semantic-slice", "implementations", "callers", "callees",
    )

    def __init__(self, endpoint: str, workspace_id: str) -> None:
        super().__init__()
        self.endpoint = endpoint
        self.workspace_id = workspace_id

    def compose(self) -> ComposeResult:
        with Vertical(id="semantic-query-card"):
            yield Static(tr("ISyCo Gateway · semantic operations"), id="semantic-query-title")
            yield Static(
                f"Endpoint: {self.endpoint}\nConfigured workspace ID: {self.workspace_id}\n"
                "The ID is an operator-managed binding, not a filesystem grant. Each request is "
                "denied if the Gateway reports a different ID.", id="semantic-query-copy")
            yield Select([(operation, operation) for operation in self.OPERATIONS],
                         value="symbols/search", id="semantic-operation")
            yield Static(tr("Operation payload · JSON (fields are validated for the selected operation)"),
                         id="semantic-payload-label")
            yield TextArea('{\n  "query": "",\n  "max_results": 25\n}',
                           language="json", id="semantic-payload")
            yield Static(tr(""), id="semantic-query-error")
            with Horizontal(id="semantic-query-actions"):
                yield Button(tr("Cancel"), id="semantic-query-cancel")
                yield Button(tr("Review request…"), id="semantic-query-review", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#semantic-operation", Select).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "semantic-query-review":
            self.dismiss(None)
            return
        operation = str(self.query_one("#semantic-operation", Select).value)
        try:
            payload = json.loads(self.query_one("#semantic-payload", TextArea).text)
            from isycode.semantic_gateway import validate_semantic_payload
            payload = validate_semantic_payload(operation, payload)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.query_one("#semantic-query-error", Static).update(f"Invalid request: {exc}")
            return
        self.dismiss((operation, payload))

    def action_cancel(self) -> None:
        self.dismiss(None)


class GatewaySemanticConfirmScreen(ApprovalScreen):
    """Show the exact native HTTP semantic request and remote-root limitation."""

    CSS = """
    GatewaySemanticConfirmScreen { align: center middle; background: #000000 58%; }
    #semantic-confirm-card { width: 88; max-width: 94%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #semantic-confirm-title { height: 2; color: #fbbf24; text-style: bold; }
    #semantic-confirm-copy { height: auto; margin-bottom: 1; }
    #semantic-confirm-actions { height: 3; align-horizontal: right; }
    #semantic-confirm-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, endpoint: str, operation: str, payload: dict, workspace_id: str) -> None:
        super().__init__()
        self.endpoint = endpoint
        self.operation = operation
        self.payload = payload
        self.workspace_id = workspace_id

    def compose(self) -> ComposeResult:
        payload = json.dumps({**self.payload, "workspace_id": self.workspace_id},
                             ensure_ascii=False, indent=2)
        with Vertical(id="semantic-confirm-card"):
            yield Static(f"Confirm native Gateway · {self.operation}", id="semantic-confirm-title")
            yield Static(
                f"POST {self.endpoint}/v1/{self.operation}\nExpected workspace ID: {self.workspace_id}\n\n"
                "Exact payload:\n" + payload +
                "\n\nThis is native HTTP, not MCP. The Gateway independently checks its "
                "isyco.semantic scope and workspace ID. The result stays in this TUI and is "
                "not added to model context. A one-use local approval is required.",
                id="semantic-confirm-copy")
            with Horizontal(id="semantic-confirm-actions"):
                yield Button(tr("Cancel · n"), id="semantic-confirm-cancel")
                yield Button(tr("Approve once and run · y"), id="semantic-confirm-approve", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "semantic-confirm-approve")

    def action_cancel(self) -> None:
        self.dismiss(False)


class LSPQueryScreen(ModalScreen[str | None]):
    """Capture a bounded workspace-symbol query for Pyright."""

    CSS = """
    LSPQueryScreen { align: center middle; background: #000000 58%; }
    #lsp-query-card { width: 78; max-width: 92%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #lsp-query-title { height: 2; color: #bb8cff; text-style: bold; }
    #lsp-query-copy { height: auto; margin-bottom: 1; }
    #lsp-query-input { height: 3; margin-bottom: 1; }
    #lsp-query-actions { height: 3; align-horizontal: right; }
    #lsp-query-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, root: Path, label: str = "Pyright") -> None:
        super().__init__()
        self.root = root
        self.label = label

    def compose(self) -> ComposeResult:
        with Vertical(id="lsp-query-card"):
            yield Static(f"{self.label} · workspace symbol search", id="lsp-query-title")
            yield Static(f"Local workspace: {self.root}\nQuery goes only to the sandboxed local language server.", id="lsp-query-copy")
            yield Input(placeholder=tr("Symbol name…"), id="lsp-query-input", max_length=256)
            with Horizontal(id="lsp-query-actions"):
                yield Button(tr("Cancel"), id="lsp-query-cancel")
                yield Button(tr("Review search…"), id="lsp-query-review", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#lsp-query-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "lsp-query-review":
            self.dismiss(None)
            return
        query = self.query_one("#lsp-query-input", Input).value.strip()
        if query:
            self.dismiss(query)

    def action_cancel(self) -> None:
        self.dismiss(None)


class LSPConfirmScreen(ApprovalScreen):
    """Confirm the exact local, sandboxed LSP operation before its one-use approval."""

    CSS = """
    LSPConfirmScreen { align: center middle; background: #000000 58%; }
    #lsp-confirm-card { width: 82; max-width: 92%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #lsp-confirm-title { height: 2; color: #fbbf24; text-style: bold; }
    #lsp-confirm-copy { height: auto; margin-bottom: 1; }
    #lsp-confirm-actions { height: 3; align-horizontal: right; }
    #lsp-confirm-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, root: Path, query: str, label: str = "Pyright") -> None:
        super().__init__()
        self.root = root
        self.query_text = query
        self.label = label

    def compose(self) -> ComposeResult:
        with Vertical(id="lsp-confirm-card"):
            yield Static(tr("Confirm local LSP search"), id="lsp-confirm-title")
            yield Static(
                f"Server: {self.label} · operation: workspace/symbol\nQuery: {self.query_text}\nWorkspace root: {self.root}\n\n"
                "ISyCode starts the approved Bubblewrap sandbox after the workspace.files.read grant is checked. "
                "The workspace is read-only; seccomp denies network access (TypeScript uses anonymous local IPC), "
                "and output/time limits apply. No Gateway or provider receives this query.",
                id="lsp-confirm-copy")
            with Horizontal(id="lsp-confirm-actions"):
                yield Button(tr("Cancel · n"), id="lsp-confirm-cancel")
                yield Button(tr("Approve once and search · y"), id="lsp-confirm-approve", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "lsp-confirm-approve")

    def action_cancel(self) -> None:
        self.dismiss(False)


class BrokerProvisionConfirmScreen(ApprovalScreen):
    """Review exact source, root, network effects, and runtime sandbox before Docker."""

    CSS = """
    BrokerProvisionConfirmScreen { align: center middle; background: #000000 58%; }
    #broker-provision-card { width: 100; max-width: 96%; height: auto; max-height: 90%; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #broker-provision-title { height: 2; color: #fbbf24; text-style: bold; }
    #broker-provision-copy { height: auto; max-height: 1fr; overflow-y: auto; margin-bottom: 1; }
    #broker-provision-actions { height: 3; align-horizontal: right; }
    #broker-provision-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, project: Path, recipe: Any, image: str) -> None:
        super().__init__()
        self.project = project
        self.recipe = recipe
        self.image = image

    def compose(self) -> ComposeResult:
        file_rows = "\n".join(f"  {name} · SHA-256 {digest}" for name, digest in self.recipe.files)
        with Vertical(id="broker-provision-card"):
            yield Static(tr("Review semantic broker build + start"), id="broker-provision-title")
            yield Static(
                f"Project root: {self.project}\nRecipe root: {self.recipe.source_root}\n"
                f"Recipe SHA-256: {self.recipe.digest}\nImage: {self.image}\nFiles:\n{file_rows}\n\n"
                "Build effect: Docker daemon builds this recipe and may download base images and Python packages. "
                "Runtime: internal-only Docker network, random 127.0.0.1 port, project mounted read-only at /workspace, "
                "read-only container filesystem, all Linux capabilities dropped, no-new-privileges, 128 PIDs, "
                "1 CPU, 2 GiB memory, bounded temporary storage, and no credentials mounted. "
                "ISyCode will grant the exact Docker executable for these two actions, bind one-use approvals to "
                "this root and recipe digest, then revoke those grants after the attempt. Failed health checks "
                "remove only the container/network created by this request.", id="broker-provision-copy")
            with Horizontal(id="broker-provision-actions"):
                yield Button(tr("Cancel · n"), id="broker-provision-cancel")
                yield Button(tr("Approve · Build + Start · y"), id="broker-provision-confirm", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "broker-provision-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class BrokerManagementScreen(ModalScreen[str | None]):
    """Choose one explicit action for a broker registered outside the project."""

    CSS = """
    BrokerManagementScreen { align: center middle; background: #000000 58%; }
    #broker-manage-card { width: 86; max-width: 92%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #broker-manage-title { height: 2; color: #c7b8d4; text-style: bold; }
    #broker-manage-copy { height: auto; margin-bottom: 1; }
    #broker-manage-actions { height: 3; align-horizontal: right; }
    #broker-manage-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, project: Path, item: dict[str, Any]) -> None:
        super().__init__()
        self.project = project
        self.item = item

    def compose(self) -> ComposeResult:
        with Vertical(id="broker-manage-card"):
            yield Static(tr("Manage semantic broker"), id="broker-manage-title")
            yield Static(
                f"Project: {self.project}\nStatus: {self.item.get('status')} · "
                f"127.0.0.1:{self.item.get('host_port')}\nContainer: {self.item.get('container')}\n"
                f"Recipe: {self.item.get('recipe_digest')}\n\n"
                "Logs are capped and common credential patterns are redacted. Stop and Remove require a second "
                "one-use confirmation. Start reuses this registered container. Remove deletes this container and "
                "its dedicated network; the shared image stays.",
                id="broker-manage-copy")
            with Horizontal(id="broker-manage-actions"):
                yield Button(tr("Close"), id="broker-manage-close")
                yield Button(tr("Health"), id="broker-manage-health")
                yield Button(tr("Logs…"), id="broker-manage-logs")
                yield Button(tr("Start…"), id="broker-manage-start", variant="primary")
                yield Button(tr("Stop…"), id="broker-manage-stop", variant="warning")
                yield Button(tr("Remove…"), id="broker-manage-remove", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        value = (event.button.id or "").removeprefix("broker-manage-")
        self.dismiss(None if value == "close" else value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BrokerOperationConfirmScreen(ApprovalScreen):
    CSS = """
    BrokerOperationConfirmScreen { align: center middle; background: #000000 58%; }
    #broker-operation-card { width: 88; max-width: 92%; height: auto; padding: 1 2; border: round #514d5a; background: #292a2e; }
    #broker-operation-title { height: 2; color: #fbbf24; text-style: bold; }
    #broker-operation-copy { height: auto; margin-bottom: 1; }
    #broker-operation-actions { height: 3; align-horizontal: right; }
    #broker-operation-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, operation: str, project: Path, container: str) -> None:
        super().__init__()
        self.operation, self.project, self.container = operation, project, container

    def compose(self) -> ComposeResult:
        with Vertical(id="broker-operation-card"):
            yield Static(f"Confirm broker {self.operation}", id="broker-operation-title")
            effect = {
                "logs": "Read up to 200 log lines. The output is redacted and capped.",
                "start": "Start this exact registered container and verify its loopback health endpoint.",
                "stop": "Stop the registered container with a 10-second grace period.",
                "remove": "Force-remove this container and its dedicated network. The shared image is retained.",
            }.get(self.operation, "Perform the selected operation.")
            yield Static(
                f"Project: {self.project}\nContainer: {self.container}\n\n{effect}\n"
                "This grants only the exact Docker executable and broker target for this single operation; "
                "the temporary grant is revoked afterward.", id="broker-operation-copy")
            with Horizontal(id="broker-operation-actions"):
                yield Button(tr("Cancel · n"), id="broker-operation-cancel")
                yield Button(tr("Approve once · y"), id="broker-operation-approve", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "broker-operation-approve")

    def action_cancel(self) -> None:
        self.dismiss(False)
