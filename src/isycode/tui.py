#!/usr/bin/env python3
"""ISyCode — local-first terminal agent with optional IsyMotron runtime.

Aesthetic inspired by Crush: banner with diagonal hatch, soft side panel,
gentle colors. But friendlier to normal users than OpenCode's hard black bar.

Chat-first: plain messages stream instantly, model reasoning streams into a
click-to-expand ThoughtBlock (collapsed to "thought for Xs" when done).
IsyMotron is an optional plugin: /plan <intent> uses its capability runtime.

Widgets and modals live in tui_theme, tui_widgets, tui_composer, and
tui_screens_*. TUIApp re-exports them so existing imports keep working.
Session, idea, queue, and harness methods live on SessionMixin in
tui_app_sessions.py. File, skill, and LSP rail methods live on
RailMixin in tui_app_rail.py. Provider, model, and key methods live
on ProviderMixin in tui_app_providers.py. Authority menu and grant
methods live on AuthorityMixin in tui_app_authority.py.
Remote access lives on RemoteMixin in tui_app_remote.py.
Workspace effects live on WorkspaceMixin in tui_app_workspace.py.
Chat tools and subagents live on ToolMixin in tui_app_tools.py.
The chat turn lives on ChatMixin in tui_app_chat.py.
The menu kind table and built-in commands live on MenuMixin in
tui_app_menu.py.
"""
from __future__ import annotations

import inspect
import sys
import os
import asyncio
from isycode.asyncio_compat import note_cancel_requested
import hashlib
import json
import shlex
import shutil
import tempfile
import uuid
import urllib.request
from pathlib import Path
from rich.cells import cell_len
from typing import Any, cast
from urllib.parse import urlparse

from isycode.config import (
    ConfigurationError, discover_workspace_identity, gateway_workspace_id,
    find_isymotron_root, isymotron_provider_available, provider_default_model,
)
from isycode.decision_view import verified_receipt_line
from isycode.authority import workspace_parent
from isycode.chat_sessions import ChatSessionStore
from isycode.session_owner import ChatSessionOwner
from isycode.work_list import SessionMessageScreen, WorkList, age_label, clock_label, fit_heading, preview_line
from isycode.bridge_presence import BridgePresenceOwner
from isycode.harness_graph import (
    CATALOG_IDS, SEED_OPTIONS, copyable_default_model, gap_status, present_by_semantic,
)
from isycode.harness_probe import probe_catalog, unlock_dotfolder
from isycode.harness_readers import read_harness_root
from isycode.harness_readers.transcript import TranscriptCopy, read_transcript, transcript_candidates
from isycode.harness_copy import copy_default_model_selection
from datetime import datetime
from isycode.credential_owner import GATEWAY_SERVICE, CredentialOwner, CredentialUseOwner
from isycode.search import TextMatch, find_text_matches
from isycode.workspace_setup import (
    WorkspaceSetupStore, broad_workspace_reason, new_workspace_choice, shared_root_warning,
)
from isycode.localization import configure_locale, tr
from isycode.user_defaults import UserDefaultsStore
from isycode.tool_history import record_tool_result, sanitize_historical_text, tool_history_context
from isycode.throughput import ThroughputMeter
from isycode.usage import UsageLedger
from isycode.shortcuts import APP_SHORTCUTS
from isycode.catalog import (
    ISYCODE_AGENTS, ISYCODE_SUBAGENTS, ISYCO_MOTORS, ROLE_KERNEL,
    SEMANTIC_BRANCHES,
)
from isycode.credentials import (
    CredentialVault, CredentialVaultError, saved_secret_exists, set_saved_secret_reader,
)
from isycode.approvals import ActionApprovalStore
from isycode.workspace_authority import (
    OneShotActionAuthority, WorkspaceAuthority, WorkspaceAuthorityError,
)
from isycode.workspace_folders import WorkspaceFolders
from isycode.folder_screens import AddWorkspaceFolderScreen, AutomaticEditsWarningScreen
from isycode.file_picker import (
    ContextFilePickerOwner, FilePickerUnavailable, SiblingFolderPickerOwner, choose_harness_folder,
)
from isycode.harness_store import HarnessStore
from isycode.harness_probe import validate_picked_root
from isycode.action_runtime import (
    CHAT_WORKSPACE_TOOLS, CONTEXT_ACCESS_TOOL, CONTEXT_ACCESS_TOOL_NAME,
    GatewayMCPInvocationOwner, GatewaySemanticOwner,
    LocalWorkspaceReadOwner, ProviderNetworkOwner, SessionDeleteOwner,
    GritPeersOwner, LPSSymbolOwner, ProductActionGate, TOOL_ACTIONS,
)
from isycode.actions import ACTION_BY_ID
from isycode.chat_transport import assistant_turn, provider_complete
from isycode.agent_loop import split_history, summary_messages, summary_system_message
from isycode.mcp_local import LocalMCPOwner, config_path as mcp_config_path, load_config as load_mcp_config
from isycode.prompt_expansion import (
    MAX_MENTIONS, WORKSPACE_COMMANDS_DIR, attach_files, find_mentions, load_user_commands,
    parse_command, read_result_text, render_command,
)
from isycode.clipboard_owner import CLIPBOARD_TARGET, ClipboardOwner
from isycode.action_audit import add_decision_listener, remove_decision_listener
from isycode.sentinel_rail import SentinelFeed
from isycode.terminal_safety import install as _install_terminal_safety

_install_terminal_safety()  # untrusted text never reaches the terminal as control codes
from isycode.agent_tasks import TASK_TOOL, TASK_TOOL_NAME, render_tasks, validate_tasks
from isycode.startup_art import MAX_SCENE_ROWS, render_landscape
from isycode.agent_questions import ASK_USER_TOOL, ASK_USER_TOOL_NAME, validate_question
from isycode.idea_box import (
    IDEA_BOX_TOOL, IDEA_BOX_TOOL_NAME, IDEA_NUDGE_PREFIX, IDEA_NUDGE_SECONDS,
    idea_nudge, validate_idea_box,
)
from isycode.workspace_write import (
    DELETE_TOOL, DELETE_TOOL_NAME, EDIT_TOOL, EDIT_TOOL_NAME, MOVE_TOOL, MOVE_TOOL_NAME,
    WRITE_TOOL, WRITE_TOOL_NAME, WorkspaceWriteOwner, WritePreview,
)
from isycode.workspace_config_owner import WorkspaceConfigOwner
from isycode.authority_view import (
    MOBILE_HOST_ADDRESS, MOBILE_PAIR_ACTIONS, MOBILE_PAIR_TARGET, displayed_on, mobile_host_enabled,
    mobile_host_saved, other_saved_grants,
)
from isycode.action_audit import ActionAuditJournal
from isycode.broker import (
    BrokerManagementOwner, BrokerPreviewOwner, BrokerProvisionOwner, BrokerRegistry,
    load_reviewed_recipe, provision_requests,
)
from isycode.security import ActionRequest
from isycode.contracts import (
    AgentRuntime,
    CatalogSnapshot,
    OpenIsyClientFactory,
    RuntimeFactory,
    WorkspaceFactory,
)

try:
    ISYMOTRON_ROOT: Path | None = find_isymotron_root()
except ConfigurationError:
    ISYMOTRON_ROOT = None
if ISYMOTRON_ROOT is not None:
    for import_root in (ISYMOTRON_ROOT, ISYMOTRON_ROOT / "core", ISYMOTRON_ROOT / "hosts"):
        import_root_text = str(import_root)
        if import_root_text not in sys.path:
            sys.path.insert(0, import_root_text)

from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.css.query import NoMatches
from textual.dom import NoScreen
from textual.events import Click
from textual.widget import Widget
from textual.widgets import (
    Static, Input, Footer, Collapsible, Button, Tree, TextArea, OptionList, Select, Checkbox,
)
from textual.widgets import Collapsible as TextualCollapsible
from textual.widgets.option_list import Option
from rich.console import Console
from rich.text import Text
from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax

try:
    from agents.planner import PlanRejected  # type: ignore[reportMissingImports]
except ModuleNotFoundError:
    class PlanRejected(RuntimeError):
        """A planner rejection raised only when an optional runtime is present."""

from isycode.providers import (
    DEFAULT_MODEL, PRESETS, PROVIDER_SCREEN, Provider, ProviderError, featured_models,
    load_provider_key,
    model_slot, provider_credential_state, resolved_chat_model, save_provider_selection,
    selected_model_name, selected_provider_name,
)
from isycode.streaming import (
    StreamError, async_stream_complete, detect_unexecuted_tool_request,
)
from isycode.plugins import PluginRegistry, Plugin, PluginCommand
from isycode.gateway_client import GatewayClient
from isycode.gateway_mcp import (
    GatewayMCPUnavailable, discover_gateway_tools, tool_schema_digest,
)
from isycode.lsp import discover_servers, language_server_catalog
from isycode.workspace import IsyMotronWorkspace, WorkspaceUnavailable
from isycode.openisy_client import OpenIsyClient
from isycode.runtime import AuthorityContextChanged, IsyMotronRuntime
from isycode.mobile_host import MobileHost, MobileHostOwner
from isycode.tailscale import (
    DEFAULT_GATEWAY_PORT, LINUX_OPERATOR_HINT, TailscaleAdapter, TailscaleSnapshot,
)
from isycode.tailscale_read import TailscaleReadOwner
from isycode.tailscale_login import TailscaleLoginOwner
from isycode.tailscale_install import TailscalePackageInstallOwner
from isycode.tailscale_serve import MOBILE_HOST_ROUTE_ID, TailscaleServeOwner, route_url
from isycode.private_access import PrivateAccessStateStore
import time as _time

# Surfaces live in sibling modules. Names stay importable from isycode.tui.
from isycode.tui_theme import (
    _authority_capability_label,
    BG,
    BG2,
    ACCENT,
    ACCENT2,
    TEXT,
    MUTED,
    GREEN,
    YELLOW,
    RED,
    CYAN,
    BANNER,
    banner_text,
    status_phrase,
    switch_row,
    switch_rows,
    _semantic_box_title,
    _fit_cells,
    _elapsed_label,
    static_content,
    plain_text,
)
from isycode.tui_widgets import (
    PreviewOptionList,
    Banner,
    ActivityStatus,
    IdleBoard,
    BoxTitle,
    ExpandableBox,
    Collapsible,
    SidePanel,
    ToolActivityGroup,
    ThoughtBlock,
    _CHILD_ANCHOR,
    QuietScrollBar,
    QuietVerticalScroll,
    ChatArea,
    SelectableText,
    CommandOutputCard,
)
from isycode.tui_composer import (
    IdeaBox,
    ShellBox,
    QueuedTitle,
    QueuedBox,
    PromptArea,
    TasksPanel,
    BarSpacer,
)
from isycode.tui_screens_approval import (
    ReviewConsentScreen,
    ApprovalScreen,
    ContextAccessScreen,
    TailscaleConfirmScreen,
    WriteApprovalScreen,
    CommandApprovalScreen,
    CommitApprovalScreen,
    LocalMCPConfirmScreen,
    DeleteSessionScreen,
)
from isycode.tui_screens_grants import (
    WorkspaceSetupScreen,
    GlobalRecurringDefaultScreen,
    QuickStartScreen,
    WorkspaceModeScreen,
    GrantWorkspaceReadScreen,
    GrantProviderNetworkScreen,
    GrantMCPInvocationScreen,
    GrantLSPProcessScreen,
    BrokerPreviewGrantScreen,
    AddCredentialScreen,
)
from isycode.tui_screens_mcp import (
    MCPArgumentsScreen,
    MCPInvocationConfirmScreen,
    GatewaySemanticQueryScreen,
    GatewaySemanticConfirmScreen,
    LSPQueryScreen,
    LSPConfirmScreen,
    BrokerProvisionConfirmScreen,
    BrokerManagementScreen,
    BrokerOperationConfirmScreen,
)
from isycode.tui_screens_harness import (
    HarnessFolderConfirmScreen,
    HarnessModelConfirmScreen,
    HarnessTranscriptConfirmScreen,
    ModelsScreen,
    HarnessComposeScreen,
    MultiHarnessScreen,
)
from isycode.tui_screens_sessions import (
    IdeaNoteScreen,
    ShellProcessesScreen,
    PastedTextScreen,
    QueuedMessagesScreen,
    IdeaBacklogScreen,
    AgentQuestionScreen,
    BridgePresenceScreen,
    ChatSessionsScreen,
    SessionSearchScreen,
    SessionTitleScreen,
    ConsoleSearchScreen,
)

from isycode.tui_app_sessions import SessionMixin
from isycode.tui_app_rail import RailMixin
from isycode.tui_app_providers import ProviderMixin
from isycode.tui_app_authority import FILE_CHANGE_GRANTS, AuthorityMixin
from isycode.tui_app_remote import RemoteMixin
from isycode.tui_app_workspace import WorkspaceMixin
from isycode.tui_app_chat import ChatMixin
from isycode.tui_app_tools import ToolMixin, _tool_display_context
from isycode.tui_app_menu import MenuMixin


