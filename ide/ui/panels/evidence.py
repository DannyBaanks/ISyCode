"""Evidence panel: contract verifier results, verification report and
the read-only ISyCo bridge contract viewer."""

from __future__ import annotations

from datetime import datetime
import json

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QSplitter, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)


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
        self.verify_button = QPushButton("Run contract verifier")
        self.verify_button.setToolTip("Ejecuta el verificador de contratos determinista sobre el workspace")
        self.verify_button.clicked.connect(self.run_verify)
        row.addWidget(self.verify_button)

        self.report_button = QPushButton("Ver reporte")
        self.report_button.setToolTip("Ver tests/CONTRACT_VERIFICATION.md")
        self.report_button.clicked.connect(self.show_report)
        row.addWidget(self.report_button)

        self.bridge_button = QPushButton("ISyCo contracts")
        self.bridge_button.setToolTip("Ver contratos del bridge ISyCo (solo lectura)")
        self.bridge_button.clicked.connect(self.show_bridge)
        row.addWidget(self.bridge_button)

        row.addStretch(1)

        self.help_button = QPushButton("?")
        self.help_button.setObjectName("helpButton")
        self.help_button.setToolTip(
            "Evidence: Muestra los resultados de la verificación formal de contratos de IsyVM y "
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
        self.receipts_tree.header().setStretchLastSection(True)
        self.receipts_tree.currentItemChanged.connect(self._inspect_receipt)
        rec_split.addWidget(self.receipts_tree)

        self.receipt_detail = QPlainTextEdit()
        self.receipt_detail.setReadOnly(True)
        self.receipt_detail.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        rec_split.addWidget(self.receipt_detail)
        rec_split.setSizes([340, 420])
        rec_layout.addWidget(rec_split, stretch=1)
        self.tabs.addTab(receipts_page, "📜 Recibos y evidencia")

        # Tab 2: Contract verifier & ISyCo bridge
        contracts_page = QWidget()
        contracts_layout = QVBoxLayout(contracts_page)
        contracts_layout.setContentsMargins(4, 4, 4, 4)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Target", "PASS", "Checks"])
        self.tree.header().setStretchLastSection(True)
        split.addWidget(self.tree)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self.view.setPlainText(
            "Pulsa «Run contract verifier» para ejecutar la verificación determinista de contratos "
            "o «ISyCo contracts» para inspeccionar los contratos del bridge (solo lectura)."
        )
        split.addWidget(self.view)
        split.setSizes([300, 450])
        contracts_layout.addWidget(split, stretch=1)
        self.tabs.addTab(contracts_page, "✅ Verificador de contratos")

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
                    "time": str(rec.get("created") or "")[:19].replace("T", " "),
                    "source": "proposal",
                    "status": str(rec.get("status", "")),
                    "target": str(rec.get("path", "") or rec.get("id", ""))[:40],
                    "payload": rec,
                })
        except (OSError, ValueError):
            pass
        for entry in items:
            row = QTreeWidgetItem([entry["time"], entry["source"], entry["status"], entry["target"]])
            row.setData(0, Qt.ItemDataRole.UserRole, entry["payload"])
            self.receipts_tree.addTopLevelItem(row)
        if items:
            self.receipts_summary.setText(f"{len(items)} recibo(s) verificable(s) en {self.controller.working_dir.name}")
            self.receipts_tree.setCurrentItem(self.receipts_tree.topLevelItem(0))
        else:
            self.receipts_summary.setText("Sin recibos todavía en este proyecto")
            self.receipt_detail.setPlainText(
                "Aún no hay recibos registrados en este proyecto.\n\n"
                "Cómo generar evidencia verificable:\n"
                "1. Pide al agente una inspección en PLAN o un cambio en CODER.\n"
                "2. Ejecuta pruebas desde el panel Pruebas.\n"
                "3. O pulsa «Run contract verifier» arriba para verificar los contratos del proyecto."
            )

    def _inspect_receipt(self, current, _previous=None) -> None:
        if current is None:
            return
        payload = current.data(0, Qt.ItemDataRole.UserRole)
        self.receipt_detail.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False, default=str))

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
                "ISyCo contracts (read-only bridge, GOLDEN 1):\n\n"
                + "\n".join(contracts))
            self.view.appendPlainText(
                "\n\n--- bootstrap/bootstrap.iesy ---\n"
                + self.controller.bridge_read_contract("bootstrap/bootstrap.iesy"))
        except Exception as exc:
            self.view.setPlainText(f"bridge error: {exc}")