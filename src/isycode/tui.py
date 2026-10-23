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
from isycode.localization import configure_locale, language_msgid, tr
from isycode.user_defaults import UserDefaultsStore
from isycode.tui_presentation import MenuHeading, SettingRow
from isycode.tool_history import record_tool_result, sanitize_historical_text, tool_history_context
from isycode.throughput import ThroughputMeter
from isycode.usage import UsageLedger
from isycode.shortcuts import APP_SHORTCUTS
from isycode.gus_role import is_isycode_checkout
from isycode.catalog import (
    ISYCODE_AGENTS, ISYCODE_SUBAGENTS, ISYCO_MOTORS, ROLE_CYCLE, ROLE_KERNEL,
    SEMANTIC_BRANCHES, role_color,
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
from textual.actions import SkipAction
from textual.screen import ModalScreen
from textual.css.query import NoMatches
from textual.dom import NoScreen
from textual.events import Click, Key, Resize
from textual.widget import Widget
from textual.widgets import (
    Static, Input, Footer, Button, Tree, TextArea, OptionList, Select, Checkbox,
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
    fit_rail_button,
    PreviewOptionList,
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
    BrowserReadPreviewScreen,
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


_IS_WINDOWS = sys.platform == "win32"


def _terminal_grid_size() -> tuple[int, int] | None:
    """Read the console window grid, not the scrollback buffer size.

    Textual's Windows event loop reports ``WINDOW_BUFFER_SIZE_RECORD.dwSize``.
    On conhost that is the screen buffer, which can stay larger than the
    visible window after a monitor or DPI change, leaving the TUI painting the
    old grid. ``os.get_terminal_size`` asks for the visible window rectangle.
    """
    try:
        size = os.get_terminal_size(sys.__stdout__.fileno())
    except (AttributeError, OSError, ValueError):
        return None
    if size.columns <= 0 or size.lines <= 0:
        return None
    return size.columns, size.lines


class TUIApp(SessionMixin, RailMixin, ProviderMixin, AuthorityMixin, RemoteMixin, WorkspaceMixin, ToolMixin, ChatMixin, MenuMixin, App):
    """ISyCode TUI — Crush-inspired, chat-first, IsyMotron as a plugin."""

    ENABLE_COMMAND_PALETTE = False
    ALLOW_SELECT = True

    CSS_PATH = [Path(__file__).with_name("isycode.tcss"),
                Path(__file__).with_name("design.tcss")]

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
        # F-01 readiness: set once _startup_workspace finishes (success or failure)
        # so tests and callers never have to guess with blind pilot.pause() loops.
        self._ready_event = asyncio.Event()
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
        self._settings_category = ""
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
            self._reduced_motion = defaults.get("reduced_motion", False)
            self._ascii_only = defaults.get("ascii_only", False)
            self._sidebar_file_preview = defaults.get("sidebar_file_preview", False)
            self._locale = defaults.get("locale", "es")
        except (OSError, ValueError):
            self._compact_marquee_default = False
            self._notification_sounds = True
            self._high_contrast = False
            self._reduced_motion = False
            self._ascii_only = False
            self._sidebar_file_preview = False
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
            self._lsp_status_title = ""
            self._bridge_identity = ""
        self._search_query = ""
        self._search_mode = False
        self._rail_view = "overview"
        self._rail_visible = False
        self._rail_auto_hidden = False
        self._rail_visibility_override: bool | None = None
        self._interrupted_turn: Any | None = None
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
        with Horizontal(id="workspace-layout"):
            with Vertical(id="main"):
                yield WorkList(id="work-list")
                yield ChatArea(id="chat")
                yield TasksPanel("", id="agent-tasks")
                with Vertical(id="composer"):
                    with Horizontal(id="queued-row"):
                        yield Static(tr(""), classes="queue-spacer")
                        with Vertical(id="queue-stack"):
                            yield QueuedBox(id="queued-box")
                            with Horizontal(id="queue-notice"):
                                yield Static(tr(""), id="queue-warning")
                                yield Button(tr("[?]"), id="queue-steer-help")
                        yield Static(tr(""), classes="queue-spacer")
                    with Horizontal(id="idea-box-row"):
                        yield ActivityStatus(tr("Chat ready"), id="activity-status")
                        yield IdeaBox(tr("Idea box\nCapture an idea · Ctrl+Shift+Enter"), id="idea-box", markup=False)
                        yield ShellBox(tr("ShellBox · no processes"), id="shell-box", markup=False)
                        yield Static(tr(""), id="usage-status")
                    yield OptionList(id="slash-suggestions")
                    yield PromptArea(id="prompt-input")
                    yield Static(tr("Enter send · Ctrl+J newline · Esc back · Ctrl+P commands · F1 help"), id="composer-hint")
                    with Horizontal(id="command-bar"):
                        yield Button(tr("Sidebar"), id="sidebar-button")
                        yield Button(tr("Sessions"), id="sessions-button")
                        yield Button(tr("Multi Harness"), id="harness-button")
                        # Preserve dynamic labels; these actions are in Settings.
                        yield Button(tr("Providers"), id="providers-button")
                        yield Button(tr("Role"), id="role-button")
                        yield Button(tr("Context"), id="context-button")
                        yield Button(tr("Inject context"), id="inject-context-button")
                        yield Button(tr("Model ▾"), id="model-button")
                        yield BarSpacer(id="bar-spacer")
                        yield Button("", id="mode-button")
                        yield Button(tr("⚙"), id="settings-button")
            yield SidePanel(id="side-panel")
        with Vertical(id="action-menu"):
            with Vertical(id="action-card"):
                yield Static(tr("Commands"), id="action-title")
                yield Static("", id="action-description")
                yield Input(placeholder=tr("Filter this list…"), id="action-search")
                with Horizontal(id="action-body"):
                    yield OptionList(id="settings-categories")
                    with Vertical(id="action-results"):
                        yield PreviewOptionList(id="action-list")
                        yield Static(tr(""), id="action-detail")
                yield Static(tr("↑↓ move · Enter open · Click preview · Double-click open · Esc back · Shift+Tab search"),
                             id="action-hint")
                with Vertical(id="key-entry"):
                    yield Static(tr("API key is stored outside this project."), id="key-entry-label")
                    yield Input(placeholder=tr("Paste API key…"), password=True, id="provider-key-input")
                    with Horizontal(id="key-entry-buttons"):
                        yield Button(tr("Save key"), id="save-provider-key", variant="primary")
                        yield Button(tr("Cancel"), id="cancel-provider-key")
        yield Footer(show_command_palette=False)

    def _apply_locale_chrome(self) -> None:
        """Refresh compose-time labels after the interface language changes."""
        buttons = {
            "#sidebar-button": "Sidebar",
            "#sessions-button": "Sessions",
            "#harness-button": "Multi Harness",
            "#providers-button": "Providers",
            "#role-button": "Role",
            "#inject-context-button": "Inject context",
            "#show-overview": "Overview",
            "#show-files": "Files",
            "#refresh-openisy": "Refresh integrations",
            "#file-up": "↑ Up",
            "#file-refresh": ("Refresh", "file rail"),
            "#workspace-folders": "Folders",
            "#file-copy-path": "Copy path",
            "#file-open-preview": ("Open preview", "file rail"),
            "#lsp-install-hint": "Install commands",
            "#save-provider-key": "Save key",
            "#cancel-provider-key": "Cancel",
        }
        for widget_id, msgid in buttons.items():
            msgid, context = msgid if isinstance(msgid, tuple) else (msgid, None)
            try:
                button = self.query_one(widget_id, Button)
                button.label = tr(msgid, context=context)
                if widget_id == "#file-up":
                    fit_rail_button(button, str(button.label))
            except (NoMatches, NoScreen, ScreenStackError):
                continue
        try:
            self.query_one("#context-button", Button).label = self._context_button_label()
        except (NoMatches, NoScreen, ScreenStackError):
            pass
        statics = {
            "#composer-hint": "Enter send · Ctrl+J newline · Esc back · Ctrl+P commands · F1 help",
            "#action-hint": "↑↓ move · Enter open · Click preview · Double-click open · Esc back · Shift+Tab search",
            "#key-entry-label": "API key is stored outside this project.",
            "#file-preview": "Select a file to preview it.",
        }
        for widget_id, msgid in statics.items():
            try:
                if widget_id == "#file-preview" and self._selected_file_path is not None:
                    continue
                self.query_one(widget_id, Static).update(tr(msgid))
            except (NoMatches, NoScreen, ScreenStackError):
                continue
        try:
            self.query_one(PromptArea).placeholder = tr(PromptArea.DEFAULT_PLACEHOLDER)
            self.query_one("#idea-box").border_title = tr("Idea · Space expand")
        except (NoMatches, NoScreen, ScreenStackError):
            pass
        try:
            self.query_one("#action-search", Input).placeholder = tr("Filter this list…")
        except (NoMatches, NoScreen, ScreenStackError):
            pass
        try:
            self.query_one("#provider-key-input", Input).placeholder = tr("Paste API key…")
        except (NoMatches, NoScreen, ScreenStackError):
            pass
        try:
            self.query_one("#file-search", Input).placeholder = tr("Search workspace paths…")
        except (NoMatches, NoScreen, ScreenStackError):
            pass
        try:
            self.query_one("#idea-box").update(
                tr("Idea box\nCapture an idea · Ctrl+Shift+Enter"))
        except (NoMatches, NoScreen, ScreenStackError):
            pass
        try:
            self.query_one("#shell-box").update(tr("ShellBox · no processes"))
        except (NoMatches, NoScreen, ScreenStackError):
            pass
        collapsibles = {
            "#rail-sentinel": "IsySentinel",
            "#rail-mcp": "MCPs",
            "#rail-lsp": "LSPs",
            "#rail-skills": "Skills",
            "#rail-connections": "Connections · 4",
            "#rail-gateway": "ISyCo Gateway",
            "#rail-gateway-mcp": "Gateway MCP",
            "#rail-mobile": "Mobile Host",
            "#rail-bridge": "Bridge Coordination",
            "#rail-workspace": "Workspace",
        }
        for widget_id, msgid in collapsibles.items():
            try:
                self.query_one(widget_id).title = tr(msgid)
            except (NoMatches, NoScreen, ScreenStackError):
                continue
        self._refresh_model_button()
        self._paint_idea_box()
        if self.query("#idle-board"):
            self._paint_idle()

    def on_mount(self) -> None:
        if self._high_contrast:
            self._apply_high_contrast(True)
        self._apply_sidebar_file_preview(self._sidebar_file_preview)
        self._refresh_usage()
        self._apply_locale_chrome()
        self._set_activity(tr("Chat ready"), MUTED)
        self.set_interval(1.0, self._paint_work_status)
        if _IS_WINDOWS and not self.is_headless:
            self.set_interval(0.5, self._sync_terminal_size)
        add_decision_listener(self._on_journal_decision)
        self.set_interval(5.0, self._paint_sentinel)   # permissions changed in Settings
        self.run_worker(self._load_sentinel_journal(), group="sentinel-journal",
                        exit_on_error=False)
        prompt = self.query_one("#prompt-input", PromptArea)
        self._paint_role_chrome()
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
        self._paint_workspace_chrome()
        self._apply_rail_width(self.size.width)
        if self.size.width < 80 or (self.size.width < 88 and self._rail_visibility_override is None):
            self._rail_auto_hidden = True
            self._rail_visible = False
            self.query_one(SidePanel).display = False
        self._mount_idle_board()
        self.sub_title = (tr("{name}  ·  workspace {workspace_root}  ·  launch {launch_dir}", name=self._workspace_root.name, workspace_root=self._workspace_root, launch_dir=self._launch_dir))
        self.query_one("#workspace-label", Static).update(tr("Workspace Root · {workspace_root}", workspace_root=self._workspace_root))
        self.query_one("#workspace-launch-label", Static).update(tr("Launch Directory · {launch_dir}", launch_dir=self._launch_dir))
        self.query_one("#workspace-source-label", Static).update(self._root_source_label())
        self._paint_workspace_chrome()
        self.query_one("#workspace-authority-label", Static).update(
            tr("Filesystem Authority · loading ISyCode grants…"))
        self._paint_rail_identity()
        commands = self._plugins.command_items()
        self._command_names = [name for name, _ in commands]
        self._command_entries = [
            {"label": f"/{name}  {tr(description)}", "kind": "command", "value": name}
            for name, description in commands
        ]
        # Without a read grant there is simply nothing to apply yet; printing that at
        # every start reads like an error. The reason stays available in Settings.
        if self._workspace_config_warning and "grant" not in self._workspace_config_warning:
            self._append_startup(f"  Workspace preferences · {self._workspace_config_warning[:200]}", YELLOW)
        self.run_worker(self._startup_workspace(), exclusive=True, group="workspace-startup",
                        exit_on_error=False)
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

    @property
    def ready(self) -> bool:
        """True once _startup_workspace has finished (successfully or not)."""
        return self._ready_event.is_set()

    async def wait_for_ready(self, timeout: float = 10.0) -> None:
        """Block until startup completes; TimeoutError means startup never finished."""
        await asyncio.wait_for(self._ready_event.wait(), timeout)

    def _register_saved_key_reader(self) -> None:
        """Security mode: every saved-key read is its own owned, journaled decision."""
        try:
            owner = CredentialUseOwner(self._workspace_root,
                                       WorkspaceAuthority(self._workspace_root))
        except (CredentialVaultError, WorkspaceAuthorityError, OSError, ValueError):
            set_saved_secret_reader(None)
            return
        set_saved_secret_reader(lambda service, consumer: owner.secret_for(service, consumer)[1])






    def on_key(self, event: Key) -> None:
        if (event.key == "question_mark" or getattr(event, "character", None) == "?") and not isinstance(self.focused, (Input, TextArea)):
            event.stop()
            event.prevent_default()
            self.action_quick_help()

    def _sync_terminal_size(self) -> None:
        """Re-issue a resize when the console grid changed behind Textual."""
        if not _IS_WINDOWS:
            return
        measured = _terminal_grid_size()
        if measured is None:
            return
        width, height = measured
        if (width, height) != (self.size.width, self.size.height):
            self.post_message(Resize.from_dimensions((width, height), None))

    def on_resize(self, event) -> None:
        if not self.is_mounted:
            return
        # The context bar is drawn to the column's width; redraw it once the new layout lands.
        self.call_after_refresh(self._refresh_usage)
        rail = self.query_one(SidePanel)
        self._paint_workspace_chrome()
        self._apply_rail_width(event.size.width)
        if event.size.width < 80:
            self._rail_auto_hidden = True
            self._rail_visible = False
            rail.display = False
        elif self._rail_visibility_override is not None:
            self._rail_visible = self._rail_visibility_override
            rail.display = self._rail_visible
        elif event.size.width < 88:
            self._rail_auto_hidden = True
            self._rail_visible = False
            rail.display = False
        elif event.size.width > 90:
            if self._rail_auto_hidden:
                self._rail_auto_hidden = False
                self._rail_visible = True
            rail.display = self._rail_visible
        self.call_after_refresh(self._paint_workspace_chrome)
        self.call_after_refresh(self._refresh_model_button)
        self.call_after_refresh(self._paint_idle)
        if getattr(self, "_menu_mode", ""):
            card = self.query_one("#action-card", Vertical)
            card.set_class(event.size.width >= 100 and self._menu_mode == "providers", "wide-detail-menu")
            card.set_class(event.size.width < 100, "compact-menu")
            self._size_action_menu()

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
        authority_text = (tr("Filesystem Authority · list/read/name-search granted for this workspace")
                          if enabled else
                          tr("Filesystem Authority · no read grant; tree enumeration is unavailable"))
        self.query_one("#workspace-authority-label", Static).update(authority_text)
        self._paint_rail_identity()
        await self._load_directory(self._file_path)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "review-cancel":
            request_task = self._review_request_task
            if request_task is not None and not request_task.done():
                request_task.cancel()
                event.button.disabled = True
                event.button.label = tr("Cancelling…")
                self._set_activity(
                    tr("Review cancelled · no automatic retry; inspect before requesting again"),
                    YELLOW)
        elif button_id == "rail-identity":
            self._show_identity()
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
            self._open_scoped_models(selected_provider_name())
        elif button_id == "role-button":
            self._open_role_menu()
        elif button_id == "settings-button":
            self._open_settings_menu()
        elif button_id == "mode-button":
            self.run_worker(self._switch_mode_from_chip(), exclusive=True, group="authority-grant")
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
                self._set_activity(tr("Review copied to composer · edit it, then press Enter to send"), YELLOW)
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

    def action_quick_help(self) -> None:
        from isycode.tui_screens_help import QuickHelpScreen
        self.push_screen(QuickHelpScreen())

    def notify_semantic(
        self,
        message: str,
        kind: str = "info",
        *,
        title: str = "",
        timeout: float | None = None,
    ) -> None:
        """Present a semantic toast notification with unified severity prefixes and calibrated timeouts."""
        from isycode.tui_theme import ascii_only
        use_ascii = ascii_only()

        semantics = {
            "success": ("✓ ", "[OK] ", "information", 3.0),
            "authorized": ("⚡ ", "[AUTH] ", "information", 3.0),
            "info": ("ℹ ", "[INFO] ", "information", 3.0),
            "warning": ("! ", "[WARN] ", "warning", 4.5),
            # F-07: security-policy DENY gets its own severity so the toast is
            # orange, distinct from operational errors (severity "error").
            "denied": ("× ", "[DENY] ", "security-denied", 5.5),
            "error": ("× ", "[ERROR] ", "error", 5.5),
        }
        u_pfx, a_pfx, def_sev, def_timeout = semantics.get(kind, ("ℹ ", "[INFO] ", "information", 3.0))
        prefix = a_pfx if use_ascii else u_pfx
        calibrated_timeout = timeout if timeout is not None else def_timeout
        self.notify(f"{prefix}{message}", title=title, severity=def_sev, timeout=calibrated_timeout)

    @staticmethod
    def _provider_failure(error: ProviderError, operation: str) -> str:
        """Translate provider failures without rendering URLs or response bodies."""
        from isycode.provider_errors import classify_provider_error
        detail = classify_provider_error(error)
        suffix = f" · HTTP {detail['http_status']}" if detail["http_status"] else ""
        if detail["provider_code"]:
            suffix += " · " + detail["provider_code"]
        if detail["retry_after_s"] is not None:
            suffix += " · " + tr("retry after {seconds}s", seconds=f"{detail['retry_after_s']:g}")
        return tr("{operation} failed · {kind}: {hint}{suffix}.", operation=tr(operation),
                  kind=detail["error_kind"], hint=tr(detail["provider_hint"]), suffix=suffix)

    @staticmethod
    def _model_display_label(name: str, model: str) -> str:
        from isycode.model_presentation import model_display_name
        from isycode.reasoning_options import reasoning_label
        preset = PRESETS.get(name, {})
        effort = reasoning_label(name, model, preset.get("reasoning_effort"))
        return f"{model_display_name(model)} / {tr(effort.capitalize())} · {preset.get('label', name)}"

    def _role_button_label(self) -> str:
        if not self._active_role:
            return "Role"
        name = self._active_role["name"]
        return f"Role: {name[:12]}"

    @property
    def _active_role(self) -> dict[str, str] | None:
        return getattr(self, "_active_role_value", None)

    @_active_role.setter
    def _active_role(self, role: dict[str, str] | None) -> None:
        # Every way of choosing a role (menu, Shift+Tab, session restore,
        # default) repaints the composer, so its color never goes stale.
        self._active_role_value = role
        self._paint_role_chrome()

    def _role_mark(self, name: str) -> str:
        return ("* " if self._ascii_only else "● ") + name

    def _paint_role_chrome(self) -> None:
        """Frame the composer in the selected role's color and name it in the title."""
        try:
            prompt = self.query_one("#prompt-input", PromptArea)
        except Exception:   # before compose, or while the app tears down
            return
        role = self._active_role
        color = role_color(role["name"]) if role else None
        if color is None:
            prompt.styles.border = None     # back to the stylesheet's neutral/focus frame
            prompt.border_title = None
            prompt.border_subtitle = None
        else:
            prompt.styles.border = ("solid", color)
            prompt.border_title = Text(self._role_mark(role["name"]), style=f"bold {color}")
            prompt.border_subtitle = Text(tr("Shift+Tab role"), style=MUTED)
        try:
            self.query_one("#role-button", Button).label = self._role_button_label()
        except Exception:
            pass

    def _paint_role_turn(self, widget, role_name: str | None) -> None:
        """Mark an assistant answer with the color of the role that wrote it."""
        color = role_color(role_name)
        if color is not None:
            widget.styles.border_left = ("solid", color)
            widget.styles.padding = (0, 0, 0, 1)

    def _assistant_clock(self, clock: str, role_name: str | None) -> Static:
        """The time above an answer, followed by its role so it reads without color."""
        line = Text(clock, style=MUTED)
        color = role_color(role_name)
        if color is not None:
            line.append("  " + self._role_mark(role_name), style=color)
        return Static(line, classes="message-clock")

    def action_cycle_role(self) -> None:
        """Shift+Tab in the main chat: next primary role, then back to no role.

        Uses the same role contract as the Role menu: the role's workflow is
        sent as guidance with the next message and grants nothing. It works
        wherever focus sits in the chat (composer, command bar, rail); a
        dialog or the command menu keeps Shift+Tab for its own focus moves.
        """
        if isinstance(self.screen, ModalScreen) or self.query_one("#action-menu").display:
            raise SkipAction()
        current = self._active_role["name"] if self._active_role else None
        names = [role["name"] for role in ROLE_CYCLE]
        index = names.index(current) + 1 if current in names else 0
        if index >= len(names):
            self._active_role = None
            self._set_activity(tr("Role · none"), MUTED)
            return
        role = ROLE_CYCLE[index]
        self._active_role = {
            "name": role["name"], "kind": role["kind"],
            "description": role.get("description", ""),
            "engine": role.get("engine", "ISyCode selected provider and model"),
        }
        self._set_activity(tr("Role · {name}", name=role["name"]), role_color(role["name"]) or GREEN)

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
        if getattr(self, "_rail_visible", False) and getattr(self, "size", None) and self.size.width < 100:
            self.action_toggle_sidebar()
            return
        if self._review_request_task and not self._review_request_task.done():
            self._review_request_task.cancel()
            self._set_activity(tr("Stopping external review…"), YELLOW)
            return
        if self._subagent_task and not self._subagent_task.done():
            self._subagent_task.cancel()
            self._set_activity(tr("Stopping subagent…"), YELLOW)
            return
        if self._chat_turn_task and not self._chat_turn_task.done():
            # Stops the whole agent turn: a pending model request, a tool, or a running command.
            note_cancel_requested(self._chat_turn_task)
            self._chat_turn_task.cancel()
            self._set_activity(tr("Stopping response…"), YELLOW)
            return
        if self._chat_request_task and not self._chat_request_task.done():
            self._chat_request_task.cancel()
            self._set_activity(tr("Stopping response…"), YELLOW)
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
        if event.option_list.id == "settings-categories":
            event.stop()
            self.query_one("#action-list", OptionList).focus()
            return
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




    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "action-search" and self._menu_mode:
            query = event.value.casefold().strip()
            self._render_options(query)
        elif event.input.id == "provider-key-input":
            # Input uses password mode; don't reflect its value into status/UI.
            return

    # ── semantic navigation and account menus ─────────────────────

    @staticmethod
    def _entry(label: str, kind: str, value: str = "", detail: str = "",
               *, translate: bool = True) -> dict[str, str]:
        return {"label": tr(label) if translate else label, "kind": kind,
                "value": value,
                "detail": tr(detail) if translate and detail else detail}

    @staticmethod
    def _capability_entry(label: str, value: str, enabled: bool,
                          detail: str = "") -> dict[str, str | bool]:
        return {"label": tr(label), "kind": "authority_toggle", "value": value,
                "detail": tr(detail) if detail else detail, "enabled": enabled,
                "display_value": tr("ON") if enabled else tr("OFF")}


    def _open_role_menu(self) -> None:
        entries = [
            self._entry("ISyCode agents", "role_category", "agents"),
            self._entry("ISyCode specialists", "role_category", "subagents"),
            self._entry("ISyCo CLI motors", "role_category", "motors"),
        ]
        if self._active_role:
            entries.insert(0, self._entry(
                tr("Current · {name} ({kind})",
                   name=self._active_role['name'], kind=self._active_role['kind']),
                "info", "", self._active_role.get("description", ""),
                translate=False))
        self._menu_stack = []
        self._render_menu("roles_root", "Role · choose a catalog", entries)

    def _open_settings_menu(self) -> None:
        from isycode.rtk_integration import Settings as RTKSettings
        try:
            rtk_label = tr("on") if RTKSettings().load()["enabled"] else tr("off")
        except (OSError, ValueError):
            rtk_label = tr("needs attention")
        on = tr("on")
        off = tr("off")
        entries = [
            self._entry(tr("RTK compression · {state}", state=rtk_label), "rtk_settings", "",
                        "Compression by RTK · https://github.com/rtk-ai/rtk · permissions unchanged."),
            self._entry(tr("Providers & models"), "providers_open", ""),
            self._entry("Model", "models_open", ""),
            self._entry(tr("Reasoning level"), "reasoning_open", ""),
            self._entry(tr("Notification sounds · {state}",
                           state=on if self._notification_sounds else off), "sounds_toggle", "",
                        "Distinct bell rhythms for completion, approval, questions and errors; requires terminal audible bell."),
            self._entry(tr("Reduced motion · {state}", state=on if self._reduced_motion else off), "motion_toggle", "",
                        "Keep activity symbols static and disable compact text scrolling."),
            self._entry(tr("High contrast display · {state}",
                           state=on if self._high_contrast else off), "contrast_toggle", "",
                        "Brighten text and focused frames while keeping the shared black surfaces."),
            self._entry(tr("ASCII-only display · {state}",
                           state=on if self._ascii_only else off), "ascii_toggle", "",
                        "Plain [x]/[ ]/[ON]/[OFF] marks instead of Unicode glyphs, for terminals without Unicode."),
            self._entry(tr("Language · {name}",
                           name=tr(language_msgid(self._locale))),
                        "locale_cycle", "",
                        tr("Interface language for ISyCode. This does not change permissions or workspace files.")),
            self._entry(tr("Choose role"), "roles_open", ""),
            self._entry(tr("Context"), "context_menu", ""),
            self._entry(tr("My defaults · all workspaces"), "user_defaults", ""),
            self._entry(tr("Compact text scroll · {state}",
                           state=on if self._compact_marquee_default else off),
                        "marquee_toggle", ""),
            self._entry(tr("Sidebar file preview · {state}",
                           state=on if self._sidebar_file_preview else off),
                        "sidebar_preview_toggle", "",
                        tr("Show a preview box below the file tree in the sidebar.")),
        ]
        if is_isycode_checkout(self._workspace_root):
            entries.append(self._entry(tr("GUS model · {model}", model=self._gus_slot_label()),
                                       "gus_slot_open", ""))
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
            self._entry(tr("Workflow"), "workflow_open", ""),
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
                "models_open": "Choose the model used for this conversation.",
                "reasoning_open": "Choose supported reasoning settings for the active provider and model.",
                "gus_slot_open": "The model GUS uses to maintain ISyCode: another provider or a local model, 32k tokens or more.",
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
                "contrast_toggle": "Brighten text and focused frames while keeping the shared black surfaces.",
                "ascii_toggle": "Replace ✓/✗/●/○ and the banner art with plain ASCII marks for terminals without Unicode.",
                "marquee_toggle": "Scroll completed text in collapsed headers. Use Space to expand a box. Reduced motion disables this scrolling.",
                "sidebar_preview_toggle": "Show a preview box below the file tree in the sidebar.",
                "locale_cycle": tr("Interface language for ISyCode. This does not change permissions or workspace files."),
            }),
            tr("Permissions"): (YELLOW, {
                "workflow_open": "Choose Classic, Flow or Security for this workspace.",
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
                    entry["category_id"] = next(part for part in ("Conversation", "Preferences", "Permissions", "Connections") if tr(part) == category)
                    entry["color"] = color
                    entry["detail"] = tr(descriptions[entry["kind"]])
                    ordered.append(entry)
        for entry in entries:
            if entry not in ordered:
                entry["category"] = tr("Preferences")
                entry["category_id"] = "Preferences"
                ordered.append(entry)
        from isycode.reasoning_options import reasoning_label
        from isycode.model_presentation import model_display_name
        provider = selected_provider_name()
        model = resolved_chat_model(provider)
        provider_label = next((label for _, key, label, _ in PROVIDER_SCREEN if key == provider), provider)
        context = getattr(self, "_agent_context", None)
        values = {
            "providers_open": ("Provider", provider_label),
            "models_open": ("Model", model_display_name(model)),
            "reasoning_open": ("Reasoning level", tr(reasoning_label(
                provider, model, PRESETS.get(provider, {}).get("reasoning_effort")))),
            "roles_open": ("Role", self._active_role["name"] if self._active_role else tr("None")),
            "context_menu": ("Context", tr("Loaded") if context else tr("None")),
            "context_inject": ("Context file", context["path"] if context else tr("None")),
            "clear_role": ("Clear selected role", tr("Selected") if self._active_role else tr("None")),
            "rtk_settings": ("RTK compression", rtk_label),
            "sounds_toggle": ("Notification sounds", on if self._notification_sounds else off),
            "motion_toggle": ("Reduced motion", on if self._reduced_motion else off),
            "contrast_toggle": ("High contrast display", on if self._high_contrast else off),
            "ascii_toggle": ("ASCII-only display", on if self._ascii_only else off),
            "locale_cycle": ("Language", tr(language_msgid(self._locale))),
            "marquee_toggle": ("Compact text scroll", off if self._reduced_motion else on if self._compact_marquee_default else off),
            "sidebar_preview_toggle": ("Sidebar file preview", on if self._sidebar_file_preview else off),
            "user_defaults": ("My defaults", tr("All workspaces")),
            "workspace_config_preferences": ("Workspace preferences", tr("This workspace")),
            "workflow_open": ("Workflow", self._workspace_mode().title()),
            "authority_open": ("Authority & Security", self._workspace_mode().title()),
            "shortcuts": ("Commands & shortcuts", tr("Browse")),
            "named_credentials": ("Named API keys", tr("Manage")),
            "security_journal": ("Action journal", tr("Inspect")),
            "folders_open": ("Workspace folders", tr("Review")),
            "harness_open": ("Multi Harness", tr("Inspect")),
            "files": ("Workspace files", tr("Browse")),
            "integrations_open": ("Integrations", "MCP / LSP / Gateway"),
        }
        for entry in ordered:
            name, current = values.get(entry["kind"], (entry["label"], tr("Review")))
            entry["label"] = tr(name)
            entry["display_value"] = current
            if entry["kind"] == "models_open":
                entry["search_value"] = model
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
            entries = [self._entry(
                tr("Workspace preferences unavailable · {error}", error=issue[:140]),
                "info", translate=False)]
        elif parsed is None:
            entries = [self._entry("Initialize .isycode/ before saving preferences.", "info")]
        elif not parsed.valid:
            entries = [self._entry(
                tr("Config ignored · {error}", error=parsed.error[:140]),
                "info", translate=False)]
        else:
            entries = [self._entry(
                tr("Config warning · {error}", error=warning[:140]),
                "info", translate=False)
                       for warning in parsed.warnings]
            if self._active_role:
                entries.append(self._entry(
                    tr("Use {name} as this workspace's default role",
                       name=self._active_role['name']),
                    "workspace_pref_role", "", translate=False))
            if parsed.values.get("default_role"):
                entries.append(self._entry("Clear this workspace's default role",
                                           "workspace_pref_role_clear", ""))
        entries.append(self._entry(tr("Back to Settings"), "settings_back", ""))
        if self._menu_mode != "workspace_config":
            self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("workspace_config", "Settings · Workspace preferences", entries)






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
                status = tr("Browse") if available else tr("Unavailable")
                entries.append(self._entry(
                    tr("{status} {alias} · {path}", status=status, alias=alias, path=item['path']),
                    "folder_browse" if available else "info", alias, translate=False))
                if item['editable'] and available:
                    enabled = store.auto_edit_allowed(alias)
                    automatic_available = store.auto_edit_available(alias)
                    if not automatic_available:
                        state = tr("OFF · Security requires each review")
                    elif enabled:
                        state = tr("ON — dangerous; disable")
                    else:
                        state = tr("OFF — enable…")
                    entries.append(self._entry(
                        tr("{alias} · automatic edits {state}", alias=alias, state=state),
                        'info' if not automatic_available else 'folder_auto_off' if enabled else 'folder_auto_on', alias,
                        tr("Only file creation/edits. Authority and ISySentinel stay active."),
                        translate=False))
                if alias != 'main':
                    entries.append(self._entry(
                        tr("Remove attachment · {alias}", alias=alias), "folder_remove", alias,
                        tr("Files and standalone workspace settings are kept. This chat loses access."),
                        translate=False))
        except (OSError, ValueError) as exc:
            entries.append(self._entry(
                tr("Folder settings unavailable · {error}", error=str(exc)[:140]),
                "info", translate=False))
        self._menu_stack = []
        self._render_menu('workspace_folders', 'Workspace folders · explicit access', entries)







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
        if (total == 0 and not self._history and self._throughput.last_rate is None
                and not self._usage.requests and not self._usage.unknown_requests):
            # Nothing has run yet. Three rows of zeros are noise, not telemetry.
            # A recorded request keeps its panel even when the provider did not
            # report its counters, because an unknown count is real information.
            widget.update("")
            return
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



































    def _push_models_screen(self, entries: list[dict[str, str]]) -> None:
        # Entries may have been refreshed (a catalog load finished) while the
        # push was pending; open the latest ones, exactly once.
        pending = getattr(self, "_models_screen_pending", None)
        self._models_screen_pending = None
        self.push_screen(ModelsScreen(pending if pending is not None else entries,
                                      provider_scope=getattr(self, "_models_scope", None)),
                         self._model_picker_result)

    def _render_menu(self, mode: str, title: str, entries: list[dict[str, str]]) -> None:
        source_title = title
        display_title = tr(title)
        if mode == "branch" and source_title == "Models":
            # A provider-scoped picker loads that provider's catalog, not the active one.
            name = getattr(self, "_models_scope", None) or selected_provider_name()
            attempted = getattr(self, "_account_models_attempted", set())
            if name not in attempted:
                self._account_models_attempted = attempted | {name}
                self._account_models_loading = True
                self.run_worker(self._load_account_models(name), exclusive=True, group="provider-models")
        self._menu_mode = mode
        self._menu_title = display_title
        self._menu_entries = entries
        if (mode == "branch" and source_title == "Models") or mode == "model_account":
            existing = next((screen for screen in reversed(self.screen_stack)
                             if isinstance(screen, ModelsScreen)), None)
            if existing is not None:
                existing.entries = entries
                if mode == "branch" and source_title == "Models":
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
        card.set_class(mode == "settings", "settings-menu")
        card.set_class(self.size.width >= 100 and mode == "providers", "wide-detail-menu")
        card.set_class(self.size.width < 100, "compact-menu")
        categories = self.query_one("#settings-categories", OptionList)
        categories.display = mode == "settings"
        if mode == "settings":
            names = list(dict.fromkeys(entry.get("category_id", "Preferences") for entry in entries))
            self._settings_categories = names
            if self._settings_category not in names:
                self._settings_category = names[0] if names else ""
            categories.clear_options()
            categories.add_options([tr(name) for name in names])
            categories.highlighted = names.index(self._settings_category) if names else None
        if mode == "providers":
            card.add_class("provider-menu")
        else:
            card.remove_class("provider-menu")
        menu = self.query_one("#action-menu", Vertical)
        menu.display = True
        heading = MenuHeading(display_title, tr(self._settings_category) if mode == "settings" else "")
        self.query_one("#action-title", Static).update(heading)
        description = self.query_one("#action-description", Static)
        description.display = mode == "settings"
        description.update(tr("Personalize ISyCode for this workspace."))
        search = self.query_one("#action-search", Input)
        search.display = True
        search.value = ""
        self.query_one("#action-list", OptionList).display = True
        self.query_one("#key-entry", Vertical).display = False
        self._render_options("")
        hint = (tr("↑↓ move · Enter choose · Click preview · Esc back · Shift+Tab search")
                if mode == "providers" else
                tr("↑↓ move · Enter open · Esc back · Shift+Tab search"))
        self.query_one("#action-hint", Static).update(hint)
        self.query_one("#action-list", OptionList).focus()




    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "settings-categories" and self._menu_mode == "settings":
            names = getattr(self, "_settings_categories", [])
            if 0 <= event.option_index < len(names) and self._settings_category != names[event.option_index]:
                self._settings_category = names[event.option_index]
                self._render_options(self.query_one("#action-search", Input).value.casefold())
        if event.option_list.id == "action-list":
            self._show_menu_detail(event.option_index)

    def _close_menu(self) -> None:
        self.query_one("#action-menu", Vertical).display = False
        self.query_one("#key-entry", Vertical).display = False
        self._menu_stack = []
        self._menu_mode = ""
        self._models_scope = None
        self._models_return_settings = False
        self.query_one("#prompt-input", PromptArea).focus()


    def _branch_entries(self, branch: str) -> list[dict[str, str]]:
        key = branch.casefold()
        if key == "skills":
            from isycode.skill_catalog import skills
            entries = [self._entry("Clear selected skills", "skill_clear", "",
                                  "Skills guide the current chat; they do not add tools or authority.")]
            entries.extend(self._entry(
                tr("{name} · active", name=name) if name in self._active_skills else name,
                "skill_use", name,
                tr("Superpowers · pinned MIT Markdown; select to toggle guidance for this chat"),
                translate=False)
                for name in skills())
            snapshot = self._skill_snapshot
            if snapshot.state == "ready":
                entries.extend(self._entry(
                    tr("{name} · discovered", name=item['name']), "info", "",
                    item.get("description", ""), translate=False) for item in snapshot.items)
            return entries
        if key == "models":
            active_provider = selected_provider_name()
            current = selected_model_name()
            models = [self._entry(
                tr("Load account models · {provider}", provider=active_provider),
                "model_list", active_provider,
                tr("Makes a read-only catalog request only after you select this item."),
                translate=False)]
            from isycode.providers import recent_models
            models.extend(self._entry(
                tr("Recent · {provider} · {model}  · recent",
                   provider=item['provider'], model=item['model']),
                "model", f"{item['provider']}|{item['model']}",
                tr("Previously selected model; not verified against this account."),
                translate=False)
                for item in recent_models())
            denied = getattr(self, "_account_model_denied", None)
            if denied:
                models.append(self._entry(
                    tr("Grant network access to {label} and load its real catalog",
                       label=PRESETS.get(denied, {}).get('label', denied)),
                    "provider_catalog_grant", denied,
                    tr("The live catalog request was denied; this asks once, saves the host grant for this workspace, and reloads the provider's real models."),
                    translate=False))
            for name, preset in PRESETS.items():
                model = resolved_chat_model(name)
                selected = name == active_provider and (not current or model == current)
                if name == active_provider and current:
                    model = current
                    selected = True
                models.append(self._entry(
                    tr("{label}  ·  {model}  ◂ current  · preset",
                       label=preset['label'], model=model)
                    if selected else
                    tr("{label}  ·  {model}  · preset",
                       label=preset['label'], model=model),
                    "model", f"{name}|{model}",
                    tr("Hardcoded preset model, not verified against this account; load the account catalog for the provider's real list."),
                    translate=False))
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
                    tr("Current model {model} is not in the refreshed {label} "
                       "catalog · still selected · choose a replacement explicitly",
                       model=active_model, label=PRESETS[active_provider]['label']),
                    "info", translate=False))
            from isycode.model_catalog import catalog_models
            for name in PRESETS:
                if name in live_catalogs:
                    continue
                for entry in catalog_models(name):
                    marker = "" if entry["tool_call"] else tr("  ⚠ no tools")
                    models.append(self._entry(
                        tr("{label}  ·  {model}{marker}  · catalog",
                           label=PRESETS[name]['label'], model=entry['id'], marker=marker),
                        "model", f"{name}|{entry['id']}",
                        tr("models.dev snapshot (offline; not verified against this account). reasoning={value} · context={value2} · tool_call={value3}", value=tr("yes") if entry['reasoning'] else tr("no"), value2=entry['context'] or '?', value3=tr("yes") if entry['tool_call'] else tr("NO — chat needs tools")),
                        translate=False))
            from isycode.providers import custom_models
            listed_values = {row["value"] for row in models if row["kind"] == "model"}
            for name in PRESETS:
                for model_id in custom_models(name):
                    if f"{name}|{model_id}" in listed_values:
                        continue
                    row = self._entry(
                        tr("{label}  ·  {model}  · added by you",
                           label=PRESETS[name]['label'], model=model_id),
                        "model", f"{name}|{model_id}",
                        tr("Model ID you added; not verified against this account."),
                        translate=False)
                    row["custom"] = True
                    models.append(row)
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
                visible.append(self._entry(
                    tr("{count} unavailable in tested endpoint · retained in capability results",
                       count=len(unavailable)),
                    "info", "", "".join(row["value"] + "\n" for row in unavailable),
                    translate=False))
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
                        tr("Manage broker · {name} · {status}",
                           name=Path(broker['project_root']).name, status=broker['status']),
                        "broker_manage", broker["project_root"],
                        tr("{container} · 127.0.0.1:{host_port} · recipe {value}", container=broker['container'], host_port=broker['host_port'], value=broker['recipe_digest'][:12]),
                        translate=False))
            except (OSError, RuntimeError, TypeError, ValueError):
                entries.append(self._entry(
                    "Managed broker inventory unavailable", "info", "",
                    "Private state could not be read; no Docker action is available."))
            if snap.state == "ready":
                entries.extend(self._entry(
                    tr("{name}  ·  {status}", name=item['name'], status=item['status']),
                    "info", "",
                    tr("Listed by the connected service; discovery does not authorize calls."),
                    translate=False)
                    for item in snap.items)
            elif snap.state not in {"not_checked", "not_configured"}:
                entries.append(self._entry(
                    tr("Configured services · {state}",
                       state=snap.state.replace('_', ' ')),
                    "info", "", snap.detail, translate=False))
            gateway = self._gateway_mcp_snapshot
            if gateway.state == "ready":
                entries.extend(self._entry(
                    tr("ISyCo Gateway · {name}", name=item["name"]),
                    "gateway_mcp_tool", item["name"],
                    (tr("{value} · Enter to review arguments and request a one-use approval", value=str(item.get("description", "No description supplied."))[:1200])),
                    translate=False)
                    for item in gateway.items)
            elif gateway.state not in {"not_checked", "not_configured"}:
                entries.append(self._entry(
                    tr("ISyCo Gateway MCP · {state}",
                       state=gateway.state.replace('_', ' ')),
                    "info", "", gateway.detail, translate=False))
            from isycode.mcp_presets import PRESETS as MCP_PRESETS
            entries.extend(self._entry(
                tr("Add {name} preset", name=name), "mcp_preset", name, preset["description"],
                translate=False)
                           for name, preset in MCP_PRESETS.items())
            return entries
        if key == "lsp":
            entries = []
            for server in self._lsp_inventory:
                if server["state"] == "sandbox_ready":
                    entries.append(self._entry(
                        tr("{label} · {status}",
                           label=server['label'], status=tr("workspace symbol search")),
                        "lsp_server", server["id"],
                        tr("Real LSP initialize + workspace/symbol, read-only .isyroot mount, no network; each request needs a grant and one-use approval."),
                        translate=False))
                else:
                    entries.append(self._entry(
                        tr("{label} · {status}",
                           label=server['label'],
                           status=tr(server['state'].replace('_', ' '))),
                        "info", "",
                        tr("Detected executable only; no safe LSP execution adapter is connected for this server."),
                        translate=False))
            return entries or [self._entry("No LSP servers detected", "info", "", "Install or configure a supported language server.")]
        if key == "files":
            return [self._entry("Open workspace file browser", "files"),
                    self._entry(
                        tr("Current Directory · {path}",
                           path=self._file_path or self._workspace_root),
                        "info", translate=False)]
        if key == "roles":
            return [self._entry("ISyCode agents", "role_category", "agents"),
                    self._entry("ISyCode specialists", "role_category", "subagents"),
                    self._entry("ISyCo CLI motors", "role_category", "motors")]
        if key == "providers":
            return [self._entry("Open provider selector", "providers_open"),
                    self._entry("OAuth methods", "oauth_info", "Provider accounts", self._provider_auth_snapshot.detail or self._provider_auth_snapshot.state)]
        if key == "session":
            return [self._entry("/help", "command", "help"),
                    self._entry(
                        tr("Provider · {name}", name=selected_provider_name()),
                        "providers_open", translate=False),
                    self._entry(
                        tr("Role · {name}", name=self._role_button_label()),
                        "info", translate=False)]
        if key == "workspace":
            return [self._entry(
                        tr("Workspace Root · {path}", path=self._workspace_root),
                        "info", translate=False),
                    self._entry(
                        tr("Launch Directory · {path}", path=self._launch_dir),
                        "info", translate=False),
                    self._entry(
                        tr("Root Source · {source}",
                           source=self._workspace_identity.workspace_root_source),
                        "info", translate=False),
                    self._entry(
                        tr("Gateway Binding · {id}",
                           id=gateway_workspace_id(self._workspace_root)),
                        "info", "",
                        tr("Opaque workspace match label; it does not grant access."),
                        translate=False),
                    self._entry(
                        tr("Current Folder · {path}",
                           path=self._file_path or self._workspace_root),
                        "info", translate=False),
                    self._entry("Open Files view", "files")]
        if key == "commands":
            return self._command_entries + [self._entry("Keyboard shortcuts", "shortcuts")]
        return []

    # ── helpers ──────────────────────────────────────────────────


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


    def _idle_mounted(self) -> bool:
        try:
            board = self.query_one("#idle-board", IdleBoard)
        except (NoMatches, NoScreen, ScreenStackError):
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
        except (NoMatches, NoScreen, ScreenStackError):
            return
        if board.is_mounted and not board.has_class("startup-archived"):
            board.add_class("startup-archived")
            self.query_one(ChatArea).resume_tail()

    def _paint_idle(self) -> None:
        if not self.is_mounted:
            return
        try:
            board = self.query_one("#idle-board", IdleBoard)
        except (NoMatches, NoScreen, ScreenStackError):
            return
        if not board.is_mounted or board.has_class("startup-archived"):
            return
        if getattr(self, "size", None) and self.size.height <= 28:
            board.styles.height = 2
            board.styles.padding = (0, 0)
        else:
            board.styles.height = "auto"
            board.styles.padding = (0, 1, 1, 1)
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





    def _start_operation(self, coroutine, label: str) -> None:
        self._activity_label = label
        self._activity_frame = 0
        self._set_activity(label, CYAN)
        timer = getattr(self, "_activity_timer", None)
        if timer is not None:
            timer.stop()
        self._activity_timer = None if self._reduced_motion else self.set_interval(0.12, self._animate_activity)
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

    def notify(self, message, *, title=tr(""), severity="information", timeout=None,
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
                self._set_activity(tr("Interrupted"), YELLOW)
            elif failed is not None:
                self._set_activity(tr("Failed · {name}", name=type(failed).__name__), RED)
            elif self._last_plan is not None:
                self._set_activity(tr("Plan ready · review it in Overview"), YELLOW)
            else:
                self._set_activity(tr("Chat ready"), MUTED)
            self._paint_idea_box()
            if self._idea_backlog:
                self.notify(tr("{len} captured ideas · /ideas reviews and promotes", len=len(self._idea_backlog)))
            return
        if not followed:
            if cancelled:
                lane.activity_message = "Interrupted"
                lane.activity_color = YELLOW
            elif failed is not None:
                lane.activity_message = tr("Failed · {kind}", kind=type(failed).__name__)
                lane.activity_color = RED
            else:
                lane.activity_message = tr("Chat ready")
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

    def push_screen(self, screen, callback=None, wait_for_dismiss=False, *, mode=None):
        """Keep a modal card inside the main column instead of over the rail.

        Modal screens center their card on the whole terminal, so a wide rail
        used to be painted over and its labels were clipped mid-word. Reserve
        the visible rail width as right padding: the card stays legible and the
        rail keeps its content behind the overlay.
        """
        if isinstance(screen, ModalScreen):
            self._reserve_rail_for_modal(screen)
        return super().push_screen(screen, callback, wait_for_dismiss, mode=mode)

    def _reserve_rail_for_modal(self, screen: ModalScreen) -> None:
        """Pad a modal screen on the right by the visible rail width."""
        if not getattr(self, "_rail_visible", False):
            return
        try:
            rail = self.query_one(SidePanel)
            main = self.query_one("#main", Widget)
        except Exception:
            return
        if not rail.display or not main.display:
            return
        width = int(rail.outer_size.width or 0)
        if width <= 0:
            width = int(getattr(self, "_rail_width", 0) or 0)
        if width <= 0:
            return
        # Keep the dialog readable: a card squeezed into a narrow column wraps
        # the copy into more lines than it can show. The rail is only reserved
        # when the main column still has room for a normal-width dialog.
        available = int(self.size.width or 0) - width
        if available < 60:
            return
        screen.styles.padding = (0, width, 0, 0)

    async def _await_screen(self, screen: Any) -> Any:
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

        # Await both the modal and its descendants before the caller continues.
        # Otherwise a fast second modal can receive input before its controls
        # have mounted (the race is especially visible on Windows).
        await self.push_screen(screen, finished)
        return await future

    def _animate_activity(self) -> None:
        if self._reduced_motion or self._loop_task is None or self._loop_task.done():
            return
        from isycode.cat_activity import walking_cat
        self._activity_frame += 1
        try:
            status = self.query_one("#activity-status", Static)
            status.update(walking_cat(status.content_size.width, self._activity_frame))
        except (NoScreen, ScreenStackError):
            pass


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



    # ── chat (default path) ──────────────────────────────────────





















    def on_text_selected(self, event) -> None:
        """Selection marks a range. Ctrl+C or an explicit menu choice copies it."""

    def _folder_store(self) -> WorkspaceFolders:
        return WorkspaceFolders(self._workspace_root)

    async def _browse_workspace_folder(self, alias: str) -> None:
        try:
            root = self._folder_store().resolve(alias)
        except (OSError, ValueError) as exc:
            self._append("  " + tr("Folder unavailable · {value}", value=str(exc)[:160]), YELLOW)
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

    async def _initialize_workspace_config(self) -> None:
        if self._workspace_identity.workspace_root_source != "isyroot":
            self._append("  " + tr(".isycode/ is available only in a workspace with its own .isyroot marker."),
                         YELLOW)
            return
        try:
            owner = WorkspaceConfigOwner(self._workspace_root,
                                         WorkspaceAuthority(self._workspace_root),
                                         self._action_approvals)
            plan = await asyncio.to_thread(owner.prepare_initialization)
        except (OSError, ValueError) as exc:
            self._append("  " + tr("Workspace config unavailable · {value}", value=str(exc)[:180]), YELLOW)
            return
        if not plan.previews:
            self._append(f"  {plan.message}", YELLOW if plan.message else MUTED)
            return
        if plan.message:
            self._append(f"  {plan.message}", MUTED)
        for preview in plan.previews:
            if not await self._await_screen(WriteApprovalScreen(preview)):
                self._append("  " + tr("Initialization stopped · {path} unchanged", path=preview.path), MUTED)
                return
            approval = self._action_approvals.issue(preview.request, ttl_seconds=60)
            outcome = await asyncio.to_thread(owner.apply, preview, approval)
            if outcome.decision != "ALLOW":
                self._append("  " + tr("Workspace setup {decision} · {value}", decision=outcome.decision, value=outcome.reason[:180]), YELLOW)
                return
            self._append("  " + tr("{text} · receipt {receipt_id}", text=outcome.text, receipt_id=outcome.receipt.receipt_id), GREEN)
        self._workspace_config_values = None
        self._workspace_config_warning = ""
        self._active_role = self._load_global_default_role()

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
            self._set_activity(tr("Default mode saved for new workspaces"), GREEN)
        except (OSError, ValueError, json.JSONDecodeError):
            self._set_activity(tr("Could not save the default mode; existing settings remain"), RED)
        self._open_user_defaults_menu()

    async def _set_global_workspace_default(self, value: str) -> None:
        if value == "recurring":
            accepted = await self._await_screen(GlobalRecurringDefaultScreen())
            if not accepted:
                self._open_user_defaults_menu()
                return
        try:
            UserDefaultsStore().update(new_workspace=value)
            self._set_activity(tr("Default saved for new workspaces"), GREEN)
        except (OSError, ValueError, json.JSONDecodeError):
            self._set_activity(tr("Could not save your global default; existing settings remain"), RED)
        self._open_user_defaults_menu()

    async def _startup_workspace(self) -> None:
        """Offer recurrence once, then choose persistent or temporary chat storage."""
        try:
            setup_store = WorkspaceSetupStore()
            self._workspace_setup = setup_store
            recurring = self._workspace_identity.workspace_root_source == "isyroot"
            self._quick_start = False
            # Register the journalled key reader before any provider probe so the
            # QuickStart readiness check can see vault-stored keys (F-11). It is
            # registered again below, once the workspace root is final.
            self._register_saved_key_reader()
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
                    # Windows parity: keep the blocking marker write off the event loop.
                    await asyncio.to_thread(setup_store.choose_recurrent, self._launch_dir, choice)
                elif choice:
                    # Re-create a marker if the user removed it after opting in.
                    await asyncio.to_thread(setup_store.choose_recurrent, self._launch_dir, True)
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
                self._paint_workspace_chrome()
            except (WorkspaceAuthorityError, OSError, ValueError):
                self._append_startup("  Workspace mode could not be saved · Security rules apply.", YELLOW)
            self._update_workspace_identity_ui()
            self._register_saved_key_reader()
            await self._initialize_workspace()
            self._refresh_lsp_status()
            self.run_worker(self._refresh_openisy(), exclusive=False, exit_on_error=False)
            self.run_worker(self._check_gateway_async(), exclusive=False, exit_on_error=False)
            self.run_worker(self._check_model(), exclusive=False, exit_on_error=False)
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
        finally:
            # F-01: release waiters even when startup failed partway through.
            self._ready_event.set()

    def _update_workspace_identity_ui(self) -> None:
        if not self.is_mounted:
            return
        self.sub_title = (tr("{name}  ·  workspace {workspace_root}  ·  launch {launch_dir}", name=self._workspace_root.name, workspace_root=self._workspace_root, launch_dir=self._launch_dir))
        self.query_one("#workspace-label", Static).update(tr("Workspace Root · {workspace_root}", workspace_root=self._workspace_root))
        self.query_one("#workspace-launch-label", Static).update(tr("Launch Directory · {launch_dir}", launch_dir=self._launch_dir))
        self.query_one("#workspace-source-label", Static).update(self._root_source_label())
        self._paint_workspace_chrome()

    async def _load_project_context(self) -> bool:
        """Explicitly read root AGENTS.md; the file never supplies grants or tools."""
        return await self._load_context_file("AGENTS.md")

    def copy_to_clipboard(self, text: str) -> None:
        """Every copy Textual makes (selection, Ctrl+C, text fields) goes through the owner."""
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
                self.notify(tr("Image attached · Ctrl+P reviews attachments"))
            else:
                from textual.events import Paste
                await prompt._on_paste(Paste(data.decode("utf-8")))
        except (ValueError, UnicodeError):
            self.notify(tr("Clipboard content could not be attached"), severity="warning")
        prompt.focus()

    def action_open_copy_menu(self) -> None:
        """Keyboard door to the copy menu: the same choices as a double click."""
        from textual.screen import ModalScreen
        from isycode.tui_copy import CopyTextArea, open_copy_menu
        from isycode.tui_widgets import SelectableText
        if isinstance(self.screen, ModalScreen):
            return
        widget = self.focused
        if isinstance(widget, CopyTextArea):
            open_copy_menu(widget, widget.text, widget.selected_text)
            return
        if isinstance(widget, SelectableText):
            container = next(
                (parent for parent in widget.ancestors
                 if isinstance(parent, (ExpandableBox, CommandOutputCard))), None)
            whole = container.copy_text() if container is not None else widget._selection_plain
            open_copy_menu(widget, whole)
            return
        self._append("  " + tr("Focus a message or a preview, then press Copy."), MUTED)

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
            self.notify_semantic(tr("API keys are never copied."), kind="warning")
            return
        try:
            owner = ClipboardOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root))
            outcome = owner.copy(text, source=source,
                                 terminal_write=super().copy_to_clipboard)
        except (WorkspaceAuthorityError, OSError, ValueError):
            self.notify_semantic(tr("Copy failed · Workspace Authority is unavailable."), kind="denied")
            return
        if outcome.decision == "ALLOW":
            where = ("terminal clipboard" if outcome.text == "terminal"
                     else f"clipboard via {outcome.text}")
            if outcome.text == 'terminal':
                self.notify_semantic(tr("Copy request sent to terminal. If paste stays empty, install wl-clipboard (Wayland) or xclip (X11); some terminals ignore OSC 52."), kind="info", timeout=8)
            else:
                self.notify_semantic(tr("Copied {len} characters to the {where}.", len=len(text), where=where), kind="success", timeout=2.5)
        elif "grant" in outcome.reason:
            self.notify_semantic(tr("Copying is off for this workspace · turn on “Copy selected text” in Settings → Authority."), kind="denied", timeout=5)
        else:
            self.notify_semantic(tr("Nothing copied · {value}", value=outcome.reason[:120]), kind="denied")

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
                    self._set_activity(tr("Draft saved up to 16,000 characters; full text remains in the composer"), YELLOW)
            else:
                self._set_activity(tr("Draft not saved · {value}", value=outcome.reason[:100]), YELLOW)
        except (OSError, ValueError):
            self._set_activity(tr("Draft not saved · private state unavailable"), YELLOW)

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
                self.notify(tr("Pending messages cleared"))
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
                    self.notify(tr("Steer attempt pending; draft kept"))
                    return
                if len(self._pending_steering) >= 8:
                    self._append(tr("Steering queue is full; this draft is kept."), YELLOW)
                    return
                self._pending_steering.append(instruction)
                self._steering_try_active = True
                prompt.load_text("") if isinstance(prompt, PromptArea) else setattr(prompt, "value", "")
                self._mount_user_turn("Steer attempt · " + instruction)
                self._append(tr("Steering queued · current tool effects remain; pending calls will be skipped."), CYAN)
                request = self._chat_request_task
                if request is not None and not request.done():
                    request.cancel()
                return
            if not text.startswith("/"):
                if len(self._queued_messages) >= 8:
                    self.notify(tr("Message queue is full; draft kept"), severity="warning")
                    return
                self._queued_messages.append(text)
                self._paint_queued_messages()
                prompt.load_text("") if isinstance(prompt, PromptArea) else setattr(prompt, "value", "")
                self._append(tr("Queued · {len} pending · {fit_cells} · /queue reviews", len=len(self._queued_messages), fit_cells=_fit_cells(" ".join(text.split()), 70)), CYAN)
                return
            self._append("  " + tr("Still working. Your message remains in the composer; send it again when ready."), YELLOW)
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

    def _append_startup(self, text: str, color: str = TEXT) -> None:
        """Keep startup notices beneath the welcome art without archiving it."""
        self._append(text, color, startup=True)

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
            self._entry(
                tr("Default model · {provider} · {model}",
                   provider=provider.get('label', provider_name), model=model_name),
                "info", "", tr("Change it from Providers; model selection is already saved globally."),
                translate=False),
        ]
        role = defaults.get("default_role")
        entries.append(self._entry(
            tr("Default role · {name}", name=role['name']) if role else tr("Default role · none"),
            "info", "", tr("Role guidance is global preference only; it never grants permissions."),
            translate=False))
        if self._active_role:
            entries.append(self._entry(
                tr("Use current role ({name}) as my default", name=self._active_role['name']),
                "user_default_role_save", "", translate=False))
        if role:
            entries.append(self._entry("Clear my default role", "user_default_role_clear", ""))
        new_workspace = defaults.get("new_workspace", "ask")
        choices = (
            ("ask", "Ask me when I open a new folder"),
            ("temporary", "Always use temporary mode for new folders"),
            ("recurring", "Make new folders recurring by default"),
        )
        entries.extend(self._entry(
            ("● " if new_workspace == value else "○ ") + tr(label),
            "user_default_workspace", value,
            (tr("A recurring workspace gets an empty .isyroot marker when first opened. This identifies the workspace; it does not grant file access. Home, its parents, temp and mount points still ask first."))
            if value == "recurring" else tr("Applies only when this folder has no saved choice yet."),
            translate=False)
            for value, label in choices)
        new_mode = defaults.get("new_workspace_mode", "ask")
        mode_choices = (
            ("ask", "Ask me which mode a new folder uses"),
            ("classic", "Start new folders in Classic · Ready To Use"),
            ("security", "Start new folders in Security · everything off until I allow it"),
        )
        entries.extend(self._entry(
            ("● " if new_mode == value else "○ ") + tr(label), "user_default_mode", value,
            tr("Applies only to folders opened for the first time; each workspace keeps its own mode and you can switch it in Settings → Authority."),
            translate=False)
            for value, label in mode_choices)
        entries.append(self._entry(tr("Back to Settings"), "settings_back", ""))
        if self._menu_mode != "user_defaults":
            self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("user_defaults", "Settings · My defaults", entries)

    def _root_source_label(self) -> str:
        source = ".isyroot" if self._workspace_identity.workspace_root_source == "isyroot" else "Fallback"
        broad = " · Broad Shared Root" if self._shared_root_warning() else ""
        mode = {"classic": "Classic", "flow": "Flow"}.get(self._workspace_mode(), "Security")
        return f"Root Source · {source}{broad} · {mode} Mode"

    async def _load_context_file(self, relative_path: str) -> bool:
        """Load one selected workspace document through the read owner and receipt."""
        self._agent_context = None
        owner = LocalWorkspaceReadOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root))
        outcome = await asyncio.to_thread(owner.execute, "workspace.context.inject", {"path": relative_path})
        text = read_result_text(outcome.text) if outcome.decision == "ALLOW" else ""
        if text and outcome.receipt is not None:
            self._agent_context = {"path": relative_path, "text": text,
                                   "receipt_id": outcome.receipt.receipt_id, "verification": "PASS"}
            self._append("  " + tr("Context loaded · {relative_path} · owned read; no permissions changed.", relative_path=relative_path), MUTED)
        else:
            self._append("  " + tr("Context not loaded · {value}", value=outcome.reason[:160]), YELLOW)
        if self._lane_on_screen():
            self.query_one("#context-button", Button).label = self._context_button_label()
        return self._agent_context is not None

























    # ── /plan (IsyMotron plugin) ─────────────────────────────────


    # ── Contextual demo-plan approval ────────────────────────────








import isycode.tui_composer as _split_tui_composer
import isycode.tui_screens_sessions as _split_tui_screens_sessions
_split_tui_composer.TUIApp = TUIApp
_split_tui_screens_sessions.TUIApp = TUIApp

def main():
    app = TUIApp()
    app.run()


if __name__ == "__main__":
    main()
