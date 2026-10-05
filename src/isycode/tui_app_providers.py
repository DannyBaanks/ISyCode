"""Provider, model, and credential methods for the ISyCode TUI.

Moved verbatim from tui.py. TUIApp inherits ProviderMixin.
"""
from __future__ import annotations

import os
import asyncio
from isycode.config import (
    ConfigurationError,
    isymotron_provider_available,
    provider_default_model,
)
from isycode.credential_owner import (
    GATEWAY_SERVICE,
    CredentialOwner,
)
from isycode.credentials import (
    CredentialVault,
    CredentialVaultError,
    saved_secret_exists,
)
from isycode.workspace_authority import (
    WorkspaceAuthority,
    WorkspaceAuthorityError,
)
from isycode.action_runtime import ProviderNetworkOwner
from isycode.authority_view import displayed_on
from textual.containers import Vertical
from textual.widgets import (
    Static,
    Input,
    OptionList,
)
from isycode.providers import (
    DEFAULT_MODEL,
    PRESETS,
    PROVIDER_SCREEN,
    Provider,
    ProviderError,
    featured_models,
    load_provider_key,
    provider_credential_state,
    resolved_chat_model,
    save_provider_selection,
    selected_provider_name,
)
from isycode.tui_theme import (
    MUTED,
    GREEN,
    YELLOW,
    RED,
    CYAN,
)
from isycode.tui_screens_approval import TailscaleConfirmScreen
from isycode.shortcuts import APP_SHORTCUTS
from textual.widgets import Button
from isycode.tui_widgets import ExpandableBox
from isycode.catalog import ISYCODE_AGENTS, ISYCODE_SUBAGENTS, ISYCO_MOTORS
from isycode.user_defaults import UserDefaultsStore


