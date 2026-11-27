"""Evidence panel: contract verifier results, verification report and
the read-only ISyCo bridge contract viewer."""

from __future__ import annotations

from datetime import datetime
import json

from html import escape

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
                               QPushButton, QSplitter, QStackedWidget, QTabWidget,
                               QTextBrowser, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

_SOURCE_LABELS = {"proposal": "Propuesta"}
_STATUS_LABELS = {
    "applied": ("Aplicada", "#4ade80"), "ok": ("OK", "#4ade80"), "pass": ("PASS", "#4ade80"),
    "pending": ("Pendiente", "#fbbf24"), "proposed": ("Pendiente", "#fbbf24"),
    "rejected": ("Rechazada", "#f87171"), "reverted": ("Revertida", "#94a3b8"),
    "fail": ("Fallo", "#f87171"), "failed": ("Fallo", "#f87171"),
}
_OPERATION_LABELS = {"edit": "Edición", "write": "Escritura", "create": "Creación",
                     "delete": "Borrado", "rename": "Renombrado", "patch": "Parche"}
_FIELD_LABELS = [("operation", "Operación"), ("path", "Archivo"), ("tool", "Herramienta"),
                 ("id", "ID"), ("created", "Creado"), ("before_sha256", "SHA-256 antes"),
                 ("after_sha256", "SHA-256 después"), ("error_code", "Error")]


def _fmt_time(raw: str) -> str:
    """Uniform local 'dd/mm HH:MM:SS' for ISO stamps and bare HH:MM:SS."""
    raw = str(raw or "").strip()
    if not raw:
        return "—"
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            stamp = datetime.combine(datetime.now().date(), datetime.strptime(raw, "%H:%M:%S").time())
        except ValueError:
            return raw[:19]
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone()
    return stamp.strftime("%d/%m %H:%M:%S")


def _status_label(status: str) -> tuple[str, str | None]:
    return _STATUS_LABELS.get(str(status).lower(), (str(status) or "—", None))


