"""File, skill, and LSP rail methods for the ISyCode TUI.

Moved verbatim from tui.py. TUIApp inherits RailMixin.
"""
from __future__ import annotations

import os
import asyncio
import json
from pathlib import Path
from isycode.decision_view import verified_receipt_line
from isycode.contracts import CatalogSnapshot
from textual.css.query import NoMatches
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
from isycode.tui_theme import (
    TEXT,
    MUTED,
    YELLOW,
    status_phrase,
    switch_row,
    switch_rows,
)
from isycode.tui_widgets import (
    Banner,
    Collapsible,
    SidePanel,
)


class RailMixin:
    """Sidebar files, skills, and the LSP rail."""

    def _apply_rail_width(self, terminal_width: int) -> None:
        """Keep the rail inside the configured range and available columns."""
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
        self._set_activity(f"Sidebar width · {width} columns", MUTED)
        self.call_after_refresh(self.query_one(Banner).set_compact, True)

    def action_narrow_sidebar(self) -> None:
        if self.size.width >= 100:
            self._rail_width = max(32, self._rail_width - 2)
            width = self._rail_width
        else:
            self._rail_compact_width = max(22, self._rail_compact_width - 2)
            width = self._rail_compact_width
        self._apply_rail_width(self.size.width)
        self._set_activity(f"Sidebar width · {width} columns", MUTED)
        self.call_after_refresh(self.query_one(Banner).set_compact, True)

    async def _refresh_openisy(self) -> None:
        self._openisy_refresh_generation += 1
        generation = self._openisy_refresh_generation
        self.query_one("#mcp-status", Static).update(
            switch_row(None, "Checking", status_phrase("connected tool services")))
        self._set_rail_title("rail-mcp", "MCPs · checking")
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
                        False, "External catalog denied",
                        "grant its host in Settings · Authority & Security"))
                    self._set_rail_title("rail-mcp", "MCPs · denied")
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
            self.query_one("#mcp-status", Static).update(switch_row(False, "Configuration error", message))
            self._set_rail_title("rail-mcp", "MCPs · error")
            self._populate_skill_tree(CatalogSnapshot(True, [], "error", message))
            self._provider_auth_snapshot = CatalogSnapshot(True, [], "error", message)
            self._openisy_provider_snapshot = CatalogSnapshot(True, [], "error", message)
        except Exception as exc:
            if generation != self._openisy_refresh_generation:
                return
            message = f"Integration refresh failed ({type(exc).__name__})."
            self.query_one("#mcp-status", Static).update(switch_row(False, "Refresh failed", message))
            self._set_rail_title("rail-mcp", "MCPs · error")
            self._populate_skill_tree(CatalogSnapshot(True, [], "error", message))
            self._provider_auth_snapshot = CatalogSnapshot(True, [], "error", message)
            self._openisy_provider_snapshot = CatalogSnapshot(True, [], "error", message)
        else:
            if generation != self._openisy_refresh_generation:
                return
            mcp_body, mcp_title = self._format_mcp_snapshot(mcp)
            self.query_one("#mcp-status", Static).update(mcp_body)
            self._set_rail_title("rail-mcp", mcp_title)
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
            return switch_row(None, "Checking", snapshot.detail), status_phrase("MCPs · checking")
        if snapshot.state != "ready":
            state = snapshot.state.replace("_", " ")
            inactive = snapshot.state in {"not_configured", "not_checked"}
            shown = "off" if inactive else state
            return (
                switch_row(False, status_phrase(state), snapshot.detail, inactive=inactive),
                status_phrase(f"MCPs · {shown}"),
            )
        if not snapshot.items:
            return (
                switch_row(False, "No MCP Servers", status_phrase("none configured"), inactive=True),
                status_phrase("MCPs · none"),
            )
        rows, on = [], 0
        for item in snapshot.items:
            healthy = (str(item.get("status", "")).lower() in {"connected", "ready", "running", "ok", "active"}
                       and not item.get("has_error"))
            on += healthy
            note = ("service reports an error" if item.get("has_error") else str(item.get("status", "")))
            rows.append(switch_row(
                healthy, str(item["name"]), "" if healthy else RailMixin._status_note(note)))
        return switch_rows(rows), status_phrase(f"MCPs · {on}/{len(snapshot.items)} on")

    @staticmethod
    def _format_skill_snapshot(snapshot: CatalogSnapshot) -> tuple[Text, str]:
        if snapshot.state == "loading":
            return switch_row(None, "Checking", snapshot.detail), status_phrase("Skills · checking")
        if snapshot.state != "ready":
            state = snapshot.state.replace("_", " ")
            inactive = snapshot.state in {"not_configured", "not_checked"}
            shown = "off" if inactive else state
            return (
                switch_row(False, status_phrase(state), snapshot.detail, inactive=inactive),
                status_phrase(f"Skills · {shown}"),
            )
        if not snapshot.items:
            return (
                switch_row(False, "No Skills", status_phrase("none available for this project"), inactive=True),
                status_phrase("Skills · none"),
            )
        count = len(snapshot.items)
        return (
            switch_row(True, status_phrase(f"{count} available"), status_phrase("select one below for details")),
            status_phrase(f"Skills · {count} available"),
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

    def _set_rail_title(self, section: str, title: str) -> None:
        try:
            self.query_one(f"#{section}", Collapsible).title = status_phrase(title)
        except Exception:
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
            body = switch_row(False, "No Language Servers", status_phrase("none detected"), inactive=True)
            title = "LSPs · None"
        else:
            rows = []
            ready = missing = 0
            for server in catalog:
                state = server.get("state")
                label = str(server.get("label") or server.get("id") or "language server")
                if state == "sandbox_ready":
                    ready += 1
                    rows.append(switch_row(True, label, status_phrase("workspace symbols")))
                elif state == "not_installed":
                    missing += 1
                    rows.append(switch_row(False, label, status_phrase("not on PATH"), inactive=True))
                elif state == "installed_unsupported":
                    rows.append(switch_row(False, label, status_phrase("installed · sandbox does not run it")))
                else:
                    rows.append(switch_row(False, label, status_phrase("installed · sandbox unavailable")))
            title = status_phrase(f"LSPs · {ready} ready")
            if missing:
                title = status_phrase(f"{title} · {missing} missing")
            body = switch_rows(rows)
        self.query_one("#lsp-status", Static).update(body)
        self._set_rail_title("rail-lsp", title)
        self._paint_idle()

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
        self._set_activity("Language servers were not installed · commands are under LSPs", YELLOW)

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
        self._set_rail_title("rail-skills", skill_title)
        has_skills = snapshot.state == "ready" and bool(snapshot.items)
        tree.display = has_skills
        detail = self.query_one("#skill-detail", Static)
        detail.display = False
        detail.update("")
        if snapshot.state != "ready":
            tree.root.set_label(
                "Loading skills…" if snapshot.state == "loading"
                else status_phrase(f"Skills · {snapshot.state.replace('_', ' ')}"))
            return
        if not snapshot.items:
            tree.root.set_label(status_phrase("No skills available"))
            return
        tree.root.set_label(status_phrase(f"Available skills ({len(snapshot.items)})"))
        for item in snapshot.items:
            tree.root.add_leaf(
                Text(f"{item['name']} · {self._origin_tag(item.get('origin', ''))}"), data=dict(item))
        tree.root.expand()

    async def _load_directory(self, logical_path: str) -> None:
        if self._workspace is None:
            return
        self._selected_file_path = None
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
            self.query_one("#file-preview", Static).update(f"Folder unavailable: {exc}")
            return
        if relative_dir == ".":
            relative_dir = ""
        current_label = self._file_browser_alias + " · " + browser_root.name + (f"/{relative_dir}" if relative_dir else "")
        tree.root.set_label(f"📁 {current_label}/")
        tree.root.data = {"path": logical_path, "kind": "directory"}
        self._file_path = logical_path
        self.query_one("#file-preview", Static).update("Checking Workspace Authority and IsySentinel…")
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
                self.query_one("#file-preview", Static).update(
                    str(exc) if isinstance(exc, WorkspaceUnavailable) else
                    f"Workspace read failed closed ({type(exc).__name__}).")
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
            label = f"📁 {name}/" if entry.get("kind") == "directory" else f"📄 {name}"
            tree.root.add(label, allow_expand=entry.get("kind") == "directory", data={"path": child_path, "kind": entry.get("kind"),
                                       "bytes": entry.get("bytes", 0)})
        self._search_mode = False
        status = verified_receipt_line(outcome.receipt.receipt_id)
        self.query_one("#file-preview", Static).update(
            f"{len(tree.root.children)} entries · {browser_root}\n"
            f"{status}")
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
        self.query_one("#file-copy-path", Button).disabled = True
        self.query_one("#file-open-preview", Button).disabled = True
        tree = self.query_one("#workspace-tree", Tree)
        tree.root.remove_children()
        tree.root.set_label(f"Searching: {query}")
        self.query_one("#file-preview", Static).update("Checking Workspace Authority and IsySentinel…")
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
            f"{len(payload.get('matches', []))} results · {payload.get('directories_scanned', 0)} directories scanned"
            f"{skipped_note}{limit_note}")
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
                    f"{name} · {state}\n"
                    "Workflow guidance only. /skills clear removes selected guidance."))
                return
            origin = self._origin_tag(skill.get("origin", "workspace"))
            description = skill.get("description") or "No description provided by the skill manifest."
            detail.update(Text(
                f"{name} · {origin}\n{description}\n"
                "Discovery only. This does not activate the skill."))
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
        self.query_one("#file-copy-path", Button).disabled = False
        self.query_one("#file-open-preview", Button).disabled = False
        await self._preview_file(uri)

    async def _preview_file(self, uri: str, *, modal: bool = False) -> None:
        if self._workspace is None:
            return
        self._workspace_generation += 1
        generation = self._workspace_generation
        self.query_one("#file-preview", Static).update("Checking Workspace Authority and IsySentinel…")
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
            self.query_one("#file-preview", Static).update(
                f"{relative} · {size} bytes · UTF-8\n"
                f"{verified_receipt_line(read.receipt.receipt_id)}\n\n{preview}")
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
        self.query_one(SidePanel).display = self._rail_visible
        self.call_after_refresh(self.query_one(Banner).set_compact, True)

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
        self.query_one(SidePanel).display = True
        self.call_after_refresh(self.query_one(Banner).set_compact, True)
        show_files = view == "files"
        self._rail_view = "files" if show_files else "overview"
        self.query_one("#overview-view").display = not show_files
        self.query_one("#files-view").display = show_files
        overview = self.query_one("#show-overview", Button)
        files = self.query_one("#show-files", Button)
        overview.set_class(not show_files, "rail-lit")
        files.set_class(show_files, "rail-lit")

    def _menu_branch(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
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
