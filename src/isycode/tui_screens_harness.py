"""Harness, model, and multi-harness modals.

Moved verbatim from tui.py. isycode.tui re-exports these names.
"""
from __future__ import annotations

from typing import Any
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.widgets import Button, Input, Static
from isycode.harness_graph import CATALOG_IDS, SEED_OPTIONS, gap_status
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from isycode.providers import PRESETS, resolved_chat_model, selected_provider_name
from pathlib import Path
from rich.text import Text
from isycode.tui_theme import (
    YELLOW,
    MUTED,
    CYAN,
    GREEN,
    TEXT,
)
from isycode.tui_widgets import Collapsible, activate_on_second_click
from isycode.tui_effort_slider import EffortSlider
from isycode.localization import tr



class HarnessFolderConfirmScreen(ModalScreen[bool]):
    CSS = """
    HarnessFolderConfirmScreen { align: center middle; background: #000000 68%; }
    #harness-folder-confirm { width: 86; max-width: 94%; height: auto; padding: 1 2; border: solid #718291; background: #000000; }
    #harness-folder-path { height: auto; color: #edf1f5; margin: 1 0; }
    #harness-folder-actions { height: 3; align-horizontal: right; }
    #harness-folder-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "decline", "Cancel", show=False),
                Binding("n", "decline", "Cancel", show=False),
                Binding("y", "approve", "Use folder", show=False)]

    def __init__(self, harness_id: str, path: Path) -> None:
        super().__init__()
        self.harness_id = harness_id
        self.path = path

    def compose(self) -> ComposeResult:
        label = self.harness_id.title()
        with Vertical(id="harness-folder-confirm", classes="isy-dialog"):
            yield Static(
                f"Use this folder for {label}? ISyCode will read option names only. "
                "This does not grant workspace access, a network host, or a credential.")
            yield Static(str(self.path), id="harness-folder-path", markup=False)
            with Horizontal(id="harness-folder-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel"), id="harness-folder-no")
                yield Button(tr("Use folder"), id="harness-folder-yes", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "harness-folder-yes")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_decline(self) -> None:
        self.dismiss(False)


class HarnessModelConfirmScreen(ModalScreen[bool]):
    CSS = """
    HarnessModelConfirmScreen { align: center middle; background: #000000 68%; }
    #harness-model-confirm { width: 92; max-width: 95%; height: auto; padding: 1 2; border: solid #718291; background: #000000; }
    #harness-model-actions { height: 3; align-horizontal: right; margin-top: 1; }
    #harness-model-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "decline", "Cancel", show=False),
                Binding("n", "decline", "Cancel", show=False),
                Binding("y", "approve", "Save", show=False)]

    def __init__(self, provider: str, model: str) -> None:
        super().__init__()
        self.provider = provider
        self.model = model

    def compose(self) -> ComposeResult:
        with Vertical(id="harness-model-confirm", classes="isy-dialog"):
            yield Static(
                f"Save provider {self.provider} and model {self.model} as this process's selection "
                "and in preferences/provider.json? The open chat's state.model is not changed. "
                "No API key is loaded. No network call is made.", markup=False)
            with Horizontal(id="harness-model-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel"), id="harness-model-no")
                yield Button(tr("Save selection"), id="harness-model-yes", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "harness-model-yes")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_decline(self) -> None:
        self.dismiss(False)


