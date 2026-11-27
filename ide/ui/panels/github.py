"""GitHub repository catalog and explicit local synchronization in Qt."""

from __future__ import annotations

import asyncio
import html
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal, QTimer, QSize
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton,
                               QSplitter, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget, QFrame, QScrollArea,
                               QTabWidget, QTextBrowser, QComboBox)

from core.github_service import GitHubError, GitHubService, GitSyncService
from ui.icons import icon
from ui import theme
from ui.widgets import button_row


class GitHubJob(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, operation, *, mutating=False, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.mutating = mutating
        self._loop = self._task = None
        self._cancelled = False

    def cancel(self):
        if self.mutating:
            return  # Finish the Git transaction before destroying its worker.
        self._cancelled = True
        if self._loop is not None and self._task is not None:
            try:
                self._loop.call_soon_threadsafe(self._task.cancel)
            except RuntimeError:
                pass

    def run(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            if self._cancelled:
                return
            self._task = loop.create_task(self.operation())
            result = loop.run_until_complete(self._task)
            if not self._cancelled:
                self.ready.emit(result)
        except asyncio.CancelledError:
            pass
        except GitHubError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("No se pudo completar la operación de GitHub. Revisa la sesión, la carpeta y sus permisos.")
        finally:
            self._loop = self._task = None
            loop.close()


class GitHubPanel(QWidget):
    folder_open_requested = Signal(str)
    project_status_changed = Signal(object)

    def __init__(self, controller, *, busy_guard=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.busy_guard = busy_guard or (lambda: False)
        self.service = GitHubService()
        self._worker = None
        self._repos = []
        self._syncs = {}
        self._status = None
        self._statuses = {}
        self._catalog_loading = False
        self._account_verified = False
        self._selected_repo = self._selected_folder = ""
        self.setMinimumWidth(520)
        self._details = {}
        self._detail_pending = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)
        header = QHBoxLayout()
        title = QLabel("GitHub")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.account = QLabel("gh · sin verificar")
        self.account.setObjectName("githubAccount")
        header.addWidget(self.account)
        self.catalog_button = QPushButton("Conectar gh · cargar repos")
        self.catalog_button.setIcon(icon("github"))
        self.catalog_button.clicked.connect(self.load_catalog)
        header.addWidget(self.catalog_button)
        self.cancel_button = QPushButton("Cancelar consulta")
        self.cancel_button.clicked.connect(self.cancel)
        header.addWidget(self.cancel_button)
        layout.addLayout(header)
        self.notice = QLabel("Conecta tu cuenta para consultar repositorios y actividad.")
        self.notice.setWordWrap(True)
        self.notice.setObjectName("pageSubtitle")
        layout.addWidget(self.notice)
        # Non-blocking opt-in banner for automatic gh verification
        from PySide6.QtWidgets import QCheckBox
        self.auto_verify_banner = QFrame()
        self.auto_verify_banner.setObjectName("statusCard")
        av_lay = QHBoxLayout(self.auto_verify_banner)
        av_lay.setContentsMargins(12, 8, 12, 8)
        av_lay.setSpacing(10)
        av_lbl = QLabel("¿Verificar gh y cargar tus repositorios automáticamente al abrir GitHub?")
        av_lbl.setWordWrap(True)
        av_lay.addWidget(av_lbl, 1)
        self.auto_verify_remember = QCheckBox("No volver a mostrar")
        av_lay.addWidget(self.auto_verify_remember)
        av_yes = QPushButton("Sí, verificar ahora")
        av_yes.setProperty("variant", "primary")
        av_yes.clicked.connect(lambda: self._answer_auto_verify(True))
        av_lay.addWidget(av_yes)
        av_no = QPushButton("Ahora no")
        av_no.clicked.connect(lambda: self._answer_auto_verify(False))
        av_lay.addWidget(av_no)
        self.auto_verify_banner.hide()
        layout.addWidget(self.auto_verify_banner)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        layout.addWidget(split, 1)
        left = QWidget()
        left.setMinimumWidth(260)
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 18, 0)
        left_box.setSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en tus repositorios…")
        self.search.textChanged.connect(self._filter)
        left_box.addWidget(self.search)
        self.repo_filter = QComboBox()
        self.repo_filter.addItem("Todos los repositorios", "all")
        self.repo_filter.addItem("Repos públicos ISyCo", "public")
        self.repo_filter.addItem("Con carpeta vinculada", "linked")
        self.repo_filter.addItem("Con commits pendientes de Pull", "behind")
        self.repo_filter.currentIndexChanged.connect(lambda _: self._filter(self.search.text()))
        left_box.addWidget(self.repo_filter)
        self.tree = QTreeWidget()
        self.tree.setObjectName("githubRepositories")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setColumnHidden(1, True)
        self.tree.setIndentation(18)
        self.tree.currentItemChanged.connect(self._select)
        left_box.addWidget(self.tree, 1)
        self.link_button = QPushButton("Vincular carpeta local…")
        self.link_button.setIcon(icon("folder"))
        self.link_button.clicked.connect(self.link_folder)
        self.auto_link_button = QPushButton("Autodetectar")
        self.auto_link_button.setToolTip("Escanea ~/Development y vincula automáticamente cada carpeta con su repositorio remoto de GitHub")
        self.auto_link_button.clicked.connect(self.auto_discover_folders)
        self.auto_link_button.setProperty("variant", "ghost")
        self.check_all_button = QPushButton("Comprobar vinculadas")
        self.check_all_button.setToolTip("Consulta el estado remoto de todas las carpetas vinculadas")
        self.check_all_button.clicked.connect(self.refresh_all)
        self.check_all_button.setProperty("variant", "ghost")
        left_box.addLayout(button_row(self.link_button, self.auto_link_button, self.check_all_button, align="left"))
        split.addWidget(left)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        right = QWidget()
        right.setObjectName("githubDetail")
        right.setMinimumWidth(390)
        scroll.setWidget(right)
        box = QVBoxLayout(right)
        box.setContentsMargins(18, 0, 4, 4)
        box.setSpacing(16)
        heading = QHBoxLayout()
        self.repo_title = QLabel("Elige un repositorio")
        self.repo_title.setTextFormat(Qt.TextFormat.PlainText)
        self.repo_title.setObjectName("repoTitle")
        self.repo_title.setWordWrap(True)
        heading.addWidget(self.repo_title, 1)
        self.web_button = QPushButton("Abrir en GitHub")
        self.web_button.clicked.connect(self.open_web)
        heading.addWidget(self.web_button)
        box.addLayout(heading)
        self.repo_description = QLabel("La actividad remota está disponible aunque todavía no vincules una carpeta.")
        self.repo_description.setTextFormat(Qt.TextFormat.PlainText)
        self.repo_description.setWordWrap(True)
        self.repo_description.setObjectName("repoDescription")
        box.addWidget(self.repo_description)
        self.repo_meta = QLabel("Sin consulta remota")
        self.repo_meta.setTextFormat(Qt.TextFormat.PlainText)
        self.repo_meta.setWordWrap(True)
        self.repo_meta.setObjectName("repoMetadata")
        box.addWidget(self.repo_meta)
        metrics = QHBoxLayout()
        self.metrics = {}
        for key, caption in (("branch", "RAMA PRINCIPAL"), ("language", "LENGUAJE"), ("stars", "ESTRELLAS"), ("forks", "FORKS")):
            card = QFrame()
            card.setObjectName("githubMetric")
            cell = QVBoxLayout(card)
            cell.setContentsMargins(12, 12, 12, 12)
            label = QLabel(caption)
            label.setObjectName("metricCaption")
            cell.addWidget(label)
            value = QLabel("—")
            value.setObjectName("metricValue")
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(True)
            cell.addWidget(value)
            self.metrics[key] = value
            metrics.addWidget(card, 1)
        box.addLayout(metrics)
        activity_header = QHBoxLayout()
        activity_title = QLabel("Actividad en GitHub")
        activity_title.setObjectName("githubSectionTitle")
        activity_header.addWidget(activity_title, 1)
        self.activity_button = QPushButton("Actualizar actividad")
        self.activity_button.clicked.connect(self.refresh_activity)
        activity_header.addWidget(self.activity_button)
        box.addLayout(activity_header)
        self.activity_tabs = QTabWidget()
        self.activity_tabs.setDocumentMode(True)
        self.activity_tabs.setMinimumHeight(230)
        self.activity_tabs.setMaximumHeight(290)
        self.activity_views = {}
        for key, caption in (("pulls", "Pull requests"), ("issues", "Issues"), ("commits", "Commits"), ("actions", "CI · Actions")):
            view = QTextBrowser()
            view.setObjectName("githubActivity")
            view.setOpenExternalLinks(True)
            view.setHtml("<p>Selecciona un repositorio para consultar su actividad.</p>")
            self.activity_tabs.addTab(view, caption)
            self.activity_views[key] = view
        box.addWidget(self.activity_tabs, 1)
        self.activity_stamp = QLabel("Listas recientes · los commits remotos no indican cuánto falta en tu carpeta.")
        self.activity_stamp.setObjectName("repoMetadata")
        self.activity_stamp.setWordWrap(True)
        box.addWidget(self.activity_stamp)
        local_card = QFrame()
        local_card.setObjectName("githubLocalCard")
        local_box = QVBoxLayout(local_card)
        local_box.setContentsMargins(18, 16, 18, 16)
        local_box.setSpacing(10)
        local_title = QLabel("Tu carpeta local")
        local_title.setObjectName("githubSectionTitle")
        local_box.addWidget(local_title)
        self.folder_label = QLabel("Vincula la raíz del proyecto para comparar rama y commits.")
        self.folder_label.setWordWrap(True)
        self.folder_label.setTextFormat(Qt.TextFormat.PlainText)
        local_box.addWidget(self.folder_label)
        self.counters = QLabel("Sin carpeta vinculada")
        self.counters.setObjectName("syncCount")
        self.counters.setWordWrap(True)
        local_box.addWidget(self.counters)
        self.local_label = QLabel()
        self.local_label.setWordWrap(True)
        local_box.addWidget(self.local_label)
        self.commits = QPlainTextEdit()
        self.commits.setReadOnly(True)
        self.commits.setMaximumHeight(130)
        self.commits.setPlaceholderText("Comprueba el remoto para ver los commits entrantes en esta rama.")
        self.commits.hide()
        local_box.addWidget(self.commits)
        self.incoming_button = QPushButton("Ver commits que llegarán")
        self.incoming_button.clicked.connect(lambda: self.commits.setVisible(not self.commits.isVisible()))
        self.incoming_button.hide()
        local_box.addWidget(self.incoming_button)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Comprobar remoto")
        self.refresh_button.clicked.connect(self.refresh_remote)
        actions.addWidget(self.refresh_button)
        self.pull_button = QPushButton("Revisar Pull…")
        self.pull_button.setToolTip("Inspecciona los archivos que cambiarán y aplica un pull fast-forward (solo avance directo; no comenta ni aprueba PRs)")
        self.pull_button.setProperty("variant", "primary")
        self.pull_button.clicked.connect(self.preview_pull)
        actions.addWidget(self.pull_button)
        self.diff_button = QPushButton("Ver diferencias")
        self.diff_button.clicked.connect(self.show_differences)
        actions.addWidget(self.diff_button)
        local_box.addLayout(actions)
        self.open_folder_button = QPushButton("Abrir carpeta en IDE")
        self.open_folder_button.clicked.connect(self.open_folder)
        local_box.addWidget(self.open_folder_button)
        note = QLabel("Pull revisa los archivos y usa avance directo. Cambios locales o divergencia requieren revisión manual.")
        note.setObjectName("repoMetadata")
        note.setWordWrap(True)
        local_box.addWidget(note)
        box.addWidget(local_card)
        box.insertWidget(4, local_card)
        split.addWidget(scroll)
        split.setStretchFactor(1, 1)
        split.setSizes([440, 1000])
        self._controls()

    def _controls(self):
        running = self._worker is not None and self._worker.isRunning()
        self.catalog_button.setEnabled(not running)
        self.tree.setEnabled(not running)
        self.link_button.setEnabled(not running and bool(self._selected_repo) and self._account_verified)
        if hasattr(self, "auto_link_button"):
            self.auto_link_button.setEnabled(not running and self._account_verified)
        self.check_all_button.setEnabled(not running and self._account_verified)
        self.refresh_button.setEnabled(not running and bool(self._selected_folder) and self._account_verified)
        self.pull_button.setEnabled(not running and self._account_verified and self._status is not None and self._status.can_update)
        self.diff_button.setEnabled(not running and self._status is not None and bool(self._status.target))
        self.open_folder_button.setEnabled(not running and bool(self._selected_folder))
        self.web_button.setEnabled(bool(self._selected_repo))
        self.activity_button.setEnabled(not running and self._account_verified and bool(self._selected_repo))
        for button in (self.refresh_button, self.pull_button, self.diff_button, self.open_folder_button):
            button.setVisible(bool(self._selected_folder))
        self.cancel_button.setVisible(running and not self._worker.mutating if running else False)

    def _job(self, operation, ready, *, mutating=False, failed=None):
        if self._worker is not None and self._worker.isRunning():
            return False
        if self.busy_guard():
            self.notice.setText("Detén el turno del agente antes de modificar o consultar este checkout desde GitHub.")
            return False
        worker = GitHubJob(operation, mutating=mutating, parent=self)
        self._worker = worker
        worker.ready.connect(ready)
        worker.failed.connect(failed or self._failed)
        worker.finished.connect(lambda w=worker: self._finished(w))
        self._busy_notice = "Actualizando carpeta; espera a que Git termine…" if mutating else "Consultando…"
        self.notice.setText(self._busy_notice)
        worker.start()
        self._controls()
        return True

    def _finished(self, worker):
        if self._worker is worker:
            self._worker = None
            self._catalog_loading = False
            if self.notice.text() == getattr(self, "_busy_notice", None):
                self.notice.clear()
            self._controls()
            if self._detail_pending:
                QTimer.singleShot(0, self._load_pending_activity)
        worker.deleteLater()

    def _failed(self, text):
        self.notice.setText(text)
        if self._catalog_loading:
            self._account_verified = False
            self.account.setText("gh sin verificar")
            self.account.setProperty("verified", False)
            theme.repolish(self.account)
        self._status = None
        if self._selected_folder:
            self._statuses.pop(self._selected_folder, None)
            if Path(self._selected_folder).resolve() == self.controller.working_dir.resolve():
                self.project_status_changed.emit(None)
        self.counters.setText("Estado remoto desconocido · vuelve a comprobar")
        self._controls()

    def cancel(self):
        self._detail_pending = ""
        if self._worker is not None:
            if self._worker.mutating:
                return
            self._worker.cancel()
        self.notice.setText("Consulta cancelada; vuelve a comprobar antes de actualizar.")
        self._status = None
        if self._selected_folder:
            self._statuses.pop(self._selected_folder, None)
            if Path(self._selected_folder).resolve() == self.controller.working_dir.resolve():
                self.project_status_changed.emit(None)

    def load_catalog(self):
        self.auto_verify_banner.hide()
        if self._job(self.service.catalog, self._catalog_ready):
            self._catalog_loading = True
            self._account_verified = False
            self._statuses.clear()
            self.project_status_changed.emit(None)
            self.account.setText("Verificando gh…")
            self.account.setProperty("verified", False)
            theme.repolish(self.account)
            self._empty_activity("Verificando la cuenta activa…")
            self._details.clear()

    def _catalog_ready(self, report):
        self.auto_verify_banner.hide()
        self._account_verified = report["verified"]
        self.account.setProperty("verified", self._account_verified)
        theme.repolish(self.account)
        self.account.setText(report["login"] + " · gh verificado")
        self.catalog_button.setText("Actualizar catálogo")
        self._repos = report["repositories"]
        self.tree.clear()
        try:
            links = self.service.links.list()
        except (ValueError, OSError):
            links = []
            self.notice.setText("No se pudo leer el registro de carpetas; puedes volver a vincularlas.")
        for repo in self._repos:
            matched = [link for link in links if str(link.get("repo", "")).lower() == repo["name"].lower()]
            visibility = "Privado" if repo["private"] else "Público"
            if repo.get("archived"):
                visibility += " · Archivado"
            item = QTreeWidgetItem([repo["name"].split("/", 1)[1] + "\n" + visibility + " · " + repo["name"].split("/", 1)[0], visibility])
            item.setIcon(0, icon("github"))
            item.setSizeHint(0, QSize(260, 64))
            item.setToolTip(0, repo["name"] + "\n" + repo.get("description", ""))
            item.setData(0, Qt.ItemDataRole.UserRole, (repo["name"], ""))
            self.tree.addTopLevelItem(item)
            for link in matched:
                child = QTreeWidgetItem([Path(link["folder"]).name + "\nSin comprobar", "Sin comprobar"])
                child.setToolTip(0, link["folder"])
                child.setSizeHint(0, QSize(260, 58))
                child.setData(0, Qt.ItemDataRole.UserRole, (repo["name"], link["folder"]))
                item.addChild(child)
            item.setExpanded(True)
        self.notice.setText("Repositorios propios consultados. Vincula o selecciona una carpeta local." +
                            (" Se alcanzó el límite de 10 000 repositorios; la cuenta puede tener más." if report["may_have_more"] else ""))
        self._filter(self.search.text())
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _filter(self, text):
        mode = self.repo_filter.currentData()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            linked = item.childCount() > 0
            behind = any((self._statuses.get(item.child(child).data(0, Qt.ItemDataRole.UserRole)[1]) or (None,))[0] is not None
                         and (self._statuses[item.child(child).data(0, Qt.ItemDataRole.UserRole)[1]][0].behind or 0) > 0
                         for child in range(item.childCount()))
            item.setHidden(text.casefold() not in item.data(0, Qt.ItemDataRole.UserRole)[0].casefold()
                           or (mode == "public" and "Privado" in item.text(1))
                           or (mode == "linked" and not linked) or (mode == "behind" and not behind))

    def _select(self, current, previous=None):
        self._status = None
        self._selected_repo = self._selected_folder = ""
        self.commits.clear()
        self.commits.hide()
        self.incoming_button.hide()
        self._detail_pending = ""
        if current is None:
            self.repo_meta.clear()
            self.folder_label.clear()
            self.local_label.clear()
            self.counters.setText("Sin repositorio seleccionado")
            self.repo_title.setText("Elige un repositorio")
            self.repo_description.setText("Conecta gh y selecciona un repositorio del catálogo.")
            self._empty_activity("Sin repositorio seleccionado")
            self._controls()
            return
        self._selected_repo, self._selected_folder = current.data(0, Qt.ItemDataRole.UserRole)
        self.repo_title.setText(self._selected_repo)
        self.folder_label.setText(self._selected_folder or "Repositorio sin carpeta vinculada. Elige Vincular carpeta local.")
        self.counters.setText("Sin comprobar" if self._selected_folder else "Sin carpeta vinculada")
        self.local_label.clear()
        metadata = next((repo for repo in self._repos if repo["name"].casefold() == self._selected_repo.casefold()), {})
        self.repo_description.setText(metadata.get("description") or "Este repositorio no tiene descripción.")
        self._empty_activity("Consultando actividad…")
        self.repo_meta.setText(("Privado" if metadata.get("private") else "Público") + (" · Archivado" if metadata.get("archived") else ""))
        if self._selected_repo in self._details:
            self._show_activity(self._details[self._selected_repo])
        else:
            self._detail_pending = self._selected_repo
            QTimer.singleShot(0, self._load_pending_activity)
        if self._selected_folder in self._statuses:
            self._show_status(*self._statuses[self._selected_folder])
        self._controls()

    def _empty_activity(self, message):
        loading = message.startswith(("Consultando", "Verificando"))
        for value in self.metrics.values():
            value.setText("…" if loading else "—")
        self.activity_stamp.setText("Actividad sin consultar · no describe la sincronización local.")
        for view in self.activity_views.values():
            view.setHtml("<p>" + html.escape(message) + "</p>")

    def _load_pending_activity(self):
        if self._detail_pending != self._selected_repo or not self._selected_repo:
            return
        if self._worker is not None:
            return
        self._detail_pending = ""
        self.refresh_activity()

    def refresh_activity(self):
        if not self._account_verified or not self._selected_repo:
            return
        repo = self._selected_repo
        def ready(report):
            self._details[repo] = report
            if self._selected_repo == repo:
                self._show_activity(report)
        def failed(message):
            if self._selected_repo == repo:
                self._details.pop(repo, None)
                self._empty_activity("Actividad no disponible. " + message)
                self.notice.setText(message)
                self._account_verified = False
                self.account.setText("gh · vuelve a verificar")
                self.account.setProperty("verified", False)
                theme.repolish(self.account)
                self._controls()
        if self._job(lambda: self.service.repository_details(repo), ready, failed=failed):
            self._empty_activity("Consultando GitHub…")
        else:
            self._empty_activity("Termina la operación activa y pulsa Actualizar actividad.")

    def _show_activity(self, report):
        if report["repo"] != self._selected_repo:
            return
        self.repo_description.setText(report["description"] or "Este repositorio no tiene descripción.")
        self.repo_meta.setText(("Privado" if report["private"] else "Público") +
                              (" · Archivado" if report["archived"] else "") +
                              " · Último push: " + self._date(report["pushed"]))
        for key, value in self.metrics.items():
            data = report.get(key)
            value.setText(str(data) if data is not None and data != "" else "—")
        names = {"pulls": "PRs abiertos", "issues": "Issues abiertos", "commits": "Commits recientes · rama principal", "actions": "Ejecuciones recientes · todas las ramas"}
        for key, view in self.activity_views.items():
            section = report["sections"][key]
            if not section["available"]:
                view.setHtml("<p>" + html.escape(section["error"]) + "</p>")
                continue
            rows = section["rows"]
            content = f'<h3>{names[key]}</h3><p style="color:{theme.TEXT_DIM}">Muestra reciente · {len(rows)} elementos' + (" · puede haber más" if section["limited"] else "") + "</p>"
            if not rows:
                content += "<p>No hay elementos en esta muestra.</p>"
            for row in rows:
                tag = ("#" + str(row["number"]) + (" · Borrador" if row.get("draft") else "")) if "number" in row else row.get("sha", "")[:8]
                state = row.get("conclusion") or row.get("status", "")
                detail = " · ".join(filter(None, [tag, row.get("author", ""), row.get("branch", ""), state, self._date(row.get("updated", ""))]))
                url = html.escape(row["url"], quote=True)
                title = html.escape(row["title"] or "Sin título")
                content += f'<p><a href="{url}" style="color:{theme.TEXT};text-decoration:none"><b>{title}</b></a><br><span style="color:{theme.TEXT_DIM}">{html.escape(detail)}</span></p><hr>'
            view.setHtml(content)
        self.activity_stamp.setText("Consultado: " + self._date(report["checked"]) + " · muestras de hasta 30 elementos")
        self.notice.setText("Actividad remota disponible. La sincronización local se comprueba por separado.")

    @staticmethod
    def _date(value):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y · %H:%M UTC")
        except (ValueError, TypeError, AttributeError):
            return "sin fecha"

    def _sync(self, folder=None):
        folder = folder or self._selected_folder
        return self._syncs.setdefault(folder, GitSyncService(folder))

    def link_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Vincular raíz del checkout o worktree", str(self.controller.working_dir))
        if not folder:
            return
        repo = self._selected_repo
        async def link():
            return await self._sync(folder).link(repo)
        def ready(status):
            self._selected_folder = status.folder
            self._show_status(status)
            self.notice.setText("Carpeta vinculada por su identidad remota. Comprueba el remoto para habilitar Pull.")
            item = self.tree.currentItem()
            if item is not None:
                while item.parent() is not None:
                    item = item.parent()
                child = QTreeWidgetItem([Path(status.folder).name + "\nSin comprobar", "Sin comprobar"])
                child.setToolTip(0, status.folder)
                child.setSizeHint(0, QSize(260, 58))
                child.setData(0, Qt.ItemDataRole.UserRole, (repo, status.folder))
                item.addChild(child)
                item.setExpanded(True)
                self.tree.setCurrentItem(child)
        self._job(link, ready)

    def refresh_remote(self):
        repo = self._selected_repo
        sync = self._sync()
        async def refresh():
            status = await sync.inspect(refresh=True, expected_repo=repo)
            return status, await sync.incoming(status)
        self._job(refresh, lambda result: self._show_status(*result))

    def refresh_all(self):
        owned = {repo["name"].casefold() for repo in self._repos}
        try:
            links = [link for link in self.service.links.list() if link["repo"].casefold() in owned]
        except (ValueError, OSError):
            self._failed("No se pudo leer el registro de carpetas vinculadas.")
            return
        semaphore = asyncio.Semaphore(2)
        async def refresh():
            async def one(link):
                async with semaphore:
                    try:
                        sync = self._sync(link["folder"])
                        status = await sync.inspect(refresh=True, expected_repo=link["repo"])
                        return link["folder"], status, await sync.incoming(status), None
                    except GitHubError as exc:
                        return link["folder"], None, [], str(exc)
            return await asyncio.gather(*(one(link) for link in links))
        def ready(results):
            failures = 0
            for folder, status, commits, error in results:
                if status is not None:
                    self._statuses[folder] = (status, commits)
                else:
                    failures += 1
                    self._statuses.pop(folder, None)
                    if Path(folder).resolve() == self.controller.working_dir.resolve():
                        self.project_status_changed.emit(None)
                for index in range(self.tree.topLevelItemCount()):
                    item = self.tree.topLevelItem(index)
                    for child_index in range(item.childCount()):
                        child = item.child(child_index)
                        if child.data(0, Qt.ItemDataRole.UserRole)[1] == folder:
                            child.setText(1, self._count_text(status) if status else "Desconocido")
                            child.setText(0, Path(folder).name + "\n" + (self._count_text(status) if status else "Desconocido"))
                            child.setToolTip(1, error or ("Comprobado: " + status.checked))
            if self._selected_folder in self._statuses:
                self._show_status(*self._statuses[self._selected_folder])
            elif self._selected_folder:
                self._status = None
                self.counters.setText("Estado remoto desconocido")
            self.notice.setText(f"{len(results)} carpetas consultadas · {failures} sin comprobar. Ninguna carpeta se actualiza automáticamente.")
            self._filter(self.search.text())
        self._job(refresh, ready)

    @staticmethod
    def _count_text(status):
        if status.behind is None:
            return "Historia incompleta o upstream desconocido"
        return f"{status.behind} commits detrás · {status.ahead} por delante"

    def _show_status(self, status, commits=None):
        self._status = status
        self._statuses[status.folder] = (status, commits or [])
        self.folder_label.setText(f"{status.folder}\n{status.branch or 'HEAD separado'} → {status.upstream or 'sin upstream'}")
        counts = self._count_text(status)
        self.counters.setText(counts + ("" if status.fresh else " · información sin refrescar"))
        self.local_label.setText(f"{status.staged} staged · {status.unstaged} sin preparar · {status.untracked} sin seguimiento" +
                                 (" · CONFLICTOS" if status.conflicts else ""))
        self.commits.setPlainText("Cambios que llegarán\n\n" + "\n".join(commits or []))
        self.incoming_button.setVisible(bool(commits))
        self.notice.setText("Última comprobación local: " + self._date(status.checked) + ". " +
                            ("Comparación verificada." if status.fresh else "Comprueba el remoto para actualizar la información."))
        current = self.tree.currentItem()
        if current is not None and current.data(0, Qt.ItemDataRole.UserRole)[1]:
            current.setText(1, counts)
            current.setText(0, Path(status.folder).name + "\n" + counts)
            current.setToolTip(0, status.folder + "\n" + counts)
        self._filter(self.search.text())
        self._controls()
        if Path(status.folder).resolve() == self.controller.working_dir.resolve():
            self.project_status_changed.emit(status)

    def show_differences(self):
        status = self._status
        if status is None:
            return
        def ready(diff):
            dialog = QDialog(self)
            dialog.setWindowTitle("Diferencias locales → GitHub")
            dialog.resize(1000, 700)
            layout = QVBoxLayout(dialog)
            label = QLabel(f"{status.repo} · {status.branch}\n{status.head[:12]} → {status.target[:12]}")
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label)
            view = QPlainTextEdit()
            view.setReadOnly(True)
            view.setObjectName("monoView")
            view.setPlainText(diff or "Sin diferencias de archivos entre estas revisiones.")
            layout.addWidget(view)
            dialog.show()
        self._job(lambda: self._sync(status.folder).differences(status), ready)

    def preview_pull(self):
        sync = self._sync()
        repo = self._selected_repo
        self._job(lambda: sync.preview_pull(repo), self._review_pull)

    def _review_pull(self, preview):
        dialog = QDialog(self)
        dialog.setWindowTitle("Revisar actualización de carpeta")
        dialog.resize(800, 620)
        box = QVBoxLayout(dialog)
        label = QLabel(f"{preview.status.repo}\nRama: {preview.status.branch}\n{preview.status.head[:12]} → {preview.status.target[:12]}\n{len(preview.files)} archivos afectados")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        box.addWidget(label)
        manifest = QPlainTextEdit()
        manifest.setReadOnly(True)
        manifest.setPlainText("\n".join(f"{change}\t{path}" for change, path in preview.files))
        box.addWidget(manifest, 1)
        note = QLabel("A = nuevo · M = modificado · D = eliminado. Actualizar aplica exactamente este manifiesto; se comprobarán de nuevo rama, base, remoto y cambios locales.")
        note.setWordWrap(True)
        box.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Aplicar actualización revisada")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        # Defer until this preview worker finishes before starting another.
        from PySide6.QtCore import QTimer
        def review():
            if self._worker is not None and self._worker.isRunning():
                QTimer.singleShot(20, review)
                return
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.notice.setText("Actualización rechazada; la carpeta se conserva.")
                return
            sync = self._sync(preview.status.folder)
            self._job(lambda: sync.apply_pull(preview.id, operator_approved=True),
                      lambda result: self._show_status(result[0]), mutating=True)
        QTimer.singleShot(0, review)

    def maybe_auto_verify(self):
        """Non-blocking opt-in automatic gh verification with 'No volver a mostrar' persistence."""
        if self._account_verified or self._catalog_loading or (self._worker is not None and self._worker.isRunning()):
            return
        if getattr(self, "_auto_verify_prompted", False):
            return
        from core.ui_preferences import UiPreferences
        try:
            pref = UiPreferences().load().get("github_auto_verify")
        except (OSError, ValueError):
            pref = None
        if pref is True:
            self._auto_verify_prompted = True
            self.auto_verify_banner.hide()
            self.load_catalog()
            return
        if pref is False:
            self._auto_verify_prompted = True
            self.auto_verify_banner.hide()
            return
        self._auto_verify_prompted = True
        self.auto_verify_banner.show()

    def _answer_auto_verify(self, accepted: bool) -> None:
        self.auto_verify_banner.hide()
        if self.auto_verify_remember.isChecked():
            from core.ui_preferences import UiPreferences
            try:
                UiPreferences().save(github_auto_verify=accepted)
            except (OSError, ValueError):
                pass
        if accepted:
            self.load_catalog()

    def auto_discover_folders(self):
        """Scan local Development folders and auto-link every git checkout matching a catalog repo."""
        import re
        if not self._account_verified or not self._repos:
            self.notice.setText("Primero carga el catálogo de repositorios para autodetectar carpetas.")
            return
        owned_map = {repo["name"].casefold(): repo["name"] for repo in self._repos}

        def _parse_remote(url: str) -> str:
            m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?$", url.strip(), re.IGNORECASE)
            return m.group(1) if m else ""

        async def _origin_remote(folder: Path) -> str:
            """Non-blocking ``git remote get-url origin``; empty string when absent.

            P1-6: the previous ``subprocess.run`` blocked the worker's event loop for up
            to 2 s per candidate (and cancelled nothing), stalling every other GitHub
            job; the async child process is awaited and cancellable.
            """
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "-C", str(folder), "remote", "get-url", "origin",
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
                )
            except (OSError, ValueError):
                return ""
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2)
            except asyncio.CancelledError:
                try:
                    proc.kill()
                    await proc.wait()
                except (OSError, ProcessLookupError):
                    pass
                raise
            except (asyncio.TimeoutError, OSError):
                try:
                    proc.kill()
                    await proc.wait()
                except (OSError, ProcessLookupError):
                    pass
                return ""
            return stdout.decode(errors="replace").strip() if proc.returncode == 0 else ""

        async def scan():
            roots = []
            for base in (Path.home() / "Development", Path("/home/danny/Development")):
                if base.is_dir() and str(base.resolve()) not in {str(r) for r in roots}:
                    roots.append(base.resolve())
            candidates: list[Path] = []
            for base in roots:
                for sub in sorted(base.iterdir()):
                    if not sub.is_dir() or sub.name.startswith("."):
                        continue
                    if (sub / ".git").exists():
                        candidates.append(sub)
                    else:
                        try:
                            for nested in sorted(sub.iterdir()):
                                if nested.is_dir() and not nested.name.startswith(".") and (nested / ".git").exists():
                                    candidates.append(nested)
                        except OSError:
                            continue
            linked = []
            existing = {(l.get("repo", "").casefold(), str(Path(l.get("folder", "")).resolve()))
                        for l in self.service.links.list() if l.get("folder")}
            for folder in candidates:
                try:
                    remote_repo = _parse_remote(await _origin_remote(folder))
                    if not remote_repo:
                        continue
                    canonical = owned_map.get(remote_repo.casefold())
                    if not canonical:
                        continue
                    resolved = str(folder.resolve())
                    if (canonical.casefold(), resolved) in existing:
                        continue
                    await self._sync(resolved).link(canonical)
                    existing.add((canonical.casefold(), resolved))
                    linked.append((canonical, resolved))
                except Exception:
                    continue
            return linked

        def ready(linked):
            if linked:
                self.notice.setText(f"Autodetección completada: {len(linked)} carpeta(s) nueva(s) vinculada(s) automáticamente.")
                # Refresh tree with newly linked folders
                self._catalog_ready({"verified": True, "login": self.account.text().split(" · ")[0], "repositories": self._repos, "may_have_more": False})
            else:
                self.notice.setText("Autodetección completada: no se encontraron carpetas locales nuevas sin vincular en ~/Development.")

        self._job(scan, ready)

    def open_folder(self):
        if self._selected_folder and not self.busy_guard():
            self.folder_open_requested.emit(self._selected_folder)

    def open_web(self):
        if self._selected_repo:
            QDesktopServices.openUrl(QUrl("https://github.com/" + self._selected_repo))
