"""Native ISyMCP Hub Control Panel: MCP servers, Skills, and ISyCo Connectors."""

from __future__ import annotations

import json
import shutil
import socket
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def _mcp_config_path() -> Path:
    real_home = Path("/home/danny") if Path("/home/danny/.config/isycode/mcp.json").is_file() else Path.home()
    return real_home / ".config" / "isycode" / "mcp.json"


def _skill_search_dirs(working_dir: Path | None) -> list[Path]:
    dirs: list[Path] = []
    if working_dir is not None:
        dirs.append(Path(working_dir) / ".agents" / "skills")
    dirs.extend([
        Path.home() / ".agents" / "skills",
        Path("/home/danny/Development/ISyCo/.agents/skills"),
    ])
    seen: set[str] = set()
    unique: list[Path] = []
    for d in dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key not in seen and d.is_dir():
            seen.add(key)
            unique.append(d)
    return unique


class AddMcpServerDialog(QDialog):
    """Dialog to add an MCP server entry to ~/.config/isycode/mcp.json."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Añadir servidor MCP")
        self.resize(480, 260)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("ej. isymcp-hub")
        self.cmd_edit = QLineEdit()
        self.cmd_edit.setPlaceholderText("ej. /home/danny/.local/bin/isymcp o npx")
        self.args_edit = QLineEdit()
        self.args_edit.setPlaceholderText('ej. ["--stdio"] (lista JSON opcional)')
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("ej. http://127.0.0.1:8798/mcp (opcional si es HTTP)")
        form.addRow("Nombre:", self.name_edit)
        form.addRow("Comando:", self.cmd_edit)
        form.addRow("Argumentos:", self.args_edit)
        form.addRow("URL HTTP:", self.url_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.entry: tuple[str, dict] | None = None

    def _validate(self) -> None:
        name = self.name_edit.text().strip()
        cmd = self.cmd_edit.text().strip()
        url = self.url_edit.text().strip()
        if not name or (not cmd and not url):
            QMessageBox.warning(self, "Datos requeridos", "Indica un nombre y al menos un comando o URL HTTP.")
            return
        spec: dict = {}
        if url:
            spec["url"] = url
        if cmd:
            spec["command"] = cmd
            raw_args = self.args_edit.text().strip()
            if raw_args:
                try:
                    parsed = json.loads(raw_args)
                    if not isinstance(parsed, list):
                        raise ValueError("Debe ser lista JSON")
                    spec["args"] = [str(a) for a in parsed]
                except Exception as exc:
                    QMessageBox.warning(self, "Argumentos inválidos", f"Formato JSON inválido: {exc}")
                    return
        self.entry = (name, spec)
        self.accept()


class AddSkillDialog(QDialog):
    """Dialog to scaffold a new SKILL.md inside <project>/.agents/skills/<name>/."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crear nueva Skill")
        self.resize(480, 240)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("ej. code-review-isyco")
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Qué hace esta skill y cuándo activarla")
        form.addRow("Nombre (slug):", self.name_edit)
        form.addRow("Descripción:", self.desc_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.result_data: tuple[str, str] | None = None

    def _validate(self) -> None:
        import re
        slug = self.name_edit.text().strip().lower().replace(" ", "-")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", slug):
            QMessageBox.warning(self, "Nombre inválido", "Usa letras minúsculas, números, guiones o guiones bajos.")
            return
        self.result_data = (slug, self.desc_edit.text().strip() or "Skill personalizada para ISyCode IDE.")
        self.accept()


class ISyMCPControlPanel(QWidget):
    """Unified control center for ISyMCP Hub, MCP servers, Skills, and ISyCo Connectors."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        hdr = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("ISyMCP Hub")
        title.setObjectName("pageTitle")
        title_box.addWidget(title)
        sub = QLabel("Panel de control nativo: servidores MCP, Skills y conectores del ecosistema ISyCo")
        sub.setObjectName("pageSubtitle")
        title_box.addWidget(sub)
        hdr.addLayout(title_box, 1)

        self.hub_badge = QLabel("Hub :8798 · sin comprobar")
        self.hub_badge.setStyleSheet("padding: 4px 10px; border-radius: 10px; background: #142030; color: #94a3b8; font-weight: 600;")
        hdr.addWidget(self.hub_badge)

        self.web_btn = QPushButton("Abrir Hub :8798")
        self.web_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("http://127.0.0.1:8798")))
        hdr.addWidget(self.web_btn)

        self.refresh_btn = QPushButton("Comprobar todo")
        self.refresh_btn.setProperty("variant", "primary")
        self.refresh_btn.clicked.connect(self.refresh_all)
        hdr.addWidget(self.refresh_btn)
        layout.addLayout(hdr)

        self.tabs = QTabWidget()

        # --- Tab 1: MCP Servers ---
        mcp_page = QWidget()
        m_lay = QVBoxLayout(mcp_page)
        m_lay.setContentsMargins(8, 8, 8, 8)
        m_lay.setSpacing(8)
        m_top = QHBoxLayout()
        self.mcp_path_label = QLabel("")
        self.mcp_path_label.setStyleSheet("color: #9aa3b2; font-size: 12px;")
        m_top.addWidget(self.mcp_path_label, 1)
        add_mcp_btn = QPushButton("➕ Añadir servidor MCP")
        add_mcp_btn.setProperty("variant", "primary")
        add_mcp_btn.clicked.connect(self._add_mcp_server)
        m_top.addWidget(add_mcp_btn)
        del_mcp_btn = QPushButton("Eliminar seleccionado")
        del_mcp_btn.setProperty("variant", "danger")
        del_mcp_btn.clicked.connect(self._remove_mcp_server)
        m_top.addWidget(del_mcp_btn)
        m_lay.addLayout(m_top)

        self.mcp_table = QTableWidget(0, 4)
        self.mcp_table.setHorizontalHeaderLabels(["Servidor", "Transporte", "Comando / URL", "Estado"])
        self.mcp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.mcp_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        mhdr = self.mcp_table.horizontalHeader()
        mhdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        mhdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        mhdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        mhdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        m_lay.addWidget(self.mcp_table, stretch=1)
        self.tabs.addTab(mcp_page, "🔌 Servidores MCP")

        # --- Tab 2: Skills ---
        skills_page = QWidget()
        sk_lay = QVBoxLayout(skills_page)
        sk_lay.setContentsMargins(8, 8, 8, 8)
        sk_lay.setSpacing(8)
        sk_top = QHBoxLayout()
        self.skill_search = QLineEdit()
        self.skill_search.setPlaceholderText("Buscar skill por nombre o descripción…")
        self.skill_search.textChanged.connect(self._filter_skills)
        sk_top.addWidget(self.skill_search, 1)
        self.skills_count = QLabel("0 skills")
        self.skills_count.setStyleSheet("color: #9aa3b2; font-size: 12px;")
        sk_top.addWidget(self.skills_count)
        add_skill_btn = QPushButton("➕ Nueva Skill")
        add_skill_btn.setProperty("variant", "primary")
        add_skill_btn.clicked.connect(self._add_skill)
        sk_top.addWidget(add_skill_btn)
        sk_lay.addLayout(sk_top)

        sk_split = QSplitter(Qt.Orientation.Horizontal)
        self.skills_table = QTableWidget(0, 3)
        self.skills_table.setHorizontalHeaderLabels(["Skill", "Origen", "Descripción"])
        self.skills_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.skills_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        shdr = self.skills_table.horizontalHeader()
        shdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        shdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        shdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.skills_table.currentCellChanged.connect(lambda r, _c, _pr, _pc: self._inspect_skill(r))
        sk_split.addWidget(self.skills_table)

        self.skill_preview = QPlainTextEdit()
        self.skill_preview.setReadOnly(True)
        self.skill_preview.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self.skill_preview.setPlaceholderText("Selecciona una skill para ver sus instrucciones SKILL.md.")
        sk_split.addWidget(self.skill_preview)
        sk_split.setSizes([560, 440])
        sk_lay.addWidget(sk_split, stretch=1)
        self.tabs.addTab(skills_page, "✨ Skills")

        # --- Tab 3: Connectors ---
        conn_page = QWidget()
        c_lay = QVBoxLayout(conn_page)
        c_lay.setContentsMargins(8, 8, 8, 8)
        c_lay.setSpacing(8)
        self.conn_summary = QLabel("Conectores locales y herramientas públicas de ISyCo")
        self.conn_summary.setStyleSheet("color: #9aa3b2; font-size: 12px;")
        c_lay.addWidget(self.conn_summary)
        self.conn_table = QTableWidget(0, 4)
        self.conn_table.setHorizontalHeaderLabels(["Conector", "Estado", "Ubicación / Puerto", "Descripción"])
        self.conn_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.conn_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        chdr = self.conn_table.horizontalHeader()
        chdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        chdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        chdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        chdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        c_lay.addWidget(self.conn_table, stretch=1)
        self.tabs.addTab(conn_page, "🔗 Conectores")

        layout.addWidget(self.tabs, stretch=1)
        self._skills_data: list[dict] = []
        self.refresh_all()

    @staticmethod
    def _port_open(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            return False

    @staticmethod
    def _find_bin(name: str) -> str:
        found = shutil.which(name)
        if found:
            return found
        for base in (Path.home() / ".local" / "bin", Path("/home/danny/.local/bin")):
            cand = base / name
            if cand.exists():
                return str(cand)
        return ""

    def refresh_all(self) -> None:
        hub_up = self._port_open(8798)
        mon_up = self._port_open(8799)
        if hub_up:
            self.hub_badge.setText("● Hub :8798 ACTIVO" + (" · Monitor :8799 ON" if mon_up else ""))
            self.hub_badge.setStyleSheet("padding: 4px 10px; border-radius: 10px; background: #0d3326; color: #34d399; font-weight: 700;")
        else:
            self.hub_badge.setText("○ Hub :8798 detenido" + (" · Monitor :8799 ON" if mon_up else ""))
            self.hub_badge.setStyleSheet("padding: 4px 10px; border-radius: 10px; background: #1e293b; color: #94a3b8; font-weight: 600;")
        self._refresh_mcp_servers()
        self._refresh_skills()
        self._refresh_connectors(hub_up, mon_up)

    def _load_mcp_json(self) -> tuple[Path, dict]:
        cfg = _mcp_config_path()
        if not cfg.is_file():
            return cfg, {"mcpServers": {}}
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return cfg, {"mcpServers": {}}
            return cfg, data
        except Exception:
            return cfg, {"mcpServers": {}}

    def _refresh_mcp_servers(self) -> None:
        cfg, data = self._load_mcp_json()
        servers = data.get("mcpServers") or data.get("servers") or {}
        if not isinstance(servers, dict):
            servers = {}
        self.mcp_path_label.setText(f"Configuración MCP: {cfg} · {len(servers)} servidor(es)")
        self.mcp_table.setRowCount(len(servers))
        for idx, (name, spec) in enumerate(sorted(servers.items())):
            if not isinstance(spec, dict):
                spec = {}
            transport = "HTTP/SSE" if spec.get("url") else "stdio"
            target = str(spec.get("url") or (str(spec.get("command", "")) + " " + " ".join(map(str, spec.get("args", [])))).strip())
            disabled = bool(spec.get("disabled"))
            self.mcp_table.setItem(idx, 0, QTableWidgetItem(name))
            self.mcp_table.setItem(idx, 1, QTableWidgetItem(transport))
            self.mcp_table.setItem(idx, 2, QTableWidgetItem(target))
            self.mcp_table.setItem(idx, 3, QTableWidgetItem("Desactivado" if disabled else "Registrado"))

    def _add_mcp_server(self) -> None:
        dlg = AddMcpServerDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.entry:
            return
        name, spec = dlg.entry
        cfg, data = self._load_mcp_json()
        servers = data.setdefault("mcpServers", {})
        servers[name] = spec
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self._refresh_mcp_servers()

    def _remove_mcp_server(self) -> None:
        row = self.mcp_table.currentRow()
        if row < 0:
            return
        name = self.mcp_table.item(row, 0).text()
        cfg, data = self._load_mcp_json()
        servers = data.get("mcpServers") or data.get("servers")
        if isinstance(servers, dict) and name in servers:
            del servers[name]
            cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            self._refresh_mcp_servers()

    def _refresh_skills(self) -> None:
        self._skills_data = []
        seen: set[str] = set()
        for base in _skill_search_dirs(self.controller.working_dir):
            for skill_md in sorted(base.glob("*/SKILL.md")):
                slug = skill_md.parent.name
                if slug in seen:
                    continue
                seen.add(slug)
                desc = ""
                try:
                    content = skill_md.read_text(encoding="utf-8", errors="replace")
                    if content.startswith("---"):
                        parts = content.split("---", 2)
                        if len(parts) >= 3:
                            for line in parts[1].splitlines():
                                if line.strip().startswith("description:"):
                                    desc = line.split(":", 1)[1].strip().strip('"').strip("'")
                                    break
                except OSError:
                    content = ""
                self._skills_data.append({
                    "name": slug,
                    "origin": base.parent.parent.name,
                    "desc": desc or "(sin descripción)",
                    "path": str(skill_md),
                    "content": content,
                })
        self._filter_skills(self.skill_search.text())

    def _filter_skills(self, query: str) -> None:
        q = query.strip().casefold()
        filtered = [
            s for s in self._skills_data
            if not q or q in s["name"].casefold() or q in s["desc"].casefold()
        ]
        self.skills_count.setText(f"{len(filtered)} / {len(self._skills_data)} skills")
        self.skills_table.setRowCount(len(filtered))
        for idx, s in enumerate(filtered):
            item = QTableWidgetItem(s["name"])
            item.setData(Qt.ItemDataRole.UserRole, s)
            self.skills_table.setItem(idx, 0, item)
            self.skills_table.setItem(idx, 1, QTableWidgetItem(s["origin"]))
            self.skills_table.setItem(idx, 2, QTableWidgetItem(s["desc"]))

    def _inspect_skill(self, row: int) -> None:
        if row < 0:
            return
        item = self.skills_table.item(row, 0)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            self.skill_preview.setPlainText(f"# {data['path']}\n\n{data['content']}")

    def _add_skill(self) -> None:
        dlg = AddSkillDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_data:
            return
        slug, desc = dlg.result_data
        target = self.controller.working_dir / ".agents" / "skills" / slug / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"---\nname: {slug}\ndescription: {desc}\n---\n\n# {slug}\n\n{desc}\n",
            encoding="utf-8",
        )
        self._refresh_skills()

    def _refresh_connectors(self, hub_up: bool, mon_up: bool) -> None:
        rows = [
            ("ISyMCP Hub", "ACTIVO" if hub_up else ("Instalado" if self._find_bin("isymcp") else "No encontrado"),
             "http://127.0.0.1:8798" if hub_up else (self._find_bin("isymcp") or "—"),
             "Gateway MCP local + puente ChatGPT↔MCP"),
            ("ISyMCP Monitor", "ACTIVO" if mon_up else "Detenido", "http://127.0.0.1:8799",
             "Demonio de tareas y leases SQLite WAL"),
            ("isymem", "Disponible" if self._find_bin("isymem") else "No encontrado",
             self._find_bin("isymem") or "—", "Memoria compartida multi-harness (grafo en Sistema → Memoria local)"),
            ("ziggrep", "Disponible" if self._find_bin("ziggrep") else "No encontrado",
             self._find_bin("ziggrep") or "—", "Búsqueda de código ultra-rápida en Zig"),
            ("isycode CLI", "Disponible" if self._find_bin("isycode") else "No encontrado",
             self._find_bin("isycode") or "—", "CLI/TUI oficial de DannyBaanks/ISyCode"),
            ("GitHub CLI (gh)", "Disponible" if self._find_bin("gh") else "No encontrado",
             self._find_bin("gh") or "—", "Catálogo, PRs, Issues y sync de repos públicos ISyCo"),
            ("Codex CLI", "Disponible" if self._find_bin("codex") else "No encontrado",
             self._find_bin("codex") or "—", "Conector de agente / suscripción OpenAI Codex"),
            ("Claude Code", "Disponible" if self._find_bin("claude") else "No encontrado",
             self._find_bin("claude") or "—", "Conector de agente / suscripción Anthropic Claude"),
        ]
        self.conn_table.setRowCount(len(rows))
        for idx, (name, st, loc, desc) in enumerate(rows):
            self.conn_table.setItem(idx, 0, QTableWidgetItem(name))
            self.conn_table.setItem(idx, 1, QTableWidgetItem(st))
            self.conn_table.setItem(idx, 2, QTableWidgetItem(loc))
            self.conn_table.setItem(idx, 3, QTableWidgetItem(desc))
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn_summary.setText(f"Conectores ISyCo · comprobado {stamp}")
