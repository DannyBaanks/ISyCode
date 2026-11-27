"""Worktrees panel: list, create, open and safely remove Git worktrees.

All Git work runs in a :class:`WorktreeJob` (QThread + private asyncio loop) so
the UI never blocks. Removal always goes through ``WorktreeManager.preflight_remove``
first; when preflight finds uncommitted, untracked or unmerged work the panel
shows the warnings and refuses unless the operator explicitly confirms a force.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                                QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                                QPushButton, QVBoxLayout, QWidget)

from core.worktrees import PreflightReport, Worktree, WorktreeError, WorktreeManager
from ui.icons import icon


class WorktreeJob(QThread):
    """Runs an async worktree operation on a private event loop."""

    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._cancelled = False

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            loop = self._loop
            task = self._task
            if loop is not None and not loop.is_closed() and task is not None:
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    pass

    def run(self):
        loop = asyncio.new_event_loop()
        with self._lock:
            self._loop = loop
        try:
            with self._lock:
                if self._cancelled:
                    return
                task = loop.create_task(self.operation())
                self._task = task
            result = loop.run_until_complete(task)
            if not self._cancelled:
                self.ready.emit(result)
        except asyncio.CancelledError:
            pass
        except WorktreeError as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))
        except Exception:
            if not self._cancelled:
                self.failed.emit("No se pudo completar la operación de worktree. Revisa la carpeta y sus permisos.")
        finally:
            with self._lock:
                self._loop = None
                self._task = None
            loop.close()


class WorktreesPanel(QWidget):
    """Lists every worktree of the active repository with safe create/open/remove."""

    worktree_open_requested = Signal(str)   # absolute path of the worktree to open
    worktrees_changed = Signal()            # emitted after any successful add/remove

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.repo: Path | None = None
        self.manager: WorktreeManager | None = None
        self._worker: WorktreeJob | None = None
        self._worktrees: list[Worktree] = []
        self._reports: dict[str, PreflightReport] = {}
        # ``True`` once Git confirmed the bound folder is a checkout. A non-repo folder
        # keeps the panel visible but inert so the operator is never offered actions that
        # would fail; it flips back on as soon as ``set_repo`` receives a real checkout.
        self._repo_ok: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Worktrees")
        title.setObjectName("githubSectionTitle")
        header.addWidget(title)
        self.repo_label = QLabel("sin repositorio")
        self.repo_label.setObjectName("repoMetadata")
        header.addWidget(self.repo_label)
        header.addStretch(1)
        layout.addLayout(header)

        self.notice = QLabel("Abre una carpeta con Git para gestionar sus worktrees.")
        self.notice.setWordWrap(True)
        self.notice.setObjectName("pageSubtitle")
        layout.addWidget(self.notice)

        self.list = QListWidget()
        self.list.setObjectName("worktreeList")
        self.list.setIconSize(self.list.iconSize())
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemDoubleClicked.connect(lambda item: self.open_selected())
        self.list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.list, stretch=1)

        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setObjectName("repoMetadata")
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail)

        buttons = QHBoxLayout()
        self.create_btn = QPushButton("Crear worktree")
        self.create_btn.setIcon(icon("plus", size=18))
        self.create_btn.clicked.connect(self.create_worktree)
        buttons.addWidget(self.create_btn)
        self.open_btn = QPushButton("Abrir en IDE")
        self.open_btn.clicked.connect(self.open_selected)
        buttons.addWidget(self.open_btn)
        self.remove_btn = QPushButton("Eliminar")
        self.remove_btn.setToolTip("Preflight primero: nunca borra cambios sin confirmar")
        self.remove_btn.clicked.connect(self.remove_selected)
        buttons.addWidget(self.remove_btn)
        buttons.addStretch(1)
        self.refresh_btn = QPushButton("Actualizar")
        self.refresh_btn.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_btn)
        layout.addLayout(buttons)

        self._controls()
        # Bind immediately to the active workspace so a panel constructed by MainWindow
        # is already populated; ``set_repo`` is a no-op when nothing changes.
        self.set_repo(self._active_root())

    # --- repository binding --------------------------------------------------

    def set_repo(self, repo: str | Path | None) -> None:
        """Bind to ``repo`` (any folder inside a Git checkout). ``None`` disables the panel.

        Re-binding the same folder only refreshes the list; a different folder resets
        state. Safe to call while a job is running (the new refresh is simply refused
        until the worker finishes, leaving the previous list in place).
        """
        new_repo = Path(repo).resolve() if repo else None
        self._repo_ok = new_repo is not None
        if new_repo == self.repo and new_repo is not None:
            self.refresh()
            return
        self.repo = new_repo
        self.manager = WorktreeManager(self.repo) if self.repo else None
        self._worktrees = []
        self._reports = {}
        self.list.clear()
        self.detail.setText("")
        self.repo_label.setText(self.repo.name if self.repo else "sin repositorio")
        if self.repo is None:
            self.notice.setText("Abre una carpeta con Git para gestionar sus worktrees.")
            self._controls()
            return
        if not any((p / ".git").exists() for p in (self.repo, *self.repo.parents)):
            self._repo_ok = False
            self.notice.setText("La carpeta no es un repositorio Git.")
            self._controls()
            return
        self.refresh()

    def shutdown(self, wait_ms: int = 1500) -> None:
        worker = self._worker
        if worker is not None:
            try:
                worker.cancel()
                if worker.isRunning():
                    worker.wait(wait_ms)
            except RuntimeError:
                pass

    def worktrees(self) -> list[Worktree]:
        return list(self._worktrees)

    def _active_root(self) -> Path | None:
        return getattr(self.controller, "working_dir", None)

    # --- jobs -----------------------------------------------------------------

    def _job(self, operation, ready, *, failed=None) -> bool:
        # ``ready`` is delivered (queued) after ``run()`` returned, so by the time a
        # callback chains a second job the previous worker is no longer executing even
        # though ``_finished`` has not run yet; only refuse while the thread is alive.
        if self._worker is not None and self._worker.isRunning():
            return False
        if self._worker is not None:
            # Retire the finished worker eagerly so chained jobs are accepted.
            self._finished(self._worker)
        worker = WorktreeJob(operation, parent=self)
        self._worker = worker
        worker.ready.connect(ready)
        worker.failed.connect(failed or self._failed)
        worker.finished.connect(lambda w=worker: self._finished(w))
        self.notice.setText("Consultando Git…")
        worker.start()
        self._controls()
        return True

    def _finished(self, worker: WorktreeJob) -> None:
        if self._worker is worker:
            self._worker = None
        worker.deleteLater()
        self._controls()

    def _failed(self, text: str) -> None:
        self.notice.setText(text)
        # A listing failure on bind means the folder is not a usable checkout: keep the
        # panel inert until a real repo is bound, instead of offering buttons that fail.
        if not self._worktrees:
            self._repo_ok = False
        self._controls()

    def busy(self) -> bool:
        # ``isRunning()`` is False in the window between ``start()`` and the thread
        # actually spinning up, so treat a live worker handle as busy until finished —
        # except once ``isFinished()`` is True (callback chaining).
        worker = self._worker
        return worker is not None and not worker.isFinished()

    def _controls(self) -> None:
        idle = not self.busy()
        has_repo = self.manager is not None and self._repo_ok
        has_selection = self.list.currentItem() is not None
        self.create_btn.setEnabled(idle and has_repo)
        self.refresh_btn.setEnabled(idle and has_repo)
        self.open_btn.setEnabled(idle and has_selection)
        self.remove_btn.setEnabled(idle and has_selection and not self._selected_is_main())

    def _selected_is_main(self) -> bool:
        item = self.list.currentItem()
        if item is None or not self._worktrees:
            return False
        return bool(item.data(Qt.ItemDataRole.UserRole + 1))

    # --- listing ----------------------------------------------------------------

    def refresh(self) -> None:
        if self.manager is None:
            return
        manager = self.manager

        def ready(records):
            self._repo_ok = True
            self._worktrees = list(records)
            self._reports = {}
            self._populate()
            self.worktrees_changed.emit()

        self._job(manager.list_worktrees, ready)

    def _populate(self) -> None:
        current = self.list.currentItem()
        current_path = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.list.clear()
        if not self._worktrees:
            self.notice.setText("No hay worktrees; el checkout principal no aparece como vinculado.")
        for index, record in enumerate(self._worktrees):
            is_main = index == 0 and not record.detached
            label = record.name
            if record.detached:
                label = f"{record.head[:7] or 'HEAD'} (detached)"
            if record.bare:
                label = f"{Path(record.path).name} (bare)"
            item = QListWidgetItem(icon("changes", size=18), label)
            item.setData(Qt.ItemDataRole.UserRole, record.path)
            item.setData(Qt.ItemDataRole.UserRole + 1, is_main)
            item.setToolTip(record.path)
            self.list.addItem(item)
        if current_path:
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.ItemDataRole.UserRole) == current_path:
                    self.list.setCurrentRow(i)
                    break
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.notice.setText(f"{len(self._worktrees)} worktree(s) · {self.repo.name if self.repo else ''}")
        self._controls()

    def _on_row_changed(self, row: int) -> None:
        self._controls()
        if row < 0 or row >= len(self._worktrees):
            self.detail.setText("")
            return
        record = self._worktrees[row]
        flags = []
        if row == 0:
            flags.append("principal")
        if record.detached:
            flags.append("HEAD separado")
        if record.locked:
            flags.append("bloqueado" + (f": {record.lock_reason}" if record.lock_reason else ""))
        if record.prunable:
            flags.append("prunable" + (f": {record.prunable_reason}" if record.prunable_reason else ""))
        self.detail.setText(f"{record.path}\n{record.head[:12] or 'sin HEAD'}  ·  " + " · ".join(flags))

    # --- actions -----------------------------------------------------------------

    def selected_path(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def open_selected(self) -> None:
        path = self.selected_path()
        if path:
            self.worktree_open_requested.emit(path)

    def create_worktree(self) -> None:
        """Ask for a branch and relative folder, then add a worktree (``-b`` creates the branch)."""
        if self.manager is None or self.busy():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Crear worktree")
        form = QFormLayout(dialog)
        branch = QLineEdit()
        branch.setPlaceholderText("feature/nueva-rama")
        form.addRow("Rama", branch)
        folder = QLineEdit()
        default_folder = self._suggest_folder("")
        folder.setText(default_folder)
        folder.setPlaceholderText("..\\nombre-carpeta")
        form.addRow("Carpeta", folder)
        create_box = QCheckBox("Crear la rama si no existe")
        create_box.setChecked(True)
        form.addRow(create_box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Crear")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        branch.textChanged.connect(lambda text: folder.setText(self._suggest_folder(text)))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = branch.text().strip()
        target = folder.text().strip()
        if not name or not target:
            self.notice.setText("Indica una rama y una carpeta para el worktree.")
            return
        manager = self.manager
        want_branch = create_box.isChecked()

        def operation():
            return manager.add_worktree(self._resolve_target(target), name, create_branch=want_branch)

        def ready(record):
            self.notice.setText(f"Worktree creado: {record.path}")
            self.refresh()

        self._job(operation, ready)

    def _suggest_folder(self, branch: str) -> str:
        base = self.repo.name if self.repo else "repo"
        slug = branch.strip().replace("/", "-").replace(" ", "-") or "feature"
        return f"../{base}-{slug}"

    def _resolve_target(self, target: str) -> Path:
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = (self.repo.parent if self.repo else Path.cwd()) / path
        return path

    def remove_selected(self) -> None:
        """Preflight → confirm → remove. Refusal warnings are surfaced, never swallowed."""
        path = self.selected_path()
        if not path or self.manager is None or self.busy():
            return
        if self._selected_is_main():
            self.notice.setText("El checkout principal no se elimina desde aquí; usa 'git worktree remove' en el terminal.")
            return
        manager = self.manager

        def operation():
            return manager.preflight_remove(path)

        def ready(report: PreflightReport):
            self._reports[path] = report
            self._on_row_changed(self.list.currentRow())
            if report.blocking:
                self.notice.setText("No se puede eliminar: el worktree está bloqueado"
                                    + (f" ({report.lock_reason})" if report.lock_reason else "") + ".")
                return
            if report.safe:
                self._do_remove(path, force=False)
                return
            self.notice.setText("Preflight encontró trabajo en riesgo en este worktree; revisa el detalle.")
            warning = "\n".join("• " + w for w in report.warnings())
            answer = QMessageBox.warning(
                self, "Eliminar worktree con cambios",
                f"Se perdería trabajo no integrado en:\n{report.path}\n\n{warning}\n\n"
                "Elige 'Forzar' para eliminarlo de todas formas, o 'Cancelar' para conservarlo.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Discard,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Discard:
                self._do_remove(path, force=True)
            else:
                self.notice.setText("Se conservó el worktree con su trabajo local.")

        self._job(operation, ready)

    def _do_remove(self, path: str, *, force: bool) -> None:
        """Second stage: run the removal Git already preflighted (``force`` only after consent)."""
        manager = self.manager

        def operation():
            return manager.remove_worktree(path, force=force)

        def failed(text: str) -> None:
            # Preflight passed but Git still refused (e.g. a lock appeared meanwhile):
            # surface Git's own message rather than the generic failure line.
            self.notice.setText("Git no eliminó el worktree: " + text)

        def ready(report: PreflightReport):
            self._reports.pop(path, None)
            self.notice.setText(f"Worktree eliminado: {report.path}")
            self.refresh()
            self.worktrees_changed.emit()

        self._job(operation, ready, failed=failed)


__all__ = ["WorktreeJob", "WorktreesPanel"]
