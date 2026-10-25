"""File, skill, and LSP rail methods for the ISyCode TUI.

Moved verbatim from tui.py. TUIApp inherits RailMixin.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from isycode.tui import TUIApp

from isycode.localization import tr
from isycode.tui_dialog import Dialog, DialogAction

import os
import asyncio
import json
from pathlib import Path
from isycode.decision_view import verified_receipt_line
from isycode.contracts import CatalogSnapshot
from textual.css.query import NoMatches
from textual.dom import NoScreen
from textual.containers import Vertical
from textual.widgets import (
    Static,
    Input,
    Button,
    Tree,
)
from rich.text import Text
from isycode.lsp import (
    discover_servers,
    language_server_catalog,
)
from isycode.workspace import WorkspaceUnavailable
from isycode.action_audit import ActionAuditJournal
from isycode.workspace_authority import WorkspaceAuthority, WorkspaceAuthorityError
from isycode.tui_theme import (
    _fit_cells,
    status_chip,
    TEXT,
    MUTED,
    CYAN,
    YELLOW,
    status_phrase,
    switch_row,
    switch_rows,
)
from isycode.tui_widgets import (
    RailHeader,
    workspace_mode_chip,
    workspace_mode_name,
    Collapsible,
    SidePanel,
)
from isycode.bridge_presence import BridgePresenceOwner
from isycode.search import find_text_matches
from isycode.startup_art import MAX_SCENE_ROWS, render_landscape
from isycode.tui_composer import PromptArea
from isycode.tui_screens_sessions import BridgePresenceScreen, ConsoleSearchScreen
from isycode.tui_theme import ACCENT, static_content
from isycode.tui_widgets import ChatArea, CommandOutputCard
from isycode.workspace_authority import OneShotActionAuthority
from rich.console import Console
from textual.widgets import Collapsible as TextualCollapsible


class IdentityDialog(Dialog):
    """The full workspace identity, one key press away from the one-line rail."""

    dialog_title = "Workspace identity"
    dialog_width = "normal"
    dialog_default_action = "identity-close"

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        super().__init__()

    def dialog_note(self) -> str:
        return "\n".join(self.lines)

    def dialog_actions(self):
        return (DialogAction("identity-close", tr("Close"), "primary", focused=True),)

    def dismiss_action(self, action_id: str) -> None:
        self.dismiss(None)


class RailMixin:
    """Sidebar files, skills, and the LSP rail."""

    def _apply_rail_width(self, terminal_width: int) -> None:
        """Keep the rail inside the configured range and available columns."""
        if terminal_width < 100 and getattr(self, "_dedicated_space", False) and getattr(self, "_rail_visible", False):
            try:
                self.query_one("#main").display = False
                self.query_one(SidePanel).styles.width = "100%"
                return
            except Exception:
                pass
        try:
            self.query_one("#main").display = True
        except Exception:
            pass
        available = max(22, terminal_width - 52)
        preferred = self._rail_width if terminal_width >= 100 else self._rail_compact_width
        requested = min(preferred, available)
        self.query_one(SidePanel).styles.width = requested

    def action_widen_sidebar(self) -> None:
        if self.size.width >= 100:
            self._rail_width = min(38, self._rail_width + 2)
            width = self._rail_width
        else:
            self._rail_compact_width = min(34, self._rail_compact_width + 2)
            width = self._rail_compact_width
        self._apply_rail_width(self.size.width)
        self._set_activity(tr("Sidebar width · {width} columns", width=width), MUTED)
        self.call_after_refresh(self._paint_workspace_chrome)

    def action_narrow_sidebar(self) -> None:
        if self.size.width >= 100:
            self._rail_width = max(32, self._rail_width - 2)
            width = self._rail_width
        else:
            self._rail_compact_width = max(22, self._rail_compact_width - 2)
            width = self._rail_compact_width
        self._apply_rail_width(self.size.width)
        self._set_activity(tr("Sidebar width · {width} columns", width=width), MUTED)
        self.call_after_refresh(self._paint_workspace_chrome)

    async def _refresh_openisy(self) -> None:
        self._openisy_refresh_generation += 1
        generation = self._openisy_refresh_generation
        self.query_one("#mcp-status", Static).update(
            switch_row(None, tr("Checking"), status_chip("connected tool services")))
        self._set_rail_title("rail-mcp", status_chip("MCPs · {state}", state=tr("checking")), chip=True)
        self._populate_skill_tree(
            CatalogSnapshot(True, [], "loading", "Fetching the ISyCode skill catalog."))
        refresh = self.query_one("#refresh-openisy", Button)
        refresh.disabled = True
        try:
            catalog_url = os.environ.get("OPENISY_API_URL", "").strip()
            if catalog_url:
                allowed, reason = self._authorize_remote_read("catalog.external.read", catalog_url)
                if not allowed:
                    denied = CatalogSnapshot(True, [], "denied", reason)
                    self.query_one("#mcp-status", Static).update(switch_row(
                        False, tr("External catalog denied"),
                        "grant its host in Settings · Authority & Security"))
                    self._set_rail_title("rail-mcp", status_chip("MCPs · {state}", state=tr("denied")), chip=True)
                    self._populate_skill_tree(denied)
                    self._provider_auth_snapshot = denied
                    self._openisy_provider_snapshot = denied
                    return
            client = self._openisy_client_factory(self._workspace_root)
            mcp, skills, auth, provider_catalog = await asyncio.gather(
                asyncio.to_thread(client.mcp_status),
                asyncio.to_thread(client.skills),
                asyncio.to_thread(client.provider_auth),
                asyncio.to_thread(client.provider_catalog),
                return_exceptions=False,
            )
        except (ValueError, OSError) as exc:
            if generation != self._openisy_refresh_generation:
                return
            message = f"Integration configuration error: {exc}"
            self.query_one("#mcp-status", Static).update(switch_row(False, tr("Configuration error"), message))
            self._set_rail_title("rail-mcp", status_chip("MCPs · {state}", state=tr("error")), chip=True)
            self._populate_skill_tree(CatalogSnapshot(True, [], "error", message))
            self._provider_auth_snapshot = CatalogSnapshot(True, [], "error", message)
            self._openisy_provider_snapshot = CatalogSnapshot(True, [], "error", message)
        except Exception as exc:
            if generation != self._openisy_refresh_generation:
                return
            message = f"Integration refresh failed ({type(exc).__name__})."
            self.query_one("#mcp-status", Static).update(switch_row(False, tr("Refresh failed"), message))
            self._set_rail_title("rail-mcp", status_chip("MCPs · {state}", state=tr("error")), chip=True)
            self._populate_skill_tree(CatalogSnapshot(True, [], "error", message))
            self._provider_auth_snapshot = CatalogSnapshot(True, [], "error", message)
            self._openisy_provider_snapshot = CatalogSnapshot(True, [], "error", message)
        else:
            if generation != self._openisy_refresh_generation:
                return
            mcp_body, mcp_title = self._format_mcp_snapshot(mcp)
            self.query_one("#mcp-status", Static).update(mcp_body)
            self._set_rail_title("rail-mcp", mcp_title, chip=True)
            self._mcp_snapshot = mcp
            self._skill_snapshot = skills
            self._provider_auth_snapshot = auth
            self._openisy_provider_snapshot = provider_catalog
            self._populate_skill_tree(skills)
        finally:
            if generation == self._openisy_refresh_generation:
                refresh.disabled = False
                self._paint_idle()

    @staticmethod
    def _status_note(note: str) -> str:
        """Title-case a short chip. Sentences and server ids stay as written."""
        text = str(note)
        if not text or "." in text or len(text) > 48:
            return text
        return status_phrase(text)

    @staticmethod
    def _format_mcp_snapshot(snapshot: CatalogSnapshot) -> tuple[Text, str]:
        """Switch rows for the MCP section, plus its folded title."""
        if snapshot.state == "loading":
            return (switch_row(None, tr("Checking"), snapshot.detail),
                    status_chip("MCPs · {state}", state=tr("checking")))
        if snapshot.state != "ready":
            state = snapshot.state.replace("_", " ")
            inactive = snapshot.state in {"not_configured", "not_checked"}
            shown = tr("off") if inactive else tr(state)
            return (
                switch_row(False, status_phrase(state), snapshot.detail, inactive=inactive),
                status_chip("MCPs · {state}", state=shown),
            )
        if not snapshot.items:
            return (
                switch_row(False, tr("No MCP Servers"), status_chip("none configured"), inactive=True),
                status_chip("MCPs · none"),
            )
        rows, on = [], 0
        for item in snapshot.items:
            healthy = (str(item.get("status", "")).lower() in {"connected", "ready", "running", "ok", "active"}
                       and not item.get("has_error"))
            on += healthy
            note = ("service reports an error" if item.get("has_error") else str(item.get("status", "")))
            rows.append(switch_row(
                healthy, str(item["name"]), "" if healthy else RailMixin._status_note(note)))
        return switch_rows(rows), status_chip("MCPs · {on}/{total} on", on=on, total=len(snapshot.items))

    @staticmethod
    def _format_skill_snapshot(snapshot: CatalogSnapshot) -> tuple[Text, str]:
        if snapshot.state == "loading":
            return (switch_row(None, tr("Checking"), snapshot.detail),
                    status_chip("Skills · {state}", state=tr("checking")))
        if snapshot.state != "ready":
            state = snapshot.state.replace("_", " ")
            inactive = snapshot.state in {"not_configured", "not_checked"}
            shown = tr("off") if inactive else tr(state)
            return (
                switch_row(False, status_phrase(state), snapshot.detail, inactive=inactive),
                status_chip("Skills · {state}", state=shown),
            )
        if not snapshot.items:
            return (
                switch_row(False, tr("No Skills"), status_chip("none available for this project"), inactive=True),
                status_chip("Skills · none"),
            )
        count = len(snapshot.items)
        return (
            switch_row(False, status_chip("{count} available", count=count), status_chip("select one below for details"), inactive=True),
            status_chip("Skills · {count} available", count=count),
        )

    @staticmethod
    def _origin_tag(origin: object) -> str:
        """Title-case a short origin word. Paths and skill names stay untouched."""
        text = str(origin or "")
        if not text or any(mark in text for mark in "/\\ ."):
            return text
        if len(text) > 24 or any(character.isdigit() for character in text):
            return text
        return status_phrase(text)

    def _set_rail_title(self, section: str, title: str, *, chip: bool = False) -> None:
        """Folded section title. Translated chips keep their own casing."""
        try:
            label = title if chip else status_phrase(title)
            self.query_one(f"#{section}", Collapsible).title = label
        except (NoMatches, NoScreen):
            pass

    def _refresh_lsp_status(self) -> None:
        try:
            self._lsp_inventory = discover_servers()
        except (OSError, RuntimeError, ValueError):
            self._lsp_inventory = []
        if not self.is_mounted:
            return
        try:
            catalog = language_server_catalog(self._lsp_inventory)
        except (OSError, RuntimeError, ValueError):
            catalog = []
        if not catalog:
            body = switch_row(False, tr("No Language Servers"), status_chip("none detected"), inactive=True)
            title = status_chip("LSPs · none")
        else:
            rows = []
            ready = missing = 0
            for server in catalog:
                state = server.get("state")
                label = str(server.get("label") or server.get("id") or "language server")
                if state == "sandbox_ready":
                    ready += 1
                    rows.append(switch_row(True, label, status_chip("workspace symbols")))
                elif state == "not_installed":
                    missing += 1
                    rows.append(switch_row(False, label, status_chip("not on PATH"), inactive=True))
                elif state == "installed_unsupported":
                    rows.append(switch_row(False, label, status_chip("installed · sandbox does not run it")))
                else:
                    rows.append(switch_row(False, label, status_chip("installed · sandbox unavailable")))
            title = status_chip("LSPs · {ready} ready", ready=ready)
            if missing:
                title = status_chip("LSPs · {ready} ready · {missing} missing", ready=ready, missing=missing)
            body = switch_rows(rows)
        self._lsp_status_title = title
        self.query_one("#lsp-status", Static).update(body)
        self._set_rail_title("rail-lsp", title, chip=True)
        self._paint_idle()

    # ── IsySentinel ────────────────────────────────────────────────────
    def _on_journal_decision(self, record: dict) -> None:
        """Journal observer: may run on a worker thread; paints on the UI thread."""
        def apply() -> None:
            self._sentinel_feed.add(record)
            self._paint_sentinel()
        try:
            self.call_from_thread(apply)
        except RuntimeError:          # already on the app's thread (or not running)
            apply()

    def _paint_sentinel(self) -> None:
        if not self.is_mounted or not self.screen_stack:
            return
        from isycode.sentinel_rail import render
        from isycode.workspace_trust import WorkspaceTrust
        try:
            authority = WorkspaceAuthority(self._workspace_root)
            policy = authority.effective_policy()
            trusted = policy.get("mode") == "classic" and WorkspaceTrust().trusted(authority)
        except (WorkspaceAuthorityError, OSError, ValueError):
            policy, trusted = None, False
        body, title = render(self._sentinel_feed, policy, trusted=trusted)
        try:
            self.screen_stack[0].query_one("#sentinel-status", Static).update(body)
        except NoMatches:
            return
        self._set_rail_title(
            "rail-sentinel",
            status_chip("IsySentinel · {allowed} allow · {denied} deny",
                         allowed=self._sentinel_feed.allowed,
                         denied=self._sentinel_feed.denied),
            chip=True)

    async def _load_sentinel_journal(self) -> None:
        """Verify the hash chain once and show its latest decisions (not counted)."""
        def read():
            journal = ActionAuditJournal.for_read_only_inspection(self._workspace_root)
            return journal.verify(recent_limit=40)
        try:
            report = await asyncio.to_thread(read)
        except Exception as exc:  # noqa: BLE001 - a background journal read must never kill the app
            self._sentinel_feed.journal = f"unreadable · {type(exc).__name__}"
        else:
            if report.status == "NOT_VERIFIABLE":
                self._sentinel_feed.journal = "empty"
            else:
                self._sentinel_feed.journal = f"{report.status} · {report.records} records"
            seen = list(self._sentinel_feed.recent)
            self._sentinel_feed.recent.clear()
            for record in report.recent:
                self._sentinel_feed.add(record, count=False)
            for entry in seen:                 # decisions that arrived while verifying
                self._sentinel_feed.recent.append(entry)
        self._paint_sentinel()

    def _show_lsp_install_hints(self) -> None:
        """Show the exact install command. Nothing is downloaded or started."""
        try:
            self.query_one("#rail-lsp", Collapsible).collapsed = False
            target = self.query_one("#lsp-install-note", Static)
        except NoMatches:
            return
        catalog = language_server_catalog(getattr(self, "_lsp_inventory", []))
        note = Text(no_wrap=False, overflow="fold")
        note.append("ISyCode does not download language servers. Nothing was installed.\n", style=MUTED)
        missing = [row for row in catalog if row.get("state") == "not_installed"]
        blocked = [row for row in catalog
                   if row.get("presence") == "installed" and row.get("state") != "sandbox_ready"]
        if not missing:
            note.append("Nothing is missing from PATH.\n", style=TEXT)
        else:
            note.append("Not on PATH. Run the command yourself, then Refresh integrations:\n", style=TEXT)
            for row in missing:
                note.append(str(row["label"]) + "\n", style=f"bold {TEXT}")
                note.append("  " + str(row["install_hint"]) + "\n", style=YELLOW)
        if blocked:
            note.append("Already on PATH. Installing again will not make these ready:\n", style=MUTED)
            for row in blocked:
                reason = ("the sandbox does not run it" if row.get("state") == "installed_unsupported"
                          else "the sandbox cannot launch it")
                note.append(f"  {row['label']}: {reason}\n", style=MUTED)
        target.display = True
        target.update(note)
        self._set_activity(tr("Language servers were not installed · commands are under LSPs"), YELLOW)

    def _populate_skill_tree(self, snapshot: CatalogSnapshot) -> None:
        from isycode.skill_catalog import skills
        try:
            bundled = [{"name": name, "origin": "bundled", "description": "Pinned Superpowers MIT workflow guidance; select to toggle for this chat. No tools or authority are added."}
                       for name in skills()]
        except (OSError, ValueError):
            bundled = []
        if bundled:
            external = snapshot.items if snapshot.state == "ready" else []
            snapshot = CatalogSnapshot(True, bundled + external, "ready", snapshot.detail)
        tree = self.query_one("#skills-tree", Tree)
        tree.root.remove_children()
        skill_body, skill_title = self._format_skill_snapshot(snapshot)
        self.query_one("#skill-status", Static).update(skill_body)
        self._set_rail_title("rail-skills", skill_title, chip=True)
        has_skills = snapshot.state == "ready" and bool(snapshot.items)
        tree.display = has_skills
        detail = self.query_one("#skill-detail", Static)
        detail.display = False
        detail.update("")
        if snapshot.state != "ready":
            tree.root.set_label(
                "Loading skills…" if snapshot.state == "loading"
                else status_chip("Skills · {value}", value=snapshot.state.replace('_', ' ')))
            return
        if not snapshot.items:
            tree.root.set_label(status_chip("No skills available"))
            return
        tree.root.set_label(status_chip("Available skills ({value})", value=len(snapshot.items)))
        for item in snapshot.items:
            tree.root.add_leaf(
                Text(f"{item['name']} · {self._origin_tag(item.get('origin', ''))}"), data=dict(item))
        tree.root.expand()

    def _show_file_preview(self, text: str) -> bool:
        """Paint the file preview. Return False when that widget is no longer on screen."""
        try:
            self.query_one("#file-preview", Static).update(text)
        except (NoMatches, NoScreen):
            return False
        return True

    async def _load_directory(self, logical_path: str) -> None:
        if self._workspace is None:
            return
        self._selected_file_path = None
        self.query_one("#file-preview-meta", Static).update("")
        self.query_one("#file-copy-path", Button).disabled = True
        self.query_one("#file-open-preview", Button).disabled = True
        self._workspace_generation += 1
        generation = self._workspace_generation
        tree = self.query_one("#workspace-tree", Tree)
        tree.root.remove_children()
        try:
            browser_root = self._workspace_read_owner().root
            relative_dir = Path(logical_path).relative_to(browser_root).as_posix()
        except (OSError, ValueError) as exc:
            self.query_one("#file-preview", Static).update(tr("Folder unavailable: {exc}", exc=exc))
            return
        if relative_dir == ".":
            relative_dir = ""
        current_label = self._file_browser_alias + " · " + browser_root.name + (f"/{relative_dir}" if relative_dir else "")
        tree.root.set_label(f"📁 {current_label}/")
        tree.root.data = {"path": logical_path, "kind": "directory"}
        self._file_path = logical_path
        self.query_one("#file-preview", Static).update(tr("Checking Workspace Authority and IsySentinel…"))
        try:
            outcome = await asyncio.to_thread(
                self._workspace_read_owner().execute, "workspace.files.list", {"path": logical_path})
            if outcome.decision != "ALLOW" or outcome.receipt is None or not outcome.receipt.verify(
                    self._workspace_request("workspace.files.list", logical_path), outcome.text):
                raise WorkspaceUnavailable(
                    "This folder cannot be enumerated. Grant workspace read access in Settings · Authority & Security.")
            payload = json.loads(outcome.text)
            entries = payload.get("entries", [])
        except (WorkspaceUnavailable, json.JSONDecodeError, OSError, ValueError) as exc:
            if generation == self._workspace_generation:
                message = (str(exc) if isinstance(exc, WorkspaceUnavailable) else
                           f"Workspace read failed closed ({type(exc).__name__}).")
                if not self._show_file_preview(message):
                    return
            tree.root.expand()
            return
        if generation != self._workspace_generation:
            return
        entries = sorted(entries if isinstance(entries, list) else [],
                         key=lambda item: (item.get("kind") != "directory", item.get("name", "").casefold())
                         if isinstance(item, dict) else (True, ""))
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", "")
            if not name:
                continue
            child_path = str(Path(logical_path) / name)
            from isycode.operation_style import operation_icon
            from isycode.tui_theme import ascii_only
            label = (f"{name}/" if entry.get("kind") == "directory"
                     else operation_icon("workspace_read", ascii_only=ascii_only()) + f" {name}")
            tree.root.add(label, allow_expand=entry.get("kind") == "directory", data={"path": child_path, "kind": entry.get("kind"),
                                       "bytes": entry.get("bytes", 0)})
        self._search_mode = False
        limit_note = " · listing capped" if payload.get("truncated") else ""
        status = verified_receipt_line(outcome.receipt.receipt_id)
        if not self._show_file_preview(
                f"{len(tree.root.children)} entries{limit_note} · {browser_root}\n"
                f"{status}"):
            return
        tree.root.expand()

    async def _search_workspace(self, query: str) -> None:
        query = query.strip()[:200]
        if self._workspace is None or not query:
            return
        self._workspace_generation += 1
        generation = self._workspace_generation
        self._search_query = query
        self._search_mode = True
        self._selected_file_path = None
        self.query_one("#file-preview-meta", Static).update("")
        self.query_one("#file-copy-path", Button).disabled = True
        self.query_one("#file-open-preview", Button).disabled = True
        tree = self.query_one("#workspace-tree", Tree)
        tree.root.remove_children()
        tree.root.set_label(f"Searching: {query}")
        self.query_one("#file-preview", Static).update(tr("Checking Workspace Authority and IsySentinel…"))
        try:
            browser_root = self._workspace_read_owner().root
            outcome = await asyncio.to_thread(self._workspace_read_owner().execute,
                "workspace.files.search", {"path": str(browser_root), "query": query})
            if outcome.decision != "ALLOW" or outcome.receipt is None:
                raise WorkspaceUnavailable(
                    "Search is unavailable. Grant workspace read access in Settings · Authority & Security.")
            payload = json.loads(outcome.text)
            if not outcome.receipt.verify(self._workspace_request(
                    "workspace.files.search", str(browser_root), query=query), outcome.text):
                raise WorkspaceUnavailable("The local read receipt did not verify; results were blocked.")
        except (WorkspaceUnavailable, json.JSONDecodeError, OSError, ValueError) as exc:
            if generation == self._workspace_generation:
                self.query_one("#file-preview", Static).update(
                    str(exc) if isinstance(exc, WorkspaceUnavailable) else
                    f"Workspace search failed closed ({type(exc).__name__}).")
            return
        if generation != self._workspace_generation:
            return
        tree.root.set_label(f"Results for: {query}")
        tree.root.data = {"path": str(browser_root), "kind": "directory"}
        for hit in payload.get("matches", []):
            if not isinstance(hit, dict) or not isinstance(hit.get("path"), str):
                continue
            relative = hit["path"]
            full_path = browser_root / relative
            kind = hit.get("kind") if hit.get("kind") in {"directory", "file"} else "file"
            icon = "📁" if kind == "directory" else "📄"
            tree.root.add(f"{icon} {relative}", data={"path": str(full_path), "kind": kind})
        limit_note = " · scan limit reached" if payload.get("truncated") else ""
        skipped_note = ""
        self._file_path = str(browser_root)
        self.query_one("#file-preview", Static).update(
            tr("{len} results · {get} directories scanned{skipped_note}{limit_note}", len=len(payload.get('matches', [])), get=payload.get('directories_scanned', 0), skipped_note=skipped_note, limit_note=limit_note))
        tree.root.expand()

    async def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.control.id == "skills-tree":
            skill = event.node.data
            if not isinstance(skill, dict):
                return
            name = skill.get("name", "Unknown skill")
            detail = self.query_one("#skill-detail", Static)
            detail.display = True
            if skill.get("origin") == "bundled":
                self._select_skill(name)
                state = "Active" if name in self._active_skills else "Inactive"
                detail.update(Text(
                    tr("{name} · {state}\nWorkflow guidance only. /skills clear removes selected guidance.", name=name, state=state)))
                return
            origin = self._origin_tag(skill.get("origin", "workspace"))
            description = skill.get("description") or "No description provided by the skill manifest."
            detail.update(Text(
                tr("{name} · {origin}\n{description}\nDiscovery only. This does not activate the skill.", name=name, origin=origin, description=description)))
            return
        data = event.node.data
        if not isinstance(data, dict) or self._workspace is None:
            return
        uri = data.get("path")
        if not isinstance(uri, str):
            return
        if data.get("kind") == "directory":
            self._selected_file_path = None
            self.query_one("#file-copy-path", Button).disabled = True
            self.query_one("#file-open-preview", Button).disabled = True
            self._search_mode = False
            self._search_query = ""
            self.query_one("#file-search", Input).value = ""
            await self._load_directory(uri)
            self._selected_file_path = uri
            self.query_one("#file-copy-path", Button).disabled = False
            return
        self._selected_file_path = uri
        # Copying goes through ClipboardOwner (clipboard.copy grant + IsySentinel).
        try:
            self.query_one("#file-copy-path", Button).disabled = False
            self.query_one("#file-open-preview", Button).disabled = False
        except (NoMatches, NoScreen):
            pass
        if getattr(self, "_sidebar_file_preview", False):
            await self._preview_file(uri, modal=False)

    async def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.control.id != "workspace-tree":
            return
        data = event.node.data
        if not isinstance(data, dict) or self._workspace is None:
            return
        uri = data.get("path")
        if not isinstance(uri, str):
            return
        if data.get("kind") != "directory":
            self._selected_file_path = uri
            try:
                self.query_one("#file-copy-path", Button).disabled = False
                self.query_one("#file-open-preview", Button).disabled = False
            except (NoMatches, NoScreen):
                pass
            if getattr(self, "_sidebar_file_preview", False):
                self.run_worker(self._preview_file(uri, modal=False), group="file-preview")

    def _apply_sidebar_file_preview(self, enabled: bool) -> None:
        try:
            box = self.query_one("#file-preview-box", Vertical)
            box.display = enabled
        except (NoMatches, NoScreen):
            pass

    async def _preview_file(self, uri: str, *, modal: bool = False) -> None:
        if self._workspace is None:
            return
        self._workspace_generation += 1
        generation = self._workspace_generation
        self.query_one("#file-preview-meta", Static).update("")
        self.query_one("#file-preview", Static).update(tr("Checking Workspace Authority and IsySentinel…"))
        try:
            browser_root = self._workspace_read_owner().root
            read = await asyncio.to_thread(self._workspace_read_owner().execute,
                                           "workspace.files.read", {"path": uri})
            if generation != self._workspace_generation:
                return
            if read.decision != "ALLOW" or read.receipt is None:
                raise WorkspaceUnavailable(
                    "File contents are unavailable. Grant workspace read access in Settings · Authority & Security.")
            if not read.receipt.verify(self._workspace_request("workspace.files.read", uri), read.text):
                raise WorkspaceUnavailable("The local read receipt did not verify; contents were blocked.")
            result = json.loads(read.text)
            preview = result.get("text")
            full_preview = preview if isinstance(preview, str) else "Preview unavailable: binary or invalid UTF-8."
            if not isinstance(preview, str):
                preview = "Preview unavailable: file is binary or not valid UTF-8."
            elif len(preview) > 8000:
                preview = preview[:8000] + "\n\n… preview truncated at 8,000 characters …"
            relative = Path(uri).relative_to(browser_root).as_posix() or browser_root.name
            size = len(result.get("text", "").encode("utf-8"))
            self.query_one("#file-preview-meta", Static).update(
                tr("{relative} · {size} bytes · UTF-8\n{verified_receipt_line}", relative=relative, size=size, verified_receipt_line=verified_receipt_line(read.receipt.receipt_id)))
            from rich.syntax import Syntax
            lexer = Syntax.guess_lexer(uri, code=preview)
            highlighted = Syntax(preview, lexer, background_color="default").highlight(preview)
            # Syntax must never normalize whitespace used by exact-range copy.
            self.query_one("#file-preview", Static).set_selectable_content(
                highlighted if highlighted.plain == preview else Text(preview), preview)
            if modal:
                from isycode.file_preview import FilePreviewScreen
                await self._await_screen(FilePreviewScreen(uri, full_preview))
        except (WorkspaceUnavailable, json.JSONDecodeError, OSError, ValueError) as exc:
            if generation == self._workspace_generation:
                self.query_one("#file-preview", Static).update(
                    str(exc) if isinstance(exc, WorkspaceUnavailable) else
                    f"Workspace read failed closed ({type(exc).__name__}).")

    def action_toggle_sidebar(self) -> None:
        self._rail_visible = not self._rail_visible
        self._rail_visibility_override = self._rail_visible
        self._rail_auto_hidden = False
        side_panel = self.query_one(SidePanel)
        side_panel.display = self._rail_visible
        if self.size.width < 100 and getattr(self, "_dedicated_space", False):
            self.query_one("#main").display = not self._rail_visible
            if self._rail_visible:
                side_panel.styles.width = "100%"
        else:
            self.query_one("#main").display = True
            self._apply_rail_width(self.size.width)
        self._update_model_button_visibility()
        self.call_after_refresh(self._paint_workspace_chrome)

    def action_toggle_dedicated_space(self) -> None:
        """Dedicated full-width space view in compact terminals."""
        self._dedicated_space = not getattr(self, "_dedicated_space", False)
        if self._dedicated_space:
            self._rail_visible = True
            self._rail_visibility_override = True
            self._rail_auto_hidden = False
            self.query_one(SidePanel).display = True
            if self.size.width < 100:
                self.query_one("#main").display = False
                self.query_one(SidePanel).styles.width = "100%"
            else:
                self._apply_rail_width(self.size.width)
        else:
            self.query_one("#main").display = True
            self._apply_rail_width(self.size.width)
            self.query_one(SidePanel).display = self._rail_visible

    def action_focus_files(self) -> None:
        self._set_rail_view("files")
        self.query_one("#workspace-tree", Tree).focus()

    def action_focus_overview(self) -> None:
        self._set_rail_view("overview")
        self.query_one("#skills-tree", Tree).focus()

    def _set_rail_view(self, view: str) -> None:
        self._rail_visible = True
        self._rail_visibility_override = True
        self._rail_auto_hidden = False
        side_panel = self.query_one(SidePanel)
        side_panel.display = True
        if self.size.width < 100 and getattr(self, "_dedicated_space", False):
            self.query_one("#main").display = False
            side_panel.styles.width = "100%"
        else:
            self.query_one("#main").display = True
            self._apply_rail_width(self.size.width)
        self.call_after_refresh(self._paint_workspace_chrome)
        self.call_after_refresh(self._update_model_button_visibility)
        show_files = view == "files"
        self._rail_view = "files" if show_files else "overview"
        self.query_one("#overview-view").display = not show_files
        self.query_one("#files-view").display = show_files
        overview = self.query_one("#show-overview", Button)
        files = self.query_one("#show-files", Button)
        overview.set_class(not show_files, "rail-lit")
        files.set_class(show_files, "rail-lit")

    def _menu_branch(self, entry: dict[str, str | bool]) -> None:
        value = entry["value"]
        self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("branch:" + value.casefold(), value, self._branch_entries(value))
        return

    def _menu_files(self, entry: dict[str, str | bool]) -> None:
        self._set_rail_view("files")
        self.query_one("#workspace-tree", Tree).focus()
        self._close_menu()
        return

    def _menu_overview(self, entry: dict[str, str | bool]) -> None:
        self._set_rail_view("overview")
        self.query_one("#skills-tree", Tree).focus()
        self._close_menu()
        return

    def _menu_refresh(self, entry: dict[str, str | bool]) -> None:
        self._close_menu()
        self.run_worker(self._refresh_openisy(), exclusive=False)
        self.run_worker(self._check_gateway_mcp_async(), exclusive=False, group="gateway-mcp")
        return

    def _idle_status_rows(self) -> int:
        """Model line, the blank under it, the integration summary, and board padding."""
        return 4

    def _idle_integration_summary(self) -> Text:
        """One line of integration state; the right rail keeps the detail.

        The idle board used to repeat every LSP, MCP and Skill name that the
        rail already lists. Counts plus a pointer keep one detail surface.
        """
        lsp = getattr(self, "_lsp_status_title", "") or status_chip("LSPs · none")
        mcp = self._format_mcp_snapshot(self._mcp_snapshot)[1]
        skills = self._format_skill_snapshot(self._skill_snapshot)[1]
        line = Text()
        line.append(f"{lsp} · {mcp} · {skills}", style=MUTED)
        line.append("  " + tr("details in the right rail"), style=MUTED)
        return line

    def _landscape_row_budget(self) -> int:
        """Panorama rows that still leave the model line and status columns visible."""
        chat_h = self.query_one(ChatArea).content_size.height
        if chat_h <= 0:
            return 16
        return max(1, min(MAX_SCENE_ROWS, chat_h - self._idle_status_rows()))

    def _idle_board_text(self, measured_width: int | None = None, max_rows: int | None = None) -> Text:
        """Cell-accurate landscape, model, and integration summary."""
        width = measured_width or self._idle_content_width()
        height = getattr(self, "size", None) and self.size.height or 40
        if height <= 28:
            body = Text()
            checking = not self._model_line
            model = self._model_line or tr("Checking the configured model")
            mode = self._workspace_mode() if callable(getattr(self, "_workspace_mode", None)) else getattr(self, "_workspace_mode", "Classic")
            body.append(f"ISYCODE · {model} · {mode}\n", style=MUTED if checking else TEXT)
            body.append(tr("Connections and tools (LSPs, MCPs, Skills) in the rail"), style=MUTED)
            return body
        body = Text()
        body.append(render_landscape(width, max_rows))
        body.append("\n")
        checking = not self._model_line
        model = self._model_line or tr("Checking the configured model")
        body.append("◇ ", style=MUTED if checking else ACCENT)
        body.append(_fit_cells(model, max(8, width - 2)) + "\n\n", style=self._model_line_style)
        body.append(self._idle_integration_summary())
        return body

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

    def _refresh_activity(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            self._animate_activity()
        else:
            self._set_activity(getattr(self, "_activity_message", tr("Chat ready")),
                               getattr(self, "_activity_color", MUTED))

    def _rail_identity_line(self) -> str:
        """One line: the three facts that change how a turn is interpreted."""
        root = self._workspace_root
        name = root.name or str(root)
        mode = {"classic": "Classic", "flow": "Flow"}.get(self._workspace_mode(), "Security")
        bridge = getattr(self, "_bridge_identity", "") or tr("no bridge")
        return f"{name} · {mode} · {bridge}"

    def _paint_workspace_chrome(self) -> None:
        """Wordmark and launch folder in the rail; the workspace mode by Settings."""
        try:
            header = self.query_one(RailHeader)
            button = self.query_one("#mode-button", Button)
        except (NoMatches, NoScreen):
            return
        header.paint()
        mode = workspace_mode_name(self)
        button.label = Text(workspace_mode_chip(self), style=CYAN if mode == "Classic" else MUTED)
        button.tooltip = tr("Workspace mode · click to switch between Classic, Flow and Security")
        try:
            gus = self.query_one("#gus-button", Button)
        except (NoMatches, NoScreen):
            gus = None
        if gus is not None:
            from isycode.tui_screens_gus import GUS_COLOR
            self._gus_offered = True
            gus.label = Text("GUS", style=GUS_COLOR if self._gus_enabled_here() else MUTED)
            gus.tooltip = tr("GUS, your assistant and ISyCode maintainer · click to talk to it")
        self._update_model_button_visibility()

    def _paint_rail_identity(self) -> None:
        try:
            button = self.query_one("#rail-identity", Button)
        except (NoMatches, NoScreen):
            return
        line = self._rail_identity_line()
        width = button.content_size.width or button.size.width or 0
        button.label = _fit_cells(line, width) if width else line
        button.tooltip = line

    def _identity_lines(self) -> list[str]:
        root = self._workspace_root
        identity = getattr(self, "_bridge_identity", "") or tr("Disabled · No Bridge Handshake")
        return [
            f"{tr('Workspace Root')} · {root}",
            f"{tr('Launch Directory')} · {self._launch_dir}",
            self._root_source_label(),
            f"{tr('Bridge')} · {identity}",
            f"{tr('Model')} · {getattr(self, '_model_line', '') or '—'}",
        ]

    def _show_identity(self) -> None:
        self.push_screen(IdentityDialog(self._identity_lines()))

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
        line = presence_line(rows, width)
        identity = getattr(self, "_bridge_identity", "")
        if identity:
            line = f"{identity} · {line}" if rows else f"{identity} · Bridge ready"
        panel.update(line)

    async def _show_bridge_presence(self) -> None:
        confirmed = await self._await_screen(BridgePresenceScreen())
        panel = self.query_one("#work-presence", Static)
        if not confirmed:
            self._presence_rows = None
            panel.update(tr("Bridge presence off"))
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
            panel.update(tr("Presence unavailable"))
            return
        if outcome.decision != "ALLOW":
            self._presence_rows = None
            panel.update(tr("Presence unavailable"))
            return
        self._presence_rows = rows
        self._paint_bridge_presence()
