# Contratos TYPE_CHECKING de mixins — reconciliación (F-05a)

Generado: 2026-10-24  |  Rama: `origin/main` (fab2d1a)  |  Worktree: `/tmp/opencode/isycode-refactor` (c1a41ce)
Owner: librarian (`documentation.reconciliation`, `documentation.provenance`)
Estado: **implementado y verificado** (PR #99 / F-05a) — 10 de 10 mixins con guard y Protocolo explícito.

## Contexto

Los mixins del TUI (`TUIApp`) colaboran a través de la superficie de la app. `tui_protocols.py` define los
Protocolos explícitos (contratos cruzados entre mixins) para que mypy (M9 strict, futuro) y los tests
(M8, `test_tui_protocols.py`) puedan afirmar conformidad. Los imports de `TUIApp` dentro de los mixins van
detrás de `if TYPE_CHECKING:` para evitar import circular.

## Estado por mixin

| Mixin | Archivo:línea | Protocolo en `tui_protocols.py` | `if TYPE_CHECKING: from isycode.tui import TUIApp` |
|---|---|---|---|
| `SessionMixin` | `tui_app_sessions.py:182` | ✅ `SessionProvider` | ✅ |
| `ChatMixin` | `tui_app_chat.py:96` | ✅ `ChatController` | ✅ |
| `WorkspaceMixin` | `tui_app_workspace.py:39` | ✅ `WorkspaceController` | ✅ |
| `MenuMixin` | `tui_app_menu.py:672` | ✅ `MenuController` | ✅ |
| `RailMixin` | `tui_app_rail.py:84` | ✅ `RailController` | ✅ |
| `GusMixin` | `tui_app_gus.py:19` | ✅ `GusController` | ✅ |
| `AuthorityMixin` | `tui_app_authority.py:46` | ✅ `AuthorityController` | ✅ |
| `ToolMixin` | `tui_app_tools.py:81` | ✅ `ToolController` | ✅ |
| `ProviderMixin` | `tui_app_providers.py:80` | ✅ `ProviderController` | ✅ |
| `RemoteMixin` | `tui_app_remote.py:55` | ✅ `RemoteController` | ✅ |

**Resumen:** 10 de 10 mixins tienen Protocolo explícito y guard `TYPE_CHECKING`. Verificado con `pytest tests/test_tui_protocols.py`.

## Contratos existentes (`tui_protocols.py`)

- `SessionProvider` — implementado por `SessionMixin`: `_active_lane`, `_lane_on_screen`, `_ensure_lane_session`,
  `_sessions_enabled`, `_persist_chat_message`, `_return_steering_to_queue`, `_apply_idea_nudge`,
  `_mark_idea_nudge_due`, `_paint_idea_box`, `_paint_work_status`, `_refresh_work_list`, `_show_chat_again`,
  `_session_state`, `_session_is_diverged`, `_active_chat_session_id`.
- `ChatController` — implementado por `ChatMixin`: `_run_chat`, `_mount_thought`.
- `WorkspaceController` — implementado por `WorkspaceMixin`: `_workspace_request`, `_workspace_read_owner`,
  `_workspace_chat_tools_enabled`, `_workspace_write_tool_enabled`, `_command_tool_enabled`, `_file_action_enabled`,
  `_git_enabled`, `_session_trust_active`, `_dispatch_write_tool`, `_dispatch_file_change`, `_run_workspace_command`,
  `_git_tool`, `_confirm_and_load_external_context`.

Test: `tests/test_tui_protocols.py` verifica que cada miembro del Protocolo existe como atributo/callable en `TUIApp`.

## Recomendación (para el coder)

1. Añadir `if TYPE_CHECKING: from isycode.tui import TUIApp` a los 7 mixins que referencian la app sin guard,
   y anotar parámetros `app: "TUIApp"` donde corresponda (hoy solo `MenuMixin` lo hace).
2. Definir Protocolos para los 7 mixins sin contrato (`MenuController`, `RailController`, `GusController`,
   `AuthorityController`, `ToolController`, `ProviderController`, `RemoteController`) nombrando los métodos
   que cada mixin expone y otros mixins consumen (mirror del call graph medido, como se pide en el docstring
   de `tui_protocols.py:8`).
3. Registrar los nuevos Protocolos en `PROTOCOLS` y extender `tests/test_tui_protocols.py` con las aserciones
   de conformidad.
4. Considerar activar `strict = true` en `[tool.mypy]` una vez los guards estén completos.

## Evidencia

- `src/isycode/tui_protocols.py:1-74` — definiciones de Protocolos y `PROTOCOLS`
- `src/isycode/pyproject.toml:53-56` — configuración mypy (no strict)
- `tests/test_tui_protocols.py` — tests de conformidad de los 3 protocolos existentes
- `src/isycode/tui_app_menu.py:43-44` — único guard TYPE_CHECKING existente

*Fuente: lectura directa de disco. Estados basados en evidencia, no en memoria.*
