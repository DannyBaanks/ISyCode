"""Main window: workspace | chat + collapsible bottom panels, native Qt layout."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QKeySequence, QShortcut, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QLabel, QLineEdit,
                                QListWidget, QListWidgetItem, QMainWindow, QMenu,
                                QPushButton, QSizePolicy, QSplitter, QToolBar,
                                QToolButton, QVBoxLayout, QWidget)

from . import theme
from .app import AppController
from .thread import AgentWorker
from .panels.chat import ChatPanel
from .panels.config import ConfigPanel
from .panels.conversations import ConversationsPanel
from .panels.github import GitHubPanel
from .panels.editor import EditorPanel
from .panels.evidence import EvidencePanel
from .panels.policy import PolicyPanel
from .panels.resident import ResidentPanel
from .panels.status import StatusPanel
from .panels.terminal import TerminalPanel
from .panels.tests import TestsPanel
from .panels.tools import ToolsPanel
from .panels.changes import ChangesPanel
from .panels.workspace import WorkspacePanel
from .shell import DesktopShell
from .icons import icon, provider_icon
from .panels.settings import SettingsPanel
from core.ui_preferences import UiPreferences
from .diff import render_diff

MAX_TURNS = 20


class CommandPaletteDialog(QDialog):
    """Fuzzy-searchable command palette dialog (Ctrl+K)."""

    def __init__(self, actions: list[tuple[str, str, callable]], parent=None):
        super().__init__(parent)
        self.setObjectName("commandPalette")
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.resize(520, 320)
        self._actions = actions
        self._filtered: list[tuple[str, str, callable]] = list(actions)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Escribe un comando o acción…  (Esc para cerrar)")
        self.input.textChanged.connect(self._on_search)
        self.input.returnPressed.connect(self._on_activate)
        layout.addWidget(self.input)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._on_activate())
        layout.addWidget(self.list_widget)

        self._populate_list()
        self.input.setFocus()

    def _populate_list(self) -> None:
        self.list_widget.clear()
        for label, shortcut, _cb in self._filtered:
            text = f"{label}   [{shortcut}]" if shortcut else label
            item = QListWidgetItem(text)
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _on_search(self, text: str) -> None:
        query = text.lower().strip()
        if not query:
            self._filtered = list(self._actions)
        else:
            self._filtered = [
                (lbl, sc, cb) for (lbl, sc, cb) in self._actions
                if query in lbl.lower() or (sc and query in sc.lower())
            ]
        self._populate_list()

    def _on_activate(self) -> None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._filtered):
            _lbl, _sc, cb = self._filtered[row]
            self.accept()
            cb()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Down:
            curr = self.list_widget.currentRow()
            if curr < self.list_widget.count() - 1:
                self.list_widget.setCurrentRow(curr + 1)
            event.accept()
            return
        elif key == Qt.Key.Key_Up:
            curr = self.list_widget.currentRow()
            if curr > 0:
                self.list_widget.setCurrentRow(curr - 1)
            event.accept()
            return
        elif key == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController | None = None):
        super().__init__()
        self.controller = controller or AppController()
        self._worker: AgentWorker | None = None
        self._stream_active = False
        self._tool_cards: dict[str, object] = {}
        self.panel_windows: dict[str, QDialog] = {}
        self._total_tokens_estimated: int = 0
        self._last_prompt: str = ""
        self._session_id: str | None = None
        self._provider_replacement_required = False
        self._pending_new_session = False
        self.ui_preferences = UiPreferences()

        self.setWindowTitle(f"ISyCode IDE — {self.controller.working_dir}")
        self.resize(1360, 840)

        self._build_central()
        self._build_toolbar()
        self._build_statusbar()
        self._populate_panels_menu()
        self._setup_shortcuts()
        self._refresh_project_selector()
        self._refresh_provider_models()
        self._load_appearance()
        self._refresh_local_git_indicator()
        saved = self.controller.conversations.list()
        if saved:
            self._resume_session(saved[0]["id"])
        if self.controller.working_dir.resolve() in {Path.home().resolve(), Path("/")}:
            self.chat.add_recovery_card(
                "Workspace activo en carpeta personal",
                f"El workspace actual es {self.controller.working_dir}. Selecciona un proyecto vinculado o abre una carpeta de proyecto para habilitar el agente y evitar errores de alcance.",
                [("Abrir proyecto…", self._open_workspace), ("Ir a GitHub", lambda: self.panel_bar.show_title("GitHub"))],
            )

    # --- construction -------------------------------------------------

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("ISyCode IDE")
        toolbar.setObjectName("ideToolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.menu_button = QToolButton()
        self.menu_button.setObjectName("menuButton")
        self.menu_button.setIcon(icon("menu"))
        self.menu_button.setToolTip("Navegación y menú · Ctrl+K")
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        self.menu = self._build_menu()
        self.menu_button.setMenu(self.menu)
        self.menu_button.clicked.connect(self._toggle_drawer)
        toolbar.addWidget(self.menu_button)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(Path(__file__).parent / "assets" / "isycode_64x64.png")).scaled(
            34, 34, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        logo.setToolTip("ISyCode IDE")
        toolbar.addWidget(logo)
        brand = QLabel("ISyCode IDE")
        brand.setObjectName("ideBrand")
        toolbar.addWidget(brand)
        self.workspace_label = QLabel()
        self.workspace_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.workspace_label.setToolTip("Proyecto · Ctrl+O abrir · Ctrl+B archivos")
        self.workspace_label.mousePressEvent = lambda _e: self._toggle_workspace()
        self.workspace_label.hide()
        self.project_combo = QComboBox()
        self.project_combo.setObjectName("projectSelector")
        self.project_combo.setMinimumWidth(150)
        self.project_combo.setMaximumWidth(240)
        self.project_combo.setToolTip("Proyecto activo · cambia entre repos vinculados o abre otra carpeta (Ctrl+O)")
        self.project_combo.activated.connect(self._on_project_selected)
        toolbar.addWidget(self.project_combo)
        self.workspace_toggle_button = QToolButton()
        self.workspace_toggle_button.setIcon(icon("folder"))
        self.workspace_toggle_button.setText("Árbol")
        self.workspace_toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.workspace_toggle_button.setToolTip("Mostrar u ocultar archivos del proyecto · Ctrl+B")
        self.workspace_toggle_button.setAccessibleName("Mostrar u ocultar árbol del proyecto")
        self.workspace_toggle_button.clicked.connect(self._toggle_workspace)
        toolbar.addWidget(self.workspace_toggle_button)
        self.provider_combo = QComboBox()
        self.provider_combo.setMinimumWidth(130)
        self.provider_combo.setMaximumWidth(220)
        self.provider_combo.setIconSize(QSize(22, 22))
        self.provider_combo.setToolTip("Provider · Ctrl+P configura")
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        toolbar.addWidget(self.provider_combo)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(220)
        self.model_combo.setMaximumWidth(360)
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model_combo.setToolTip("Modelo del siguiente turno")
        self.model_combo.currentTextChanged.connect(lambda txt: self.model_combo.setToolTip(f"Modelo: {txt}" if txt else "Modelo del siguiente turno"))
        toolbar.addWidget(self.model_combo)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.command_search = QPushButton("Buscar archivos y comandos · Ctrl+K")
        self.command_search.setIcon(icon("search"))
        self.command_search.setToolTip("Abrir la paleta de comandos")
        self.command_search.clicked.connect(self.open_command_palette)
        self.command_search_action = toolbar.addWidget(self.command_search)
        self.mode_buttons = {}
        for mode in ("plan", "coder"):
            button = QPushButton(mode.upper())
            button.setObjectName("modeSwitch")
            button.setCheckable(True)
            button.setToolTip("PLAN inspecciona y propone" if mode == "plan" else "CODER pide permiso para aplicar")
            button.clicked.connect(lambda checked=False, m=mode: self._set_mode(m))
            toolbar.addWidget(button)
            self.mode_buttons[mode] = button
        self.mode_badge = QLabel()
        self.mode_badge.hide()
        self.mode_button = QPushButton()
        self.mode_button.hide()

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)

        new_sess_act = menu.addAction("New session", self._new_session)
        new_sess_act.setShortcut(QKeySequence("Ctrl+N"))
        menu.addAction("Providers…", self.open_providers)
        menu.addAction("GitHub y carpetas", lambda: self.panel_bar.show_title("GitHub"))
        menu.addAction("Vista Conversación", lambda: self.panel_bar.set_view("conversation"))
        menu.addAction("Vista Código + chat", lambda: self.panel_bar.set_view("code"))
        menu.addAction("Open workspace…", self._open_workspace)
        self.mode_action = menu.addAction("Toggle mode", self._toggle_mode)
        menu.addAction("Clear chat", lambda: self.chat.clear_log())
        menu.addSeparator()

        self.panels_menu = menu.addMenu("Panels")
        menu.addSeparator()
        menu.addAction("Close all panel windows", self.close_all_panel_windows)
        return menu

    def _populate_panels_menu(self) -> None:
        """One entry per panel; each opens its own window."""
        self.panels_menu.clear()
        for panel in self.panel_bar.panels():
            title = panel.title()
            self.panels_menu.addAction(
                title, lambda t=title: self.open_panel_window(t))

    def panel_menu_labels(self) -> list[str]:
        return [a.text() for a in self.panels_menu.actions()]

    def toolbar_buttons(self) -> list:
        """Push/tool buttons actually shown on the toolbar."""
        bar = self.findChild(QToolBar)
        if bar is None:
            return []
        # findChildren takes one type at a time in PySide6; a tuple raises.
        found = bar.findChildren(QPushButton) + bar.findChildren(QToolButton)
        return [w for w in found if w.isVisible() or w is self.menu_button]

    # --- panels in their own windows -----------------------------------

    def open_panel_window(self, title: str) -> QDialog | None:
        """Show one panel in a separate, non-modal window.

        The live widget is reparented rather than copied, so the window shows
        the same panel the app is driving. Closing it hands the widget back to
        the tab it came from, which is why the drawer keeps working afterwards.
        """
        existing = self.panel_windows.get(title)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing

        panel = next((p for p in self.panel_bar.panels() if p.title() == title), None)
        if panel is None:
            return None

        dialog = QDialog(self)
        dialog.setWindowTitle(f"{title} — ISyCode IDE")
        dialog.setModal(False)
        dialog.resize(1280 if title == "GitHub" else 1080 if title == "Config" else 880,
                      800 if title == "GitHub" else 740 if title == "Config" else 520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)

        widget = panel.content()
        self.panel_bar.detach(panel)
        layout.addWidget(widget)
        widget.setVisible(True)
        widget.show()

        dialog.finished.connect(lambda _=0, t=title: self._return_panel(t))
        self.panel_windows[title] = dialog
        dialog.show()
        return dialog

    def _return_panel(self, title: str) -> None:
        dialog = self.panel_windows.pop(title, None)
        if dialog is None:
            return
        panel = next((p for p in self.panel_bar.panels() if p.title() == title), None)
        if panel is not None:
            self.panel_bar.reattach(panel)
        dialog.deleteLater()

    def close_all_panel_windows(self) -> None:
        for dialog in list(self.panel_windows.values()):
            dialog.close()
        self.panel_windows.clear()

    def open_providers(self) -> None:
        """Providers in their own window: it is the first thing anyone needs."""
        self.panel_bar.show_title("Config")

    def _build_central(self) -> None:
        self.panel_bar = DesktopShell()
        self._setup_panels()
        self.chat = ChatPanel()
        self.chat.provider_setup_requested.connect(self.open_providers)
        self.chat.prompt_submitted.connect(self._start_agent)
        self.chat.stop_button.clicked.connect(self._stop_agent)
        self.chat.input.escape_pressed.connect(self._stop_agent)
        self.workspace = WorkspacePanel()
        self.workspace.set_root(self.controller.working_dir)
        self.workspace.file_open.connect(self._open_file)
        self.workspace.hide_requested.connect(self._toggle_workspace)
        self.panel_bar.build_workspace(self.chat, self.workspace, self.conversations_panel,
                                       self.editor_panel, self.changes_panel, self.diff_view)
        self.panel_bar.group_pages([("Status", "Estado"), ("Policy", "Políticas"), ("Resident", "Memoria local")])
        self.panel_bar.finish_pages()
        self.panel_bar.view_changed.connect(self._remember_view)
        self.main_split = self.panel_bar.columns
        self.setCentralWidget(self.panel_bar)

    def _setup_panels(self) -> None:
        """Create all technical panels and add them as collapsible drawers."""

        self.conversations_panel = ConversationsPanel(self.controller)
        self.conversations_panel.new_requested.connect(self._new_session)
        self.conversations_panel.session_selected.connect(self._resume_session)
        self.panel_bar.add_panel("Conversaciones", self.conversations_panel, status="")

        self.github_panel = GitHubPanel(self.controller, busy_guard=lambda: self._agent_busy() or self._host_tool_busy())
        self.github_panel.folder_open_requested.connect(self._switch_workspace)
        self.github_panel.project_status_changed.connect(self._project_git_status)
        self.panel_bar.add_panel("GitHub", self.github_panel, status="")

        # Editor panel
        self.editor_panel = EditorPanel(self.controller)
        self.editor_panel.content_changed.connect(self._refresh_diff)
        self.editor_collapsible = self.panel_bar.add_panel(
            "Editor", self.editor_panel, status="")
        self.editor_collapsible.toggled.connect(
            lambda expanded: self.editor_collapsible.set_status(
                self.editor_panel.current_path.name if self.editor_panel.current_path else "") if expanded else "")

        # Tool calls panel
        self.tools_panel = ToolsPanel(controller=self.controller)
        self.tools_collapsible = self.panel_bar.add_panel(
            "Tool calls", self.tools_panel, status="")

        self.changes_panel = ChangesPanel(self.controller)
        self.changes_collapsible = self.panel_bar.add_panel("Cambios", self.changes_panel, status="")

        # Diff panel
        self.diff_view = QWidget()
        self.diff_browser = self._build_diff_browser()
        self.diff_collapsible = self.panel_bar.add_panel(
            "Diff", self.diff_view, status="")

        # Tests panel
        self.tests_panel = TestsPanel(self.controller)
        self.tests_panel.busy_guard = lambda: self._agent_busy() or self._github_busy()
        self.tests_panel.result_ready.connect(self._host_tool_finished)
        self.changes_panel.busy_guard = lambda: self._agent_busy() or self._github_busy() or self._host_tool_busy()
        self.tests_collapsible = self.panel_bar.add_panel(
            "Tests", self.tests_panel, status="")

        # Evidence panel
        self.evidence_panel = EvidencePanel(self.controller)
        self.evidence_collapsible = self.panel_bar.add_panel(
            "Evidence", self.evidence_panel, status="")

        # Policy panel
        self.policy_panel = PolicyPanel(self.controller)
        self.policy_collapsible = self.panel_bar.add_panel(
            "Policy", self.policy_panel, status="")

        # Resident panel
        self.resident_panel = ResidentPanel(self.controller)
        self.resident_collapsible = self.panel_bar.add_panel(
            "Resident", self.resident_panel, status="")

        # Config panel
        self.config_panel = ConfigPanel(self.controller)
        self.config_panel.subscriptions.busy_guard = self._agent_busy
        self.config_panel.providers_changed.connect(self._refresh_provider_models)
        self.config_collapsible = self.panel_bar.add_panel(
            "Config", self.config_panel, status="")

        # Terminal panel
        self.terminal_panel = TerminalPanel(self.controller)
        self.terminal_collapsible = self.panel_bar.add_panel(
            "Terminal", self.terminal_panel, status="")

        self.settings_panel = SettingsPanel(self.controller)
        self.settings_panel.appearance_changed.connect(self._apply_appearance)
        self.settings_panel.migration_done.connect(self._migration_finished)
        self.settings_panel.workspace_change_requested.connect(self._open_workspace)
        self.settings_panel.busy_guard = lambda: self._agent_busy() or self._github_busy() or self._host_tool_busy()
        self.panel_bar.add_panel("Ajustes", self.settings_panel, status="")

        # Status panel
        self.status_panel = StatusPanel(self.controller)
        self.status_collapsible = self.panel_bar.add_panel(
            "Status", self.status_panel, status="")

    def _build_diff_browser(self):
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout
        widget = self.diff_view
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        hdr_row = QHBoxLayout()
        label = QLabel("DIFF EN TIEMPO REAL (VS ÚLTIMO ESTADO GUARDADO)")
        label.setStyleSheet("font-size: 11px; font-weight: 700; color: #6b7385; letter-spacing: 1px;")
        hdr_row.addWidget(label)
        hdr_row.addStretch(1)

        help_btn = QPushButton("?")
        help_btn.setObjectName("helpButton")
        help_btn.setToolTip(
            "Diff: Compara las modificaciones actuales en el editor contra la versión guardada en disco\n"
            "mostrando adiciones en verde y eliminaciones en rojo."
        )
        hdr_row.addWidget(help_btn)
        layout.addLayout(hdr_row)

        browser = QTextBrowser()
        layout.addWidget(browser)
        return browser

    def _build_statusbar(self) -> None:
        self.status_label = QLabel()
        self.statusBar().addWidget(self.status_label, stretch=1)
        self.context_meter = QLabel("Contexto estimado: ~0 tokens")
        self.context_meter.setToolTip("Estimación por longitud del texto; no es una medida del tokenizer ni del límite del modelo.")
        self.context_meter.setStyleSheet("color: #0a7d33; font-size: 11px; padding-right: 8px;")
        self.git_notice = QLabel("GitHub · comprobar carpeta")
        self.git_notice.setCursor(Qt.CursorShape.PointingHandCursor)
        self.git_notice.mousePressEvent = lambda _e: self.panel_bar.show_title("GitHub")
        self.statusBar().addPermanentWidget(self.git_notice)
        self.statusBar().addPermanentWidget(self.context_meter)
        self._update_statusbar()

    def _update_context_meter(self, tokens: int) -> None:
        self.context_meter.setText(f"Contexto estimado: ~{tokens:,} tokens")

    def _project_git_status(self, status) -> None:
        if status is None:
            self.git_notice.setText("GitHub · sin comprobar")
            self.git_notice.setToolTip("La última consulta falló o se canceló. Comprueba el remoto otra vez.")
            self.workspace.git_label.setText("Git · sin comprobar")
            return
        self.git_notice.setText("GitHub · " + (f"{status.behind} detrás · {status.ahead} delante" if status.behind is not None else "sin comprobar"))
        self.git_notice.setToolTip(f"{status.folder} · {status.branch}\nComprobado: {status.checked or 'sin consulta reciente'}\nCambios locales: {status.local_changes}")
        self.workspace.git_label.setText(status.branch or "HEAD separado")
        self.workspace.git_label.setToolTip(f"{status.local_changes} cambios locales · {status.upstream}\n{self.git_notice.text()}")

    def _load_appearance(self) -> None:
        try:
            self._apply_appearance(self.ui_preferences.load())
        except (OSError, ValueError):
            self.chat.add_system_message("No se pudieron leer los ajustes de interfaz; se conserva el archivo existente.")

    def _apply_appearance(self, values) -> None:
        font = self.editor_panel.editor.font()
        font.setPointSize(values["editor_font_size"])
        self.editor_panel.editor.setFont(font)
        self.panel_bar.set_view(values["view"], notify=False)

    def _remember_view(self, view) -> None:
        try:
            if self.ui_preferences.load()["remember_view"]:
                self.ui_preferences.save(view=view)
                self.settings_panel.refresh()
        except (OSError, ValueError):
            self.chat.add_system_message("La vista cambió; no se pudo guardar la preferencia.")

    def _migration_finished(self) -> None:
        self._refresh_provider_models()
        self.config_panel.refresh()
        self.conversations_panel.refresh()
        self.changes_panel.refresh()
        self.tools_panel.refresh_settings()
        self._update_statusbar()

    def _new_session(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._pending_new_session = True
            self._stop_agent()
            return
        self._session_id = None
        self._provider_replacement_required = False
        self.panel_bar.conversation_title.setText("Nueva conversación")
        self.chat.clear_log()
        self._total_tokens_estimated = 0
        self._update_context_meter(0)
        self.chat.add_system_message("Nueva sesión iniciada.")
        self._update_statusbar()

    def _resume_session(self, session_id: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.chat.add_system_message("Detén el turno actual antes de cambiar de conversación.")
            return
        if session_id not in {item["id"] for item in self.controller.conversations.list()}:
            return
        self._session_id = session_id
        selected = next(item for item in self.controller.conversations.list() if item["id"] == session_id)
        self.panel_bar.conversation_title.setText(selected["title"])
        self.chat.clear_log()
        self._provider_replacement_required = True
        self.provider_combo.blockSignals(True)
        self.provider_combo.setCurrentIndex(-1)
        self.provider_combo.blockSignals(False)
        self.model_combo.clear()
        try:
            saved_config = self.controller.provider_registry.get_config(selected["provider"], selected["model"])
            if selected["protocol"] and saved_config.provider_type != selected["protocol"]:
                raise ValueError("El protocolo guardado cambió.")
            index = self.provider_combo.findData(selected["provider"])
            if index < 0:
                raise ValueError("El provider guardado no está disponible.")
            self.provider_combo.setCurrentIndex(index)
            if self.model_combo.findText(selected["model"]) < 0:
                self.model_combo.addItem(selected["model"])
            self.model_combo.setCurrentText(selected["model"])
        except ValueError:
            self.chat.add_system_message("El provider/modelo guardado no está disponible. Elige explícitamente un reemplazo en la barra antes de enviar; esta conversación se enviará al provider elegido.")
        transcript = self.controller.conversations.transcript(session_id)
        tokens = 0
        last_user_prompt = ""
        for item in transcript:
            content = item.get("content") or ""
            tokens += max(1, len(content) // 4) if content else 0
            if item["role"] == "user":
                last_user_prompt = content
                self.chat.add_user_message(content)
            elif item["role"] == "assistant":
                self.chat.start_assistant_stream()
                self.chat.append_chunk(content)
                self.chat.end_assistant_stream()
        self._last_prompt = last_user_prompt
        self._total_tokens_estimated = tokens
        self._update_context_meter(tokens)
        status = self.controller.conversations.turn_status(session_id)
        for event in self.controller.conversations.events(session_id):
            item = event["payload"]
            if item["type"] == "proposal_decided":
                self.chat.add_system_message("Cambio " + item.get("proposal_id", "")[:12] + " · " + item.get("status", "desconocido") + " · consultar Cambios")
            elif item["type"] == "provider_reasoning":
                self.chat.start_assistant_stream()
                self.chat.append_reasoning(item.get("text", ""))
                self.chat.end_assistant_stream("guardado · " + item.get("status", "parcial") + (" · vista limitada" if item.get("truncated") else ""))
            elif item["type"] == "agent_failed":
                self.chat.add_system_message(item.get("code", "AGENT_INTERNAL_ERROR") + " · " + item.get("message", "") + " · paso " + str(item.get("step", "?")))
            elif item["type"] == "command_decided":
                self.chat.add_system_message("Comando · " + item.get("status", "desconocido") + " · permiso " + item.get("scope", "sin permiso"))
        if status in {"interrupted", "cancelled", "failed"}:
            actions = []
            if last_user_prompt:
                actions.append(("Reintentar último turno", lambda p=last_user_prompt: self._retry_last_prompt(p)))
            actions.append(("Abrir proyecto…", self._open_workspace))
            self.chat.add_recovery_card(
                f"El último turno quedó {status}",
                "Puedes reintentar el último mensaje en el proyecto activo o abrir una carpeta de proyecto concreta antes de continuar.",
                actions,
            )

    # --- provider / model selection ------------------------------------

    def _refresh_provider_models(self) -> None:
        current_provider = self.provider_combo.currentData()
        current_model = self.model_combo.currentText()
        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()
        configured = self.controller.providers()
        self.chat.empty_state.configure_button.setVisible(not configured)
        if configured:
            for name, values in configured.items():
                kind = values.get("provider", "")
                category = "suscripción" if values.get("auth") == "subscription" else "local" if kind == "ollama" or values.get("auth") == "none" else "API"
                self.provider_combo.addItem(provider_icon(name, values), name + " · " + category, name)
        else:
            self.provider_combo.setPlaceholderText("Configura un provider…")
        if current_provider:
            index = self.provider_combo.findData(current_provider)
            if index >= 0:
                self.provider_combo.setCurrentIndex(index)
            else:
                self._provider_replacement_required = True
                self.chat.add_system_message("La conexión seleccionada se eliminó. Elige explícitamente otro provider antes de enviar.")
        if self._provider_replacement_required:
            self.provider_combo.setCurrentIndex(-1)
        self.provider_combo.blockSignals(False)
        self._on_provider_changed(self.provider_combo.currentText())
        if current_provider and current_provider == self.provider_combo.currentData() and current_model:
            if self.model_combo.findText(current_model) < 0:
                self.model_combo.addItem(current_model)
            self.model_combo.setCurrentText(current_model)

    def _on_provider_changed(self, provider: str) -> None:
        provider = self.provider_combo.currentData() or ""
        if provider:
            self._provider_replacement_required = False
        models = self.controller.default_models()
        candidates = []
        configured = self.controller.providers().get(provider)
        if configured and configured.get("model"):
            candidates.append(configured["model"])
        default = models.get(provider)
        if default and default not in candidates:
            candidates.append(default)
        self.model_combo.clear()
        self.model_combo.addItems(candidates)

    def _set_mode(self, mode) -> None:
        if self._agent_busy():
            self.chat.add_system_message("El modo del turno activo se conserva hasta que termine.")
        else:
            self.controller.set_mode(mode)
        self._update_statusbar()

    def _toggle_mode(self) -> None:
        self._set_mode("coder" if self.controller.mode() == "plan" else "plan")

    def _agent_busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _host_tool_busy(self) -> bool:
        panel = getattr(self, "tests_panel", None)
        return panel is not None and panel._worker is not None and panel._worker.isRunning()

    def _host_tool_finished(self, result) -> None:
        self.changes_panel.refresh()
        self.settings_panel.refresh_grants()
        self.workspace.refresh_git_status()
        if hasattr(self.evidence_panel, "refresh_receipts"):
            self.evidence_panel.refresh_receipts()
        if self.editor_panel.current_path and not self.editor_panel.dirty():
            self.editor_panel.open_file(str(self.editor_panel.current_path))

    def _github_busy(self) -> bool:
        return self.github_panel._worker is not None and self.github_panel._worker.isRunning()

    def _refresh_project_selector(self) -> None:
        if not hasattr(self, "project_combo"):
            return
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        current = str(self.controller.working_dir.resolve())
        seen: set[str] = set()
        self.project_combo.addItem(icon("folder"), self.controller.working_dir.name or current, current)
        seen.add(current)
        try:
            for link in self.github_panel.service.links.list():
                folder = str(link.get("folder", "")).strip()
                if not folder:
                    continue
                resolved = str(Path(folder).expanduser().resolve())
                if resolved not in seen and Path(resolved).is_dir():
                    label = Path(resolved).name
                    repo = link.get("repo", "")
                    self.project_combo.addItem(icon("github"), f"{label} ({repo.split('/')[-1]})" if repo else label, resolved)
                    seen.add(resolved)
        except Exception:
            pass
        self.project_combo.addItem(icon("folder"), "Abrir otra carpeta…", "__OPEN__")
        self.project_combo.setCurrentIndex(0)
        self.project_combo.setToolTip(f"Proyecto activo: {current}\nCtrl+O para abrir otro")
        self.project_combo.blockSignals(False)

    def _on_project_selected(self, index: int) -> None:
        data = self.project_combo.itemData(index)
        if data == "__OPEN__":
            self._refresh_project_selector()
            self._open_workspace()
        elif isinstance(data, str) and data:
            self._switch_workspace(data)

    def _refresh_local_git_indicator(self) -> None:
        """Populate local Git branch & status in statusbar/workspace immediately without network."""
        import subprocess
        wd = self.controller.working_dir
        try:
            branch = subprocess.run(
                ["git", "-C", str(wd), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=2,
            )
            if branch.returncode != 0:
                self.workspace.git_label.setText("sin repo Git")
                self.git_notice.setText("GitHub · carpeta sin Git")
                return
            branch_name = branch.stdout.strip() or "HEAD"
            porcelain = subprocess.run(
                ["git", "-C", str(wd), "status", "--porcelain"],
                capture_output=True, text=True, timeout=2,
            )
            changed = len([ln for ln in porcelain.stdout.splitlines() if ln.strip()]) if porcelain.returncode == 0 else 0
            self.workspace.git_label.setText(f"{branch_name}" + (f" · {changed}Δ" if changed else ""))
            self.workspace.git_label.setToolTip(f"Rama local: {branch_name}\nCambios sin commitear: {changed}")
            self.git_notice.setText(f"Git · {branch_name}" + (f" ({changed}Δ)" if changed else " · limpio"))
            self.git_notice.setToolTip(f"{wd}\nRama: {branch_name}\nPulsa para abrir el panel GitHub y comprobar el remoto")
        except Exception:
            pass

    def _retry_last_prompt(self, prompt: str) -> None:
        if prompt:
            self._start_agent(prompt)

    def _open_workspace(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Abrir proyecto", str(self.controller.working_dir))
        if chosen:
            self._switch_workspace(chosen)

    def _switch_workspace(self, chosen: str) -> None:
        if self._agent_busy() or self._github_busy() or self._host_tool_busy():
            self.chat.add_system_message("Espera a que termine el turno o la operación Git antes de cambiar de proyecto.")
            return
        if self.editor_panel.dirty():
            self.chat.add_system_message("Conserva o guarda el borrador del editor antes de cambiar de proyecto.")
            return
        if Path(chosen).resolve() == self.controller.working_dir.resolve():
            return
        self.controller.set_workspace(chosen)
        resolved = self.controller.working_dir.resolve()
        if resolved not in {Path.home().resolve(), Path("/")}:
            try:
                self.ui_preferences.save(last_workspace=str(resolved))
            except (OSError, ValueError):
                pass
        if hasattr(self.editor_panel, "reset_workspace"):
            self.editor_panel.reset_workspace()
        else:
            self.editor_panel.current_path = None
            self.editor_panel.snapshot = ""
            self.editor_panel.title_label.setText("Abre un archivo del proyecto")
            self.editor_panel.editor.clear()
        self.settings_panel.refresh()
        self.tools_panel.refresh_settings()
        self.changes_panel.refresh()
        if hasattr(self.tests_panel, "refresh_discovery"):
            self.tests_panel.refresh_discovery()
        if hasattr(self.evidence_panel, "refresh_receipts"):
            self.evidence_panel.refresh_receipts()
        if hasattr(self.terminal_panel, "on_workspace_changed"):
            self.terminal_panel.on_workspace_changed()
        self.status_panel.refresh()
        self._session_id = None
        self._provider_replacement_required = False
        self._total_tokens_estimated = 0
        self._update_context_meter(0)
        self.panel_bar.conversation_title.setText("Nueva conversación")
        self.chat.clear_log()
        self.conversations_panel.refresh()
        self.workspace.set_root(chosen)
        self._refresh_project_selector()
        self._refresh_local_git_indicator()
        self.setWindowTitle(f"ISyCode IDE — {self.controller.working_dir}")
        self._update_statusbar()

    def _open_file(self, path: str) -> None:
        if self.editor_panel.open_file(path):
            self.panel_bar.set_view("code")
            self.editor_collapsible.set_expanded(True)
            self._refresh_diff()

    def _refresh_diff(self) -> None:
        if self.editor_panel.current_path is None:
            self.diff_browser.setHtml("")
            return
        old_text = self.editor_panel.snapshot
        new_text = self.editor_panel.current_text()
        self.diff_browser.setHtml(render_diff(old_text, new_text))

    def _setup_shortcuts(self) -> None:
        """Register global window shortcuts matching ISyCode keymap."""
        self._shortcuts: list[QShortcut] = []

        def add_sc(seq: str, callback):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(callback)
            self._shortcuts.append(sc)

        add_sc("Ctrl+K", self.open_command_palette)
        add_sc("Ctrl+B", self._toggle_workspace)
        add_sc("Ctrl+P", self.open_providers)
        add_sc("Ctrl+`", self._toggle_drawer)
        add_sc("Ctrl+O", self._open_workspace)
        add_sc("Ctrl+M", self._toggle_mode)
        add_sc("Shift+Backtab", self._toggle_mode)
        add_sc("Ctrl+N", self._new_session)
        add_sc("Ctrl+1", lambda: self.panel_bar.set_view("conversation"))
        add_sc("Ctrl+2", lambda: self.panel_bar.set_view("code"))

    def _toggle_workspace(self) -> None:
        if self.panel_bar.pages.currentWidget() is not self.panel_bar.work_page:
            self.panel_bar.show_title("Conversaciones")
            self.workspace.show()
        else:
            self.workspace.setVisible(not self.workspace.isVisible())

    def _toggle_drawer(self) -> None:
        self.panel_bar.set_drawer_visible(not self.panel_bar.drawer_visible())

    def open_command_palette(self) -> None:
        actions: list[tuple[str, str, callable]] = [
            ("Nueva sesión", "Ctrl+N", self._new_session),
            ("Abrir workspace…", "Ctrl+O", self._open_workspace),
            ("Alternar modo PLAN / CODER", "Shift+Tab", self._toggle_mode),
            ("Configurar providers…", "Ctrl+P", self.open_providers),
            ("Mostrar/Ocultar Workspace (árbol)", "Ctrl+B", self._toggle_workspace),
            ("Mostrar/Ocultar navegación", "Ctrl+`", self._toggle_drawer),
            ("Limpiar historial de chat", "", lambda: self.chat.clear_log()),
            ("Detener agente en ejecución", "Esc", self._stop_agent),
            ("Cerrar todas las ventanas flotantes", "", self.close_all_panel_windows),
        ]
        for panel in self.panel_bar.panels():
            t = panel.title()
            actions.append((f"Panel: {t} (ventana flotante)", "", lambda title=t: self.open_panel_window(title)))

        dlg = CommandPaletteDialog(actions, self)
        dlg.exec()

    def _update_statusbar(self) -> None:
        runtime = self.controller.runtime_status()
        layers = ", ".join(
            f"{name}={ 'on' if ok else 'off' }" for name, ok in runtime.items())
        mode = self.controller.mode().upper()
        self.mode_button.setText(f"MODE: {mode}")
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode.lower())
        self.status_label.setText(f"{self.controller.working_dir.name}  ·  {mode}")
        self.status_label.setToolTip(f"{self.controller.working_dir}\nRuntime: {layers}")
        if hasattr(self, "mode_badge"):
            self.mode_badge.setText(f"● {mode}")
            self.mode_badge.setProperty("mode", mode.lower())
            theme.repolish(self.mode_badge)
        if hasattr(self, "workspace_label"):
            p = self.controller.working_dir
            self.workspace_label.setText(p.name[:24] + ("…" if len(p.name) > 24 else ""))
            self.workspace_label.setToolTip(str(p))

    # --- agent lifecycle ------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "command_search_action"):
            self.command_search_action.setVisible(self.width() >= 1300)

    def _start_agent(self, prompt: str) -> None:
        if self.controller.working_dir.resolve() in {Path.home().resolve(), Path("/")}:
            self.chat.input.setPlainText(prompt)
            self.chat.add_system_message("Abre una carpeta concreta como proyecto (Ctrl+O) antes de enviar. La carpeta personal y la raíz del sistema no se exponen al modelo como proyecto.")
            return
        if self._github_busy() or self._host_tool_busy():
            self.chat.input.setPlainText(prompt)
            self.chat.add_system_message("Espera a que termine la operación Git antes de enviar otro turno.")
            return
        if self._worker is not None and self._worker.isRunning():
            self.chat.add_system_message("El agente sigue trabajando; espera o pulsa Detener.")
            return
        if self._provider_replacement_required:
            self.chat.input.setPlainText(prompt)
            self.chat.add_system_message("Elige un provider y modelo de reemplazo antes de enviar esta conversación.")
            self.open_providers()
            return
        provider = self.provider_combo.currentData()
        model = self.model_combo.currentText()
        if not provider or not model.strip():
            self.chat.input.setPlainText(prompt)
            self.chat.add_system_message("Configura un provider y un modelo antes de enviar. Abriendo Providers…")
            self.open_providers()
            return
        try:
            config = self.controller.provider_registry.get_config(provider, model)
            if config.provider_type == "claude":
                raise ValueError("Este perfil antiguo de Claude está deshabilitado. Configura Claude por suscripción o Anthropic por API en Providers.")
        except ValueError as exc:
            self.chat.input.setPlainText(prompt)
            self.chat.add_system_message(str(exc))
            self.open_providers()
            return
        if self._session_id is None:
            self._session_id = self.controller.conversations.create()
        self.chat.set_status_working()
        self._stream_active = False
        self._tool_cards.clear()

        self._last_prompt = prompt
        self._total_tokens_estimated += max(1, len(prompt) // 4)
        self._update_context_meter(self._total_tokens_estimated)
        self.chat.add_user_message(prompt)
        self.chat.add_system_message(
            f"Inicio de turno · provider: {provider}, modelo: {model}, "
            f"modo: {self.controller.mode()}, máximo de pasos: {MAX_TURNS}")

        self._worker = AgentWorker(
            self.controller, prompt, provider, model, max_turns=MAX_TURNS,
            session_id=self._session_id)
        self._worker.text_chunk.connect(self._on_chunk)
        self._worker.reasoning_chunk.connect(self._on_reasoning)
        self._worker.progress.connect(self.chat.set_agent_progress)
        self._worker.tool_call.connect(self._on_tool_call)
        self._worker.tool_result.connect(self._on_tool_result)
        self._worker.approval_requested.connect(self._on_approval_requested)
        self._worker.session_done.connect(self._on_session_done)
        self._worker.agent_error.connect(self._on_agent_error)
        self._worker.finished.connect(self._worker_finished)
        self._worker.start()

    def _on_chunk(self, chunk: str) -> None:
        if not self._stream_active:
            self.chat.start_assistant_stream()
            self._stream_active = True
        self.chat.append_chunk(chunk)
        self._total_tokens_estimated += max(1, len(chunk) // 4)
        self._update_context_meter(self._total_tokens_estimated)

    def _on_reasoning(self, chunk: str) -> None:
        if not self._stream_active:
            self.chat.start_assistant_stream()
            self._stream_active = True
        self.chat.append_reasoning(chunk)

    def _on_approval_requested(self, approval_id: str, tool_name: str, args: dict, diff: str) -> None:
        self.changes_panel.refresh()
        card = self.chat.add_approval_card(approval_id, tool_name, args, diff)
        card.decision_made.connect(
            lambda approved, aid=approval_id: self._worker.resolve_approval(aid, approved)
            if self._worker is not None else None
        )

    def _on_tool_call(self, event: dict) -> None:
        tool_name = event.get("tool", "?")
        arguments = event.get("arguments", {})
        call_id = event.get("id", "")
        card = self.chat.add_tool_call(tool_name, arguments)
        self._stream_active = True
        self.chat.set_agent_progress({"phase": "tool", "tool": tool_name})
        if card and call_id:
            self._tool_cards[call_id] = card
        # Also update the ToolsPanel for detailed view
        self.tools_panel.on_tool_call(event)

    def _on_tool_result(self, event: dict) -> None:
        evidence = event.get("evidence") or {}
        call_id = event.get("id", "")
        card = self._tool_cards.get(call_id)
        if card:
            success = event.get("success", False)
            stdout = event.get("stdout", "")
            stderr = event.get("stderr", "")
            evidence = event.get("evidence")
            card.set_result(success, stdout, stderr, evidence, cancelled=event.get("error_code") == "CANCELLED",
                            error_code=event.get("error_code", ""), returncode=event.get("returncode"),
                            presentation=event.get("presentation"),
                            stdout_truncated=event.get("stdout_truncated", False),
                            stderr_truncated=event.get("stderr_truncated", False))
        # Also update the ToolsPanel
        self.tools_panel.on_tool_result(event)
        self.changes_panel.refresh()
        if hasattr(self.evidence_panel, "record_tool_receipt"):
            self.evidence_panel.record_tool_receipt(event)

        # Refresh editor/workspace if file was written
        tool_name = event.get("tool", "")
        if event.get("success") and tool_name in {"write", "edit", "run_command"}:
            self.workspace.refresh_git_status()
            args = event.get("arguments", {})
            p = (evidence or {}).get("proposal", {}).get("path") or args.get("path")
            paths = [p] if p else (evidence or {}).get("changeset", {}).get("paths", [])
            if self.editor_panel.current_path and any((self.controller.working_dir / path).resolve() == self.editor_panel.current_path.resolve() for path in paths) and not self.editor_panel.dirty():
                self.editor_panel.open_file(str(self.editor_panel.current_path))
                self._refresh_diff()

    def _on_session_done(self, session_id: str) -> None:
        self.chat.end_assistant_stream()
        self._stream_active = False
        cancelled = self._worker is not None and self._worker._cancelled
        self.chat.add_system_message(f"Conversación {session_id} · " + ("turno detenido; respuesta parcial conservada" if cancelled else "turno finalizado"))
        self._update_statusbar()
        self.resident_panel._refresh_lists()
        self.conversations_panel.refresh()

    def _worker_finished(self) -> None:
        active_approval = self.chat.active_approval_card()
        if active_approval is not None:
            active_approval.expire()
        self.changes_panel.refresh()
        self.conversations_panel.refresh()
        self.settings_panel.refresh_grants()
        if self._pending_new_session:
            self._pending_new_session = False
            self._new_session()

    def _on_agent_error(self, message: str) -> None:
        self.chat.end_assistant_stream()
        self._stream_active = False
        self.chat.set_status_error(message)
        actions = []
        if self._last_prompt:
            actions.append(("Reintentar turno", lambda p=self._last_prompt: self._retry_last_prompt(p)))
        actions.append(("Revisar Providers", self.open_providers))
        self.chat.add_recovery_card("Error en el turno del agente", message, actions)

    def _stop_agent(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            if self._worker._cancelled:
                return
            self.chat.set_status_stopping()
            self._worker.cancel()
            self.chat.add_system_message("Detención solicitada · se conservará la respuesta parcial recibida.")

    def closeEvent(self, event) -> None:
        workers = [self._worker, self.config_panel._worker, self.config_panel.subscriptions._worker, self.github_panel._worker, self.tests_panel._worker]
        running = [worker for worker in workers if worker is not None and worker.isRunning()]
        if running:
            for worker in running:
                worker.cancel()
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        self.close_all_panel_windows()
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        card = self.chat.active_approval_card()
        if card is not None and not card._decided:
            if key == Qt.Key.Key_Y:
                card.approve_button.click()
                event.accept()
                return
            elif key in (Qt.Key.Key_N, Qt.Key.Key_Escape):
                card.reject_button.click()
                event.accept()
                return

        if key == Qt.Key.Key_Escape:
            if self._worker is not None and self._worker.isRunning():
                self._stop_agent()
                event.accept()
                return

        super().keyPressEvent(event)