class HarnessTranscriptConfirmScreen(ModalScreen[bool]):
    CSS = """
    HarnessTranscriptConfirmScreen { align: center middle; background: #000000 68%; }
    #harness-transcript-confirm { width: 92; max-width: 95%; height: auto; padding: 1 2; border: solid #718291; background: #000000; }
    #harness-transcript-path { height: auto; color: #edf1f5; margin: 1 0; }
    #harness-transcript-actions { height: 3; align-horizontal: right; margin-top: 1; }
    #harness-transcript-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "decline", "Cancel", show=False),
                Binding("n", "decline", "Cancel", show=False),
                Binding("y", "approve", "Copy", show=False)]

    def __init__(self, harness_id: str, relative_path: str) -> None:
        super().__init__()
        self.harness_id = harness_id
        self.relative_path = relative_path

    def compose(self) -> ComposeResult:
        label = self.harness_id.title()
        with Vertical(id="harness-transcript-confirm", classes="isy-dialog"):
            yield Static(
                f"Copy reviewed transcript text from {label} into this chat? The text is data, "
                "not instructions to ISyCode, and it is not the same process or the same agent.",
                markup=False)
            yield Static(self.relative_path, id="harness-transcript-path", markup=False)
            with Horizontal(id="harness-transcript-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel"), id="harness-transcript-no")
                yield Button(tr("Copy transcript"), id="harness-transcript-yes", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "harness-transcript-yes")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_decline(self) -> None:
        self.dismiss(False)


class ModelChoice(Button):
    """One model row. The first click reads it; Enter or a second click uses it."""

    async def _on_click(self, event) -> None:
        # prevent_default skips Button._on_click, which would select on this same click.
        event.prevent_default()
        event.stop()
        self.focus()
        # Arm on the screen, keyed by row: arming another row disarms this one,
        # so A, B, A reads A again instead of selecting it.
        if activate_on_second_click(self.screen, event, self.id or str(id(self))):
            self.press()


class ModelsScreen(ModalScreen):
    """Searchable provider accordions; model IDs belong only in this selector.

    With ``provider_scope`` it lists only that provider's models (the step after
    choosing a provider). The detail card shows the highlighted model's facts and
    where each came from. A click reads a model. Enter, or a second click on the
    same row, is what selects it.
    """

    DEFAULT_CSS = """
    ModelsScreen { align: center middle; background: #000000 58%; }
    #models-card { width: 110; max-width: 96%; height: 94%; padding: 0 1; background: #000000; border: solid #718291; }
    #models-title { height: 1; }
    #models-search { height: 3; margin-bottom: 1; }
    #models-body { height: 1fr; }
    #models-scroll { height: 1fr; min-height: 4; width: 1fr; }
    #model-detail-scroll { width: 46; height: 1fr; margin-left: 1; padding: 0 1; border-left: solid #3f4d59; }
    #model-detail { height: auto; }
    ModelsScreen.-narrow #models-body { layout: vertical; }
    ModelsScreen.-narrow #model-detail-scroll { width: 100%; height: 6; margin-left: 0; border-left: none; border-top: solid #3f4d59; }
    ModelsScreen.-short #model-detail-scroll { height: 4; }
    .model-group { height: auto; background: transparent; }
    .model-group > Contents { padding: 0 1; }
    .model-family-block { height: auto; margin-top: 1; background: transparent; }
    .model-family { height: 1; color: #a9b5c2; padding: 0 1; }
    .model-choice { width: 100%; height: 1; min-height: 1; border: none; background: transparent; text-align: left; content-align: left top; padding: 0 1; margin: 0; text-style: none; text-wrap: nowrap; text-overflow: ellipsis; }
    .model-choice:focus, .model-choice.-selected { background: #03252d; }
    .model-choice:hover { background: #03252d; }
    #models-status { height: auto; max-height: 2; color: #a9b5c2; }
    #models-add { height: 3; }
    #models-add-input { width: 1fr; }
    #models-add-button { height: 3; width: auto; margin-left: 1; }
    #models-actions { height: 3; align-horizontal: right; }
    #models-actions Button { height: 3; width: auto; margin-left: 1; }
    #models-hint { height: 1; color: #a9b5c2; }
    """
    BINDINGS = [Binding("escape", "close", "Close"),
                Binding("down", "focus_next", "Next", show=False),
                Binding("up", "focus_previous", "Previous", show=False),
                Binding("left", "effort(-1)", "Less effort", show=False),
                Binding("right", "effort(1)", "More effort", show=False)]
    NARROW_WIDTH = 100
    def __init__(self, entries: list[dict], provider_scope: str | None = None) -> None:
        super().__init__()
        self.provider_scope = provider_scope
        self.entries = entries
        self.choices: dict[str, dict] = {}
        self.expanded_providers: set[str] = {provider_scope or selected_provider_name()}
        self.search_query = ""
        # Widget IDs change when a live catalog is recomposed. Retain the
        # provider/model payload, never a positional row ID, as the preview.
        self.selected_model_value: str | None = None
        # Textual chooses initial focus before refresh callbacks run. The
        # current row assigns its concrete selector while compose builds it.
        self.AUTO_FOCUS = "#models-search"
        # Draft reasoning level per provider|model; applied only with Choose.
        self.effort_drafts: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        self.choices = {}
        groups: dict[str, list[dict]] = {}
        families: dict[str, list[dict]] = {}
        for entry in self.entries:
            if entry["kind"] == "model_family":
                provider, family = entry["value"].split("|", 1)
                variants = getattr(self.app, "_account_family_variants", {}).get(
                    (provider, family), [])
                families.setdefault(provider, []).extend(variants)
                continue
            if entry["kind"] == "model":
                provider, model = entry["value"].split("|", 1)
                groups.setdefault(provider, [])
                if not any(item["value"] == entry["value"] for item in groups[provider]):
                    groups[provider].append(entry)
        for provider, variants in families.items():
            bucket = groups.setdefault(provider, [])
            for entry in variants:
                if not any(item["value"] == entry["value"] for item in bucket):
                    bucket.append(entry)
        scope = self.provider_scope
        if scope:
            groups = {scope: groups.get(scope, [])}
            self.expanded_providers.add(scope)
        heading = (tr("Models · {provider}", provider=PRESETS.get(scope, {}).get("label", scope))
                   if scope else tr("Models"))
        with Vertical(id="models-card", classes="isy-dialog"):
            yield Static(Text(heading, style=f"bold {TEXT}"), id="models-title", classes="isy-dialog-title")
            yield Input(value=self.search_query, placeholder=tr("Find a model, id or family…"), id="models-search")
            with Horizontal(id="models-body", classes="isy-dialog-body"):
                with VerticalScroll(id="models-scroll"):
                    for index, entry in enumerate(self.entries):
                        if entry["kind"] == "model_list" and (not scope or entry["value"] == scope):
                            key = f"model-catalog-{index}"
                            self.choices[key] = entry
                            yield Button(tr("Refresh account catalog · ") + PRESETS.get(entry["value"], {}).get("label", entry["value"]),
                                         id=key, classes="model-choice")
                    if scope:
                        if not groups[scope]:
                            yield Static(tr("No models listed for this provider yet · refresh its account catalog."),
                                         classes="model-empty")
                        else:
                            for entry in groups[scope]:
                                yield self._choice_button(entry)
                    else:
                        for provider, entries in groups.items():
                            with Collapsible(title=f"{PRESETS.get(provider, {}).get('label', provider)} · {len(entries)} models",
                                             collapsed=provider not in self.expanded_providers, classes="model-group", id="model-provider-" + provider):
                                for entry in entries:
                                    yield self._choice_button(entry)
                with VerticalScroll(id="model-detail-scroll"):
                    yield Static(Text("Click a model. Context, reasoning and tools show here.", style=MUTED),
                                 id="model-detail")
            slider = EffortSlider(id="models-effort")
            slider.display = False
            yield slider
            notes = [entry["label"] for entry in self.entries if entry["kind"] == "info"]
            yield Static("\n".join(notes), id="models-status", classes="isy-dialog-hint")
            if scope:
                with Horizontal(id="models-add"):
                    yield Input(placeholder=tr("Add a model ID to {provider}…",
                                               provider=PRESETS.get(scope, {}).get("label", scope)),
                                id="models-add-input")
                    yield Button(tr("+ Add"), id="models-add-button")
            with Horizontal(id="models-actions", classes="isy-dialog-actions"):
                yield Button(tr("Back") if scope else tr("Close"), id="models-close")
                yield Button(tr("Choose model"), id="models-use", variant="primary", disabled=True)
            yield Static(tr("↑↓ move · ←→ effort · Enter choose · Esc back · Tab search"), id="models-hint", classes="isy-dialog-hint")

    def _choice_button(self, entry: dict) -> ModelChoice:
        from isycode.model_presentation import model_display_name
        provider, model = entry["value"].split("|", 1)
        key = f"model-choice-{len(self.choices)}"
        self.choices[key] = entry
        wanted = self.selected_model_value or (
            f"{selected_provider_name()}|{resolved_chat_model()}")
        if entry.get("value") == wanted:
            self.AUTO_FOCUS = f"#{key}"
        label = Text(model_display_name(model), style=TEXT)
        if entry.get("custom"):
            label.append("  · " + tr("added"), style=MUTED)
        if provider == selected_provider_name() and model == resolved_chat_model(provider):
            label.append("  · " + tr("current"), style=GREEN)
        return ModelChoice(label, id=key, classes="model-choice")

    def _by_family(self, entries: list[dict]) -> list[tuple[str, list[dict]]]:
        from isycode.model_presentation import model_family
        order: list[str] = []
        buckets: dict[str, list[dict]] = {}
        for entry in entries:
            family = model_family(entry["value"].split("|", 1)[1])
            if family not in buckets:
                order.append(family)
                buckets[family] = []
            buckets[family].append(entry)
        return [(family, buckets[family]) for family in order]

    def on_mount(self) -> None:
        self._apply_width(self.app.size.width)
        self.set_class(self.app.size.height <= 26, "-short")
        # The row is registered during compose, before nested containers finish
        # mounting. Querying it here crashes the screen.
        self.call_after_refresh(self._reveal_current)

    def _reveal_current(self, attempt: int = 0) -> None:
        """Show the model already in use, without arming it for a click.

        A catalog refresh clears the rows and mounts them again on the next
        idle. A query in that gap finds the choice recorded and the widget
        not yet in the tree.
        """
        wanted = self.selected_model_value or f"{selected_provider_name()}|{resolved_chat_model()}"
        for key, entry in list(self.choices.items()):
            if entry.get("kind") != "model" or entry.get("value") != wanted:
                continue
            provider, model = wanted.split("|", 1)
            self.show_details(provider, model)
            try:
                button = self.query_one(f"#{key}", ModelChoice)
            except NoMatches:
                if attempt < 3:
                    self.call_after_refresh(self._reveal_current, attempt + 1)
                return
            if button.display:
                button.scroll_visible()
                self.set_focus(button)
            return
        if attempt < 3 and not self.choices:
            self.call_after_refresh(self._reveal_current, attempt + 1)

    def on_resize(self, event) -> None:
        self._apply_width(event.size.width)
        self.set_class(event.size.height <= 26, "-short")

    def _apply_width(self, width: int) -> None:
        self.set_class(width < self.NARROW_WIDTH, "-narrow")

    def on_descendant_focus(self, event) -> None:
        widget = event.widget
        entry = self.choices.get(getattr(widget, "id", None) or "")
        if entry is not None and entry["kind"] == "model":
            self.selected_model_value = entry["value"]
            for row in self.query(ModelChoice):
                row.set_class(row is widget, "-selected")
            self.query_one("#models-use", Button).disabled = False
            self.show_details(*entry["value"].split("|", 1))
            self._show_effort(entry["value"])

    def _show_effort(self, value: str) -> None:
        from isycode.reasoning_options import (effective_reasoning, reasoning_levels,
                                               selected_reasoning)
        provider, model = value.split("|", 1)
        slider = self.query_one("#models-effort", EffortSlider)
        levels = reasoning_levels(provider, model)
        if value not in self.effort_drafts:
            self.effort_drafts[value] = selected_reasoning(provider, model) or "default"
        hint = effective_reasoning(provider, model, PRESETS.get(provider, {}).get("reasoning_effort"))
        slider.show(levels, self.effort_drafts[value], hint)

    def action_effort(self, direction: int) -> None:
        if self.selected_model_value is None:
            return
        level = self.query_one("#models-effort", EffortSlider).step(direction)
        if level is not None:
            self.effort_drafts[self.selected_model_value] = level

    def on_effort_slider_changed(self, event: EffortSlider.Changed) -> None:
        if self.selected_model_value is not None:
            self.effort_drafts[self.selected_model_value] = event.level

    def _with_effort(self, entry: dict) -> dict:
        """The chosen entry plus its draft level, when the model has levels."""
        from isycode.reasoning_options import reasoning_levels
        if entry.get("kind") != "model":
            return entry
        provider, model = entry["value"].split("|", 1)
        if not reasoning_levels(provider, model):
            return entry
        return {**entry, "reasoning": self.effort_drafts.get(entry["value"], "default")}

    def show_details(self, provider: str, model: str) -> None:
        from isycode.model_card import model_facts
        card = Text()
        facts = model_facts(provider, model)
        for fact in facts:
            card.append(tr(fact.label) + ": ", style=MUTED)
            card.append(fact.value + "\n", style=TEXT)
        self.query_one("#model-detail", Static).update(card)

    def _haystack(self, provider: str, model: str) -> str:
        from isycode.model_card import catalog_entry
        from isycode.model_presentation import model_display_name
        label = PRESETS.get(provider, {}).get("label", provider)
        family = (catalog_entry(provider, model) or {}).get("family") or ""
        return f"{label} {provider} {model} {model_display_name(model)} {family}".casefold()

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        group_id = event.collapsible.id or ""
        if group_id.startswith("model-provider-"):
            name = group_id.removeprefix("model-provider-")
            self.expanded_providers.add(name)
            attempted = getattr(self.app, "_account_models_attempted", set())
            if name not in attempted:
                self.app._account_models_attempted = attempted | {name}
                self.app._account_models_loading = True
                self.app.run_worker(self.app._load_account_models(name), group="provider-models")

    def on_collapsible_collapsed(self, event: Collapsible.Collapsed) -> None:
        self.expanded_providers.discard((event.collapsible.id or "").removeprefix("model-provider-"))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "models-search":
            return
        self.search_query = event.value
        query = event.value.casefold().strip()
        matches = 0
        for button in self.query(ModelChoice):
            entry = self.choices[button.id]
            provider, model = entry["value"].split("|", 1)
            button.display = not query or query in self._haystack(provider, model)
            matches += bool(button.display)
        for group in self.query(".model-group"):
            matches = 0
            for button in group.query(Button):
                entry = self.choices[button.id]
                if entry.get("kind") != "model":
                    continue
                provider, model = entry["value"].split("|", 1)
                button.display = not query or query in self._haystack(provider, model)
                matches += bool(button.display)
            group.display = bool(matches)
            if query and matches:
                group.collapsed = False
        selected = self._selected_row()
        self.query_one("#models-use", Button).disabled = selected is None
        notes = [entry["label"] for entry in self.entries if entry["kind"] == "info"]
        status = tr("No matching models") if not any(row.display for row in self.query(ModelChoice)) else "\n".join(notes)
        self.query_one("#models-status", Static).update(status)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "models-add-input":
            event.stop()
            self._add_custom_model()
            return
        if event.input.id == "models-search":
            event.stop()
            first = next((row for row in self.query(ModelChoice) if row.display), None)
            if first is not None:
                first.focus()

    def _add_custom_model(self) -> None:
        """Remember a typed ID for this provider and preview it. Activates nothing."""
        from isycode.providers import add_custom_model
        scope = self.provider_scope
        field = self.query_one("#models-add-input", Input)
        model = field.value.strip()
        status = self.query_one("#models-status", Static)
        if not scope or not model:
            status.update(tr("Type a model ID first."))
            return
        try:
            add_custom_model(scope, model)
        except (ValueError, OSError) as error:
            status.update(tr("Model ID not added · {reason}", reason=str(error)[:120]))
            return
        value = f"{scope}|{model}"
        if not any(entry.get("kind") == "model" and entry.get("value") == value
                   for entry in self.entries):
            label = PRESETS.get(scope, {}).get("label", scope)
            self.entries = [*self.entries, {
                "label": tr("{label}  ·  {model}  · added by you", label=label, model=model),
                "kind": "model", "value": value, "custom": True,
                "detail": tr("Model ID you added; not verified against this account.")}]
        self.selected_model_value = value
        self.search_query = ""
        self.choices = {}
        self.refresh(recompose=True)
        self.call_after_refresh(self._reveal_current)

    def _selected_row(self) -> ModelChoice | None:
        return next((row for row in self.query(ModelChoice)
                     if row.display and self.choices.get(row.id, {}).get("value")
                     == self.selected_model_value), None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "models-add-button":
            self._add_custom_model()
        elif event.button.id == "models-close":
            self.dismiss(None)
        elif event.button.id == "models-use":
            selected = self._selected_row()
            if selected is not None:
                self.dismiss(self._with_effort(self.choices[selected.id]))
        elif event.button.id in self.choices:
            self.dismiss(self._with_effort(self.choices[event.button.id]))

    def action_close(self) -> None:
        self.dismiss(None)


class HarnessRepairConfirmScreen(ModalScreen[str | None]):
    """One window that lists every cli:file the repair will touch.

    Actions:
    - Cancel: dismiss with None
    - Launch repair conversation: dismiss with "lane" (new ISyCode lane)
    - Launch in Hive: dismiss with "hive" (spawn hive agent)
    """

    CSS = """
    HarnessRepairConfirmScreen { align: center middle; background: #000000 58%; }
    #repair-confirm-card { width: 94; max-width: 96%; height: 96%; padding: 0 1;
                          border: solid #718291; background: #000000; }
    #repair-confirm-title { height: 1; color: #edf1f5; text-style: bold; }
    #repair-confirm-scroll { height: 1fr; }
    #repair-confirm-body { height: auto; }
    #repair-confirm-actions { height: 3; align-horizontal: right; margin-top: 1; }
    #repair-confirm-actions Button { margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False),
                Binding("n", "cancel", "Cancel", show=False)]

    def __init__(self, targets: list[dict[str, Any]], brief: str) -> None:
        super().__init__()
        self.targets = targets
        self.brief = brief

    def compose(self) -> ComposeResult:
        with Vertical(id="repair-confirm-card", classes="isy-dialog"):
            yield Static(tr("Repair plan · choose how to execute"), id="repair-confirm-title",
                        classes="isy-dialog-title")
            with VerticalScroll(id="repair-confirm-scroll", classes="isy-dialog-body"):
                yield Static(self._render_body(), id="repair-confirm-body")
            with Horizontal(id="repair-confirm-actions", classes="isy-dialog-actions"):
                yield Button(tr("Cancel · Esc"), id="repair-cancel")
                yield Button(tr("Launch repair conversation"), id="repair-lane", variant="primary")
                yield Button(tr("Launch in Hive"), id="repair-hive", variant="success")

    def _render_body(self) -> Text:
        body = Text()
        if not self.targets:
            body.append("No actionable gaps · nothing to repair.\n", style="#9295a2")
            return body
        body.append(f"{len(self.targets)} setting(s) will be reviewed:\n\n", style="#edf1f5")
        for index, target in enumerate(self.targets, 1):
            harnesses = ", ".join(target["harnesses"]) or "none"
            body.append(f"{index}. {target['title']}", style="#77d8b0")
            body.append(f"\n   cli: {harnesses}", style="#aeb6c5")
            files = target["files"]
            if not files:
                body.append("\n   files: none yet (new in ISyCode)", style="#f6c77b")
            else:
                for path in files:
                    body.append(f"\n   files: {path}", style="#aeb6c5")
            body.append("\n")
        body.append("\nChoose execution mode:\n", style="#f6c77b")
        body.append("  • Lane: new ISyCode conversation in this window\n", style="#aeb6c5")
        body.append("  • Hive: spawn a hive agent (multi-agent, git-backed coordination)\n", style="#aeb6c5")
        return body

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "repair-cancel":
            self.dismiss(None)
        elif event.button.id == "repair-lane":
            self.dismiss("lane")
        elif event.button.id == "repair-hive":
            self.dismiss("hive")

    def action_cancel(self) -> None:
        self.dismiss(None)


class HarnessComposeScreen(ModalScreen[bool]):
    CSS = """
    HarnessComposeScreen { align: center middle; background: #000000 58%; }
    #compose-card { width: 90%; height: 94%; padding: 0 1; border: solid #718291; background: #000000; }
    #compose-scroll { height: 1fr; }
    #compose-body { height: auto; }
    #compose-actions { height: 3; align-horizontal: right; }
    #compose-actions Button { height: 3; width: auto; margin-left: 1; }
    """
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, brief):
        super().__init__()
        self.brief = brief

    def compose(self):
        with Vertical(id="compose-card", classes="isy-dialog"):
            yield Static(Text(tr("Repair Compose · review proposal"), style=f"bold {TEXT}"), classes="isy-dialog-title")
            with VerticalScroll(id="compose-scroll", classes="isy-dialog-body"):
                yield Static(Text(self.brief), id="compose-body")
            with Horizontal(id="compose-actions", classes="isy-dialog-actions"):
                yield Button(tr("Back · Esc"), id="compose-close")
                yield Button(tr("Copy reviewed Compose"), id="compose-copy", variant="primary")

    def on_button_pressed(self, event):
        self.dismiss(event.button.id == "compose-copy")

    def action_close(self):
        self.dismiss(False)


class MultiHarnessScreen(ModalScreen[str | None]):
    """Inspect harness evidence and prepare explicit repair proposals."""

    CSS = """
    MultiHarnessScreen { align: center middle; background: #000000 58%; }
    #harness-card { width: 100; max-width: 95%; height: 94%; padding: 0 1; border: solid #718291; background: #000000; }
    #harness-title { height: 1; color: #edf1f5; text-style: bold; }
    #harness-counts { height: 1; margin-bottom: 1; }
    .harness-count { width: auto; height: 1; margin-right: 2; border: none; background: #000000; color: #a9b5c2; }
    #harness-summary { height: auto; max-height: 2; color: #a9b5c2; margin-bottom: 1; }
    #harness-scroll { height: 1fr; scrollbar-color: #718291; }
    .harness-section { width: 100%; height: auto; padding: 0; margin: 0; background: transparent; border: none; }
    .harness-section > Contents { padding: 0 1; background: #000000; }
    .harness-section-text { width: 100%; height: auto; color: #edf1f5; }
    .harness-actions { width: 100%; height: 3; margin-top: 1; }
    .harness-actions Button { width: 1fr; min-width: 0; height: 3; margin-right: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    #harness-gap-panel { width: 100%; margin-top: 1; }
    #harness-gap-content { height: auto; }
    #harness-gap-actions { width: 100%; height: 3; margin-bottom: 1; }
    #harness-gap-actions Button { width: 1fr; min-width: 0; height: 3; }
    #harness-footer { height: 3; align-horizontal: right; }
    #harness-close { width: auto; height: 3; }
    #harness-hint { height: 1; color: #a9b5c2; }
    """
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self.sections: list[dict[str, Any]] = [
            {"harness_id": harness_id, "checking": True, "unlocked": False, "settings": []}
            for harness_id in CATALOG_IDS
        ]
        self.transcript_count = 0
        self.copyable_models: dict[str, tuple[str, str]] = {}
        self.transcript_sources: dict[str, tuple[str, str]] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="harness-card", classes="isy-dialog"):
            yield Static(tr("Multi Harness · inspection"), id="harness-title", classes="isy-dialog-title")
            with Horizontal(id="harness-counts"):
                yield Static(f"Folders  0/{len(CATALOG_IDS)}", id="harness-folders-count", classes="harness-count")
                yield Static(tr("Conversations  0"), id="harness-sessions-count", classes="harness-count")
            yield Static(self._render_summary(), id="harness-summary")
            with VerticalScroll(id="harness-scroll", classes="isy-dialog-body"):
                for harness_id in CATALOG_IDS:
                    with Collapsible(title=self._section_title(harness_id), collapsed=True,
                                     id=f"harness-fold-{harness_id}", classes="harness-section"):
                        yield Static(self._render_harness(harness_id),
                                     id=f"harness-section-text-{harness_id}",
                                     classes="harness-section-text")
                        with Horizontal(classes="harness-actions"):
                            yield Button(tr("Choose folder…"), id=self._pick_button_id(harness_id))
                            copy_button = Button(tr("Copy model"), id=self._copy_button_id(harness_id))
                            copy_button.display = False
                            yield copy_button
                            transcript_button = Button(tr("Copy transcript"), id=self._transcript_button_id(harness_id))
                            transcript_button.display = False
                            yield transcript_button
                with Collapsible(title=self._gap_title(), collapsed=True, id="harness-gap-panel"):
                    with Horizontal(id="harness-gap-actions"):
                        yield Button(tr("Repair all gaps"), id="harness-compose-all", variant="primary")
                    yield Static(self._render_gaps(), id="harness-gap-content")
                    for row in self._gap_rows():
                        with Collapsible(title=row["title"], collapsed=True):
                            yield Static(Text(SEED_OPTIONS[row["semantic_id"]].meaning))
                            yield Button(tr("Prepare repair Compose"), id=f"harness-compose-{row['semantic_id']}")
            with Horizontal(id="harness-footer", classes="isy-dialog-actions"):
                yield Button(tr("Close"), id="harness-close")
            yield Static(tr("↑↓ move · Enter inspect · Esc back"), id="harness-hint", classes="isy-dialog-hint")

    def _render_summary(self) -> Text:
        checking = sum(bool(section.get("checking")) for section in self.sections)
        summary = Text()
        if checking:
            summary.append(tr("{count} checking…", count=checking) + " · ", style=YELLOW)
        summary.append(tr("Inspect a harness · Gap map prepares repair proposals for review."), style=MUTED)
        return summary

    def _section_title(self, harness_id: str) -> str:
        section = next((item for item in self.sections if item["harness_id"] == harness_id), {})
        state = ("checking…" if section.get("checking") else
                 "ready" if section.get("unlocked") else "folder unavailable")
        return f"{harness_id.upper()} · {state}"

    def _render_harness(self, harness_id: str) -> Text:
        section = next((item for item in self.sections if item["harness_id"] == harness_id), None)
        note = Text()
        note.append(harness_id.upper(), style=TEXT)
        if section is None or section.get("checking"):
            note.append("  ·  checking…", style="#f6c77b")
            return note
        if not section.get("unlocked"):
            note.append("  ·  folder unavailable", style="#9295a2")
            return note
        note.append("  ·  " + tr("ready"), style=CYAN)
        version = section.get("version_line") or "version answered"
        note.append("\n" + str(version), style="#a5a9ba")
        settings = section.get("settings", [])
        if not settings:
            note.append("\nNo reviewed settings", style="#9295a2")
        for setting in settings:
            semantic = str(setting.get("semantic_id") or "unmapped")
            title = SEED_OPTIONS[semantic].title if semantic in SEED_OPTIONS else semantic.replace("_", " ").title()
            edge = str(setting.get("edge", "unmapped"))
            color = "#77d8b0" if edge == "same" else "#f6c77b" if edge == "non_equivalent" else "#9295a2"
            note.append("\n  · ", style=MUTED)
            note.append(title, style=TEXT)
            note.append(f"  {edge} · N={setting.get('n', 0)}", style=color)
            note.append(f"\n    {setting.get('display_value', '')}", style="#aeb6c5")
        return note

    def _gap_title(self) -> str:
        rows = self._gap_rows()
        actionable = sum(row["status"] == "ADD" for row in rows)
        return f"Gap map  ·  {actionable} to consider  ·  repair Compose"

    def _render_gaps(self) -> Text:
        content = Text()
        for row in self._gap_rows():
            color = {"ADD": "#77d8b0", "WATCH": "#f6c77b",
                     "DO_NOT_MERGE": "#e997a7", "ALIGNED": "#9295a2"}[row["status"]]
            content.append(f"{row['status']:<14}", style=f"bold {color}")
            content.append(f" {row['title']}  ·  N={row['n']}\n", style="#d9d1df")
            content.append(f"  {row['target_label']}", style="#aeb6c5")
            if row["copy_note"]:
                content.append(f"  ·  {row['copy_note']}", style="#e997a7")
            content.append("\n")
        return content

    @staticmethod
    def _pick_button_id(harness_id: str) -> str:
        return f"harness-pick-{harness_id}"

    @staticmethod
    def _copy_button_id(harness_id: str) -> str:
        return f"harness-copy-{harness_id}"

    @staticmethod
    def _transcript_button_id(harness_id: str) -> str:
        return f"harness-transcript-{harness_id}"

    def _render_text(self) -> str:
        lines = [f"ISyCode conversations · {self.transcript_count}", ""]
        for section in self.sections:
            harness_id = section["harness_id"]
            if section.get("checking"):
                lines.append(f"{harness_id} · Checking {harness_id}…")
                continue
            if not section.get("unlocked"):
                lines.append(f"{harness_id} · no automatic folder")
                continue
            version = section.get("version_line") or "version answered"
            lines.append(f"{harness_id} · {version}")
            settings = section.get("settings", [])
            if not settings:
                lines.append("  no reviewed semantic settings")
                continue
            for setting in settings:
                semantic = setting.get("semantic_id") or "unmapped"
                lines.append(
                    f"  {semantic} · {setting['edge']} · N={setting['n']} · {setting['display_value']}"
                )
        lines.extend(["", "Gap backlog · read-only"])
        for gap in self._gap_rows():
            harnesses = ", ".join(gap["harnesses"]) or "none"
            suffix = f" · {gap['copy_note']}" if gap["copy_note"] else ""
            lines.append(
                f"{gap['title']} · {gap['status']} · N={gap['n']} · {harnesses} · "
                f"{gap['target_label']}{suffix}"
            )
        return "\n".join(lines)

    def _gap_rows(self) -> list[dict[str, Any]]:
        present: dict[str, set[str]] = {}
        for section in self.sections:
            if not section.get("unlocked"):
                continue
            harness_id = str(section.get("harness_id", ""))
            for setting in section.get("settings", []):
                semantic_id = setting.get("semantic_id")
                if (not semantic_id or setting.get("counts_toward_n", True) is False):
                    continue
                present.setdefault(str(semantic_id), set()).add(harness_id)

        rows: list[dict[str, Any]] = []
        for option in SEED_OPTIONS.values():
            gap = gap_status(option, present.get(option.id, set()))
            if gap is None:
                continue
            if gap.status == "ADD":
                target_label = "Missing in ISyCode"
            elif gap.isycode_target == "absent":
                target_label = "Not an ISyCode setting"
            else:
                target_label = gap.isycode_target
            rows.append({
                "semantic_id": option.id,
                "title": option.title,
                "harnesses": gap.harnesses,
                "n": len(gap.harnesses),
                "status": gap.status,
                "target_label": target_label,
                "copy_note": "will not be copied" if gap.status == "DO_NOT_MERGE" else "",
            })
        return rows

    def update_snapshot(self, sections: list[dict[str, Any]], transcript_count: int) -> None:
        self.sections = sections
        self.transcript_count = transcript_count
        self.copyable_models = {}
        self.transcript_sources = {}
        for section in sections:
            harness_id = str(section.get("harness_id", ""))
            root = section.get("root")
            sources = section.get("transcript_sources", [])
            if (isinstance(root, str) and root
                    and isinstance(sources, list) and sources
                    and isinstance(sources[0], str) and sources[0]):
                self.transcript_sources[harness_id] = (root, sources[0])
            for setting in section.get("settings", []):
                if (setting.get("semantic_id") == "default_model"
                        and setting.get("copyable") is True
                        and isinstance(setting.get("provider_id"), str)
                        and isinstance(setting.get("model_id"), str)):
                    self.copyable_models[harness_id] = (
                        setting["provider_id"], setting["model_id"])
                    break
        if self.is_mounted:
            ready = sum(bool(section.get("unlocked")) for section in self.sections)
            self.query_one("#harness-folders-count", Static).update(f"Folders  {ready}/{len(CATALOG_IDS)}")
            self.query_one("#harness-sessions-count", Static).update(f"Conversations  {self.transcript_count}")
            self.query_one("#harness-summary", Static).update(self._render_summary())
            self.query_one("#harness-gap-content", Static).update(self._render_gaps())
            self.query_one("#harness-gap-panel", Collapsible).title = self._gap_title()
            for harness_id in CATALOG_IDS:
                fold = self.query_one(f"#harness-fold-{harness_id}", Collapsible)
                fold.title = self._section_title(harness_id)
                section = next((item for item in self.sections if item["harness_id"] == harness_id), {})
                fold.query_one("CollapsibleTitle").styles.color = (
                    YELLOW if section.get("checking") else GREEN if section.get("unlocked") else MUTED)
                self.query_one(f"#harness-section-text-{harness_id}", Static).update(
                    self._render_harness(harness_id))
                self.query_one("#" + self._copy_button_id(harness_id), Button).display = (
                    harness_id in self.copyable_models)
                self.query_one("#" + self._transcript_button_id(harness_id), Button).display = (
                    harness_id in self.transcript_sources)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "harness-close":
            self.dismiss(None)
        elif event.button.id == "harness-compose-all":
            self.dismiss("compose:all")
        elif event.button.id and event.button.id.startswith("harness-compose-"):
            semantic_id = event.button.id.removeprefix("harness-compose-")
            if semantic_id in SEED_OPTIONS:
                self.dismiss("compose:" + semantic_id)
        elif event.button.id and event.button.id.startswith("harness-pick-"):
            harness_id = event.button.id.removeprefix("harness-pick-")
            if harness_id in CATALOG_IDS:
                self.dismiss(harness_id)
        elif event.button.id and event.button.id.startswith("harness-copy-"):
            harness_id = event.button.id.removeprefix("harness-copy-")
            if harness_id in self.copyable_models:
                self.dismiss("copy:" + harness_id)
        elif event.button.id and event.button.id.startswith("harness-transcript-"):
            harness_id = event.button.id.removeprefix("harness-transcript-")
            if harness_id in self.transcript_sources:
                self.dismiss("transcript:" + harness_id)

    def action_close(self) -> None:
        self.dismiss(None)