class ProviderMixin:
    """Provider menu, model selection, and saved keys."""

    def _open_provider_menu(self) -> None:
        active = selected_provider_name()
        entries = []
        group = ""
        for section, key, label, blurb in PROVIDER_SCREEN:
            if section != group:
                group = section
                entries.append(self._entry("Popular" if section == "popular" else "Providers", "section"))
            if key and key in PRESETS:
                preset = PRESETS[key]
                state = provider_credential_state(key)
                status = {"environment": "key in environment", "saved": "key saved",
                          "stored": "legacy key saved", "legacy": "legacy key",
                          "optional": "no key required", "subscription": "subscription",
                          "signed-in": "Grok sign-in",
                          "missing": f"needs {preset['key_env']}",
                          "unavailable": "credential store unavailable"}.get(state, state)
                current = key == active or (key == "openai" and active == "chatgpt")
                mark = "✓" if current else "○"
                note = "  ← currently active" if current else f"  ·  {blurb}"
                entries.append(self._entry(
                    f"{mark}  {label}{note}",
                    "provider", key,
                    f"{blurb}. {status}. Default model: "
                    f"{provider_default_model(key) or preset.get('default_model') or DEFAULT_MODEL}"))
            else:
                entries.append(self._entry(
                    f"·  {label}  ·  {blurb}", "provider_unwired", label, blurb))
        snapshot = self._provider_auth_snapshot
        auth_methods = {item["name"]: item.get("methods", [])
                        for item in snapshot.items} if snapshot.state == "ready" else {}
        openisy_catalog = self._openisy_provider_snapshot
        if openisy_catalog.state == "ready":
            entries.append(self._entry("— Additional provider accounts —", "info"))
            for provider in openisy_catalog.items:
                methods = auth_methods.get(provider["id"], [])
                method_text = "/".join(methods) if methods else "auth metadata unavailable"
                state_text = "connected account" if provider["connected"] else "available account"
                entries.append(self._entry(
                    f"{provider['name']}  ·  {state_text} · {method_text}",
                    "openisy_provider", provider["id"],
                    "This account is not connected to ISyCode inference yet."))
        else:
            entries.append(self._entry(
                f"Additional provider catalog · {openisy_catalog.state.replace('_', ' ')}",
                "info", "", openisy_catalog.detail))
        if snapshot.state == "ready":
            catalog_ids = {provider["id"] for provider in openisy_catalog.items}
            for provider in snapshot.items:
                if "oauth" in provider.get("methods", []) and provider["name"] not in catalog_ids:
                    entries.append(self._entry(
                        f"{provider['name']}  ·  OAuth available, not connected",
                        "oauth_info", provider["name"],
                        "ISyCode does not yet have an authorization flow for this provider."))
        elif snapshot.state != "ready":
            entries.append(self._entry(
                f"OAuth discovery · {snapshot.state.replace('_', ' ')}",
                "info", "", snapshot.detail or "No additional provider auth metadata is available."))
        self._menu_stack = []
        self._render_menu("providers", "Select provider", entries)

    def _open_xai_auth_methods(self) -> None:
        from isycode.grok_session import status
        note = {"signed-in": "Grok is signed in on this machine",
                "expired": "Grok sign-in expired",
                "missing": "No Grok sign-in yet"}.get(status(), "No Grok sign-in yet")
        self._render_menu("xai_auth", "xAI · use Grok in ISyCode", [
            self._entry("API key · console.x.ai", "xai_api_key", "",
                        "Saved in the OS keyring. Chat goes to api.x.ai."),
            self._entry(f"Use Grok sign-in · {note}", "xai_session", "",
                        "Uses the grok CLI sign-in already on this machine. Chat goes to cli-chat-proxy.grok.com."),
            self._entry("Sign in with device code", "xai_device"),
            self._entry("Sign in with browser", "xai_browser"),
            self._entry("The sign-in stays in the grok CLI. ISyCode does not copy the token into the project.", "info"),
        ])

    async def _allow_grok_session_host(self) -> bool:
        from isycode.grok_session import SESSION_HOST
        authority = WorkspaceAuthority(self._workspace_root)
        grant = authority.effective_policy().get("grants", {}).get("provider.request", {})
        if displayed_on("provider.request", grant, SESSION_HOST in grant.get("network_hosts", [])):
            return True
        if not await self._await_screen(TailscaleConfirmScreen(
                "Allow Grok sign-in chat?",
                "ISyCode may send this workspace's chat to cli-chat-proxy.grok.com using the grok "
                "sign-in on this machine. The token stays in the grok CLI. File permissions stay separate.",
                "Allow")):
            return False
        hosts = set(grant.get("network_hosts", [])) | {SESSION_HOST}
        authority.set_grant("provider.request", enabled=True, network_hosts=sorted(hosts))
        return True

    async def _use_grok_sign_in(self) -> None:
        from isycode.grok_session import SESSION_MODEL, set_xai_auth_mode, status
        if status() != "signed-in":
            self._append("  No live Grok sign-in. Use device code or browser first.", YELLOW)
            return
        if not await self._allow_grok_session_host():
            self._append("  Grok sign-in not selected.", MUTED)
            return
        set_xai_auth_mode("session")
        self._select_provider("xai", SESSION_MODEL)

    async def _connect_xai_login(self, method: str) -> None:
        from isycode.grok_session import SESSION_MODEL, run_login, set_xai_auth_mode, status
        if not await self._await_screen(TailscaleConfirmScreen(
                "Sign in to Grok for ISyCode?",
                "Runs the official grok login. The sign-in stays in the grok CLI. "
                "After it finishes, ISyCode can send chat with that sign-in. "
                "The token is not copied into this project or the chat.",
                "Sign in")):
            return
        self._append("  Starting grok login.", MUTED)
        try:
            code = await run_login(method, lambda line: self._append(f"  {line}", CYAN))
        except (OSError, ValueError) as exc:
            self._append(f"  Grok login did not start ({type(exc).__name__}).", YELLOW)
            return
        if code != 0 or status() != "signed-in":
            self._append("  Grok sign-in did not finish. The API key path is unchanged.", YELLOW)
            return
        if not await self._allow_grok_session_host():
            self._append("  Signed in with grok, but ISyCode was not allowed to use it.", YELLOW)
            return
        set_xai_auth_mode("session")
        self._select_provider("xai", SESSION_MODEL)

    def _open_auth_methods(self) -> None:
        self._render_menu('provider_auth_methods', 'OpenAI · choose connection method', [
            self._entry('Manually enter API key · separate API quota', 'auth_api_key'),
            self._entry('ChatGPT Pro/Plus · browser', 'auth_browser'),
            self._entry('ChatGPT Pro/Plus · headless/device code', 'auth_device'),
            self._entry('Use saved ChatGPT sign-in · checked on request', 'auth_saved'),
            self._entry('Disconnect ChatGPT account…', 'auth_logout'),
            self._entry('Subscription needs official Codex CLI and an unlocked OS keyring. Plan limits apply.', 'info'),
        ])

    async def _connect_chatgpt(self, method: str, *, logout: bool = False) -> None:
        from isycode.provider_auth import ProviderAuthOwner, AUTH_HOSTS
        from isycode.provider_auth_screens import SubscriptionLoginScreen
        owner = None
        tasks = []
        try:
            authority = WorkspaceAuthority(self._workspace_root)
            owner = ProviderAuthOwner(self._workspace_root, authority, self._action_approvals)
            request = owner.request('logout' if logout else 'login', method)
            identity = request.parameters['connector']
            if not await self._await_screen(TailscaleConfirmScreen(
                    'Disconnect ChatGPT?' if logout else 'Connect ChatGPT subscription?',
                    f"Runs official Codex app-server at {identity['executable']}. "
                    f"Account storage: {identity['home']} in the OS keyring. "
                    "Contacts auth.openai.com and chatgpt.com. Connecting explicitly grants this connector "
                    "and subscription requests in this workspace; file permissions stay separate. "
                    "ChatGPT plan limits apply; API-key billing remains separate. Never share login codes.",
                    'Disconnect' if logout else 'Connect ChatGPT')):
                return
            authority.set_grant('provider.authenticate', enabled=True, targets=['chatgpt'],
                                executables=[owner.executable], network_hosts=list(AUTH_HOSTS))
            if not logout:
                grant = authority.effective_policy().get('grants', {}).get('provider.request', {})
                hosts = sorted(set(grant.get('network_hosts', ())) | set(AUTH_HOSTS))
                authority.set_grant('provider.request', enabled=True, network_hosts=hosts)
            outcome, challenge = await owner.begin(request, self._action_approvals.issue(request))
            if outcome.decision != 'ALLOW':
                self._append(f"  ChatGPT sign-in blocked · {outcome.reason[:160]}", YELLOW)
                return
            if logout:
                self._append('  ChatGPT account disconnected. API keys are unchanged.', GREEN)
                return
            screen = SubscriptionLoginScreen(challenge)
            visible = asyncio.create_task(self._await_screen(screen)); tasks.append(visible)
            await screen.ready.wait()
            finished = asyncio.create_task(owner.finish()); tasks.append(finished)
            done, _ = await asyncio.wait({visible, finished}, return_when=asyncio.FIRST_COMPLETED)
            if finished not in done:
                self._append('  ChatGPT sign-in cancelled.', MUTED)
                return
            outcome, account = await finished
            if screen.is_mounted:
                screen.dismiss(None)
            await visible
            if outcome.decision == 'ALLOW' and account:
                self._append(f"  ChatGPT sign-in verified · plan {account['plan']} · subscription limits apply", GREEN)
                self._select_provider('chatgpt', 'auto')
            else:
                self._append(f"  ChatGPT sign-in not completed · {outcome.reason[:160]}", YELLOW)
        except (OSError, ValueError, ProviderError, WorkspaceAuthorityError) as exc:
            self._append(f"  ChatGPT connection unavailable ({type(exc).__name__}). Install official Codex CLI, unlock the OS keyring and check Authority grants.", YELLOW)
        finally:
            for task in tasks:
                if not task.done(): task.cancel()
            if tasks: await asyncio.gather(*tasks, return_exceptions=True)
            if owner is not None: await owner.cancel()

    def _open_credentials_menu(self) -> None:
        selected = selected_provider_name()
        entries = []
        if selected in PRESETS:
            entries.append(self._entry(
                f"Add a key for {self._credential_label(selected)} · asks first",
                "credential_add", selected,
                "Saved in your OS keyring for your user; never in the project or logs."))
        entries.append(self._entry("Add an ISyCo Gateway key · asks first", "credential_add",
                                   GATEWAY_SERVICE))
        try:
            credentials = CredentialVault().list_metadata()
        except Exception:
            credentials = []
            entries.append(self._entry(
                "Credential vault unavailable", "info", "",
                "Check the user-private state directory and permissions."))
        try:
            grants = WorkspaceAuthority(self._workspace_root).effective_policy().get("grants", {})
        except (WorkspaceAuthorityError, OSError, ValueError):
            grants = {}
        use_grant = grants.get("credentials.use", {})
        for service in sorted({item["service"] for item in credentials if not item["revoked"]}):
            if not displayed_on("credentials.use", use_grant,
                                service in use_grant.get("targets", [])):
                entries.append(self._entry(
                    f"Allow using the saved {self._credential_label(service)} key here · asks first",
                    "credential_use_grant", service,
                    "Each use is decided and recorded in this workspace's action journal."))
        for item in credentials:
            if item["revoked"]:
                entries.append(self._entry(
                    f"{item['name']}  ·  {item['service']}  ·  removed",
                    "credential_info", item["id"], f"Purpose: {item['purpose']}"))
            else:
                entries.append(self._entry(
                    f"{item['name']}  ·  {item['service']}  ·  saved · value hidden · select to remove",
                    "credential_revoke", item["id"], f"Purpose: {item['purpose']}"))
        self._render_menu("named_credentials", "Settings · API keys", entries)

    def _model_picker_result(self, entry: dict | None) -> None:
        if entry is not None:
            self._select_menu_entry(entry)

    def _step_reasoning(self, direction: int) -> None:
        from isycode.reasoning_options import reasoning_levels, effective_reasoning, select_reasoning
        name = selected_provider_name()
        model = resolved_chat_model(name)
        order = {"none": 0, "off": 0, "minimal": 1, "on": 1, "low": 2, "medium": 3, "high": 4, "xhigh": 5, "max": 6}
        levels = tuple(sorted(reasoning_levels(name, model), key=order.__getitem__))
        if not levels:
            self.notify("This model does not expose adjustable reasoning levels", severity="warning")
            return
        current = effective_reasoning(name, model, PRESETS.get(name, {}).get("reasoning_effort"))
        index = levels.index(current) if current in levels else (-1 if direction > 0 else len(levels))
        selected = levels[max(0, min(len(levels) - 1, index + direction))]
        select_reasoning(name, model, selected)
        self._paint_idea_box()
        self.notify("Reasoning · " + selected.capitalize() + (" · next request" if self._loop_task and not self._loop_task.done() else ""))

    def action_increase_reasoning(self) -> None:
        self._step_reasoning(1)

    def action_decrease_reasoning(self) -> None:
        self._step_reasoning(-1)

    def _open_reasoning_menu(self, name: str | None = None, model: str | None = None) -> None:
        from isycode.reasoning_options import reasoning_levels
        name = name or selected_provider_name()
        model = model or resolved_chat_model(name)
        levels = reasoning_levels(name, model)
        detail = ("Use the provider's default reasoning behavior." if levels else
                  "This provider/model does not publish supported levels in the loaded catalog. Keep its default.")
        entries = [self._entry("Default · provider decides", "reasoning_select", f"{name}|{model}|default", detail)]
        descriptions = {"off": "Disable thinking for this model.", "on": "Enable thinking for this model.",
                        "none": "No reasoning effort. Supported by this chat/tool transport.",
                        "low": "Lower reasoning effort.", "medium": "Medium reasoning effort.",
                        "high": "Higher reasoning effort.", "xhigh": "Extra high reasoning effort.",
                        "max": "Maximum reasoning effort.", "minimal": "Minimal reasoning effort."}
        entries.extend(self._entry(level.capitalize(), "reasoning_select", f"{name}|{model}|{level}",
                                   descriptions[level]) for level in levels)
        from isycode.model_presentation import model_display_name
        self._render_menu("reasoning", "Reasoning · " + model_display_name(model), entries)

    async def _load_account_models(self, name: str | None = None) -> None:
        """Opening Models requests the active catalog through its existing owner."""
        name = name or selected_provider_name()
        try:
            provider = Provider(
                name=name, model=resolved_chat_model(name),
                api_key=load_provider_key(name) or None)
            if not provider.configured():
                rows = [self._entry(
                    f"Configure {provider.key_env} before listing account models.", "info")]
            else:
                owner = ProviderNetworkOwner(
                    self._workspace_root, WorkspaceAuthority(self._workspace_root))
                models, result = await owner.execute(
                    provider, {"operation": "models.list", "provider": name,
                              "model": provider.model},
                    lambda: asyncio.to_thread(provider.models))
                if result.decision != "ALLOW" or not isinstance(models, list):
                    rows = [self._entry(
                        f"Provider model request {result.decision.lower()}.", "info", "",
                        result.reason or "Grant this provider host in Settings → Authority & Security.")]
                elif not models:
                    rows = [self._entry("The provider returned an empty model catalog.", "info")]
                else:
                    rows = []
                    for label, model_id in featured_models(models):
                        if model_id:
                            rows.append(self._entry(
                                f"★ {label} · {model_id}"
                                f"{'  ◂ current' if model_id == provider.model else ''}",
                                "model", f"{name}|{model_id}",
                                f"Featured model, found in this account's {provider.label} catalog."))
                        else:
                            rows.append(self._entry(
                                f"★ {label} · not in this account's catalog", "info", "",
                                f"{provider.label} did not list a model matching {label}; it may "
                                "not be offered here yet."))
                    rows += [self._entry(
                        f"{model_id}{'  ◂ current' if model_id == provider.model else ''}",
                        "model", f"{name}|{model_id}") for model_id in models]
        except ProviderError as error:
            rows = [self._entry(self._provider_failure(error, "Model catalog"), "info")]
        except ConfigurationError:
            rows = [self._entry("Provider credential configuration could not be loaded.", "info")]
        except Exception as error:
            rows = [self._entry(
                f"Model catalog unavailable ({type(error).__name__}); current selection is unchanged.",
                "info")]
        if models_available := [row for row in rows if row["kind"] == "model"]:
            catalogs = getattr(self, "_account_model_catalogs", {})
            catalogs[name] = models_available
            self._account_model_catalogs = catalogs
        self._account_models_loading = False
        self._account_model_status = rows[0]["label"] if not models_available else "Account catalog loaded · choose a concrete model"
        if self._menu_mode == "model_account" or (self._menu_mode == "branch" and self._menu_title == "Models"):
            self._render_menu("branch", "Models", self._branch_entries("models"))

    def _role_button_label(self) -> str:
        if not self._active_role:
            return "Role"
        name = self._active_role["name"]
        return f"Role: {name[:12]}"

    def _select_provider(self, name: str, model: str | None = None) -> None:
        current = selected_provider_name()
        try:
            explicit = model.strip() if isinstance(model, str) else ""
            target_model = explicit or resolved_chat_model(name)
            provider = Provider(
                name=name, model=target_model,
                api_key=load_provider_key(name) or None)
        except (ProviderError, ConfigurationError):
            self._set_activity(f"{name} configuration unavailable", RED)
            self._close_menu()
            return
        os.environ["ISYCODE_PROVIDER"] = name
        os.environ["ISYCODE_MODEL"] = provider.model
        try:
            save_provider_selection(name, provider.model)
        except (OSError, ValueError):
            self._append("  Provider is selected for this run; private preference could not be saved.", YELLOW)
        # Keep the optional legacy planner provider separate when the native
        # ISyCode-only preset is not supported by that adapter.
        if isymotron_provider_available(name):
            os.environ["ISYMOTRON_PROVIDER"] = name
            os.environ["ISYMOTRON_MODEL"] = provider.model
        elif name in {"groq", "openrouter"}:
            self._append(
                "  This provider is configured for ISyCode chat; the optional "
                "IsyMotron planner keeps its own provider until its adapter supports it.",
                MUTED)
        if current != name:
            self._clear_pending_plan()
        self._paint_idea_box()
        if provider.configured():
            self._append("  Selected for this session · " + self._model_display_label(name, provider.model), GREEN)
            self._close_menu()
            return
        if saved_secret_exists(name):
            self._append(
                f"  A saved {provider.label} key exists, but this workspace does not allow using it · "
                "Settings → API keys.", YELLOW)
            self._close_menu()
            return
        self._append(f"  {provider.label} needs an API key · paste it below to save it.", YELLOW)
        self._open_key_entry(name)

    @staticmethod
    def _credential_label(service: str) -> str:
        if service == GATEWAY_SERVICE:
            return "ISyCo Gateway"
        return str(PRESETS.get(service, {}).get("label", service))

    def _open_key_entry(self, service: str) -> None:
        """Show the masked key field; nothing is read or stored until Save."""
        self._provider_key_target = service
        self.query_one("#action-menu", Vertical).display = True
        self.query_one("#action-list", OptionList).display = False
        self.query_one("#action-detail", Static).display = False
        self.query_one("#action-search", Input).display = False
        self.query_one("#key-entry-label", Static).update(
            f"API key for {self._credential_label(service)} · saved in your OS keyring for your "
            "user, never in this project or its logs. Saving asks you to confirm.")
        self.query_one("#key-entry", Vertical).display = True
        key_input = self.query_one("#provider-key-input", Input)
        key_input.value = ""
        key_input.focus()

    def _save_provider_key(self) -> None:
        key_input = self.query_one("#provider-key-input", Input)
        secret, key_input.value = key_input.value, ""
        service, self._provider_key_target = self._provider_key_target, ""
        self._close_menu()
        if not service or not secret.strip():
            self._append("  No API key was entered; nothing was saved.", MUTED)
            return
        self.run_worker(self._save_key_flow(service, secret), exclusive=True, group="credentials")

    async def _ensure_credential_grant(self, owner: CredentialOwner, service: str) -> bool:
        """Per-service grant for saving and removing keys; asked once, then remembered."""
        grants = owner.authority.effective_policy().get("grants", {})
        actions = ("credentials.add", "credentials.use", "credentials.revoke")
        if all(displayed_on(action, grants.get(action, {}),
                            service in grants.get(action, {}).get("targets", []))
               for action in actions):
            return True
        label = self._credential_label(service)
        if not await self._await_screen(TailscaleConfirmScreen(
                f"Allow managing {label} API keys?",
                f"ISyCode may save, use and remove {label} API keys in your operating-system "
                "keyring. Keys are stored for your user (every workspace), never in the project, "
                "the action journal or chat history. Each use is recorded in this workspace's "
                "journal; each save and each removal still asks you first.",
                "Allow")):
            return False
        for action in actions:
            targets = set(grants.get(action, {}).get("targets", [])) | {service}
            owner.authority.set_grant(action, enabled=True, targets=sorted(targets))
        return True

    async def _save_key_flow(self, service: str, secret: str) -> None:
        label = self._credential_label(service)
        try:
            owner = CredentialOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root),
                                    self._action_approvals)
        except (CredentialVaultError, WorkspaceAuthorityError, OSError, ValueError):
            env = PRESETS.get(service, {}).get("key_env", "the provider's API key variable")
            self._append(f"  No secure OS keyring is available here; nothing was saved. "
                         f"Set {env} in your environment instead.", YELLOW)
            return
        try:
            if not await self._ensure_credential_grant(owner, service):
                self._append("  API key not saved; permission was not granted.", MUTED)
                return
            request = owner.add_request(
                service, f"{label} key",
                "ISyCo Gateway access" if service == GATEWAY_SERVICE else "ISyCode chat")
        except (WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append(f"  API key not saved ({type(exc).__name__}).", RED)
            return
        if not await self._await_screen(TailscaleConfirmScreen(
                f"Save the {label} API key?",
                f"The key you pasted will be saved in your OS keyring for {label}. The newest saved "
                "key for a service is the one ISyCode uses.", "Save key")):
            self._append("  API key not saved; the pasted value was discarded.", MUTED)
            return
        approval = self._action_approvals.issue(request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.add, request, secret, approval)
        if outcome.decision != "ALLOW":
            self._append(f"  API key not saved · {outcome.reason[:180]}", YELLOW)
            return
        self._append(f"  {label} API key saved · receipt {outcome.receipt.receipt_id}", GREEN)
        if service in PRESETS:
            self._select_provider(service)

    async def _grant_key_use(self, service: str) -> None:
        try:
            owner = CredentialOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root),
                                    self._action_approvals)
            granted = await self._ensure_credential_grant(owner, service)
        except (CredentialVaultError, WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append(f"  Permission not changed ({type(exc).__name__}).", YELLOW)
            return
        label = self._credential_label(service)
        self._append(f"  The saved {label} key can be used in this workspace." if granted
                     else "  Permission not granted; the saved key stays unused here.",
                     GREEN if granted else MUTED)

    async def _revoke_key_flow(self, key_id: str) -> None:
        try:
            owner = CredentialOwner(self._workspace_root, WorkspaceAuthority(self._workspace_root),
                                    self._action_approvals)
            request = owner.revoke_request(key_id)
            service = request.parameters["service"]
            if not await self._ensure_credential_grant(owner, service):
                self._append("  API key not removed; permission was not granted.", MUTED)
                return
        except (CredentialVaultError, WorkspaceAuthorityError, OSError, ValueError) as exc:
            self._append(f"  API key cannot be removed ({type(exc).__name__}).", YELLOW)
            return
        label = self._credential_label(service)
        if not await self._await_screen(TailscaleConfirmScreen(
                f"Remove this {label} API key?",
                "The key is deleted from your OS keyring. ISyCode then uses an older saved key "
                "or an environment variable for this service, if any.", "Remove key")):
            self._append("  API key kept.", MUTED)
            return
        approval = self._action_approvals.issue(request, ttl_seconds=60)
        outcome = await asyncio.to_thread(owner.revoke, request, approval)
        self._append(f"  {label} API key removed." if outcome.decision == "ALLOW"
                     else f"  API key not removed · {outcome.reason[:180]}",
                     GREEN if outcome.decision == "ALLOW" else YELLOW)

    @staticmethod
    def _provider_failure(error: ProviderError, operation: str) -> str:
        """Translate provider failures without rendering URLs or response bodies."""
        from isycode.provider_errors import classify_provider_error
        detail = classify_provider_error(error)
        suffix = f" · HTTP {detail['http_status']}" if detail["http_status"] else ""
        if detail["provider_code"]:
            suffix += " · " + detail["provider_code"]
        if detail["retry_after_s"] is not None:
            suffix += f" · retry after {detail['retry_after_s']:g}s"
        return f"{operation} failed · {detail['error_kind']}: {detail['provider_hint']}{suffix}."

    @staticmethod
    def _model_display_label(name: str, model: str) -> str:
        from isycode.model_presentation import model_display_name
        from isycode.reasoning_options import reasoning_label
        preset = PRESETS.get(name, {})
        effort = reasoning_label(name, model, preset.get("reasoning_effort"))
        return f"{model_display_name(model)} / {effort.capitalize()} · {preset.get('label', name)}"

    async def _check_model(self) -> None:
        """Eager model check: is the configured provider ready?"""
        try:
            provider_name = selected_provider_name()
            provider = Provider(
                name=provider_name,
                model=resolved_chat_model(provider_name),
                api_key=load_provider_key(provider_name) or None)
            ready = self._model_display_label(provider.name, provider.model)
            if provider.configured():
                self._model_line = ready + "  ·  Ready"
                self._model_line_style = GREEN
            else:
                self._model_line = f"{provider.label} needs {provider.key_env}"
                self._model_line_style = YELLOW
            self._paint_idle()
            self._paint_idea_box()
            if not self._idle_mounted():
                self._append("  Model: " + self._model_line, self._model_line_style)
        except ConfigurationError as e:
            self._append(f"  Model: {e}", YELLOW)
        except Exception as e:
            self._append(f"  Model: configuration error ({type(e).__name__}).", RED)

    def _menu_provider_unwired(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._blocked_notice(
            "No transport",
            f"{value} is on the list. ISyCode has no transport for it yet, so nothing was contacted.")
        return

    def _menu_provider(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        if value in {"openai", "chatgpt"}:
            self._open_auth_methods()
            return
        if value == "xai":
            self._open_xai_auth_methods()
            return
        self._select_provider(value)
        return

    def _menu_xai_api_key(self, entry: dict[str, str | bool]) -> None:
        from isycode.grok_session import set_xai_auth_mode
        set_xai_auth_mode("api_key")
        self._select_provider("xai")
        return

    def _menu_xai_session(self, entry: dict[str, str | bool]) -> None:
        self._close_menu()
        self.run_worker(self._use_grok_sign_in(), group="provider-login", exclusive=True)
        return

    def _menu_xai_device(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._close_menu()
        self.run_worker(self._connect_xai_login("device" if kind == "xai_device" else "browser"),
                        group="provider-login", exclusive=True)
        return

    def _menu_auth_api_key(self, entry: dict[str, str | bool]) -> None:
        self._select_provider("openai")
        return

    def _menu_auth_browser(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._close_menu()
        self.run_worker(self._connect_chatgpt("browser" if kind == "auth_browser" else "device", logout=kind == "auth_logout"), group="provider-login", exclusive=True)
        return

    def _menu_auth_saved(self, entry: dict[str, str | bool]) -> None:
        self._select_provider("chatgpt")
        return

    def _menu_providers_open(self, entry: dict[str, str | bool]) -> None:
        self._open_provider_menu()
        return

    def _menu_roles_open(self, entry: dict[str, str | bool]) -> None:
        self._open_role_menu()
        return

    def _menu_sounds_toggle(self, entry: dict[str, str | bool]) -> None:
        enabled = not self._notification_sounds
        try:
            UserDefaultsStore().update(notification_sounds=enabled)
        except (OSError, ValueError):
            self.notify("Sound preference could not be saved", severity="warning")
            return
        self._notification_sounds = enabled
        if enabled:
            self._play_notification_sound("question")
        self._open_settings_menu()
        return

    def _menu_contrast_toggle(self, entry: dict[str, str | bool]) -> None:
        enabled = not self._high_contrast
        try:
            UserDefaultsStore().update(high_contrast=enabled)
        except (OSError, ValueError):
            self.notify("High contrast preference could not be saved", severity="warning")
            return
        self._high_contrast = enabled
        self._apply_high_contrast(enabled)
        self._open_settings_menu()
        return

    def _menu_marquee_toggle(self, entry: dict[str, str | bool]) -> None:
        enabled = not self._compact_marquee_default
        try:
            UserDefaultsStore().update(compact_marquee=enabled)
        except (OSError, ValueError):
            self._set_activity("Compact text scroll preference could not be saved", YELLOW)
            return
        self._compact_marquee_default = enabled
        for box in self.query(ExpandableBox):
            if box._marquee_enabled != enabled:
                box.toggle_marquee()
        self._open_settings_menu()
        return

    def _menu_reasoning_open(self, entry: dict[str, str | bool]) -> None:
        self._open_reasoning_menu()
        return

    def _menu_reasoning_select(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        from isycode.reasoning_options import select_reasoning
        name, model, level = value.split("|", 2)
        select_reasoning(name, model, level)
        self._paint_idea_box()
        self._close_menu()
        self.run_worker(self._check_model(), exclusive=False)
        return

    def _menu_model(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        provider_name, model_name = value.split("|", 1)
        self._select_provider(provider_name, model_name)
        if not self.query_one("#key-entry", Vertical).display:
            self._open_reasoning_menu(provider_name, model_name)
        return

    def _menu_model_list(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("model_account", "Models · account catalog", [
            self._entry("Loading models from the selected provider…", "info")])
        self.run_worker(self._load_account_models(value), exclusive=True, group="provider-models")
        return

    def _menu_role_agent(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        role = next((item for item in ISYCODE_AGENTS + ISYCODE_SUBAGENTS
                     if item["name"] == value), {})
        self._active_role = {
            "name": value,
            "kind": self._menu_mode.split(":", 1)[-1],
            "description": entry.get("detail", ""),
            "engine": role.get("engine", "ISyCode selected provider and model"),
        }
        self.query_one("#role-button", Button).label = self._role_button_label()
        self._set_activity(
            f"Role selected · {value} · {self._active_role['engine']}", GREEN)
        self._close_menu()
        return

    def _menu_role_motor(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        role = next((item for item in ISYCO_MOTORS if item["name"] == value), {})
        self._active_role = {
            "name": value,
            "kind": "ISyCo motor",
            "description": entry.get("detail", ""),
            "engine": role.get("engine", ""),
        }
        self.query_one("#role-button", Button).label = self._role_button_label()
        self._set_activity(
            f"ISyCode role loaded · {value}; role guidance does not grant permissions", GREEN)
        self._append(f"  {value} role motor loaded into the ISyCode role context.", GREEN)
        self._append(f"  Workflow: {role.get('engine', '')}", CYAN)
        if role.get("owns"):
            scopes = [scope.removeprefix("isycode.").replace(".", " ").replace("_", " ")
                      for scope in role["owns"]]
            self._append("  Scope: " + ", ".join(scopes), MUTED)
        if role.get("rule"):
            self._append("  Guardrail: " + role["rule"], YELLOW)
        if role.get("verdicts"):
            self._append("  Verdicts: " + ", ".join(role["verdicts"]), MUTED)
        self._append("  CLI operations:", CYAN)
        for command in role.get("commands", []):
            self._append(f"    {command}", MUTED)
        self._append(
            "  The workflow is loaded; no CLI operation has run from this chat.", YELLOW)
        self._close_menu()
        return

    def _menu_shortcuts(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        shortcuts = [(f"{item.key.upper():<14} {item.description}", "info")
                     for item in APP_SHORTCUTS]
        shortcuts.extend([
            ("ENTER          Send message / activate highlighted item", "info"),
            ("SHIFT+ENTER    Insert a newline in the composer", "info"),
            ("ESCAPE         Close popup / cancel current operation", "info"),
            ("Session list   Type to search; arrows select; Enter resumes", "info"),
        ])
        rows = [self._entry(label, kind) for label, kind in shortcuts]
        self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._render_menu("shortcuts", "Commands & shortcuts", rows)
        return

    def _menu_named_credentials(self, entry: dict[str, str | bool]) -> None:
        self._menu_stack.append((self._menu_mode, self._menu_title, self._menu_entries))
        self._open_credentials_menu()
        return

    def _menu_credential_add(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._open_key_entry(value)
        return

    def _menu_credential_use_grant(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._close_menu()
        self.run_worker(self._grant_key_use(value), exclusive=True, group="credentials")
        return

    def _menu_credential_revoke(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._close_menu()
        self.run_worker(self._revoke_key_flow(value), exclusive=True, group="credentials")
        return

    def _menu_credential_info(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        item = next((record for record in CredentialVault().list_metadata()
                     if record["id"] == value), None)
        if item:
            state = "revoked" if item["revoked"] else "active"
            self._append(
                f"  {item['name']} · {item['service']} · {state}. API key value remains hidden.",
                MUTED)
            self._append(f"  Purpose: {item['purpose']}", MUTED)
        return

    def _menu_clear_role(self, entry: dict[str, str | bool]) -> None:
        self._active_role = None
        self.query_one("#role-button", Button).label = "Role"
        self._set_activity("Role guidance cleared", MUTED)
        self._close_menu()
        return

    def _menu_oauth_info(self, entry: dict[str, str | bool]) -> None:
        kind, value = entry["kind"], entry["value"]
        self._blocked_notice(
            "No authorization flow",
            f"{value}: {entry.get('detail', '')}\n"
            "ISyCode does not yet have an authorization flow for this provider; "
            "no credential was stored or used.")
        self._close_menu()
        return

    def _menu_openisy_provider(self, entry: dict[str, str | bool]) -> None:
        self._blocked_notice(
            "Account not connected",
            f"{entry['label']}\n"
            "This account is discovered but is not connected to ISyCode inference. "
            "Use ISyCode credential settings when an API key is supported.")
        self._close_menu()
        return
