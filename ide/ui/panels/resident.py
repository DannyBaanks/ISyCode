"""Resident & isymem panel: Obsidian-style interactive knowledge graph for isymem
plus structural project resident status, query, scan and sessions."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

CATEGORIES = [
    "architecture", "component", "contract", "constraint", "protected",
    "decision", "change", "verification", "plan", "unknown", "general",
]

NODE_COLORS = {
    "hub": QColor("#00d4ff"),
    "index": QColor("#38bdf8"),
    "project": QColor("#34d399"),
    "feedback": QColor("#fbbf24"),
    "reference": QColor("#a78bfa"),
    "user": QColor("#fb7185"),
    "other": QColor("#94a3b8"),
}


def find_isymem_dir(working_dir: Path | None = None) -> Path | None:
    """Locate the shared isymem bank without hardcoding a single path."""
    candidates: list[Path] = []
    if working_dir is not None:
        candidates.append(Path(working_dir) / "docs" / "agent" / "memory")
    candidates.extend([
        Path.home() / "Development" / "ISyCo" / "docs" / "agent" / "memory",
        Path("/home/danny/Development/ISyCo/docs/agent/memory"),
    ])
    for cand in candidates:
        if cand.is_dir() and any(cand.glob("*.md")):
            return cand
    return None


def load_isymem_graph(memory_dir: Path | None) -> dict:
    """Parse isymem markdown files and [[wikilinks]] / .md links into nodes and edges."""
    if memory_dir is None or not memory_dir.is_dir():
        return {"dir": None, "nodes": [], "edges": [], "projects": []}

    nodes_by_id: dict[str, dict] = {}
    raw_links: list[tuple[str, str]] = []
    wiki_re = re.compile(r"\[\[([A-Za-z0-9_.-]+)(?:\|[^\]]+)?\]\]")
    md_link_re = re.compile(r"\]\(([A-Za-z0-9_.-]+)\.md\)")

    for md in sorted(memory_dir.glob("*.md")):
        slug = md.stem
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        meta: dict[str, str] = {}
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k in {"name", "description", "type", "project", "node_type"}:
                            meta[k] = v

        if slug == "MEMORY":
            kind = "index"
        elif slug.startswith("hub-") or meta.get("node_type") == "hub":
            kind = "hub"
        else:
            kind = meta.get("type", "project")
            if kind not in NODE_COLORS:
                kind = "other"

        project = meta.get("project", "")
        if not project and slug.startswith("hub-"):
            project = slug.removeprefix("hub-")

        nodes_by_id[slug] = {
            "id": slug,
            "label": meta.get("name") or slug,
            "kind": kind,
            "project": project,
            "desc": meta.get("description", ""),
            "path": str(md),
            "content": text,
            "degree": 0,
        }

        for target in wiki_re.findall(text):
            if target != slug:
                raw_links.append((slug, target))
        for target in md_link_re.findall(text):
            if target != slug:
                raw_links.append((slug, target))
        if project and f"hub-{project}" != slug:
            raw_links.append((slug, f"hub-{project}"))

    # Deduplicate edges whose endpoints both exist
    edge_set: set[tuple[str, str]] = set()
    edges: list[tuple[str, str]] = []
    for a, b in raw_links:
        if a in nodes_by_id and b in nodes_by_id and a != b:
            key = (a, b) if a < b else (b, a)
            if key not in edge_set:
                edge_set.add(key)
                edges.append(key)
                nodes_by_id[a]["degree"] += 1
                nodes_by_id[b]["degree"] += 1

    # Deterministic Fruchterman-Reingold force-directed layout
    nodes = list(nodes_by_id.values())
    n = len(nodes)
    pos: dict[str, list[float]] = {}
    if n > 0:
        hubs = [nd for nd in nodes if nd["kind"] in {"hub", "index"}]
        others = [nd for nd in nodes if nd["kind"] not in {"hub", "index"}]
        for idx, nd in enumerate(hubs):
            angle = (2 * math.pi * idx) / max(1, len(hubs))
            r = 0.0 if nd["kind"] == "index" else 180.0
            pos[nd["id"]] = [r * math.cos(angle), r * math.sin(angle)]
        for idx, nd in enumerate(others):
            angle = (2 * math.pi * idx) / max(1, len(others))
            r = 320.0 + (idx % 3) * 55.0
            pos[nd["id"]] = [r * math.cos(angle), r * math.sin(angle)]

        area = 900.0 * 900.0
        k = math.sqrt(area / max(1, n)) * 0.75
        temp = 120.0
        ids = [nd["id"] for nd in nodes]
        for _ in range(45):
            disp = {nid: [0.0, 0.0] for nid in ids}
            for i in range(n):
                u = ids[i]
                ux, uy = pos[u]
                for j in range(i + 1, n):
                    v = ids[j]
                    dx = ux - pos[v][0]
                    dy = uy - pos[v][1]
                    dist = math.hypot(dx, dy) or 0.01
                    if dist < 500.0:
                        force = (k * k) / dist
                        fx = (dx / dist) * force
                        fy = (dy / dist) * force
                        disp[u][0] += fx
                        disp[u][1] += fy
                        disp[v][0] -= fx
                        disp[v][1] -= fy
            for u, v in edges:
                dx = pos[u][0] - pos[v][0]
                dy = pos[u][1] - pos[v][1]
                dist = math.hypot(dx, dy) or 0.01
                force = (dist * dist) / (k * 1.4)
                fx = (dx / dist) * force
                fy = (dy / dist) * force
                disp[u][0] -= fx
                disp[u][1] -= fy
                disp[v][0] += fx
                disp[v][1] += fy
            for nid in ids:
                # Gentle gravity toward center so disconnected nodes stay in view
                disp[nid][0] -= pos[nid][0] * 0.04
                disp[nid][1] -= pos[nid][1] * 0.04
                mag = math.hypot(disp[nid][0], disp[nid][1]) or 0.01
                step = min(mag, temp)
                pos[nid][0] += (disp[nid][0] / mag) * step
                pos[nid][1] += (disp[nid][1] / mag) * step
            temp *= 0.90

        for nd in nodes:
            nd["x"], nd["y"] = pos[nd["id"]]

    projects = sorted({nd["project"] for nd in nodes if nd["project"]})
    return {"dir": str(memory_dir), "nodes": nodes, "edges": edges, "projects": projects}


class _GraphNodeItem(QGraphicsEllipseItem):
    def __init__(self, node: dict, radius: float, color: QColor, on_select):
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.node = node
        self.radius = radius
        self.base_color = color
        self.on_select = on_select
        self.edges: list[tuple[QGraphicsLineItem, str]] = []
        self.setPos(node["x"], node["y"])
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(3)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{node['label']} ({node['kind']})\n{node['desc'] or node['id']}")
        self._apply_style(highlighted=False, dimmed=False)

        self.label_item = QGraphicsSimpleTextItem(node["label"][:28], self)
        font = QFont("Inter", 8 if node["kind"] not in {"hub", "index"} else 9)
        if node["kind"] in {"hub", "index"}:
            font.setBold(True)
        self.label_item.setFont(font)
        self.label_item.setBrush(QBrush(QColor("#cbd5e1")))
        br = self.label_item.boundingRect()
        self.label_item.setPos(-br.width() / 2, radius + 3)

    def _apply_style(self, *, highlighted: bool, dimmed: bool) -> None:
        c = QColor(self.base_color)
        if dimmed:
            c.setAlpha(55)
            self.setBrush(QBrush(c))
            self.setPen(QPen(QColor(100, 116, 139, 50), 1.0))
            if hasattr(self, "label_item"):
                self.label_item.setBrush(QBrush(QColor(148, 163, 184, 70)))
            return
        grad = QRadialGradient(0, 0, self.radius * 1.2)
        grad.setColorAt(0.0, c.lighter(135))
        grad.setColorAt(0.75, c)
        grad.setColorAt(1.0, c.darker(140))
        self.setBrush(QBrush(grad))
        if highlighted:
            self.setPen(QPen(QColor("#ffffff"), 2.2))
            if hasattr(self, "label_item"):
                self.label_item.setBrush(QBrush(QColor("#f8fafc")))
        else:
            self.setPen(QPen(c.lighter(150), 1.1))
            if hasattr(self, "label_item"):
                self.label_item.setBrush(QBrush(QColor("#cbd5e1")))

    def mousePressEvent(self, event) -> None:
        self.on_select(self.node["id"])
        super().mousePressEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for line, end_role in self.edges:
                ln = line.line()
                p = self.pos()
                if end_role == "src":
                    line.setLine(p.x(), p.y(), ln.x2(), ln.y2())
                else:
                    line.setLine(ln.x1(), ln.y1(), p.x(), p.y())
        return super().itemChange(change, value)


class ObsidianGraphView(QGraphicsView):
    """Zoomable, pannable dark-mode knowledge graph canvas."""

    node_selected = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setStyleSheet("background: #090d14; border: 1px solid #1e293b; border-radius: 8px;")
        self._node_items: dict[str, _GraphNodeItem] = {}
        self._edge_items: list[tuple[QGraphicsLineItem, str, str]] = []
        self._graph: dict = {"nodes": [], "edges": []}

    def set_graph(self, graph: dict, *, project_filter: str = "", query: str = "") -> None:
        self._scene.clear()
        self._node_items.clear()
        self._edge_items.clear()
        self._graph = graph

        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if project_filter:
            keep = {
                nd["id"] for nd in nodes
                if nd["project"] == project_filter or nd["id"] == f"hub-{project_filter}"
            }
            # Include direct neighbors of kept nodes
            extra = set(keep)
            for a, b in edges:
                if a in keep:
                    extra.add(b)
                elif b in keep:
                    extra.add(a)
            nodes = [nd for nd in nodes if nd["id"] in extra]
            edges = [(a, b) for a, b in edges if a in extra and b in extra]

        node_map = {nd["id"]: nd for nd in nodes}
        edge_pen = QPen(QColor(56, 97, 140, 95), 1.1)
        for a, b in edges:
            na, nb = node_map.get(a), node_map.get(b)
            if not na or not nb:
                continue
            line = self._scene.addLine(na["x"], na["y"], nb["x"], nb["y"], edge_pen)
            line.setZValue(1)
            self._edge_items.append((line, a, b))

        q = query.strip().casefold()
        for nd in nodes:
            radius = 12.0 if nd["kind"] == "index" else (10.5 if nd["kind"] == "hub" else min(9.5, 5.5 + nd["degree"] * 0.6))
            color = NODE_COLORS.get(nd["kind"], NODE_COLORS["other"])
            item = _GraphNodeItem(nd, radius, color, self._on_node_clicked)
            self._scene.addItem(item)
            self._node_items[nd["id"]] = item
            if q:
                match = q in nd["label"].casefold() or q in nd["id"].casefold() or q in nd["desc"].casefold()
                item._apply_style(highlighted=match, dimmed=not match)

        for line, a, b in self._edge_items:
            if a in self._node_items:
                self._node_items[a].edges.append((line, "src"))
            if b in self._node_items:
                self._node_items[b].edges.append((line, "dst"))

        self.fit_all()

    def _on_node_clicked(self, node_id: str) -> None:
        neighbors = {node_id}
        for line, a, b in self._edge_items:
            if a == node_id or b == node_id:
                neighbors.add(a)
                neighbors.add(b)
                line.setPen(QPen(QColor("#00d4ff"), 1.8))
                line.setZValue(2)
            else:
                line.setPen(QPen(QColor(56, 97, 140, 35), 0.8))
                line.setZValue(1)
        for nid, item in self._node_items.items():
            item._apply_style(highlighted=(nid == node_id), dimmed=(nid not in neighbors))
        item = self._node_items.get(node_id)
        if item is not None:
            self.node_selected.emit(item.node)

    def fit_all(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if not rect.isNull():
            rect.adjust(-40, -40, 40, 40)
            self.setSceneRect(rect)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class ResidentPanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.tabs = QTabWidget()

        # --- Tab 1: Obsidian-style isymem Visual Graph ---
        graph_page = QWidget()
        g_layout = QVBoxLayout(graph_page)
        g_layout.setContentsMargins(6, 6, 6, 6)
        g_layout.setSpacing(8)

        g_top = QHBoxLayout()
        self.graph_summary = QLabel("Memoria compartida isymem · Grafo interactivo")
        self.graph_summary.setStyleSheet("color: #9aa3b2; font-size: 12px; font-weight: 600;")
        g_top.addWidget(self.graph_summary, 1)

        self.graph_search = QLineEdit()
        self.graph_search.setPlaceholderText("Filtrar nodos isymem…")
        self.graph_search.setMaximumWidth(210)
        self.graph_search.textChanged.connect(self._apply_graph_filter)
        g_top.addWidget(self.graph_search)

        self.graph_project = QComboBox()
        self.graph_project.addItem("Todos los proyectos", "")
        self.graph_project.currentIndexChanged.connect(self._apply_graph_filter)
        g_top.addWidget(self.graph_project)

        fit_btn = QPushButton("Encajar")
        fit_btn.clicked.connect(lambda: self.graph_view.fit_all())
        g_top.addWidget(fit_btn)

        reload_btn = QPushButton("Actualizar grafo")
        reload_btn.setProperty("variant", "primary")
        reload_btn.clicked.connect(self.refresh_isymem)
        g_top.addWidget(reload_btn)
        g_layout.addLayout(g_top)

        g_split = QSplitter(Qt.Orientation.Horizontal)
        self.graph_view = ObsidianGraphView()
        self.graph_view.node_selected.connect(self._show_memory_node)
        g_split.addWidget(self.graph_view)

        inspector = QWidget()
        ins_layout = QVBoxLayout(inspector)
        ins_layout.setContentsMargins(6, 0, 0, 0)
        ins_layout.setSpacing(6)
        self.node_title = QLabel("Selecciona un nodo del grafo")
        self.node_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #e2e8f0;")
        self.node_title.setWordWrap(True)
        ins_layout.addWidget(self.node_title)
        self.node_meta = QLabel("Cian = hubs · Verde = proyectos · Ámbar = reglas/feedback · Violeta = referencias")
        self.node_meta.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self.node_meta.setWordWrap(True)
        ins_layout.addWidget(self.node_meta)
        self.node_content = QPlainTextEdit()
        self.node_content.setReadOnly(True)
        self.node_content.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self.node_content.setPlaceholderText("Haz clic en cualquier nodo para inspeccionar su memoria isymem y resaltar sus conexiones [[wikilinks]].")
        ins_layout.addWidget(self.node_content, stretch=1)
        g_split.addWidget(inspector)
        g_split.setSizes([720, 380])
        g_layout.addWidget(g_split, stretch=1)
        self.tabs.addTab(graph_page, "🧠 Grafo isymem")

        # --- Tab 2: Structural Project Resident (existing API preserved) ---
        struct_page = QWidget()
        s_layout = QVBoxLayout(struct_page)
        s_layout.setContentsMargins(6, 6, 6, 6)
        s_layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.scan_button = QPushButton("Self-scan (deterministic)")
        self.scan_button.setToolTip("Ejecuta un auto-escaneo determinista del workspace para mapear componentes")
        self.scan_button.clicked.connect(self.run_scan)
        row.addWidget(self.scan_button)
        self.status_button = QPushButton("Status")
        self.status_button.setToolTip("Muestra el estado del servicio residente")
        self.status_button.clicked.connect(self.show_status)
        row.addWidget(self.status_button)
        row.addStretch(1)

        self.help_button = QPushButton("?")
        self.help_button.setObjectName("helpButton")
        self.help_button.setToolTip(
            "Memoria local: combina el grafo visual de isymem (docs/agent/memory/) con el "
            "residente estructural determinista del proyecto."
        )
        row.addWidget(self.help_button)
        s_layout.addLayout(row)

        query_row = QHBoxLayout()
        query_row.addWidget(QLabel("Query:"))
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("intent (e.g. modify core/runtime/base.py)")
        self.query_input.returnPressed.connect(self.run_query)
        query_row.addWidget(self.query_input, stretch=1)
        self.query_button = QPushButton("Query")
        self.query_button.clicked.connect(self.run_query)
        query_row.addWidget(self.query_button)
        s_layout.addLayout(query_row)

        split = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Sessions"))
        self.sessions = QListWidget()
        self.sessions.itemClicked.connect(self.show_session)
        left_layout.addWidget(self.sessions, stretch=1)
        left_layout.addWidget(QLabel("Plans"))
        self.plans = QListWidget()
        self.plans.itemClicked.connect(self.show_plan)
        left_layout.addWidget(self.plans, stretch=1)
        split.addWidget(left)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        split.addWidget(self.view)
        split.setSizes([320, 800])
        s_layout.addWidget(split, stretch=1)
        self.tabs.addTab(struct_page, "🔍 Residente del proyecto")

        layout.addWidget(self.tabs, stretch=1)
        self._isymem_graph: dict = {"nodes": [], "edges": [], "projects": []}
        self._refresh_lists()
        self.refresh_isymem()

    def refresh_isymem(self) -> None:
        mem_dir = find_isymem_dir(self.controller.working_dir)
        self._isymem_graph = load_isymem_graph(mem_dir)
        prev = self.graph_project.currentData() or ""
        self.graph_project.blockSignals(True)
        self.graph_project.clear()
        self.graph_project.addItem("Todos los proyectos", "")
        for proj in self._isymem_graph.get("projects", []):
            self.graph_project.addItem(proj, proj)
        idx = self.graph_project.findData(prev)
        if idx >= 0:
            self.graph_project.setCurrentIndex(idx)
        self.graph_project.blockSignals(False)
        n_nodes = len(self._isymem_graph.get("nodes", []))
        n_edges = len(self._isymem_graph.get("edges", []))
        if mem_dir:
            self.graph_summary.setText(f"isymem · {n_nodes} memorias · {n_edges} conexiones ({mem_dir})")
        else:
            self.graph_summary.setText("isymem no encontrado (esperado en docs/agent/memory/)")
        self._apply_graph_filter()

    def _apply_graph_filter(self) -> None:
        proj = self.graph_project.currentData() or ""
        query = self.graph_search.text()
        self.graph_view.set_graph(self._isymem_graph, project_filter=proj, query=query)

    def _show_memory_node(self, node: dict) -> None:
        self.node_title.setText(node["label"])
        meta = [f"tipo: {node['kind']}", f"conexiones: {node['degree']}"]
        if node.get("project"):
            meta.append(f"proyecto: {node['project']}")
        self.node_meta.setText(" · ".join(meta) + f"\n{node['path']}")
        self.node_content.setPlainText(node.get("content", ""))

    def _refresh_lists(self) -> None:
        self.sessions.clear()
        for session in self.controller.sessions():
            self.sessions.addItem(session["id"])
        self.plans.clear()
        for plan_id in self.controller.plans():
            self.plans.addItem(plan_id)

    def show_status(self) -> None:
        self.view.setPlainText(json.dumps(
            self.controller.resident_status(), indent=2, ensure_ascii=False))

    def run_scan(self) -> None:
        result = self.controller.resident_scan()
        self.view.setPlainText(json.dumps(result, indent=2, ensure_ascii=False))
        self._refresh_lists()

    def run_query(self) -> None:
        intent = self.query_input.text().strip()
        if not intent:
            return
        result = self.controller.resident_query(intent, category="general")
        self.view.setPlainText(json.dumps(result, indent=2, ensure_ascii=False))

    def show_session(self, item) -> None:
        events = self.controller.session_events(item.text())
        self.view.setPlainText(json.dumps(events, indent=2, ensure_ascii=False))

    def show_plan(self, item) -> None:
        records = self.controller.plan_records(item.text())
        self.view.setPlainText(json.dumps(records, indent=2, ensure_ascii=False))