class TUIApp(SessionMixin, RailMixin, ProviderMixin, AuthorityMixin, RemoteMixin, WorkspaceMixin, ToolMixin, ChatMixin, MenuMixin, App):
    """ISyCode TUI — Crush-inspired, chat-first, IsyMotron as a plugin."""

    ENABLE_COMMAND_PALETTE = False
    ALLOW_SELECT = True

    CSS_PATH = Path(__file__).with_name("isycode.tcss")

    BINDINGS = [Binding(
        item.key, item.action, item.label,
        show=not item.hidden, priority=item.priority)
        for item in APP_SHORTCUTS]

    def __init__(
        self,
        *,
        runtime_factory: RuntimeFactory = IsyMotronRuntime,
        workspace_factory: WorkspaceFactory = IsyMotronWorkspace,
        openisy_client_factory: OpenIsyClientFactory = OpenIsyClient,
        initial_view: str = "overview",
        initial_prompt: str = "",
    ):
        super().__init__()
        # Lanes exist before the per-conversation assignments below, which are properties.
        self._install_conversation_lanes()
        self._runtime_factory = runtime_factory
        self._workspace_factory = workspace_factory
        self._openisy_client_factory = openisy_client_factory
        self._initial_view = initial_view
        self._initial_prompt = initial_prompt
        self._openisy_refresh_generation = 0
        self._history: list[dict] = []
        self._last_context_input_tokens = None
        self._tool_history: list[dict] = []
        self._sentinel_feed = SentinelFeed()
        self._idea_box = ""
        self._idea_nudge_due = False
        self._idea_nudge_timer = None
        self._usage = UsageLedger()
        self._throughput = ThroughputMeter()
        self._presence_rows = None
        self._model_line = ""
        self._model_line_style = MUTED
        # Model-written notes replacing history that no longer fits the budget.
        self._conversation_summary = ""
        self._chat_turn_task: asyncio.Task | None = None
        self._pending_steering: list[str] = []
        self._queued_messages: list[str] = []
        self._selected_queued_message: str | None = None
        self._active_chat_provider: tuple[str, str] | None = None
        self._steering_try_active = False
        self._steering_restore_positions: dict[str, list[int]] = {}
        self._idea_backlog: list[str] = []
        from isycode.image_attachments import ImageAttachments
        self._shell_jobs = {}
        self._shell_mode = False
        self._command_run_lock = asyncio.Lock()
        self._image_attachments = ImageAttachments()
        self._agent_tasks: list[dict[str, str]] = []
        self._tasks_collapsed = False
        self._mcp_local: LocalMCPOwner | None = None
        self._action_approvals = ActionApprovalStore()
        self._workspace_config_values: dict[str, Any] | None = None
        self._workspace_config_warning = ""
        self._console_search_hits: list[tuple[Static, TextMatch]] = []
        self._console_search_index = -1
        self._plugins = PluginRegistry()
        self._last_plan = None
        self._last_runtime: AgentRuntime | None = None
        self._last_plan_origin = ""
        self._last_plan_host = ""
        self._last_plan_context: str | None = None
        self._armed_at: float = 0.0
        self._armed_plan_id: str | None = None
        self._armed_plan_digest: str | None = None
        self._armed_context: str | None = None
        self._loop_task: asyncio.Task | None = None
        self._chat_request_task: asyncio.Task | None = None
        self._workspace_identity = discover_workspace_identity(Path.cwd())
        self._launch_dir = self._workspace_identity.launch_dir
        self._workspace_root = self._workspace_identity.workspace_root
        self._workspace: Path | None = None
        self._workspace_setup: WorkspaceSetupStore | None = None
        self._chat_sessions: ChatSessionStore | None = None
        self._active_chat_session_id: str | None = None
        self._chat_session_owner: ChatSessionOwner | None = None
        self._session_save_warned = False
        self._temporary_chat_root: Path | None = None
        self._workspace_generation = 0
        self._file_path = ""
        self._file_browser_alias = "main"
        self._selected_file_path: str | None = None
        self._slash_matches: list[dict] = []
        self._command_names: list[str] = []
        self._subagent_running = False
        self._child_task = ""
        self._child_title = ""
        self._pending_user_sent_at: str | None = None
        self._subagent_task: asyncio.Task | None = None
        self._active_skills: list[str] = []
        self._command_entries: list[dict[str, str]] = []
        self._menu_entries: list[dict[str, str]] = []
        self._menu_filtered: list[dict[str, str]] = []
        self._menu_stack: list[tuple[str, str, list[dict[str, str]]]] = []
        self._menu_mode = ""
        self._menu_title = ""
        self._provider_key_target = ""
        self._active_role: dict[str, str] | None = self._load_global_default_role()
        self._review_used = False
        self._pending_review: tuple[str, str] | None = None
        self._review_request_task: asyncio.Task | None = None
        self._mobile_host = MobileHost()
        self._mobile_host_owner: MobileHostOwner | None = None
        self._tailscale_adapter = TailscaleAdapter(gateway_port=DEFAULT_GATEWAY_PORT)
        self._tailscale_snapshot: TailscaleSnapshot | None = None
        self._tailscale_login_owner: TailscaleLoginOwner | None = None
        self._tailscale_login_attempt: str | None = None
        # Saved Bridge opt-in is intentionally ignored until an execution owner is wired.
        self._bridge_enabled = False
        self._agent_context: dict[str, str] | None = None
        self._retry_prompt: str | None = None
        self._session_auto_edits: set[str] = set()
        self._batch_decisions: dict[str, str] = {}
        try:
            defaults = UserDefaultsStore().load()
            self._compact_marquee_default = defaults.get("compact_marquee", False)
            self._notification_sounds = defaults.get("notification_sounds", True)
            self._high_contrast = defaults.get("high_contrast", False)
            self._ascii_only = defaults.get("ascii_only", False)
            self._locale = defaults.get("locale", "es")
        except (OSError, ValueError):
            self._compact_marquee_default = False
            self._notification_sounds = True
            self._high_contrast = False
            self._ascii_only = False
            self._locale = "es"
        configure_locale(self._locale)
        from isycode.tui_theme import set_ascii_only
        set_ascii_only(self._ascii_only)
        self._provider_env_override = bool(os.environ.get("ISYCODE_PROVIDER"))
        self._model_env_override = bool(os.environ.get("ISYCODE_MODEL"))
        self._draft_text = initial_prompt
        self._draft_timer = None
        self._mcp_snapshot = CatalogSnapshot(False, [], "not_checked", "")
        self._skill_snapshot = CatalogSnapshot(False, [], "not_checked", "")
        self._provider_auth_snapshot = CatalogSnapshot(False, [], "not_checked", "")
        self._openisy_provider_snapshot = CatalogSnapshot(False, [], "not_checked", "")
        self._gateway_mcp_snapshot = CatalogSnapshot(False, [], "not_checked", "")
        try:
            self._lsp_inventory = discover_servers()
        except (OSError, RuntimeError, ValueError):
            self._lsp_inventory = []
        self._search_query = ""
        self._search_mode = False
        self._rail_view = "overview"
        self._rail_visible = False
        self._rail_auto_hidden = False
        self._rail_visibility_override: bool | None = False
        self._rail_width = 38
        self._rail_compact_width = 28
        self._work_rows: list[dict[str, Any]] = []
        self._work_refresh_lock = asyncio.Lock()
        self._work_refresh_again = False
        self._prompt_history: list[str] = []
        self._prompt_history_idx = -1
        self._prompt_history_draft = ""
        self._register_builtin_plugins()

    # ── layout ───────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Banner(id="banner")
        with Horizontal(id="workspace-layout"):
            with Vertical(id="main"):
                yield WorkList(id="work-list")
                yield ChatArea(id="chat")
                yield TasksPanel("", id="agent-tasks")
                with Vertical(id="composer"):
                    with Horizontal(id="queued-row"):
                        yield Static("", classes="queue-spacer")
                        with Vertical(id="queue-stack"):
                            yield QueuedBox(id="queued-box")
                            with Horizontal(id="queue-notice"):
                                yield Static("", id="queue-warning")
                                yield Button("[?]", id="queue-steer-help")
                        yield Static("", classes="queue-spacer")
                    with Horizontal(id="idea-box-row"):
                        yield ActivityStatus("Chat ready", id="activity-status")
                        yield IdeaBox("Idea box\nCapture an idea · Ctrl+Shift+Enter", id="idea-box", markup=False)
                        yield ShellBox("ShellBox · no processes", id="shell-box", markup=False)
                        yield Static("", id="usage-status")
                    yield OptionList(id="slash-suggestions")
                    yield PromptArea(id="prompt-input")
                    yield Static("Enter send · Ctrl+J newline · Esc back · Ctrl+P commands · Ctrl+B sidebar", id="composer-hint")
                    with Horizontal(id="command-bar"):
                        yield Button("Sidebar", id="sidebar-button")
                        yield Button("Sessions", id="sessions-button")
                        yield Button("Multi Harness", id="harness-button")
                        # Preserve dynamic labels; these actions are in Settings.
                        yield Button("Providers", id="providers-button")
                        yield Button("Role", id="role-button")
                        yield Button("Context", id="context-button")
                        yield Button("Inject context", id="inject-context-button")
                        yield Button("Model ▾", id="model-button")
                        yield BarSpacer(id="bar-spacer")
                        yield Button("⚙", id="settings-button")
            yield SidePanel(id="side-panel")
        with Vertical(id="action-menu"):
            with Vertical(id="action-card"):
                yield Static("Commands", id="action-title")
                yield Input(placeholder="Filter this list…", id="action-search")
                yield PreviewOptionList(id="action-list")
                yield Static("", id="action-detail")
                yield Static("↑↓ move · Enter open · Click preview · Double-click open · Esc back · Shift+Tab search",
                             id="action-hint")
                with Vertical(id="key-entry"):
                    yield Static("API key is stored outside this project.", id="key-entry-label")
                    yield Input(placeholder="Paste API key…", password=True, id="provider-key-input")
                    with Horizontal(id="key-entry-buttons"):
                        yield Button("Save key", id="save-provider-key", variant="primary")
                        yield Button("Cancel", id="cancel-provider-key")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        if self._high_contrast:
            self._apply_high_contrast(True)
        self._refresh_usage()
        self._set_activity("Chat ready", MUTED)
        self.set_interval(1.0, self._paint_work_status)
        add_decision_listener(self._on_journal_decision)
        self.set_interval(5.0, self._paint_sentinel)   # permissions changed in Settings
        self.run_worker(self._load_sentinel_journal(), group="sentinel-journal")
        prompt = self.query_one("#prompt-input", PromptArea)
        self.query_one("#role-button", Button).label = self._role_button_label()
        self._refresh_model_button()
        if self._initial_prompt:
            prompt.load_text(self._initial_prompt)
        prompt.focus()
        if self._initial_view == "files":
            self._set_rail_view("files")
            self.query_one("#workspace-tree", Tree).focus()
        elif self._initial_view == "providers":
            self._open_provider_menu()
        elif self._initial_view == "roles":
            self._open_role_menu()
        elif self._initial_view == "settings":
            self._open_settings_menu()
        self.query_one(Banner).set_compact(True)
        self._apply_rail_width(self.size.width)
        if self.size.width < 100 and self._rail_visibility_override is None:
            self._rail_auto_hidden = True
            self._rail_visible = False
            self.query_one(SidePanel).display = False
        self._mount_idle_board()
        self.sub_title = (f"{self._workspace_root.name}  ·  workspace {self._workspace_root}  ·  "
                          f"launch {self._launch_dir}")
        self.query_one("#workspace-label", Static).update(f"Workspace Root · {self._workspace_root}")
        self.query_one("#workspace-launch-label", Static).update(f"Launch Directory · {self._launch_dir}")
        self.query_one("#workspace-source-label", Static).update(self._root_source_label())
        self.query_one("#workspace-authority-label", Static).update(
            "Filesystem Authority · loading ISyCode grants…")
        commands = self._plugins.command_items()
        self._command_names = [name for name, _ in commands]
        self._command_entries = [
            {"label": f"/{name}  {description}", "kind": "command", "value": name}
            for name, description in commands
        ]
        # Without a read grant there is simply nothing to apply yet; printing that at
        # every start reads like an error. The reason stays available in Settings.
        if self._workspace_config_warning and "grant" not in self._workspace_config_warning:
            self._append_startup(f"  Workspace preferences · {self._workspace_config_warning[:200]}", YELLOW)
        self.run_worker(self._startup_workspace(), exclusive=True, group="workspace-startup")
        # Mobile Host and Bridge have catalog actions but no product execution owners yet.
        # A saved preference is not an Authority grant, approval, or Sentinel decision.
        self._bridge_enabled = False

    async def on_unmount(self, event) -> None:
        """Release local temporary state; unowned optional services never start in Secure."""
        del event
        remove_decision_listener(self._on_journal_decision)
        if self._draft_timer is not None:
            self._draft_timer.stop()
        self._save_draft()
        tasks = [job["task"] for job in self._shell_jobs.values() if not job["task"].done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        set_saved_secret_reader(None)
        if self._mcp_local is not None:
            await self._mcp_local.stop_all()
        if self._mobile_host_owner is not None:
            await self._mobile_host_owner.shutdown()
        if self._temporary_chat_root is not None:
            shutil.rmtree(self._temporary_chat_root, ignore_errors=True)

    async def _startup_workspace(self) -> None:
        """Offer recurrence once, then choose persistent or temporary chat storage."""
        try:
            setup_store = WorkspaceSetupStore()
            self._workspace_setup = setup_store
            recurring = self._workspace_identity.workspace_root_source == "isyroot"
            self._quick_start = False
            if not recurring:
                choice = setup_store.recurrent_choice(self._launch_dir)
                if choice is None:
                    try:
                        defaults = UserDefaultsStore().load()
                        preference = defaults.get("new_workspace", "ask")
                        mode_preference = defaults.get("new_workspace_mode", "ask")
                    except (OSError, ValueError, json.JSONDecodeError):
                        preference = mode_preference = "ask"
                    if preference == "ask" and mode_preference == "ask":
                        try:
                            provider_ready = Provider(
                                name=selected_provider_name(),
                                model=resolved_chat_model(selected_provider_name()),
                                api_key=load_provider_key(selected_provider_name()) or None,
                            ).configured()
                        except (ConfigurationError, ProviderError):
                            provider_ready = False
                        start = await self._await_screen(
                            QuickStartScreen(self._launch_dir, provider_ready=provider_ready))
                        if start == "quick":
                            choice = True
                            self._quick_start = True
                        else:
                            choice = await self._await_screen(WorkspaceSetupScreen(self._launch_dir))
                    else:
                        choice = new_workspace_choice(self._launch_dir, None, preference)
                        if choice is None:
                            choice = await self._await_screen(WorkspaceSetupScreen(self._launch_dir))
                    setup_store.choose_recurrent(self._launch_dir, choice)
                elif choice:
                    # Re-create a marker if the user removed it after opting in.
                    setup_store.choose_recurrent(self._launch_dir, True)
                recurring = choice
                if recurring:
                    self._workspace_identity = discover_workspace_identity(self._launch_dir)
                    self._workspace_root = self._workspace_identity.workspace_root
                    self._update_workspace_identity_ui()
            warning = self._shared_root_warning()
            if warning:
                self._append_startup(f"  {warning}", YELLOW)
            if self._initial_view == "files":
                self.query_one("#workspace-tree", Tree).focus()
            else:
                self.query_one("#prompt-input", PromptArea).focus()

            # Transcripts are saved only through the chat_sessions owner, only for
            # recurring workspaces, and only while the explicit session grants are
            # on. A recurrence choice alone is identity, not permission to persist.
            self._chat_sessions = None
            self._active_chat_session_id = None
            self._chat_session_owner = None
            if recurring:
                try:
                    self._chat_session_owner = ChatSessionOwner(
                        self._workspace_root, WorkspaceAuthority(self._workspace_root),
                        setup_store.sessions_root(self._workspace_root))
                except (WorkspaceAuthorityError, OSError, ValueError):
                    self._chat_session_owner = None
            try:
                authority = WorkspaceAuthority(self._workspace_root)
                if authority.mode() is None:
                    if self._quick_start:
                        chosen = "classic"
                    else:
                        try:
                            preferred = UserDefaultsStore().load().get("new_workspace_mode", "ask")
                        except (OSError, ValueError, json.JSONDecodeError):
                            preferred = "ask"
                        if preferred in {"classic", "security"}:
                            chosen = preferred
                            self._append_startup(f"  New workspace · using your default {preferred.title()} mode "
                                         "· change it in Settings → Authority.", MUTED)
                        else:
                            chosen = await self._await_screen(WorkspaceModeScreen(self._workspace_root))
                    authority.set_mode(chosen)
                await self._offer_quiet_trust(authority)
                if self._quick_start:
                    await self._enable_coding_toolkit(open_menu=False)
                    self._append_startup("  Quick Start done · type below to chat. /help tour shows the lay of the land.", GREEN)
                self.query_one(Banner).set_compact(True)
            except (WorkspaceAuthorityError, OSError, ValueError):
                self._append_startup("  Workspace mode could not be saved · Security rules apply.", YELLOW)
            self._update_workspace_identity_ui()
            self._register_saved_key_reader()
            await self._initialize_workspace()
            self._refresh_lsp_status()
            self.run_worker(self._refresh_openisy(), exclusive=False)
            self.run_worker(self._check_gateway_async(), exclusive=False)
            self.run_worker(self._check_model(), exclusive=False)
            if not recurring:
                self._append_startup("  Temporary workspace · this folder is the workspace; .isyroot is optional. "
                                     "File access follows the selected mode and grants. Chat history is not saved.", MUTED)
            if not self._sessions_enabled():
                self._append_startup(
                    "  This conversation stays in memory · turn on “Save conversations” in "
                    "Settings → Authority (recurring workspaces only).", MUTED)
        except Exception as exc:
            # The screen that was current during an awaited load may already be gone.
            # Reporting that must not raise, or Textual fails the worker.
            try:
                self._append_startup(f"  Workspace startup failed ({type(exc).__name__}).", RED)
            except (NoMatches, NoScreen):
                return

    def _register_saved_key_reader(self) -> None:
        """Security mode: every saved-key read is its own owned, journaled decision."""
        try:
            owner = CredentialUseOwner(self._workspace_root,
                                       WorkspaceAuthority(self._workspace_root))
        except (CredentialVaultError, WorkspaceAuthorityError, OSError, ValueError):
            set_saved_secret_reader(None)
            return
        set_saved_secret_reader(lambda service, consumer: owner.secret_for(service, consumer)[1])

    def _shared_root_warning(self) -> str | None:
        return shared_root_warning(self._workspace_root,
                                   self._workspace_identity.workspace_root_source,
                                   self._launch_dir)

    def _root_source_label(self) -> str:
        source = ".isyroot" if self._workspace_identity.workspace_root_source == "isyroot" else "Fallback"
        broad = " · Broad Shared Root" if self._shared_root_warning() else ""
        mode = "Classic" if self._workspace_mode() == "classic" else "Security"
        return f"Root Source · {source}{broad} · {mode} Mode"

    def _update_workspace_identity_ui(self) -> None:
        if not self.is_mounted:
            return
        self.sub_title = (f"{self._workspace_root.name}  ·  workspace {self._workspace_root}  ·  "
                          f"launch {self._launch_dir}")
        self.query_one("#workspace-label", Static).update(f"Workspace Root · {self._workspace_root}")
        self.query_one("#workspace-launch-label", Static).update(f"Launch Directory · {self._launch_dir}")
        self.query_one("#workspace-source-label", Static).update(self._root_source_label())



    def on_resize(self, event) -> None:
        if not self.is_mounted:
            return
        # The context bar is drawn to the column's width; redraw it once the new layout lands.
        self.call_after_refresh(self._refresh_usage)
        rail = self.query_one(SidePanel)
        self.query_one(Banner).set_compact(True)
        self._apply_rail_width(event.size.width)
        if event.size.width < 80:
            self._rail_auto_hidden = True
            self._rail_visible = False
            rail.display = False
        elif self._rail_visibility_override is not None:
            self._rail_visible = self._rail_visibility_override
            rail.display = self._rail_visible
        elif event.size.width < 100:
            self._rail_auto_hidden = True
            self._rail_visible = False
            rail.display = False
        else:
            if self._rail_auto_hidden:
                self._rail_auto_hidden = False
                self._rail_visible = True
            rail.display = self._rail_visible
        self.call_after_refresh(self.query_one(Banner).set_compact, True)
        self.call_after_refresh(self._update_model_button_visibility)
        self.call_after_refresh(self._paint_idle)

    async def _initialize_workspace(self) -> None:
        # .isyroot identifies the Files tree; only explicit Workspace Authority
        # grants below let the local read owner enumerate or read it.
        self._workspace = self._workspace_root
        self._file_path = str(self._workspace_root)
        try:
            grants = WorkspaceAuthority(self._workspace_root).effective_policy().get("grants", {})
            enabled = all(
                displayed_on(action, grants.get(action, {}),
                             str(self._workspace_root) in grants.get(action, {}).get("path_prefixes", []))
                for action in ("workspace.files.list", "workspace.files.read", "workspace.files.search")
            )
        except (WorkspaceAuthorityError, OSError, ValueError):
            enabled = False
        authority_text = ("Filesystem Authority · list/read/name-search granted for this workspace"
                          if enabled else
                          "Filesystem Authority · no read grant; tree enumeration is unavailable")
        self.query_one("#workspace-authority-label", Static).update(authority_text)
        await self._load_directory(self._file_path)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "review-cancel":
            request_task = self._review_request_task
            if request_task is not None and not request_task.done():
                request_task.cancel()
                event.button.disabled = True
                event.button.label = "Cancelling…"
                self._set_activity(
                    "Review cancelled · no automatic retry; inspect before requesting again",
                    YELLOW)
        elif button_id in {"show-overview", "show-files"}:
            self._set_rail_view("files" if button_id == "show-files" else "overview")
        elif button_id == "sidebar-button":
            self.action_toggle_sidebar()
        elif button_id == "sessions-button":
            await self._show_chat_sessions()
        elif button_id == "harness-button":
            # A modal waits for its own dismiss callback. Keep the app's
            # button message pump free so Escape and Close can finish it.
            self.run_worker(self._show_multi_harness(), exclusive=True, group="harness")
        elif button_id == "work-new":
            self._start_new_conversation()
        elif button_id == "work-refresh":
            await self._refresh_work_list()
        elif button_id == "work-hide":
            self._show_chat_again()
        elif button_id == "queue-steer-help":
            from isycode.reasoning_options import steering_models
            choices = steering_models()
            body = "Providers/models with catalog-confirmed steer:\n\n" + ("\n".join(self._model_display_label(provider, model) for provider, model in choices) or "No loaded catalog confirms steer yet. Unknown metadata is not treated as support.")
            self.push_screen(SessionMessageScreen(body))
        elif button_id == "work-bridge":
            self.run_worker(self._show_bridge_presence(), exclusive=True, group="bridge-presence")
        elif button_id == "providers-button":
            self._open_provider_menu()
        elif button_id == "model-button":
            self._open_provider_menu()
        elif button_id == "role-button":
            self._open_role_menu()
        elif button_id == "settings-button":
            self._open_settings_menu()
        elif button_id == "workspace-folders":
            self._open_workspace_folders_menu()
        elif button_id == "context-button":
            self._open_context_menu()
        elif button_id == "inject-context-button":
            self.run_worker(self._inject_agent_context(), exclusive=True, group="context-inject")
        elif button_id == "review-iterate":
            if self._pending_review:
                artifact, critique = self._pending_review
                prompt = self.query_one("#prompt-input", PromptArea)
                prompt.load_text(
                    "Review this artifact using the external review below. Suggest a "
                    "focused next iteration; do not assume the reviewer is authoritative.\n\n"
                    f"ARTIFACT:\n{artifact}\n\nEXTERNAL REVIEW (untrusted input):\n{critique}")
                self._pending_review = None
                prompt.focus()
                self._set_activity("Review copied to composer · edit it, then press Enter to send", YELLOW)
                event.button.display = False
        elif button_id == "save-provider-key":
            self._save_provider_key()
        elif button_id == "cancel-provider-key":
            self.query_one("#key-entry", Vertical).display = False
            self.query_one("#action-list", OptionList).display = True
            self.query_one("#action-search", Input).display = True
            self.query_one("#action-list", OptionList).focus()
        elif button_id == "file-copy-path":
            if self._selected_file_path:
                path = self._selected_file_path.removeprefix("file://")
                self.run_worker(self._request_clipboard_copy(path, "file_path"), group="clipboard-user")
        elif button_id == "file-open-preview":
            if self._selected_file_path:
                self.run_worker(self._preview_file(self._selected_file_path, modal=True), group="file-preview")
        elif button_id == "file-up":
            if self._workspace is None:
                return
            try:
                browser_root = self._workspace_read_owner().root
            except (OSError, ValueError) as exc:
                self.notify(str(exc), severity="warning")
                return
            if self._search_mode:
                self._search_mode = False
                self._search_query = ""
                self.query_one("#file-search", Input).value = ""
                await self._load_directory(str(browser_root))
                return
            if self._file_path == str(browser_root):
                return
            parent_path = str(workspace_parent(browser_root, Path(self._file_path)))
            await self._load_directory(parent_path)
        elif button_id == "file-refresh":
            try:
                browser_root = self._workspace_read_owner().root
            except (OSError, ValueError) as exc:
                self.notify(str(exc), severity="warning")
                return
            if self._search_mode and self._search_query:
                await self._search_workspace(self._search_query)
            elif self._workspace is not None:
                await self._load_directory(self._file_path or str(browser_root))
        elif button_id == "review-plan":
            self.action_run_plan()
        elif button_id == "lsp-install-hint":
            self._show_lsp_install_hints()
        elif button_id == "refresh-openisy":
            self.run_worker(self._check_gateway_mcp_async(), exclusive=False, group="gateway-mcp")
            await self._refresh_openisy()

    def action_focus_input(self) -> None:
        self.query_one("#prompt-input", PromptArea).focus()

    def action_escape_to_chat(self) -> None:
        """Cancel active model output; otherwise back out and keep the draft."""
        if self.query_one('#slash-suggestions').display:
            self.query_one('#slash-suggestions').display = False
            return
        if self.query_one("#action-menu").display:
            if self._menu_stack:
                mode, title, entries = self._menu_stack.pop()
                self._render_menu(mode, title, entries)
                self.query_one("#action-list", OptionList).focus()
                return
            self._close_menu()
            return
        if self._review_request_task and not self._review_request_task.done():
            self._review_request_task.cancel()
            self._set_activity("Stopping external review…", YELLOW)
            return
        if self._subagent_task and not self._subagent_task.done():
            self._subagent_task.cancel()
            self._set_activity("Stopping subagent…", YELLOW)
            return
        if self._chat_turn_task and not self._chat_turn_task.done():
            # Stops the whole agent turn: a pending model request, a tool, or a running command.
            note_cancel_requested(self._chat_turn_task)
            self._chat_turn_task.cancel()
            self._set_activity("Stopping response…", YELLOW)
            return
        if self._chat_request_task and not self._chat_request_task.done():
            self._chat_request_task.cancel()
            self._set_activity("Stopping response…", YELLOW)
            return
        prompt = self.query_one("#prompt-input", PromptArea)
        try:
            board = self.query_one("#work-list")
        except NoMatches:
            board = None
        if board is not None and board.display:
            self._show_chat_again()
        if self.focused is not prompt:
            prompt.focus()

    def action_toggle_commands_menu(self) -> None:
        self._update_slash_suggestions(force=True)
        self.query_one(PromptArea).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "queued-options":
            self._select_queued_message(event.option_index)
            return
        if event.option_list.id == 'slash-suggestions':
            self._complete_slash(event.option_index)
            return
        if event.option_list.id != "action-list":
            if (event.option_list.id == "work-conversations"
                    and event.option.id not in {None, "memory"}
                    and not str(event.option.id).startswith(("section-", "child"))):
                self.run_worker(self._resume_chat_session(event.option.id), group="work-resume")
            return
        if event.option_index >= len(self._menu_filtered):
            return
        self._select_menu_entry(self._menu_filtered[event.option_index])

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._track_composer_draft(event)
        if event.text_area.id == "prompt-input":
            self._update_slash_suggestions(prompt=event.text_area)

    def _update_slash_suggestions(self, *, force: bool = False, prompt: TextArea | None = None) -> None:
        # The composer lives on the base screen; a modal (or shutdown) may be on top,
        # where newer Textual's app-level query no longer finds it.
        try:
            prompt = prompt or self.query_one(PromptArea)
            panel = prompt.screen.query_one('#slash-suggestions', OptionList)
        except (NoMatches, NoScreen):
            return
        text = prompt.text
        eligible = text.startswith('/') and not any(c.isspace() for c in text)
        query = text[1:].casefold() if eligible else ''
        self._slash_matches = [entry for entry in self._command_entries
                               if entry['value'].casefold().startswith(query)] if eligible or force else []
        panel.clear_options()
        panel.add_options([Option(Text(entry['label'])) for entry in self._slash_matches])
        panel.display = bool(self._slash_matches)
        if self._slash_matches: panel.highlighted = 0

    def _move_slash(self, direction: int) -> bool:
        panel = self.query_one('#slash-suggestions', OptionList)
        if not panel.display: return False
        if direction > 0: panel.action_cursor_down()
        else: panel.action_cursor_up()
        return True

    def _complete_slash(self, index: int | None = None, *, submit_exact: bool = False) -> bool:
        panel = self.query_one('#slash-suggestions', OptionList)
        if not panel.display or not self._slash_matches:
            return False
        prompt = self.query_one(PromptArea)
        highlighted = 0 if panel.highlighted is None else panel.highlighted
        # Enter on a command that is already fully typed runs it. A prefix,
        # or a different highlighted row, only fills the name so arguments fit.
        if submit_exact and index is None and 0 <= highlighted < len(self._slash_matches):
            typed = prompt.text[1:] if prompt.text.startswith('/') else ''
            if typed.casefold() == self._slash_matches[highlighted]['value'].casefold():
                panel.display = False
                return False
        index = highlighted if index is None else index
        if index < 0 or index >= len(self._slash_matches):
            return False
        name = self._slash_matches[index]['value']
        prompt.load_text('/' + name + ' ')
        panel.display = False
        prompt.focus()
        return True

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "action-search" and self._menu_mode:
            query = event.value.casefold().strip()
            self._render_options(query)
        elif event.input.id == "provider-key-input":
            # Input uses password mode; don't reflect its value into status/UI.
            return

    # ── semantic navigation and account menus ─────────────────────

    @staticmethod
    def _entry(label: str, kind: str, value: str = "", detail: str = "") -> dict[str, str]:
        return {"label": label, "kind": kind, "value": value, "detail": detail}

    @staticmethod
    def _capability_entry(label: str, value: str, enabled: bool,
                          detail: str = "") -> dict[str, str | bool]:
        return {"label": label, "kind": "authority_toggle", "value": value,
                "detail": detail, "enabled": enabled}

    def _open_palette(self) -> None:
        entries = [self._entry(f"{name}  ·  {description}", "branch", name)
                   for name, description in SEMANTIC_BRANCHES]
        self._menu_stack = []
        self._render_menu("palette_root", "Navigate", entries)

    def _open_role_menu(self) -> None:
        entries = [
            self._entry("ISyCode agents", "role_category", "agents"),
            self._entry("ISyCode specialists", "role_category", "subagents"),
            self._entry("ISyCo CLI motors", "role_category", "motors"),
        ]
        if self._active_role:
            entries.insert(0, self._entry(
                f"Current · {self._active_role['name']} ({self._active_role['kind']})",
                "info", "", self._active_role.get("description", "")))
        self._menu_stack = []
        self._render_menu("roles_root", "Role · choose a catalog", entries)

    def _open_settings_menu(self) -> None:
        from isycode.rtk_integration import Settings as RTKSettings
        try:
            rtk_label = "on" if RTKSettings().load()["enabled"] else "off"
        except (OSError, ValueError):
            rtk_label = "needs attention"
        on = tr("on")
        off = tr("off")
        entries = [
            self._entry(tr("RTK compression · {state}", state=rtk_label), "rtk_settings", "",
                        "Compression by RTK · https://github.com/rtk-ai/rtk · permissions unchanged."),
            self._entry(tr("Providers & models"), "providers_open", ""),
            self._entry(tr("Reasoning level"), "reasoning_open", ""),
            self._entry(tr("Notification sounds · {state}",
                           state=on if self._notification_sounds else off), "sounds_toggle", "",
                        "Distinct bell rhythms for completion, approval, questions and errors; requires terminal audible bell."),
            self._entry(tr("High contrast display · {state}",
                           state=on if self._high_contrast else off), "contrast_toggle", "",
                        "Pure-black surfaces with brightened borders and controls; body text reaches at least 7:1."),
            self._entry(tr("ASCII-only display · {state}",
                           state=on if self._ascii_only else off), "ascii_toggle", "",
                        "Plain [x]/[ ]/[ON]/[OFF] marks instead of Unicode glyphs, for terminals without Unicode."),
            self._entry(tr("Language · {name}",
                           name=tr("Spanish") if self._locale == "es" else tr("English")),
                        "locale_cycle", "",
                        tr("Interface language for ISyCode. This does not change permissions or workspace files.")),
            self._entry(tr("Choose role"), "roles_open", ""),
            self._entry(tr("Context"), "context_menu", ""),
            self._entry(tr("My defaults · all workspaces"), "user_defaults", ""),
            self._entry(tr("Compact text scroll · {state}",
                           state=on if self._compact_marquee_default else off),
                        "marquee_toggle", ""),
        ]
        if self._workspace_identity.workspace_root_source == "isyroot":
            entries.extend([
                self._entry("Initialize this workspace's .isycode/", "workspace_config_init", "",
                            "Keeps non-security preferences local; file writes still need a separate review."),
                self._entry("Workspace preferences", "workspace_config_preferences", "",
                            "Overrides personal defaults for this .isyroot only; permissions are unaffected."),
                self._entry("Copy legacy workspace commands…", "workspace_config_migrate", "",
                            "Copies validated .isycode-commands/*.md files after diff approval; originals remain."),
            ])
        entries.extend([
            self._entry(tr("Authority & Security"), "authority_open", ""),
            self._entry(tr("Multi Harness · settings & repair Compose"), "harness_open", ""),
            self._entry(tr("Named API keys"), "named_credentials", ""),
            self._entry(tr("Action journal · verify / inspect"), "security_journal", ""),
            self._entry(tr("Choose context file (.md / .txt)"), "context_inject", ""),
            self._entry(tr("Commands & shortcuts"), "shortcuts", ""),
            self._entry(tr("Workspace files"), "files", ""),
            self._entry(tr("Workspace folders & automatic edits"), "folders_open", ""),
            self._entry(tr("Clear selected role"), "clear_role", ""),
            self._entry(tr("Integrations · MCP, LSP, Gateway & remote access"), "integrations_open", "",
                        "Optional connections and remote access. Permissions remain separate."),
        ])
        groups = {
            tr("Conversation"): (CYAN, {
                "providers_open": "Choose the provider and model used for this conversation.",
                "reasoning_open": "Choose supported reasoning settings for the active provider and model.",
                "roles_open": "Choose instructions for how the agent should work.",
                "clear_role": "Remove the selected role from this conversation.",
                "context_menu": "Review the context available to the agent.",
                "context_inject": "Choose a Markdown or text file to add to the conversation.",
            }),
            tr("Preferences"): ("#c7b8d4", {
                "rtk_settings": "Compression by RTK · https://github.com/rtk-ai/rtk · opt-in, permissions unchanged.",
                "user_defaults": "Personal defaults shared across your workspaces.",
                "workspace_config_init": "Create workspace preferences after reviewing the proposed files.",
                "workspace_config_preferences": "Preferences for this workspace; permissions are separate.",
                "workspace_config_migrate": "Review and copy legacy commands; preserve their originals.",
                "shortcuts": "Browse commands and keyboard shortcuts.",
                "sounds_toggle": "Distinct bell rhythms for completion, approval, questions and errors; terminal audible bell must be enabled.",
                "contrast_toggle": "Switch control surfaces to pure black with brightened borders; the palette already meets WCAG AA on black.",
                "ascii_toggle": "Replace ✓/✗/●/○ and the banner art with plain ASCII marks for terminals without Unicode.",
                "marquee_toggle": "Scroll completed text in collapsed headers. Click header text to toggle one box; the arrow opens it.",
                "locale_cycle": tr("Interface language for ISyCode. This does not change permissions or workspace files."),
            }),
            tr("Permissions"): (YELLOW, {
                "authority_open": "Inspect or change workspace permissions and approval settings.",
                "named_credentials": "Manage named API credentials and their allowed uses.",
                "security_journal": "Inspect recorded actions and verify their receipts.",
                "folders_open": "Review workspace folders and per-folder automatic edit settings.",
            }),
            tr("Connections"): (CYAN, {
                "harness_open": "Inspect other harness settings; copying requires a separate confirmation.",
                "integrations_open": "Manage MCP, LSP, Gateway and remote connections with separate permissions.",
                "files": "Browse workspace files.",
            }),
        }
        ordered = []
        for category, (color, descriptions) in groups.items():
            for entry in entries:
                if entry["kind"] in descriptions:
                    entry["category"] = category
                    entry["color"] = color
                    entry["detail"] = descriptions[entry["kind"]]
                    ordered.append(entry)
        ordered.extend(entry for entry in entries if entry not in ordered)
        self._menu_stack = []
        self._render_menu("settings", tr("Settings"), ordered)

    def _open_workspace_config_menu(self) -> None:
        if self._workspace_identity.workspace_root_source != "isyroot":
            self._render_menu("workspace_config", "Workspace preferences", [
                self._entry("This folder has no .isyroot marker; preferences are not persisted here.", "info"),
                self._entry(tr("Back to Settings"), "settings_back", ""),
            ])
            return
        try:
            parsed, issue = WorkspaceConfigOwner(
                self._workspace_root, WorkspaceAuthority(self._workspace_root),
                self._action_approvals).read_config()
        except (OSError, ValueError) as exc:
            parsed, issue = None, str(exc)
        if issue:
            entries = [self._entry(f"Workspace preferences unavailable · {issue[:140]}", "info")]
        elif parsed is None:
            entries = [self._entry("Initialize .isycode/ before saving preferences.", "info")]
        elif not parsed.valid:
            entries = [self._entry(f"Config ignored · {parsed.error[:140]}", "info")]
        else:
            entries = [self._entry(f"Config warning · {warning[:140]}", "info")
                       for warning in parsed.warnings]
            if self._active_role:
                entries.append(self._entry(
                    f"Use {self._active_role['name']} as this workspace's default role",
                    "workspace_pref_role", ""))
            if parsed.values.get("default_role"):
                entries.append(self._entry("Clear this workspace's default role",
                                           "workspace_pref_role_clear", ""))
        entries.append(self._entry(tr("Back to Settings"), "settings_back", ""))
        if self._menu_mode != "workspace_config":
            self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("workspace_config", "Settings · Workspace preferences", entries)

    async def _change_workspace_preference(self, kind: str) -> None:
        if kind == "workspace_pref_role":
            key = "default_role"
            value = {"kind": self._active_role["kind"], "name": self._active_role["name"]}
        else:
            key, value = "default_role", None
        try:
            owner = WorkspaceConfigOwner(self._workspace_root,
                                         WorkspaceAuthority(self._workspace_root),
                                         self._action_approvals)
            preview = await asyncio.to_thread(owner.preview_update, {key: value})
        except (OSError, ValueError) as exc:
            self._append(f"  Workspace preference not prepared · {str(exc)[:180]}", YELLOW)
            self._open_workspace_config_menu()
            return
        if not await self._await_screen(WriteApprovalScreen(preview)):
            self._append(f"  Preference unchanged · {preview.path}", MUTED)
            self._open_workspace_config_menu()
            return
        approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.apply, preview, approval)
        if outcome.decision == "ALLOW":
            self._workspace_config_values = None
            self._workspace_config_warning = ""
            self._active_role = self._load_global_default_role()
            self._append(f"  {outcome.text} · receipt {outcome.receipt.receipt_id}", GREEN)
        else:
            self._append(f"  Preference not saved · {outcome.reason[:160]}", YELLOW)
        self._open_workspace_config_menu()

    async def _open_workspace_migration_menu(self) -> None:
        if self._workspace_identity.workspace_root_source != "isyroot":
            self._render_menu("workspace_migration", "Workspace command migration", [
                self._entry("Migration is available only in a workspace with its own .isyroot.", "info"),
                self._entry(tr("Back to Settings"), "settings_back", ""),
            ])
            return
        try:
            owner = WorkspaceConfigOwner(self._workspace_root,
                                         WorkspaceAuthority(self._workspace_root),
                                         self._action_approvals)
            names, issue = await asyncio.to_thread(owner.legacy_commands)
        except (OSError, ValueError) as exc:
            names, issue = [], str(exc)
        entries = [self._entry(f"Migration unavailable · {issue[:140]}", "info")] if issue else []
        entries.extend(self._entry(f"Copy /{name} into .isycode/commands/",
                                   "workspace_config_migrate_item", name,
                                   "The exact file is reviewed; the legacy original stays in place.")
                       for name in names)
        if not names and not issue:
            entries.append(self._entry("No valid legacy workspace commands found.", "info"))
        entries.append(self._entry(tr("Back to Settings"), "settings_back", ""))
        if self._menu_mode != "workspace_migration":
            self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("workspace_migration", "Workspace command migration", entries)

    async def _copy_workspace_command(self, name: str) -> None:
        try:
            owner = WorkspaceConfigOwner(self._workspace_root,
                                         WorkspaceAuthority(self._workspace_root),
                                         self._action_approvals)
            preview = await asyncio.to_thread(owner.preview_migrate_legacy, name)
        except (OSError, ValueError) as exc:
            self._append(f"  Command not copied · {str(exc)[:180]}", YELLOW)
            await self._open_workspace_migration_menu()
            return
        if not await self._await_screen(WriteApprovalScreen(preview)):
            self._append(f"  Command unchanged · /{name}", MUTED)
            await self._open_workspace_migration_menu()
            return
        approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.apply, preview, approval)
        if outcome.decision == "ALLOW":
            self._append(f"  Copied /{name} · legacy original kept · receipt "
                         f"{outcome.receipt.receipt_id}", GREEN)
        else:
            self._append(f"  Command not copied · {outcome.reason[:160]}", YELLOW)
        await self._open_workspace_migration_menu()

    def _open_integrations_menu(self) -> None:
        self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("integrations", "Settings · Integrations", [
            self._entry("Tool servers · MCP & Gateway", "branch", "MCP"),
            self._entry("Language servers · LSP", "branch", "LSP"),
            self._entry("Mobile host status", "mobile_host_status", ""),
            self._entry("Bridge coordination · blocked in Secure", "bridge_settings", ""),
            self._entry("Private access · Tailscale", "private_access", ""),
            self._entry("Refresh integration catalogs", "refresh", ""),
            self._entry(tr("Back to Settings"), "settings_back", ""),
        ])

    def _folder_store(self) -> WorkspaceFolders:
        return WorkspaceFolders(self._workspace_root)

    def _open_workspace_folders_menu(self) -> None:
        entries = []
        try:
            store = self._folder_store()
            folders = [{'alias': 'main', 'path': str(self._workspace_root), 'editable': True}] + store.list()
            entries.append(self._entry("Add sibling folder…", "folder_add", ""))
            for item in folders:
                alias = item['alias']
                try:
                    store.resolve(alias)
                    available = True
                except (OSError, ValueError):
                    available = False
                entries.append(self._entry(f"{'Browse' if available else 'Unavailable'} {alias} · {item['path']}", "folder_browse" if available else "info", alias))
                if item['editable'] and available:
                    enabled = store.auto_edit_allowed(alias)
                    automatic_available = store.auto_edit_available(alias)
                    entries.append(self._entry(
                        f"{alias} · automatic edits " + ('OFF · Security requires each review' if not automatic_available
                            else 'ON — dangerous; disable' if enabled else 'OFF — enable…'),
                        'info' if not automatic_available else 'folder_auto_off' if enabled else 'folder_auto_on', alias,
                        'Only file creation/edits. Authority and ISySentinel stay active.'))
                if alias != 'main':
                    entries.append(self._entry(f"Remove attachment · {alias}", "folder_remove", alias,
                        'Files and standalone workspace settings are kept. This chat loses access.'))
        except (OSError, ValueError) as exc:
            entries.append(self._entry(f"Folder settings unavailable · {str(exc)[:140]}", "info"))
        self._menu_stack = []
        self._render_menu('workspace_folders', 'Workspace folders · explicit access', entries)

    async def _add_workspace_folder(self) -> None:
        try:
            selected_path = await SiblingFolderPickerOwner(self._workspace_root).choose()
        except (FilePickerUnavailable, OSError, ValueError) as exc:
            self._append(f"  Folder picker unavailable · {str(exc)[:160]}", YELLOW)
            self._open_workspace_folders_menu()
            return
        if selected_path is None:
            self._open_workspace_folders_menu()
            return
        selected = await self._await_screen(
            AddWorkspaceFolderScreen(self._workspace_root, selected_path))
        if selected is not None:
            try:
                self._folder_store().add(selected['alias'], selected['path'], editable=selected['editable'])
                self._append(f"  Folder added · {selected['alias']} · {selected['path']}", GREEN)
            except (OSError, ValueError, WorkspaceAuthorityError) as exc:
                self._append(f"  Folder not added · {str(exc)[:180]}", YELLOW)
        self._open_workspace_folders_menu()

    async def _set_folder_auto_edit(self, alias: str, enabled: bool) -> bool:
        try:
            store = self._folder_store()
            root = store.resolve(alias, write=enabled)
            binding = store.binding(alias)
            if enabled and not store.auto_edit_available(alias):
                raise ValueError('Security requires review of each edit')
            if enabled and not await self._await_screen(AutomaticEditsWarningScreen(root)):
                return False
            if store.resolve(alias, write=enabled) != root or store.binding(alias) != binding:
                raise ValueError('Folder changed during confirmation')
            store.set_auto_edit(alias, enabled)
        except (OSError, ValueError) as exc:
            self._append(f"  Automatic edit setting unchanged · {str(exc)[:160]}", YELLOW)
            return False
        self._append(f"  Automatic file edits · {alias} · {'ON — dangerous' if enabled else 'OFF — each edit asks'}", YELLOW if enabled else GREEN)
        return True

    async def _browse_workspace_folder(self, alias: str) -> None:
        try:
            root = self._folder_store().resolve(alias)
        except (OSError, ValueError) as exc:
            self._append(f"  Folder unavailable · {str(exc)[:160]}", YELLOW)
            return
        self._file_browser_alias = alias
        self._search_mode = False
        self._search_query = ''
        self.query_one('#file-search', Input).value = ''
        self._set_rail_view('files')
        await self._load_directory(str(root))

    def _additional_folder_access(self, *, write: bool = False) -> bool:
        try:
            store = self._folder_store()
            for item in store.list():
                if write and not item['editable']:
                    continue
                try:
                    root = store.resolve(item['alias'], write=write)
                except (OSError, ValueError):
                    continue
                enabled = self._workspace_write_tool_enabled(root) if write else self._workspace_chat_tools_enabled(root)
                if enabled:
                    return True
        except (OSError, ValueError, WorkspaceAuthorityError):
            pass
        return False

    def _open_user_defaults_menu(self) -> None:
        try:
            defaults = UserDefaultsStore().load()
        except (OSError, ValueError, json.JSONDecodeError):
            defaults = {"new_workspace": "ask", "default_role": None}
        provider_name = selected_provider_name()
        provider = PRESETS.get(provider_name, {})
        from isycode.model_presentation import model_display_name
        model_name = model_display_name(resolved_chat_model(provider_name))
        entries = [
            self._entry("These personal defaults follow you between workspaces.", "info"),
            self._entry("Access stays separate for each workspace; these defaults never turn on permissions.", "info"),
            self._entry(f"Default model · {provider.get('label', provider_name)} · {model_name}",
                        "info", "", "Change it from Providers; model selection is already saved globally."),
        ]
        role = defaults.get("default_role")
        entries.append(self._entry(
            f"Default role · {role['name']}" if role else "Default role · none",
            "info", "", "Role guidance is global preference only; it never grants permissions."))
        if self._active_role:
            entries.append(self._entry(
                f"Use current role ({self._active_role['name']}) as my default",
                "user_default_role_save", ""))
        if role:
            entries.append(self._entry("Clear my default role", "user_default_role_clear", ""))
        new_workspace = defaults.get("new_workspace", "ask")
        choices = (
            ("ask", "Ask me when I open a new folder"),
            ("temporary", "Always use temporary mode for new folders"),
            ("recurring", "Make new folders recurring by default"),
        )
        entries.extend(self._entry(
            ("● " if new_workspace == value else "○ ") + label,
            "user_default_workspace", value,
            ("A recurring workspace gets an empty .isyroot marker when first opened. "
             "This identifies the workspace; it does not grant file access. Home, its parents, "
             "temp and mount points still ask first.")
            if value == "recurring" else "Applies only when this folder has no saved choice yet.")
            for value, label in choices)
        new_mode = defaults.get("new_workspace_mode", "ask")
        mode_choices = (
            ("ask", "Ask me which mode a new folder uses"),
            ("classic", "Start new folders in Classic · Ready To Use"),
            ("security", "Start new folders in Security · everything off until I allow it"),
        )
        entries.extend(self._entry(
            ("● " if new_mode == value else "○ ") + label, "user_default_mode", value,
            "Applies only to folders opened for the first time; each workspace keeps its own "
            "mode and you can switch it in Settings → Authority.")
            for value, label in mode_choices)
        entries.append(self._entry(tr("Back to Settings"), "settings_back", ""))
        if self._menu_mode != "user_defaults":
            self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("user_defaults", "Settings · My defaults", entries)

    def _context_window(self) -> tuple[int | None, str]:
        """Window of the selected model: the account catalog first, then the
        vendored models.dev snapshot (exact id match), else unknown."""
        from isycode.model_card import catalog_entry
        from isycode.providers import model_context_limit, resolved_chat_model, selected_provider_name
        provider, model = selected_provider_name(), resolved_chat_model()
        limit, source = model_context_limit(provider, model)
        if limit:
            return limit, source
        entry = catalog_entry(provider, model)
        context = entry.get("context") if entry else None
        if type(context) is int and 0 < context <= 10**9:
            return context, "snapshot"
        return None, "unknown"

    def _request_is_quiet(self, request) -> bool:
        if request.parameters.get("rtk", {}).get("decision") == "ask":
            return False
        return super()._request_is_quiet(request)

    def _usage_status_text(self) -> str:
        from isycode.context_meter import compact_context_label
        limit, _source = self._context_window()
        reported = getattr(self, "_last_context_input_tokens", None)
        total = self._usage.input_tokens + self._usage.output_tokens
        context = compact_context_label(self._history, provider_limit_tokens=limit,
                                        reported_tokens=reported)
        # #usage-status is 20% of the composer row and three cells tall: one row
        # for the rate, one for the tokens, one for the context window. Flattening
        # the three into a single line needs a wider column, and that width has to
        # come from the idea box, which then stops matching the prompt and the
        # queued box. The percentage already rides inside the context label.
        text = self._throughput.widget_text(total, bool(self._usage.unknown_requests), context)
        from isycode.rtk_integration import savings_label
        rtk_label = savings_label(self._workspace_root)
        if "~0 tok" not in rtk_label:
            text += " · " + rtk_label
        return text

    def _refresh_usage(self) -> None:
        if not self._lane_on_screen():
            return
        from isycode.context_meter import usage_panel
        widget = self.query_one("#usage-status", Static)
        limit, source = self._context_window()
        total = self._usage.input_tokens + self._usage.output_tokens
        widget.update(usage_panel(
            self._history, widget.content_size.width or 18,
            self._throughput.rate_line(total, bool(self._usage.unknown_requests)),
            provider_limit_tokens=limit, limit_source=source,
            reported_tokens=getattr(self, "_last_context_input_tokens", None)))

    async def _complete_accounted_chat(self, provider, messages, *, max_tokens: int | None = None,
                                       on_chunk=None, tools=None) -> dict:
        # Called only by the authorized provider owner's send callback.
        # The rate is output tokens divided by this call's own clock.
        self._throughput.measuring = True
        self._refresh_usage()
        started = _time.monotonic()
        try:
            response = await provider_complete(provider, messages, max_tokens=max_tokens,
                                               on_chunk=on_chunk, tools=tools)
        except BaseException:
            self._usage.record(None)
            self._throughput.measuring = False
            self._refresh_usage()
            self._save_draft()
            raise
        elapsed = _time.monotonic() - started
        usage = response.get("usage") if isinstance(response, dict) else None
        if isinstance(usage, dict):
            input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
            if type(input_tokens) is int and 0 <= input_tokens <= 10**12:
                self._last_context_input_tokens = input_tokens
        self._usage.record(usage)
        self._throughput.note(usage, elapsed)
        self._throughput.measuring = False
        self._refresh_usage()
        self._save_draft()
        return response

    async def _set_global_mode_default(self, value: str) -> None:
        if value == "classic" and not await self._await_screen(TailscaleConfirmScreen(
                "Start new folders in Classic?",
                "Every folder you open for the first time will read files, propose edits you approve, "
                "chat with your provider and save conversations and keys without asking for each "
                "permission. IsySentinel and the action journal still check and record everything. "
                "Folders you already use keep their mode.", "Use Classic for new folders")):
            self._open_user_defaults_menu()
            return
        try:
            UserDefaultsStore().update(new_workspace_mode=value)
            self._set_activity("Default mode saved for new workspaces", GREEN)
        except (OSError, ValueError, json.JSONDecodeError):
            self._set_activity("Could not save the default mode; existing settings remain", RED)
        self._open_user_defaults_menu()

    async def _set_global_workspace_default(self, value: str) -> None:
        if value == "recurring":
            accepted = await self._await_screen(GlobalRecurringDefaultScreen())
            if not accepted:
                self._open_user_defaults_menu()
                return
        try:
            UserDefaultsStore().update(new_workspace=value)
            self._set_activity("Default saved for new workspaces", GREEN)
        except (OSError, ValueError, json.JSONDecodeError):
            self._set_activity("Could not save your global default; existing settings remain", RED)
        self._open_user_defaults_menu()

    def _load_global_default_role(self) -> dict[str, str] | None:
        try:
            defaults = UserDefaultsStore().load()
            defaults.update(self._workspace_preference_values())
            role = defaults.get("default_role")
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(role, dict):
            return None
        kind, name = role.get("kind"), role.get("name")
        catalogs = {"agents": ISYCODE_AGENTS, "subagents": ISYCODE_SUBAGENTS,
                    "motors": ISYCO_MOTORS}
        selected = next((item for item in catalogs.get(kind, ())
                         if item.get("name") == name), None)
        if selected is None:
            return None
        return {"name": name, "kind": kind,
                "description": str(selected.get("description", "")),
                "engine": str(selected.get("engine", "ISyCode selected provider and model"))}

    def _workspace_preference_values(self) -> dict[str, Any]:
        if self._workspace_config_values is not None:
            return self._workspace_config_values
        self._workspace_config_values = {}
        self._workspace_config_warning = ""
        if self._workspace_identity.workspace_root_source != "isyroot":
            return self._workspace_config_values
        try:
            owner = WorkspaceConfigOwner(self._workspace_root,
                                         WorkspaceAuthority(self._workspace_root),
                                         self._action_approvals)
            parsed, issue = owner.read_config()
            if parsed is not None and parsed.valid:
                self._workspace_config_values = dict(parsed.values)
                self._workspace_config_warning = "; ".join(parsed.warnings)
            elif parsed is not None and parsed.error:
                self._workspace_config_warning = f"ignored: {parsed.error}"
            elif issue:
                self._workspace_config_warning = f"unavailable: {issue}"
        except (OSError, ValueError):
            self._workspace_config_warning = "unavailable: settings could not be read safely"
        return self._workspace_config_values

    async def _initialize_workspace_config(self) -> None:
        if self._workspace_identity.workspace_root_source != "isyroot":
            self._append("  .isycode/ is available only in a workspace with its own .isyroot marker.",
                         YELLOW)
            return
        try:
            owner = WorkspaceConfigOwner(self._workspace_root,
                                         WorkspaceAuthority(self._workspace_root),
                                         self._action_approvals)
            plan = await asyncio.to_thread(owner.prepare_initialization)
        except (OSError, ValueError) as exc:
            self._append(f"  Workspace config unavailable · {str(exc)[:180]}", YELLOW)
            return
        if not plan.previews:
            self._append(f"  {plan.message}", YELLOW if plan.message else MUTED)
            return
        if plan.message:
            self._append(f"  {plan.message}", MUTED)
        for preview in plan.previews:
            if not await self._await_screen(WriteApprovalScreen(preview)):
                self._append(f"  Initialization stopped · {preview.path} unchanged", MUTED)
                return
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
            outcome = await asyncio.to_thread(owner.apply, preview, approval)
            if outcome.decision != "ALLOW":
                self._append(f"  Workspace setup {outcome.decision} · {outcome.reason[:180]}", YELLOW)
                return
            self._append(f"  {outcome.text} · receipt {outcome.receipt.receipt_id}", GREEN)
        self._workspace_config_values = None
        self._workspace_config_warning = ""
        self._active_role = self._load_global_default_role()






























    def _push_models_screen(self, entries: list[dict[str, str]]) -> None:
        # Entries may have been refreshed (a catalog load finished) while the
        # push was pending; open the latest ones, exactly once.
        pending = getattr(self, "_models_screen_pending", None)
        self._models_screen_pending = None
        self.push_screen(ModelsScreen(pending if pending is not None else entries,
                                      provider_scope=getattr(self, "_models_scope", None)),
                         self._model_picker_result)

    def _render_menu(self, mode: str, title: str, entries: list[dict[str, str]]) -> None:
        if mode == "branch" and title == "Models":
            # A provider-scoped picker loads that provider's catalog, not the active one.
            name = getattr(self, "_models_scope", None) or selected_provider_name()
            attempted = getattr(self, "_account_models_attempted", set())
            if name not in attempted:
                self._account_models_attempted = attempted | {name}
                self._account_models_loading = True
                self.run_worker(self._load_account_models(name), exclusive=True, group="provider-models")
        self._menu_mode = mode
        self._menu_title = title
        self._menu_entries = entries
        if (mode == "branch" and title == "Models") or mode == "model_account":
            existing = next((screen for screen in reversed(self.screen_stack)
                             if isinstance(screen, ModelsScreen)), None)
            if existing is not None:
                existing.entries = entries
                if mode == "branch" and title == "Models":
                    existing.provider_scope = getattr(self, "_models_scope", None)
                existing.choices = {}
                existing.refresh(recompose=True)
                existing.call_after_refresh(existing._reveal_current)
            elif getattr(self, "_models_screen_pending", None) is not None:
                # A push is already scheduled; a second one would stack two
                # pickers and later catalog loads would update the hidden one.
                self._models_screen_pending = entries
            else:
                self.query_one("#action-menu", Vertical).display = False
                # Defer the push out of the worker context: a click landing
                # while the screen is still mounting hits an Input with no
                # parent and crashes Textual's selection offset math.
                self._models_screen_pending = entries
                self.call_after_refresh(self._push_models_screen, entries)
            return
        card = self.query_one("#action-card", Vertical)
        if mode == "providers":
            card.add_class("provider-menu")
        else:
            card.remove_class("provider-menu")
        menu = self.query_one("#action-menu", Vertical)
        menu.display = True
        heading = Text(title, style="bold #c7b8d4")
        if mode == "settings":
            heading.append("\nConversation · Preferences · Permissions · Connections", style=MUTED)
        self.query_one("#action-title", Static).update(heading)
        search = self.query_one("#action-search", Input)
        search.display = True
        search.value = ""
        self.query_one("#action-list", OptionList).display = True
        self.query_one("#key-entry", Vertical).display = False
        self._render_options("")
        hint = ("↑↓ navigate  ·  Enter select  ·  Esc cancel  ·  type to filter"
                if mode == "providers" else
                "↑↓ move · Enter open · Click preview · Double-click open · Esc back · Shift+Tab search")
        self.query_one("#action-hint", Static).update(hint)
        self.query_one("#action-list", OptionList).focus()

    def _render_options(self, query: str) -> None:
        if query and self._menu_mode == "providers":
            filtered: list[dict[str, str]] = []
            pending = None
            used = False
            for entry in self._menu_entries:
                if entry.get("kind") == "section":
                    pending = entry
                    used = False
                    continue
                if (query in entry["label"].casefold()
                        or query in entry.get("detail", "").casefold()):
                    if pending is not None and not used:
                        filtered.append(pending)
                        used = True
                    filtered.append(entry)
            self._menu_filtered = filtered
        else:
            self._menu_filtered = [entry for entry in self._menu_entries
                                   if query in entry["label"].casefold()
                                   or query in entry.get("detail", "").casefold()]
        options = self.query_one("#action-list", OptionList)
        options.clear_options()
        for entry in self._menu_filtered:
            if entry.get("category"):
                label = Text(entry["category"].ljust(14) + "  ", style=entry["color"])
                label.append(entry["label"], style=TEXT)
            elif "enabled" in entry:
                label = _authority_capability_label(entry["label"], bool(entry["enabled"]))
            elif entry.get("kind") == "section":
                label = Text(entry["label"], style="bold #c7b8d4")
            elif entry.get("kind") == "info":
                label = Text(entry["label"], style="#8a8d96")
            elif entry.get("kind") == "provider_unwired":
                label = Text(entry["label"], style="#8a8d96")
            elif str(entry.get("label", "")).startswith("✓"):
                label = Text(entry["label"], style="bold #f0f0f2")
            else:
                label = Text(entry["label"])
            options.add_option(label)
        highlight = 0 if self._menu_filtered else None
        if self._menu_mode == "providers" and self._menu_filtered:
            highlight = next((index for index, entry in enumerate(self._menu_filtered)
                              if entry.get("kind") != "section"), 0)
        options.highlighted = highlight
        self._show_menu_detail(highlight or 0)

    def _show_menu_detail(self, index: int | None) -> None:
        """Describe the highlighted entry so choices are clear before pressing Enter."""
        entries = self._menu_filtered
        if index is None or not 0 <= index < len(entries):
            detail = ""
        else:
            entry = entries[index]
            detail = entry.get("detail") or (
                "Status only; this item does not run an action."
                if entry.get("kind") == "info"
                else "No extra summary is available. Press Enter or double-click to open."
            )
        try:
            panel = self.screen_stack[0].query_one("#action-detail", Static)
        except (NoMatches, NoScreen, IndexError):
            # A queued highlight may arrive after the menu unmounts at shutdown.
            return
        panel.display = bool(detail)
        panel.update(Text(str(detail)))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "action-list":
            self._show_menu_detail(event.option_index)

    def _close_menu(self) -> None:
        self.query_one("#action-menu", Vertical).display = False
        self.query_one("#key-entry", Vertical).display = False
        self._menu_stack = []
        self._menu_mode = ""
        self._models_scope = None
        self.query_one("#prompt-input", PromptArea).focus()


    def _branch_entries(self, branch: str) -> list[dict[str, str]]:
        key = branch.casefold()
        if key == "skills":
            from isycode.skill_catalog import skills
            entries = [self._entry("Clear selected skills", "skill_clear", "",
                                  "Skills guide the current chat; they do not add tools or authority.")]
            entries.extend(self._entry(
                f"{name}{' · active' if name in self._active_skills else ''}", "skill_use", name,
                "Superpowers · pinned MIT Markdown; select to toggle guidance for this chat")
                for name in skills())
            snapshot = self._skill_snapshot
            if snapshot.state == "ready":
                entries.extend(self._entry(f"{item['name']} · discovered", "info", "",
                    item.get("description", "")) for item in snapshot.items)
            return entries
        if key == "models":
            active_provider = selected_provider_name()
            current = selected_model_name()
            models = [self._entry(
                f"Load account models · {active_provider}", "model_list", active_provider,
                "Makes a read-only catalog request only after you select this item.")]
            from isycode.providers import recent_models
            models.extend(self._entry(f"Recent · {item['provider']} · {item['model']}  · recent",
                "model", f"{item['provider']}|{item['model']}",
                "Previously selected model; not verified against this account.")
                for item in recent_models())
            denied = getattr(self, "_account_model_denied", None)
            if denied:
                models.append(self._entry(
                    f"Grant network access to {PRESETS.get(denied, {}).get('label', denied)} "
                    "and load its real catalog",
                    "provider_catalog_grant", denied,
                    "The live catalog request was denied; this asks once, saves the host grant "
                    "for this workspace, and reloads the provider's real models."))
            for name, preset in PRESETS.items():
                model = resolved_chat_model(name)
                selected = name == active_provider and (not current or model == current)
                if name == active_provider and current:
                    model = current
                    selected = True
                models.append(self._entry(
                    f"{preset['label']}  ·  {model}{'  ◂ current' if selected else ''}  · preset",
                    "model", f"{name}|{model}",
                    "Hardcoded preset model, not verified against this account; "
                    "load the account catalog for the provider's real list."))
            live_catalogs = getattr(self, "_account_model_catalogs", {})
            for name, catalog in live_catalogs.items():
                models = [row for row in models
                          if row["kind"] not in {"model", "model_family"}
                          or row["value"].split("|", 1)[0] != name]
                models.extend(catalog)
            active_catalog = live_catalogs.get(active_provider)
            active_model = current or resolved_chat_model(active_provider)
            listed = {row["value"].split("|", 1)[1] for row in active_catalog or []
                      if row["kind"] == "model"}
            listed |= {variant["value"].split("|", 1)[1]
                       for (provider, _), variants in getattr(self, "_account_family_variants", {}).items()
                       if provider == active_provider for variant in variants}
            if active_catalog and active_model not in listed:
                # Never switch silently: the active model stays until the user picks another.
                models.insert(0, self._entry(
                    f"Current model {active_model} is not in the refreshed {PRESETS[active_provider]['label']} "
                    "catalog · still selected · choose a replacement explicitly", "info"))
            from isycode.model_catalog import catalog_models
            for name in PRESETS:
                if name in live_catalogs:
                    continue
                for entry in catalog_models(name):
                    marker = "" if entry["tool_call"] else "  ⚠ no tools"
                    models.append(self._entry(
                        f"{PRESETS[name]['label']}  ·  {entry['id']}{marker}  · catalog",
                        "model", f"{name}|{entry['id']}",
                        f"models.dev snapshot (offline; not verified against this account). "
                        f"reasoning={'yes' if entry['reasoning'] else 'no'} · "
                        f"context={entry['context'] or '?'} · tool_call={'yes' if entry['tool_call'] else 'NO — chat needs tools'}"))
            if getattr(self, "_account_models_loading", False):
                models.append(self._entry("Loading account catalog…", "info"))
            elif getattr(self, "_account_model_status", ""):
                models.append(self._entry(self._account_model_status, "info"))
            from isycode.capability_observations import observed
            unavailable = []
            visible = []
            for row in models:
                if row["kind"] == "model":
                    name, model_id = row["value"].split("|", 1)
                    if observed(name, model_id, "chat_available") is False:
                        unavailable.append(row)
                        continue
                visible.append(row)
            if unavailable:
                visible.append(self._entry(f"{len(unavailable)} unavailable in tested endpoint · retained in capability results", "info", "", "".join(row["value"] + "\n" for row in unavailable)))
            return visible
        if key == "mcp":
            snap = self._mcp_snapshot
            entries = [self._entry(
                "Gateway semantic operations · native HTTP",
                "gateway_semantic_search", "",
                "One explicit read-only symbols/search request; this does not use MCP."),
                self._entry(
                    "Semantic broker · choose folder and preview recipe",
                    "broker_preview", "",
                    "Inspects the fixed ISyCo semantic broker recipe, checks a read grant for the chosen subtree, "
                    "and shows a hashed, read-only plan. Docker is not started by this preview."),
                self._entry(
                    "Build + Start semantic broker…",
                    "broker_provision", "",
                    "Shows the exact recipe, network effects, root and sandbox; asks before Docker build/start, "
                    "then verifies health on a loopback-only port.")]
            try:
                for broker in BrokerRegistry().list_for_workspace(self._workspace_root):
                    entries.append(self._entry(
                        f"Manage broker · {Path(broker['project_root']).name} · {broker['status']}",
                        "broker_manage", broker["project_root"],
                        f"{broker['container']} · 127.0.0.1:{broker['host_port']} · "
                        f"recipe {broker['recipe_digest'][:12]}"))
            except (OSError, RuntimeError, TypeError, ValueError):
                entries.append(self._entry(
                    "Managed broker inventory unavailable", "info", "",
                    "Private state could not be read; no Docker action is available."))
            if snap.state == "ready":
                entries.extend(self._entry(
                    f"{item['name']}  ·  {item['status']}", "info", "",
                    "Listed by the connected service; discovery does not authorize calls.")
                    for item in snap.items)
            elif snap.state not in {"not_checked", "not_configured"}:
                entries.append(self._entry(
                    f"Configured services · {snap.state.replace('_', ' ')}",
                    "info", "", snap.detail))
            gateway = self._gateway_mcp_snapshot
            if gateway.state == "ready":
                entries.extend(self._entry(
                    f"ISyCo Gateway · {item['name']}", "gateway_mcp_tool", item["name"],
                    (str(item.get("description", "No description supplied."))[:1200]
                     + " · Enter to review arguments and request a one-use approval"))
                    for item in gateway.items)
            elif gateway.state not in {"not_checked", "not_configured"}:
                entries.append(self._entry(
                    f"ISyCo Gateway MCP · {gateway.state.replace('_', ' ')}",
                    "info", "", gateway.detail))
            from isycode.mcp_presets import PRESETS as MCP_PRESETS
            entries.extend(self._entry(f"Add {name} preset", "mcp_preset", name, preset["description"])
                           for name, preset in MCP_PRESETS.items())
            return entries
        if key == "lsp":
            entries = []
            for server in self._lsp_inventory:
                if server["state"] == "sandbox_ready":
                    entries.append(self._entry(
                        f"{server['label']} · {status_phrase('workspace symbol search')}", "lsp_server", server["id"],
                        "Real LSP initialize + workspace/symbol, read-only .isyroot mount, no network; each request needs a grant and one-use approval."))
                else:
                    entries.append(self._entry(
                        f"{server['label']} · {status_phrase(server['state'].replace('_', ' '))}", "info", "",
                        "Detected executable only; no safe LSP execution adapter is connected for this server."))
            return entries or [self._entry("No LSP servers detected", "info", "", "Install or configure a supported language server.")]
        if key == "files":
            return [self._entry("Open workspace file browser", "files"),
                    self._entry(f"Current Directory · {self._file_path or self._workspace_root}", "info")]
        if key == "roles":
            return [self._entry("ISyCode agents", "role_category", "agents"),
                    self._entry("ISyCode specialists", "role_category", "subagents"),
                    self._entry("ISyCo CLI motors", "role_category", "motors")]
        if key == "providers":
            return [self._entry("Open provider selector", "providers_open"),
                    self._entry("OAuth methods", "oauth_info", "Provider accounts", self._provider_auth_snapshot.detail or self._provider_auth_snapshot.state)]
        if key == "session":
            return [self._entry("/help", "command", "help"),
                    self._entry(f"Provider · {selected_provider_name()}", "providers_open"),
                    self._entry(f"Role · {self._role_button_label()}", "info")]
        if key == "workspace":
            return [self._entry(f"Workspace Root · {self._workspace_root}", "info"),
                    self._entry(f"Launch Directory · {self._launch_dir}", "info"),
                    self._entry(f"Root Source · {self._workspace_identity.workspace_root_source}", "info"),
                    self._entry(f"Gateway Binding · {gateway_workspace_id(self._workspace_root)}", "info", "",
                                "Opaque workspace match label; it does not grant access."),
                    self._entry(f"Current Folder · {self._file_path or self._workspace_root}", "info"),
                    self._entry("Open Files view", "files")]
        if key == "commands":
            return self._command_entries + [self._entry("Keyboard shortcuts", "shortcuts")]
        return []

    # ── helpers ──────────────────────────────────────────────────

    def _append_startup(self, text: str, color: str = TEXT) -> None:
        """Keep startup notices beneath the welcome art without archiving it."""
        self._append(text, color, startup=True)

    def _append(self, text: str, color: str = TEXT, *, startup: bool = False) -> None:
        """Append output, releasing the welcome pause only on the first message."""
        lane = self._active_lane()
        on_screen = self._lane_on_screen()
        if not startup and on_screen:
            self._dismiss_idle()
        context = _tool_display_context.get()
        if context is not None and context[0] is self:
            _, body, notes = context
            if on_screen and getattr(body, "is_mounted", False):
                if notes.plain:
                    notes.append("\n")
                notes.append(text, style=color)
                body.set_selectable_content(notes.copy(), notes.plain)
                return
            if not startup:
                lane.lines.append(("note", text, color))
            return
        if not startup:
            lane.lines.append(("note", text, color))
        if not on_screen:
            return
        chat = self.query_one(ChatArea)
        chat.mount(SelectableText(Text(text, style=color), selection_text=text))
        chat.follow_tail()

    def _mount_user_turn(self, text: str, sent_at: str | None = None) -> None:
        """Paint one user message as a rounded card and leave the idle board."""
        self._active_lane().lines.append(("user", text, sent_at))
        if not self._lane_on_screen():
            return
        self._dismiss_idle()
        chat = self.query_one(ChatArea)
        if clock_label(sent_at):
            chat.mount(Static(Text(clock_label(sent_at), style=MUTED), classes="message-clock"))
        chat.mount(SelectableText(Text(text, style=TEXT), selection_text=text, classes="user-turn"))
        chat.follow_tail()

    def _idle_mounted(self) -> bool:
        try:
            board = self.query_one("#idle-board", IdleBoard)
        except Exception:
            return False
        return bool(board.is_mounted and board.display and not board.has_class("startup-archived"))

    def _mount_idle_board(self) -> None:
        chat = self.query_one(ChatArea)
        if any(getattr(child, "id", None) == "idle-board" for child in chat.children):
            self._paint_idle()
            return
        chat.mount(IdleBoard(id="idle-board"))
        self._paint_idle()
        # The splash starts at the top, then scrolls away with chat history.
        chat.pause_tail()
        self.call_after_refresh(self._paint_idle)
        self.call_after_refresh(chat.scroll_home, animate=False, immediate=True)

    def _dismiss_idle(self) -> None:
        try:
            board = self.query_one("#idle-board", IdleBoard)
        except Exception:
            return
        if board.is_mounted and not board.has_class("startup-archived"):
            board.add_class("startup-archived")
            self.query_one(ChatArea).resume_tail()

    def _paint_idle(self) -> None:
        if not self.is_mounted:
            return
        try:
            board = self.query_one("#idle-board", IdleBoard)
        except Exception:
            return
        if not board.is_mounted or board.has_class("startup-archived"):
            return
        width = board.content_size.width or self._idle_content_width()
        rows = self._landscape_row_budget()
        board._painted_width = width
        board._painted_rows = rows
        board.update(self._idle_board_text(width, rows))

    def _idle_content_width(self) -> int:
        chat_width = self.query_one(ChatArea).content_size.width
        if chat_width > 4:
            # IdleBoard's own padding consumes two cells on each side of
            # the chat's measured content width.
            return max(24, chat_width - 4)
        rail = self.query_one(SidePanel)
        rail_width = rail.region.width if rail.display else 0
        return max(24, self.size.width - rail_width - 8)

    def _idle_status_rows(self) -> int:
        """Model line, the blank under it, the status columns, and board padding."""
        columns = [
            self._idle_column("LSPs", self._idle_lsp_rows()),
            self._idle_column("MCPs", self._idle_mcp_rows()),
            self._idle_column("Skills", self._idle_skill_rows()),
        ]
        return 2 + max(len(column) for column in columns) + 1

    def _landscape_row_budget(self) -> int:
        """Panorama rows that still leave the model line and status columns visible."""
        chat_h = self.query_one(ChatArea).content_size.height
        if chat_h <= 0:
            return 16
        return max(1, min(MAX_SCENE_ROWS, chat_h - self._idle_status_rows()))

    def _idle_board_text(self, measured_width: int | None = None, max_rows: int | None = None) -> Text:
        """Cell-accurate landscape, model, and integration columns."""
        width = measured_width or self._idle_content_width()
        body = Text()
        body.append(render_landscape(width, max_rows))
        body.append("\n")
        checking = not self._model_line
        model = self._model_line or "Checking the configured model"
        body.append("◇ ", style=MUTED if checking else ACCENT)
        body.append(_fit_cells(model, max(8, width - 2)) + "\n\n", style=self._model_line_style)
        columns = [
            self._idle_column("LSPs", self._idle_lsp_rows()),
            self._idle_column("MCPs", self._idle_mcp_rows()),
            self._idle_column("Skills", self._idle_skill_rows()),
        ]
        gap = 2
        budgets = [max(cell_len(line.plain) for line in column) for column in columns]
        room = width - gap * (len(columns) - 1)
        if sum(budgets) > room:
            share = max(8, room // len(columns))
            budgets = [min(budget, share) for budget in budgets]
            columns = [[self._clip_idle_line(line, budget) for line in column]
                       for column, budget in zip(columns, budgets)]
        height = max(len(column) for column in columns)
        for row in range(height):
            for index, column in enumerate(columns):
                line = column[row] if row < len(column) else Text("")
                body.append(line)
                pad = budgets[index] - cell_len(line.plain)
                if index < len(columns) - 1:
                    body.append(" " * (pad + gap))
            if row < height - 1:
                body.append("\n")
        return body

    @staticmethod
    def _clip_idle_line(line: Text, width: int) -> Text:
        if cell_len(line.plain) <= width:
            return line
        clipped = Text()
        used = 0
        for start, end, style in line._spans:
            piece = line.plain[start:end]
            room = width - used
            if room <= 0:
                break
            if cell_len(piece) > room:
                piece = _fit_cells(piece, room)
            clipped.append(piece, style=style)
            used += cell_len(piece)
        return clipped

    @staticmethod
    def _idle_column(title: str, rows: list[tuple[str, str]]) -> list[Text]:
        lines = [Text(title, style="bold #c7b8d4")]
        if not rows:
            lines.append(Text("○ None configured", style=MUTED))
            return lines
        shown = rows[:14]
        for color, name in shown:
            line = Text()
            line.append("● ", style=color)
            line.append(name, style=TEXT)
            lines.append(line)
        extra = len(rows) - len(shown)
        if extra:
            lines.append(Text(f"+{extra} more", style=MUTED))
        return lines

    def _idle_lsp_rows(self) -> list[tuple[str, str]]:
        rows = []
        for server in self._lsp_inventory:
            state = server.get("state")
            ready = state == "sandbox_ready"
            name = str(server.get("label") or server.get("id") or "language server")
            if ready:
                color = GREEN
            elif state in {"installed_unavailable", "installed_unsupported"}:
                color = RED
            else:
                color = YELLOW
            rows.append((color, name))
        return rows

    def _idle_mcp_rows(self) -> list[tuple[str, str]]:
        snapshot = self._mcp_snapshot
        if snapshot.state != "ready":
            return []
        rows = []
        for item in snapshot.items:
            status = str(item.get("status", "")).lower()
            healthy = status in {"connected", "ready", "running", "ok", "active"} and not item.get("has_error")
            starting = "start" in status or status in {"checking", "loading"}
            color = GREEN if healthy else YELLOW if starting or status else MUTED
            rows.append((color, str(item.get("name") or "mcp")))
        return rows

    def _idle_skill_rows(self) -> list[tuple[str, str]]:
        names: list[str] = []
        try:
            from isycode.skill_catalog import skills
            names.extend(str(name) for name in skills())
        except (OSError, ValueError):
            names = []
        if self._skill_snapshot.state == "ready":
            for item in self._skill_snapshot.items:
                name = str(item.get("name") or "")
                if name and name not in names:
                    names.append(name)
        return [(GREEN, name) for name in names]

    def action_find_console(self) -> None:
        """Open console-wide search regardless of which main view has focus."""
        if isinstance(self.screen, ConsoleSearchScreen):
            self.screen.query_one("#console-search-input", Input).focus()
            return
        self.push_screen(ConsoleSearchScreen())

    @staticmethod
    def _render_searchable_text(widget: Static) -> str:
        console = Console(width=max(24, widget.size.width), color_system=None)
        with console.capture() as capture:
            console.print(static_content(widget))
        return capture.get()

    def _search_console(self, query: str, screen: ConsoleSearchScreen) -> None:
        for widget, _ in self._console_search_hits:
            if widget.is_mounted:
                widget.remove_class("console-search-match", "console-search-current")
        self._console_search_hits = []
        self._console_search_index = -1
        if query.strip():
            chat = self.query_one(ChatArea)
            for card in chat.query(CommandOutputCard):
                if query.strip().casefold() in card.output.casefold() and not card.expanded:
                    card.action_toggle_output()
            for widget in chat.query(Static):
                if not widget.display:
                    continue
                text = self._render_searchable_text(widget)
                self._console_search_hits.extend(
                    (widget, match) for match in find_text_matches(text, query.strip()))
        if self._console_search_hits:
            self._console_search_index = 0
            self._show_console_search_match()
        screen.update_results(
            self._console_search_index,
            len(self._console_search_hits),
            self._console_search_hits[self._console_search_index][1].snippet
            if self._console_search_hits else "",
        )

    def _move_console_search(self, direction: int) -> None:
        if not self._console_search_hits:
            return
        self._console_search_index = (
            self._console_search_index + direction) % len(self._console_search_hits)
        self._show_console_search_match()
        if isinstance(self.screen, ConsoleSearchScreen):
            self.screen.update_results(
                self._console_search_index, len(self._console_search_hits),
                self._console_search_hits[self._console_search_index][1].snippet)

    def _show_console_search_match(self) -> None:
        for widget, _ in self._console_search_hits:
            if widget.is_mounted:
                widget.remove_class("console-search-current")
                widget.add_class("console-search-match")
        if not self._console_search_hits:
            return
        widget, _ = self._console_search_hits[self._console_search_index]
        if widget.is_mounted:
            widget.add_class("console-search-current")
            chat = self.query_one(ChatArea)
            chat.pause_tail()
            for parent in widget.ancestors:
                if isinstance(parent, TextualCollapsible):
                    parent.collapsed = False
            chat.call_after_refresh(chat.scroll_to_widget, widget, top=True, animate=False)

    def _clear_console_search(self) -> None:
        for widget, _ in self._console_search_hits:
            if widget.is_mounted:
                widget.remove_class("console-search-match", "console-search-current")
        self._console_search_hits = []
        self._console_search_index = -1
        if self.is_mounted:
            self.query_one("#prompt-input", PromptArea).focus()

    def _mount_thought(self, title: str = "thinking...") -> tuple[ThoughtBlock, ChatArea]:
        chat = self.query_one(ChatArea)
        block = ThoughtBlock(title=title)
        chat.mount(block)
        chat.follow_tail()
        return block, chat

    async def _check_gateway_async(self) -> None:
        """Show reachability without implying that the remote root is mounted."""
        try:
            client = GatewayClient()
            allowed, reason = self._authorize_remote_read("gateway.files.read", client.base_url + "/health")
            if not allowed:
                self.query_one("#gateway-status", Static).update(Text(
                    "Not checked · Gateway host has no read grant. Configure it in Settings · Authority & Security.",
                    style=YELLOW))
                return
            available = await asyncio.to_thread(client.is_available)
            if available:
                message = "Health reachable. Remote Files is disabled because the Gateway hides its root identity."
                if not client.api_key:
                    message += " Set GATEWAY_API_KEY for scoped read access."
                color = YELLOW
            else:
                message = "Unavailable. Local Files remains independent; no Gateway fallback is active."
                color = YELLOW
        except (ValueError, OSError) as exc:
            message = f"Gateway configuration error: {exc}"
            color = RED
        self.query_one("#gateway-status", Static).update(Text(message, style=color))

    async def _check_gateway_mcp_async(self) -> None:
        status = self.query_one("#gateway-mcp-status", Static)
        status.update(Text("Checking Gateway MCP authorization…"))
        try:
            gateway_url = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8787").rstrip("/")
            allowed, reason = self._authorize_remote_read("mcp.discover", gateway_url + "/mcp")
            if not allowed:
                self._gateway_mcp_snapshot = CatalogSnapshot(True, [], "denied", reason)
                message, color = "Not checked · grant Gateway MCP discovery in Settings · Authority & Security.", YELLOW
                if self.is_mounted:
                    status.update(Text(message, style=color))
                return
            status.update(Text("Loading · starting the native Gateway MCP tool catalog…"))
            tools = await discover_gateway_tools()
        except GatewayMCPUnavailable as exc:
            snapshot = CatalogSnapshot(True, [], "unavailable", str(exc))
            message, color = f"Unavailable · {exc}", YELLOW
        except Exception as exc:
            snapshot = CatalogSnapshot(True, [], "error", type(exc).__name__)
            message, color = f"Failed · {type(exc).__name__}", RED
        else:
            snapshot = CatalogSnapshot(True, tools, "ready")
            has_key = bool(os.environ.get("GATEWAY_API_KEY"))
            if not has_key:
                has_key = saved_secret_exists("isyco-gateway")
            auth_state = "API key supplied" if has_key else "API key needed for calls"
            message = (f"Ready · {len(tools)} tools · {auth_state} · manual calls require "
                       "per-host grant + one-use approval")
            color = GREEN if has_key else YELLOW
        self._gateway_mcp_snapshot = snapshot
        if self.is_mounted:
            self.query_one("#gateway-mcp-status", Static).update(Text(message, style=color))



    # ── input ────────────────────────────────────────────────────

    def on_input_submitted(self, message: Input.Submitted) -> None:
        if message.input.id == "console-search-input":
            self._move_console_search(1)
            return
        if message.input.id == "action-search":
            options = self.query_one("#action-list", OptionList)
            if options.option_count:
                options.action_select()
            else:
                options.focus()
            return
        if message.input.id == "provider-key-input":
            self._save_provider_key()
            return
        if message.input.id == "file-search":
            query = message.value.strip()
            if query:
                self.run_worker(self._search_workspace(query), exclusive=True,
                                group="workspace-search")
            return
        self._accept_prompt(message.input, message.value)

    def on_prompt_area_submitted(self, message: PromptArea.Submitted) -> None:
        self._accept_prompt(message.prompt, message.value)

    def _track_composer_draft(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "prompt-input":
            return
        self._draft_text = getattr(event.text_area, "pasted_text", None).expand(event.text_area.text) if hasattr(event.text_area, "pasted_text") else event.text_area.text
        if self._draft_timer is not None:
            self._draft_timer.stop()
        self._draft_timer = self.set_timer(1.0, self._save_draft)

    def _navigate_prompt_history(self, delta: int, current: str) -> str | None:
        if not self._prompt_history or (self._prompt_history_idx == -1 and delta > 0):
            return None
        if self._prompt_history_idx == -1:
            self._prompt_history_draft = current
            self._prompt_history_idx = len(self._prompt_history)
        next_index = self._prompt_history_idx + delta
        if next_index < 0:
            return None
        if next_index >= len(self._prompt_history):
            self._prompt_history_idx = -1
            return self._prompt_history_draft
        self._prompt_history_idx = next_index
        return self._prompt_history[next_index]

    def _save_draft(self) -> None:
        if not self._sessions_enabled() or (not self._active_chat_session_id and not self._draft_text
                                            and not self._tool_history and not self._usage.requests):
            return
        owner = self._chat_session_owner
        if self._session_is_diverged(self._active_chat_session_id):
            return  # read-only towards the saved conversation until the user chooses
        try:
            outcome, sid = self._chat_session_owner.manage(
                "state", self._active_chat_session_id, json.dumps(self._session_state()))
            if self._session_is_diverged(self._active_chat_session_id):
                self._session_diverged_found(self._active_chat_session_id)
                return
            if outcome.decision == "ALLOW":
                self._active_chat_session_id = sid
                if len(self._draft_text) > 16_000:
                    self._set_activity("Draft saved up to 16,000 characters; full text remains in the composer", YELLOW)
            else:
                self._set_activity(f"Draft not saved · {outcome.reason[:100]}", YELLOW)
        except (OSError, ValueError):
            self._set_activity("Draft not saved · private state unavailable", YELLOW)

    def _accept_prompt(self, prompt, raw_text: str) -> None:
        if isinstance(prompt, PromptArea) and hasattr(prompt, "pasted_text"):
            raw_text = prompt.pasted_text.expand(raw_text)
        text = raw_text.strip()
        if not text:
            self._promote_queued_message()
            return
        try:
            self._image_attachments.prepare([{"role": "user", "content": text}], selected_provider_name(), resolved_chat_model(selected_provider_name()))
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        if text == "/ideas":
            prompt.load_text("") if isinstance(prompt, PromptArea) else setattr(prompt, "value", "")
            self.push_screen(IdeaBacklogScreen(self))
            return
        if text in {"/queue", "/queue clear"}:
            prompt.load_text("") if isinstance(prompt, PromptArea) else setattr(prompt, "value", "")
            if text == "/queue clear":
                self._queued_messages.clear()
                self._paint_queued_messages()
                self.notify("Pending messages cleared")
            else:
                self.push_screen(QueuedMessagesScreen(self))
            return
        if text == "/msg" or text.startswith("/msg "):
            prompt.load_text("") if isinstance(prompt, PromptArea) else setattr(prompt, "value", "")
            self.run_worker(self._deliver_session_message(text), group="session-message", exit_on_error=False)
            return
        if self._loop_task and not self._loop_task.done():
            if self._chat_turn_task is not None and not self._chat_turn_task.done() and text.startswith("/steer "):
                from isycode.reasoning_options import steering_support
                provider, model = self._steering_target()
                if steering_support(provider, model) is False:
                    self._queue_steer_warning()
                    return
                instruction = text.removeprefix("/steer ").strip()
                if self._steering_try_active:
                    self.notify("Steer attempt pending; draft kept")
                    return
                if len(self._pending_steering) >= 8:
                    self._append("Steering queue is full; this draft is kept.", YELLOW)
                    return
                self._pending_steering.append(instruction)
                self._steering_try_active = True
                prompt.load_text("") if isinstance(prompt, PromptArea) else setattr(prompt, "value", "")
                self._mount_user_turn("Steer attempt · " + instruction)
                self._append("Steering queued · current tool effects remain; pending calls will be skipped.", CYAN)
                request = self._chat_request_task
                if request is not None and not request.done():
                    request.cancel()
                return
            if not text.startswith("/"):
                if len(self._queued_messages) >= 8:
                    self.notify("Message queue is full; draft kept", severity="warning")
                    return
                self._queued_messages.append(text)
                self._paint_queued_messages()
                prompt.load_text("") if isinstance(prompt, PromptArea) else setattr(prompt, "value", "")
                self._append(f"Queued · {len(self._queued_messages)} pending · " + _fit_cells(" ".join(text.split()), 70) + " · /queue reviews", CYAN)
                return
            self._append("  Still working. Your message remains in the composer; send it again when ready.", YELLOW)
            return
        if text.startswith("/steer "):
            text = text.removeprefix("/steer ").strip()
        if isinstance(prompt, PromptArea):
            prompt.load_text("")
        else:
            prompt.value = ""
        if not self._prompt_history or self._prompt_history[-1] != text:
            self._prompt_history.append(text)
            self._prompt_history = self._prompt_history[-200:]
        self._prompt_history_idx = -1
        self._prompt_history_draft = ""
        self._clear_pending_plan()
        plugin, cmd, arg = self._plugins.route(text)
        self._pending_user_sent_at = datetime.now().astimezone().isoformat(timespec="seconds")
        if cmd is None:
            self._mount_user_turn(text, self._pending_user_sent_at)
        if cmd is not None:
            label = "Planning · IsyMotron" if cmd.name == "plan" else f"Running /{cmd.name}"
            self._start_operation(cmd.handler(self, arg), label)
        elif text.startswith("/"):
            self._start_operation(self._run_custom_command(text), "Chat · working")
        else:
            self._start_operation(self._run_chat(text), "Chat · working")

    def _start_operation(self, coroutine, label: str) -> None:
        self._activity_label = label
        self._activity_frame = 0
        self._set_activity(label, CYAN)
        timer = getattr(self, "_activity_timer", None)
        if timer is not None:
            timer.stop()
        self._activity_timer = self.set_interval(0.12, self._animate_activity)
        task = self._pin_task(coroutine)
        self._loop_task = task
        self._animate_activity()
        self._paint_idea_box()
        task.add_done_callback(self._operation_finished)

    def _play_notification_sound(self, kind: str) -> None:
        from isycode.notification_sounds import PATTERNS
        if not getattr(self, "_notification_sounds", True) or self.is_headless:
            return
        now = _time.monotonic()
        if now - getattr(self, "_last_notification_sound", 0) < 0.9:
            return
        self._last_notification_sound = now
        self.bell()
        for delay in PATTERNS.get(kind, PATTERNS["info"])[1:]:
            self.set_timer(delay, lambda: self.bell() if self._notification_sounds else None)

    def notify(self, message, *, title="", severity="information", timeout=None,
               markup=True):
        self._play_notification_sound({"warning": "warning", "error": "error"}.get(severity, "info"))
        return super().notify(message, title=title, severity=severity, timeout=timeout,
                              markup=markup)

    def _operation_finished(self, task: asyncio.Task) -> None:
        lane = next((item for item in self._lanes.values() if item.loop_task is task), None)
        if lane is None:
            return
        lane.loop_task = None
        cancelled = task.cancelled()
        failed = None if cancelled else task.exception()
        foreground = lane.key == self._foreground_key
        followed = False
        if lane.queued_messages and not cancelled and failed is None and lane.retry_prompt is None:
            if foreground:
                self.call_after_refresh(self._send_next_queued_message)
            else:
                nxt = lane.queued_messages.pop(0)
                self._start_background_turn(lane, nxt)
                followed = True
        if foreground:
            self._play_notification_sound(
                "warning" if cancelled else "error" if failed is not None else "done")
            timer = getattr(self, "_activity_timer", None)
            if timer is not None:
                timer.stop()
                self._activity_timer = None
            if cancelled:
                self._set_activity("Interrupted", YELLOW)
            elif failed is not None:
                self._set_activity(f"Failed · {type(failed).__name__}", RED)
            elif self._last_plan is not None:
                self._set_activity("Plan ready · review it in Overview", YELLOW)
            else:
                self._set_activity("Chat ready", MUTED)
            self._paint_idea_box()
            if self._idea_backlog:
                self.notify(f"{len(self._idea_backlog)} captured ideas · /ideas reviews and promotes")
            return
        if not followed:
            if cancelled:
                lane.activity_message = "Interrupted"
                lane.activity_color = YELLOW
            elif failed is not None:
                lane.activity_message = f"Failed · {type(failed).__name__}"
                lane.activity_color = RED
            else:
                lane.activity_message = "Chat ready"
                lane.activity_color = MUTED
        if not cancelled and not followed:
            self.notify("A conversation failed" if failed is not None else "A conversation finished")
        self.run_worker(self._refresh_work_list(), group="work-list")

    async def _grit_peer_advisory(self, path: str) -> str | None:
        """Advisory peer claims (grit) for one file; never gates the approval."""
        try:
            owner = GritPeersOwner(self._workspace_root,
                                   WorkspaceAuthority(self._workspace_root),
                                   self._action_approvals)
            outcome = await owner.claims(path)
        except (OSError, ValueError, RuntimeError):
            return None
        if outcome.decision != "ALLOW":
            return None
        try:
            return json.loads(outcome.text).get("advisory")
        except ValueError:
            return None

    async def _await_screen(self, screen):
        """Show a modal screen and wait for its result from a worker or a plain task.

        App.push_screen_wait only works inside a Textual worker; chat turns and
        slash commands run as asyncio tasks, so wait on the dismiss callback.
        Resolve after the next refresh because Screen.dismiss invokes its callback
        before the previous screen has been restored.
        """
        if isinstance(screen, AgentQuestionScreen):
            self._play_notification_sound("question")
        elif isinstance(screen, ApprovalScreen):
            self._play_notification_sound("approval")
        future = asyncio.get_running_loop().create_future()

        def finished(result) -> None:
            def resolve_after_pop() -> None:
                if not future.done():
                    future.set_result(result)

            self.call_after_refresh(resolve_after_pop)

        self.push_screen(screen, finished)
        return await future

    def _animate_activity(self) -> None:
        if self._loop_task is None or self._loop_task.done():
            return
        from isycode.cat_activity import walking_cat
        self._activity_frame += 1
        try:
            status = self.query_one("#activity-status", Static)
            status.update(walking_cat(status.content_size.width, self._activity_frame))
        except (NoScreen, ScreenStackError):
            pass

    def _refresh_activity(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            self._animate_activity()
        else:
            self._set_activity(getattr(self, "_activity_message", "Chat ready"),
                               getattr(self, "_activity_color", MUTED))

    def _apply_high_contrast(self, enabled: bool) -> None:
        from isycode.tui_theme import HIGH_CONTRAST_CSS
        read_from = ("isycode", "high-contrast")
        self.stylesheet.add_source(HIGH_CONTRAST_CSS if enabled else "",
                                   read_from=read_from, is_default_css=False)
        self.stylesheet.reparse()
        self.stylesheet.update(self)

    def _set_activity(self, message: str, color: str = MUTED) -> None:
        lane = self._active_lane()
        lane.activity_message = message
        lane.activity_color = color
        if not self._lane_on_screen():
            return
        self._activity_message = message
        self._activity_color = color
        if self.is_mounted:
            try:
                status = self.query_one("#activity-status", Static)
                if self._loop_task is not None and not self._loop_task.done():
                    return
                from isycode.cat_activity import sleeping_cat
                status.update(sleeping_cat(status.content_size.width, message, color))
            except (NoScreen, ScreenStackError):
                pass

    def _blocked_notice(self, short: str, detail: str = "") -> None:
        """A menu choice that did not run. The chat transcript stays untouched."""
        self._set_activity(short, YELLOW)
        if not detail:
            return
        try:
            panel = self.screen_stack[0].query_one("#action-detail", Static)
        except (NoMatches, NoScreen, IndexError):
            return
        panel.display = True
        panel.update(Text(detail))

    def _paint_bridge_presence(self) -> None:
        rows = self._presence_rows
        if rows is None:
            return
        try:
            panel = self.query_one("#work-presence", Static)
        except (NoMatches, NoScreen):
            return
        from isycode.bridge_presence import presence_line
        width = panel.content_size.width or panel.size.width
        panel.update(presence_line(rows, width))

    async def _show_bridge_presence(self) -> None:
        confirmed = await self._await_screen(BridgePresenceScreen())
        panel = self.query_one("#work-presence", Static)
        if not confirmed:
            self._presence_rows = None
            panel.update("Bridge presence off")
            return
        root = self._workspace_root
        approvals = self._action_approvals
        try:
            base = WorkspaceAuthority(root)
            request = BridgePresenceOwner(root, base, approvals).prepare()
            owner = BridgePresenceOwner(
                root, OneShotActionAuthority(base, request), approvals)
            outcome, rows = await asyncio.to_thread(
                owner.read, request, approvals.issue(request))
        except (OSError, RuntimeError, ValueError):
            self._presence_rows = None
            panel.update("Presence unavailable")
            return
        if outcome.decision != "ALLOW":
            self._presence_rows = None
            panel.update("Presence unavailable")
            return
        self._presence_rows = rows
        self._paint_bridge_presence()

    # ── chat (default path) ──────────────────────────────────────




















    def copy_to_clipboard(self, text: str) -> None:
        """Every copy Textual makes (selection, Ctrl+C, text fields) goes through the owner."""
        self._copy_through_owner(text, "selection")

    def on_text_selected(self, event) -> None:
        """Copy on select: releasing the mouse after selecting text copies it."""
        get_selected = getattr(self.screen, "get_selected_text", None)
        text = get_selected() if callable(get_selected) else None
        if text:
            self._copy_through_owner(text, "selection")

    async def _request_clipboard_paste(self, prompt):
        authority = WorkspaceAuthority(self._workspace_root)
        grant = authority.effective_policy().get("grants", {}).get("clipboard.paste", {})
        if not displayed_on("clipboard.paste", grant, CLIPBOARD_TARGET in grant.get("targets", ())):
            if not await self._await_screen(TailscaleConfirmScreen(
                    "Allow pasting from the clipboard?", "Reads text or images only when you press Ctrl+V. Contents stay in the draft until you send it; journal records no image or text bytes.", "Allow paste")):
                return
            authority.set_grant("clipboard.paste", enabled=True, targets=[CLIPBOARD_TARGET])
        owner = ClipboardOwner(self._workspace_root, authority)
        outcome, mime, data = await asyncio.to_thread(owner.paste)
        if outcome.decision != "ALLOW":
            self.notify(outcome.reason, severity="warning")
            return
        try:
            if mime.startswith("image/"):
                prompt.insert(self._image_attachments.capture(mime, data))
                self.notify("Image attached · Ctrl+P reviews attachments")
            else:
                from textual.events import Paste
                await prompt._on_paste(Paste(data.decode("utf-8")))
        except (ValueError, UnicodeError):
            self.notify("Clipboard content could not be attached", severity="warning")
        prompt.focus()

    async def _request_clipboard_copy(self, text: str, source: str) -> None:
        authority = WorkspaceAuthority(self._workspace_root)
        grant = authority.effective_policy().get('grants', {}).get('clipboard.copy', {})
        if not displayed_on('clipboard.copy', grant, CLIPBOARD_TARGET in grant.get('targets', ())):
            if not await self._await_screen(TailscaleConfirmScreen(
                    'Allow copying in this workspace?',
                    'Copies text or paths you select to the OS clipboard. Other applications may read it. '
                    'The model receives no clipboard tool; copied contents are not written to the journal.',
                    'Allow copy')):
                return
            authority.set_grant('clipboard.copy', enabled=True, targets=[CLIPBOARD_TARGET])
        self._copy_through_owner(text, source)

    def _copy_through_owner(self, text: str, source: str) -> None:
        try:
            key_field = self.query_one("#provider-key-input", Input)
        except Exception:  # noqa: BLE001 - the field only exists in the main screen
            key_field = None
        if key_field is not None and self.focused is key_field:
            self.notify("API keys are never copied.", severity="warning")
            return
        try:
            owner = ClipboardOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root))
            outcome = owner.copy(text, source=source,
                                 terminal_write=super().copy_to_clipboard)
        except (WorkspaceAuthorityError, OSError, ValueError):
            self.notify("Copy failed · Workspace Authority is unavailable.", severity="error")
            return
        if outcome.decision == "ALLOW":
            where = ("terminal clipboard" if outcome.text == "terminal"
                     else f"clipboard via {outcome.text}")
            if outcome.text == 'terminal':
                self.notify('Copy request sent to terminal. If paste stays empty, install wl-clipboard (Wayland) or xclip (X11); some terminals ignore OSC 52.', timeout=8)
            else:
                self.notify(f"Copied {len(text)} characters to the {where}.", timeout=2)
        elif "grant" in outcome.reason:
            self.notify("Copying is off for this workspace · turn on “Copy selected text” in "
                        "Settings → Authority.", severity="warning", timeout=5)
        else:
            self.notify(f"Nothing copied · {outcome.reason[:120]}", severity="warning")



















    async def _check_provider_connection(self) -> None:
        """Explicit minimal provider request; credentials alone never authorize it."""
        try:
            name = selected_provider_name()
            provider = Provider(name=name, model=resolved_chat_model(name),
                                api_key=load_provider_key(name) or None)
            messages = [{"role": "user", "content": "Reply with OK only. Do not call any tools."}]
            material = {"operation": "chat.completions", "messages": messages,
                        "max_tokens": None, "tools": None,
                        "token_limit_field": provider.token_limit_field,
                        "reasoning_effort": provider.reasoning_effort,
                        "temperature_supported": provider.temperature_supported}
            async def send():
                return await provider_complete(provider, messages, max_tokens=None, tools=None)
            owner = ProviderNetworkOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root))
            response, outcome = await owner.execute(provider, material, send)
            if outcome.decision == "ALLOW" and isinstance(response, dict) and response.get("text"):
                self._append(f"  Provider response received · receipt {outcome.receipt.receipt_id} · "
                             "this checks chat connectivity, not tool compatibility.", GREEN)
            else:
                self._append(f"  Provider not verified · {outcome.decision} · {outcome.reason[:160]}", YELLOW)
        except (ProviderError, StreamError) as exc:
            self._append(self._provider_failure(exc, "Connection check"), YELLOW)
        except (OSError, ValueError) as exc:
            self._append(f"  Connection check unavailable ({type(exc).__name__}).", YELLOW)

    async def _load_project_context(self) -> bool:
        """Explicitly read root AGENTS.md; the file never supplies grants or tools."""
        return await self._load_context_file("AGENTS.md")

    async def _load_context_file(self, relative_path: str) -> bool:
        """Load one selected workspace document through the read owner and receipt."""
        self._agent_context = None
        owner = LocalWorkspaceReadOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root))
        outcome = await asyncio.to_thread(owner.execute, "workspace.context.inject", {"path": relative_path})
        text = read_result_text(outcome.text) if outcome.decision == "ALLOW" else ""
        if text and outcome.receipt is not None:
            self._agent_context = {"path": relative_path, "text": text,
                                   "receipt_id": outcome.receipt.receipt_id, "verification": "PASS"}
            self._append(f"  Context loaded · {relative_path} · owned read; no permissions changed.", MUTED)
        else:
            self._append(f"  Context not loaded · {outcome.reason[:160]}", YELLOW)
        if self._lane_on_screen():
            self.query_one("#context-button", Button).label = self._context_button_label()
        return self._agent_context is not None

    # ── /plan (IsyMotron plugin) ─────────────────────────────────

    async def _run_plan(self, intent: str) -> None:
        """Delegate planning to IsyMotron runtime and render its proposal."""
        self._clear_pending_plan()
        block = None
        if self._lane_on_screen():
            block, _chat = self._mount_thought()
        reason_buf: list[str] = []
        t0 = _time.monotonic()
        try:
            def on_chunk(kind: str, chunk: str) -> None:
                if kind == "reasoning":
                    reason_buf.append(chunk)
                    if block is not None and block.is_mounted and self._lane_on_screen():
                        self.call_from_thread(block.set_text, "".join(reason_buf))

            runtime = self._runtime_factory(self._workspace_root)
            outcome = await runtime.plan(intent, on_chunk=on_chunk)
            plan = outcome.plan
            from isycode.model_presentation import model_display_name
            self._append(f"  Model: {model_display_name(outcome.model)} · {outcome.provider_label}", MUTED)
            self._append(f"  Host: {outcome.host_name}", MUTED)

            if plan.verdict() == "PLANNED":
                self._append(f"\n  Understood: {plan.understood}", TEXT)
                self._append(f"  Plan ({len(plan.steps)} steps):", YELLOW)
                for i, step in enumerate(plan.steps, 1):
                    params_str = ", ".join(f"{k}={v}" for k, v in step.params.items())
                    self._append(f"    {i}. [{step.host}] {step.capability}({params_str})", TEXT)
                    self._append(f"       ↳ {step.why}", MUTED)
                self._append("\n  Proposal only · it carries no authority.", MUTED)
                self._append(
                    "  Execution is disabled in Secure until each step has an ISyCode owner, "
                    "grant, Sentinel decision and required approval.", MUTED)
                if plan.completion and plan.completion.prompt_tokens is not None and plan.completion.completion_tokens is not None:
                    self._append(f"  Tokens: {plan.completion.prompt_tokens + plan.completion.completion_tokens}", MUTED)
                self._clear_pending_plan()
                if self._lane_on_screen():
                    review = self.query_one("#review-plan", Button)
                    review.disabled = True
                    review.label = "Execution unavailable in Secure"
                self._append(
                    f"\n  {outcome.origin} proposal is ready for inspection; it cannot be run through IsyMotron.",
                    YELLOW)
            else:
                self._append(f"\n  Refused: {plan.refused or 'no plan possible'}", RED)
                self._append("  This is correct behavior, not a failure.", MUTED)

        except PlanRejected as e:
            reason = getattr(e, "reason", str(e))
            self._append(f"\n  Plan rejected: {reason}. No executable plan was retained.", RED)
        except ProviderError as e:
            self._append(f"\n  {self._provider_failure(e, 'Planning')}", RED)
        except Exception as e:
            self._append(
                f"\n  Planning failed ({type(e).__name__}). No executable plan was retained.", RED)
        finally:
            if block is not None and block.is_mounted and self._lane_on_screen():
                block.collapse_to(_time.monotonic() - t0)

    # ── Contextual demo-plan approval ────────────────────────────

    def action_run_plan(self) -> None:
        """Review and confirm a demo plan through its contextual button."""
        if self._last_plan is None or self._last_runtime is None:
            self._append("  No plan to run. Use /plan <intent> first.", MUTED)
            return
        if self._loop_task and not self._loop_task.done():
            self._append("  Wait for the current task to finish before running a plan.", YELLOW)
            return
        try:
            current_context = self._last_runtime.approval_context()
        except Exception as e:
            self._clear_pending_plan()
            self._set_activity("Plan cleared · authority could not be revalidated", RED)
            self._append(
                f"  Authority could not be revalidated ({type(e).__name__}); plan cleared.", RED)
            return
        if current_context != self._last_plan_context:
            self._clear_pending_plan()
            self._set_activity("Plan cleared · authority changed", RED)
            self._append(
                "  Host identity, grants, capabilities, or scopes changed after planning. "
                "Create a new plan before execution.", RED)
            return
        now = _time.time()
        plan_digest = self._plan_digest(self._last_plan)
        if (now - self._armed_at > 10.0
                or self._armed_plan_id != self._last_plan.plan_id
                or self._armed_plan_digest != plan_digest
                or self._armed_context != current_context):
            try:
                authority = self._last_runtime.approval_summary()
            except Exception as e:
                self._clear_pending_plan()
                self._set_activity("Plan cleared · authority details unavailable", RED)
                self._append(
                    f"  Authority details could not be loaded ({type(e).__name__}); plan cleared.",
                    RED)
                return
            self._armed_at = now
            self._armed_plan_id = self._last_plan.plan_id
            self._armed_plan_digest = plan_digest
            self._armed_context = current_context
            review = self.query_one("#review-plan", Button)
            is_local_read = self._last_plan_origin == "local-read-only"
            review.label = "Confirm local read-only plan" if is_local_read else "Confirm demo plan"
            n = len(self._last_plan.steps)
            effect = ("local filesystem.read only" if is_local_read
                      else "simulated host; no real workspace effects")
            self._append(
                f"\n  Review {self._last_plan_origin} plan ({n} steps; {effect}):",
                YELLOW)
            self._append(f"  Host: {self._last_plan_host}", MUTED)
            identity = authority.get("identity", {})
            if isinstance(identity, dict):
                self._append(
                    f"  Host identity: {identity.get('host_id', 'unknown')} · "
                    f"{identity.get('engine', 'unknown')} · {identity.get('os_family', 'unknown')}",
                    MUTED)
            capabilities = authority.get("granted", [])
            if isinstance(capabilities, list):
                self._append(
                    "  Granted capabilities: " + (", ".join(map(str, capabilities)) or "none"),
                    MUTED)
            bounds = authority.get("bounds", {})
            if isinstance(bounds, dict):
                for capability, scope in sorted(bounds.items()):
                    scope_text = json.dumps(scope, sort_keys=True, ensure_ascii=False, default=str)
                    self._append(f"  Scope {capability}: {scope_text}", MUTED)
            for i, s in enumerate(self._last_plan.steps, 1):
                params = ", ".join(f"{key}={value}" for key, value in s.params.items())
                self._append(f"    {i}. [{s.host}] {s.capability}({params})", TEXT)
            self._append(
                f"  Select {review.label} in Overview within 10s to execute it.", YELLOW)
            self._set_activity("Awaiting confirmation · expires in 10s", YELLOW)
            return
        plan, runtime = self._last_plan, self._last_runtime
        origin, host_name = self._last_plan_origin, self._last_plan_host
        self._clear_pending_plan()
        self._start_operation(
            self._execute_stored_plan(
                plan, runtime, origin, host_name, expected_context=current_context),
            f"Executing · {host_name}")

    def _clear_pending_plan(self) -> None:
        """Forget an executable plan and any approval bound to it."""
        self._last_plan = None
        self._last_runtime = None
        self._last_plan_origin = ""
        self._last_plan_host = ""
        self._last_plan_context = None
        self._armed_at = 0.0
        self._armed_plan_id = None
        self._armed_plan_digest = None
        self._armed_context = None
        review = self.query_one("#review-plan", Button)
        review.disabled = True
        review.label = "No plan pending"

    @staticmethod
    def _plan_digest(plan) -> str:
        payload = json.dumps(plan.to_dict(), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _receipt_audit_lines(receipt, verification) -> list[str]:
        """Render the receipt seal and every field from IsyMotron's verifier."""
        def label(value) -> str:
            if value is None:
                return "none"
            return str(getattr(value, "value", getattr(value, "name", value)))

        if receipt is None:
            lines = ["Receipt: unavailable"]
        else:
            decision = getattr(receipt, "decision", None)
            policy_decision = getattr(decision, "decision", None)
            policy_reason = getattr(decision, "reason", None)
            lines = [
                f"Receipt ID: {receipt.receipt_id}",
                f"Seal: kind={getattr(receipt, 'seal_kind', 'unknown')} · "
                f"status={getattr(verification, 'seal_status', 'NOT_REPORTED')} · "
                f"value={getattr(receipt, 'seal', '') or 'missing'}",
                f"Receipt decision: {label(policy_decision)} · reason={label(policy_reason)}",
            ]

        if verification is None:
            lines.append("Verification: NOT_VERIFIABLE · verifier returned no result")
            lines.extend(("Claim match: not checked", "Request match: not checked",
                          "Decision match: not checked", "Re-derived decision: unavailable"))
            return lines

        status = label(getattr(verification, "status", "NOT_VERIFIABLE"))
        lines.append(
            f"Verification: {status} · {getattr(verification, 'reason', 'no verifier reason')}")
        rederived = getattr(verification, "rederived", None)
        was_rederived = rederived is not None
        for title, field in (("Claim match", "claim_matched"),
                             ("Request match", "request_matched"),
                             ("Decision match", "decision_matched")):
            value = getattr(verification, field, None)
            rendered = ("not checked" if not was_rederived else
                        "yes" if value is True else "no" if value is False else "unknown")
            lines.append(f"{title}: {rendered}")
        if rederived is None:
            lines.append("Re-derived decision: unavailable")
        else:
            derived_decision = getattr(rederived, "decision", None)
            lines.append(
                f"Re-derived decision: {label(getattr(derived_decision, 'decision', None))} · "
                f"reason={label(getattr(derived_decision, 'reason', None))}")
        return lines

    async def _execute_stored_plan(
        self, plan, runtime: AgentRuntime, origin: str, host_name: str,
        *, expected_context: str,
    ) -> None:
        """Execute only the plan explicitly reviewed against this host."""
        self._append(f"\n  Executing on {host_name}...", CYAN)
        try:
            execution = await runtime.execute(plan, expected_context=expected_context)
        except AuthorityContextChanged as e:
            self._append(
                f"  DENY before execution: {e} No step was submitted to the host; plan cleared.",
                RED)
            return
        except Exception as e:
            self._append(
                f"  Execution returned no status ({type(e).__name__}); the host outcome is unknown. "
                "Do not retry until host state or receipts are checked.", RED)
            return
        try:
            verifications = await asyncio.to_thread(runtime.verify_execution, execution)
        except Exception as e:
            verifications = {}
            self._append(
                f"  Receipt verification unavailable ({type(e).__name__}); allowed steps remain untrusted.",
                YELLOW)
        ok_count = deny_count = unknown_count = 0
        for step in execution.steps:
            receipt = step.receipt
            verification = verifications.get(step.index)
            verify_status = verification.status if verification else "NOT_VERIFIABLE"
            for line in self._receipt_audit_lines(receipt, verification):
                self._append(f"    {step.index}. {line}", MUTED)
            if step.allowed:
                result = receipt.result or {}
                evidence = getattr(receipt.evidence, "value", str(receipt.evidence))
                if evidence != "DEMONSTRATED" or (isinstance(result, dict) and result.get("error")):
                    unknown_count += 1
                    detail = result.get("error", "engine outcome is not demonstrated") if isinstance(result, dict) else "engine outcome is unknown"
                    self._append(
                        f"    {step.index}. ALLOW decision · UNKNOWN execution ({detail}) · receipt {receipt.receipt_id[:12]} · verify {verify_status}",
                        YELLOW)
                    continue
                if verify_status != "PASS":
                    unknown_count += 1
                    self._append(
                        f"    {step.index}. ALLOW decision · execution evidence not trusted · receipt {receipt.receipt_id[:12]} · verify {verify_status}",
                        RED if verify_status == "REJECT" else YELLOW)
                    continue
                ok_count += 1
                self._append(
                    f"    {step.index}. ALLOW — receipt {receipt.receipt_id[:12]} · verify PASS", GREEN)
                result = receipt.result or {}
                if origin == "local-read-only":
                    if isinstance(result, dict) and isinstance(result.get("text"), str):
                        preview = result["text"][:4000]
                        if len(result["text"]) > 4000:
                            preview += "\n… output truncated at 4,000 characters …"
                        self._append(f"       Read result:\n{preview}", TEXT)
                    elif isinstance(result, dict) and result.get("kind") == "directory":
                        self._append(
                            "       Directory listed. Use Files for the filtered browser view.", MUTED)
            else:
                deny_count += 1
                self._append(
                    f"    {step.index}. DENY — {receipt.decision.reason} · receipt {receipt.receipt_id[:12]} · verify {verify_status}",
                    YELLOW if verify_status == "PASS" else RED)
        if execution.stopped_at is not None:
            self._append(f"    Stopped at step {execution.stopped_at}: {execution.stop_reason}", YELLOW)
        self._append(
            f"\n  Done: {ok_count} demonstrated, {deny_count} denied, {unknown_count} unknown.", CYAN)
        if origin == "local-read-only":
            self._append("  Local read-only execution; write capabilities were removed from this runtime.", MUTED)
        else:
            self._append("  Demo execution only; real workspace writes are not enabled here.", MUTED)



import isycode.tui_composer as _split_tui_composer
import isycode.tui_screens_sessions as _split_tui_screens_sessions
_split_tui_composer.TUIApp = TUIApp
_split_tui_screens_sessions.TUIApp = TUIApp

def main():
    app = TUIApp()
    app.run()


if __name__ == "__main__":
    main()