class _VerifyWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller

    def run(self) -> None:
        try:
            self.done.emit(self.controller.verify_contracts())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class EvidencePanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._worker: _VerifyWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.verify_button = QPushButton("Verificar contratos")
        self.verify_button.setToolTip("Ejecuta el verificador de contratos determinista sobre el workspace")
        self.verify_button.clicked.connect(self.run_verify)
        row.addWidget(self.verify_button)

        self.report_button = QPushButton("Ver informe")
        self.report_button.setToolTip("Ver tests/CONTRACT_VERIFICATION.md")
        self.report_button.clicked.connect(self.show_report)
        row.addWidget(self.report_button)

        self.bridge_button = QPushButton("Contratos ISyCo")
        self.bridge_button.setToolTip("Ver contratos del bridge ISyCo (solo lectura)")
        self.bridge_button.clicked.connect(self.show_bridge)
        row.addWidget(self.bridge_button)

        row.addStretch(1)

        self.help_button = QPushButton("?")
        self.help_button.setObjectName("helpButton")
        self.help_button.setToolTip(
            "Evidencia: muestra los resultados de la verificación formal de contratos de IsyVM y "
            "los contratos del bridge de ISyCo."
        )
        row.addWidget(self.help_button)
        layout.addLayout(row)

        self.tabs = QTabWidget()

        # Tab 1: Persisted proposals & live tool receipts
        receipts_page = QWidget()
        rec_layout = QVBoxLayout(receipts_page)
        rec_layout.setContentsMargins(4, 4, 4, 4)
        rec_layout.setSpacing(6)
        rec_hdr = QHBoxLayout()
        self.receipts_summary = QLabel("Recibos verificables del proyecto")
        self.receipts_summary.setStyleSheet("color: #9aa3b2; font-size: 12px;")
        rec_hdr.addWidget(self.receipts_summary, 1)
        self.refresh_receipts_btn = QPushButton("Actualizar recibos")
        self.refresh_receipts_btn.clicked.connect(self.refresh_receipts)
        rec_hdr.addWidget(self.refresh_receipts_btn)
        rec_layout.addLayout(rec_hdr)

        rec_split = QSplitter()
        self.receipts_tree = QTreeWidget()
        self.receipts_tree.setColumnCount(4)
        self.receipts_tree.setHeaderLabels(["Hora", "Origen", "Estado", "Objetivo / ID"])
        self.receipts_tree.setRootIsDecorated(False)
        header = self.receipts_tree.header()
        header.setStretchLastSection(True)
        for col in range(3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.receipts_tree.currentItemChanged.connect(self._inspect_receipt)
        rec_split.addWidget(self.receipts_tree)

        detail_box = QWidget()
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(6)
        detail_hdr = QHBoxLayout()
        detail_hdr.addStretch(1)
        self.json_toggle = QPushButton("Ver JSON")
        self.json_toggle.setProperty("variant", "ghost")
        self.json_toggle.setCheckable(True)
        self.json_toggle.setEnabled(False)
        self.json_toggle.toggled.connect(self._toggle_json)
        detail_hdr.addWidget(self.json_toggle)
        detail_layout.addLayout(detail_hdr)
        self.detail_stack = QStackedWidget()
        self.receipt_card = QTextBrowser()
        self.receipt_card.setOpenLinks(False)
        self.detail_stack.addWidget(self.receipt_card)
        self.receipt_detail = QPlainTextEdit()
        self.receipt_detail.setReadOnly(True)
        self.receipt_detail.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self.detail_stack.addWidget(self.receipt_detail)
        detail_layout.addWidget(self.detail_stack, 1)
        rec_split.addWidget(detail_box)
        rec_split.setSizes([520, 480])
        rec_layout.addWidget(rec_split, stretch=1)
        self.tabs.addTab(receipts_page, "Recibos")

        # Tab 2: Contract verifier & ISyCo bridge
        contracts_page = QWidget()
        contracts_layout = QVBoxLayout(contracts_page)
        contracts_layout.setContentsMargins(4, 4, 4, 4)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Objetivo", "Resultado", "Comprobaciones"])
        self.tree.header().setStretchLastSection(True)
        split.addWidget(self.tree)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self.view.setPlainText(
            "Pulsa «Verificar contratos» para ejecutar la verificación determinista de contratos "
            "o «Contratos ISyCo» para inspeccionar los contratos del bridge (solo lectura)."
        )
        split.addWidget(self.view)
        split.setSizes([300, 450])
        contracts_layout.addWidget(split, stretch=1)
        self.tabs.addTab(contracts_page, "Contratos")

        layout.addWidget(self.tabs, stretch=1)
        self._live_receipts: list[dict] = []
        self.refresh_receipts()

    def record_tool_receipt(self, event: dict) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._live_receipts.insert(0, {
            "time": stamp,
            "source": str(event.get("tool", "tool")),
            "status": "OK" if event.get("success") else (event.get("error_code") or "FAIL"),
            "target": str(event.get("id", ""))[:16],
            "payload": event,
        })
        self._live_receipts = self._live_receipts[:100]
        self.refresh_receipts()

    def refresh_receipts(self) -> None:
        self.receipts_tree.clear()
        items: list[dict] = list(self._live_receipts)
        try:
            for rec in sorted(self.controller.proposals.list(), key=lambda r: r.get("created") or "", reverse=True):
                items.append({
                    "time": str(rec.get("created") or ""),
                    "source": "proposal",
                    "status": str(rec.get("status", "")),
                    "target": str(rec.get("path", "") or rec.get("id", ""))[:40],
                    "payload": rec,
                })
        except (OSError, ValueError):
            pass
        for entry in items:
            status_text, status_color = _status_label(entry["status"])
            row = QTreeWidgetItem([_fmt_time(entry["time"]), _SOURCE_LABELS.get(entry["source"], entry["source"]),
                                   status_text, entry["target"]])
            row.setToolTip(3, entry["target"])
            if status_color:
                row.setForeground(2, QBrush(QColor(status_color)))
            row.setData(0, Qt.ItemDataRole.UserRole, entry["payload"])
            self.receipts_tree.addTopLevelItem(row)
        if items:
            self.receipts_summary.setText(f"{len(items)} recibo(s) verificable(s) en {self.controller.working_dir.name}")
            self.receipts_tree.setCurrentItem(self.receipts_tree.topLevelItem(0))
        else:
            self.receipts_summary.setText("Sin recibos todavía en este proyecto")
            self.json_toggle.setChecked(False)
            self.json_toggle.setEnabled(False)
            self.receipt_card.setHtml(
                "<p style='color:#cbd5e1'>Aún no hay recibos registrados en este proyecto.</p>"
                "<p style='color:#9aa3b2'>Cómo generar evidencia verificable:</p><ol style='color:#9aa3b2'>"
                "<li>Pide al agente una inspección en PLAN o un cambio en CODER.</li>"
                "<li>Ejecuta pruebas desde el panel Pruebas.</li>"
                "<li>O pulsa «Verificar contratos» arriba.</li></ol>"
            )
            self.receipt_detail.setPlainText("")

    def _toggle_json(self, checked: bool) -> None:
        self.detail_stack.setCurrentIndex(1 if checked else 0)
        self.json_toggle.setText("Ver resumen" if checked else "Ver JSON")

    def _inspect_receipt(self, current, _previous=None) -> None:
        if current is None:
            return
        payload = current.data(0, Qt.ItemDataRole.UserRole)
        self.json_toggle.setEnabled(True)
        self.receipt_detail.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        data = payload if isinstance(payload, dict) else {}
        status_text, status_color = _status_label(data.get("status") or current.text(2))
        title = escape(current.text(3) or "Recibo")
        rows = []
        for key, label in _FIELD_LABELS:
            value = data.get(key)
            if value in (None, ""):
                continue
            if key == "created":
                value = _fmt_time(value)
            elif key == "operation":
                value = _OPERATION_LABELS.get(str(value).lower(), str(value))
            else:
                value = str(value)
            mono = key.endswith("sha256") or key == "id"
            cell = f"<code>{escape(value)}</code>" if mono else escape(value)
            rows.append(f"<tr><td style='color:#9aa3b2;padding:3px 14px 3px 0'>{label}</td>"
                        f"<td style='color:#e2e8f0'>{cell}</td></tr>")
        color = status_color or "#cbd5e1"
        self.receipt_card.setHtml(
            f"<h3 style='color:#f1f5f9;margin:0 0 6px 0'>{title}</h3>"
            f"<p style='margin:0 0 10px 0'><span style='color:{color};font-weight:600'>● {escape(status_text)}</span>"
            f" <span style='color:#9aa3b2'>· {escape(current.text(1))} · {escape(current.text(0))}</span></p>"
            f"<table>{''.join(rows)}</table>"
        )

    def run_verify(self) -> None:
        self.verify_button.setEnabled(False)
        self.tree.clear()
        self._worker = _VerifyWorker(self.controller, self)
        self._worker.done.connect(self._on_verified)
        self._worker.failed.connect(self._on_verify_failed)
        self._worker.start()

    def _on_verified(self, summary: dict) -> None:
        self.verify_button.setEnabled(True)
        all_pass = True
        for target, data in summary.items():
            mark = "PASS" if data["passed"] == data["total"] else "FAIL"
            all_pass = all_pass and data["passed"] == data["total"]
            item = QTreeWidgetItem([target, f"{data['passed']}/{data['total']}", mark])
            for check in data["checks"]:
                QTreeWidgetItem(item, [check["law"], check["result"], check["detail"]])
            self.tree.addTopLevelItem(item)
        self.view.setPlainText(
            json.dumps(summary, indent=2, ensure_ascii=False))
        self.tree.expandAll()
        self.view.appendPlainText(f"\nALL CONTRACTS: {'PASS' if all_pass else 'FAIL'}")

    def _on_verify_failed(self, message: str) -> None:
        self.verify_button.setEnabled(True)
        self.view.setPlainText(f"verifier error: {message}")

    def show_report(self) -> None:
        path = self.controller.working_dir / "tests" / "CONTRACT_VERIFICATION.md"
        if path.is_file():
            self.view.setPlainText(path.read_text(encoding="utf-8"))
        else:
            self.view.setPlainText("report not found; run the verifier first")

    def show_bridge(self) -> None:
        try:
            contracts = self.controller.bridge_contracts()
            self.view.setPlainText(
                "Contratos ISyCo (bridge de solo lectura, GOLDEN 1):\n\n"
                + "\n".join(contracts))
            self.view.appendPlainText(
                "\n\n--- bootstrap/bootstrap.iesy ---\n"
                + self.controller.bridge_read_contract("bootstrap/bootstrap.iesy"))
        except Exception as exc:
            self.view.setPlainText(f"bridge error: {exc}")