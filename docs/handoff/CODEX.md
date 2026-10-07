# Handoff para Codex — ISyCode Classic — 2026-10-02

Danny pidió que Codex implemente ahora lo que quedó de esta sesión. Este archivo es la orden de trabajo. Los tres documentos de al lado son la evidencia del diseño, no un milestone.

Léelos en este orden:

1. Este archivo.
2. `docs/handoff/grok-design-doc-2bbe6015.md` (diseño Multi Harness, DESIGN_ID `2bbe6015`).
3. `docs/handoff/grok-design-review-2bbe6015.md` (revisión). El issue 19 sigue `open` y **pisa** el párrafo de PR 20 del diseño.
4. `docs/handoff/grok-design-summary-2bbe6015.md`.

Repo: `/home/danny/Development/ISyCo Git/ISyCode`. HEAD publicado: `6c00fefd96094883e837e63d4745f1a1878f8b24`. En el audit, `origin/main` estaba 0 ahead / 0 behind y el CI del último push estaba en `success`. El árbol local está sucio. No hagas commit ni push salvo que Danny lo pida en este turno. No marques G0–G6 como APROBADO. No abras M6A. Este handoff no certifica ninguna puerta.

Tests: `cd "/home/danny/Development/ISyCo Git/ISyCode" && ./.venv/bin/python -m pytest ...`. Venv: CPython 3.12.3, Textual 8.2.8, versión del paquete 0.1.0. No uses `uv run` aquí sin `--no-project`. No edites el worktree `/home/danny/Development/ISyCo Git/ISyCode-pr5/`. No edites el repo hermano `/home/danny/Development/ISyCo` salvo lectura del handshake. Si commiteas, el índice es compartido: `git commit -- <paths>`, nunca un `git commit` pelado. No hagas amend de `6c00fef`, `a495361`, `c339060`, `e4b6e87`, `1fc4c27` ni `7be5afc`.

## Roadmap

Hazlo en este orden. Cada fase tiene que dejar sus tests verdes antes de la siguiente. No mezcles el idea box con el grafo.

| Fase | Qué | Listo cuando |
|---|---|---|
| 0 | Leer el árbol sucio. No revertir trabajo ajeno ni el de esta sesión. | `git diff` revisado antes de editar un archivo ya modificado. |
| A | Idea box. Spec abajo. El diseño de Multi Harness lo declara fuera de alcance. | Tests nuevos verdes y el slice AST de `update_tasks` intacto. |
| B | Multi Harness PRs 1–19, como el diseño. | Cada PR con sus tests de fixture. Sin leer el home de Danny en los tests. |
| C | PR 20, contrato del issue 19, no el párrafo viejo del diseño. | El texto importado está en `_history` y en `_active_chat_session_id`. El modelo lo vería en el siguiente turno. |
| — | Quiet chrome, web fetch, Gemini, harness `agent`, M6A, puertas APROBADO. | No los hagas. |

## Fase 0 — no rompas lo que ya está

El audit de esta sesión (WIP, antes del arreglo): 1148 passed / 2 failed / 7 skipped, 1157 collected, 92 módulos `.py`, 116 archivos de test. Los 2 fallos eran regresiones del WIP y ya se arreglaron. No se volvió a correr la suite completa. Un flake conocido: `tests/test_chat_sequence.py::test_search_history_stays_visible_during_new_output`.

Esos dos ya pasan, junto con el switch de sesiones y el snapshot de cobertura (4 passed en 4.16 s, 2026-10-02):

- `tests/test_daily_tui.py::test_draft_resume_context_and_delete_confirmation`
- `tests/test_secure_tui_surfaces.py::test_secure_tui_persists_chat_sessions_only_through_the_owner`
- `tests/test_work_list.py::test_sessions_panel_switches_here_and_blocks_during_generation`
- `tests/test_action_coverage.py::test_checked_in_snapshot_matches_live_catalog_and_owners`

`validate_gates.py` salió 0 y ninguna puerta está aprobada. `isycode doctor` salió 0, mode classic, anthropic not-installed, network not tested. Gateway en vivo y Tailscale real siguen `NOT_DEMONSTRATED`.

### Árbol sucio en el momento del handoff

Modificados:

`.github/workflows/ci.yml`, `docs/GUIA.md`, `docs/security/m15-authority-coverage.json`, `scripts/validate_gates.py`, `src/isycode/action_coverage.py`, `src/isycode/action_runtime.py`, `src/isycode/actions.py`, `src/isycode/chat_sessions.py`, `src/isycode/command_runner.py`, `src/isycode/effect_ledger.py`, `src/isycode/providers.py`, `src/isycode/session_owner.py`, `src/isycode/staging.py`, `src/isycode/subagent_screen.py`, `src/isycode/subagents.py`, `src/isycode/tui.py`, `src/isycode/workspace_write.py`, `tests/test_command_runner.py`, `tests/test_command_runner_tui.py`, `tests/test_gate_validator.py`, `tests/test_secure_tui_surfaces.py`, `tests/test_side_panel.py`, `tests/test_staging.py`, `tests/test_subagents.py`, `tests/test_visual_tui.py`, `tests/test_workspace_write.py`.

Sin trackear:

`src/isycode/agent_questions.py`, `src/isycode/bridge_presence.py`, `src/isycode/effect_fs.py`, `src/isycode/grok_session.py`, `src/isycode/village_art.py`, `src/isycode/work_list.py`, `tests/test_agent_questions.py`, `tests/test_audit_recovery.py`, `tests/test_bridge_presence.py`, `tests/test_grok_session.py`, `tests/test_village_art.py`, `tests/test_work_list.py`, y ahora `docs/handoff/`.

Varios agentes comparten este árbol. Gates, staging, command runner, workspace_write, effect ledger, CI, providers, subagents y effect_fs no son tuyos para revertir. Antes de editar un archivo ya modificado, lee el diff y conserva los hunks que no son tu fase.

### Ya hecho en esta sesión. No lo deshagas

Pueblo denso. `src/isycode/village_art.py` guarda el SVG de asciinator (168×71) como zlib/base64. Braille 2×4, tamaño nativo 84×18, se achica para caber, no se agranda. Tinta oscura `#4a4658` si luminancia &lt; 28; si no, truecolor de la muestra más brillante. Los bits se prenden también en los `#` oscuros. No leas `~/Descargas` en runtime. El figlet `ISYCODE` se queda. El carácter `╱` está prohibido. No vuelvas a las casitas `|##|` ni `~~`. Tests: `tests/test_village_art.py` y el idle board de `tests/test_visual_tui.py` (██, LSPs/MCPs/Skills, un carácter U+2800–U+28FF, sin `╱`, sin `|##|`, a 120×40 y tras resize a 80×24).

Borrar la conversación activa llama a `_clear_open_conversation()` (`tui.py`, cerca de la línea 7750). Deja `_active_chat_session_id` en `None`. No llama a `_start_new_conversation()`: eso crea otra sesión con `owner.manage("state", None, ...)`. New y `/session new` sí crean sesión. Borrar una sesión que no es la activa no limpia el chat abierto.

Sessions abre el WorkList. `_show_chat_sessions` esconde `#chat`, muestra `#work-list` y espera `_refresh_work_list`. `owner.list_conversations` vive ahí, vía `asyncio.to_thread`. Resume usa `owner.resume`. Persistir usa `owner.record` después de `_sessions_enabled()`. El test AST exige exactamente eso. No muevas `list_conversations` de vuelta a `_show_chat_sessions`. No llames a `ChatSessionStore` desde esos métodos.

`docs/GUIA.md` abre con `isycode` y `isycode cli`. `isycode` es la TUI. `isycode cli` es el navegador de acciones. `isyco` es el CLI de motores OpenISy. El bloque pegado de `isyco --help` es la salida real de ese otro binario y todavía dice `isyco cli`. No lo reescribas.

xAI dentro de ISyCode ya está en el árbol, sin commit: API key y el OAuth del CLI `grok`, nada más. No es un framework OAuth. Login en `grok_session.run_login`, no en `tui.py`. Device: `[grok, "login", "--device-auth"]`. Browser: `[grok, "login", "--oauth"]`. Sin shell. Host de sesión `https://cli-chat-proxy.grok.com/v1` (`SESSION_HOST` `cli-chat-proxy.grok.com`, `SESSION_MODEL` `grok-4.7`). Preset de API key sigue en `https://api.x.ai/v1`, modelo `grok-4`. Modo en `state_root()/preferences/xai-auth.json`, solo `{"version":1,"mode":"session"|"api_key"}`, modo 0600. `xai_auth_mode()` no crea directorios. `load_provider_key("xai")` devuelve el access token solo en modo session, y ese modo gana sobre vault/env. El token no va al env, al journal ni a los parámetros de un ActionRequest. No llames en vivo a api.x.ai ni al proxy con el token real. No imprimas tokens, refresh tokens, email ni client id. Los tests no leen el `auth.json` real. No leas `~/.grok/auth.json` desde Multi Harness.

Dashboard ya en el árbol: WorkList en la ventana. Filas workspace, título, status idle/generating/waiting. Waiting es ApprovalScreen, ContextAccessScreen o AgentQuestionScreen. BridgePresenceScreen no es waiting. Un solo chat genera a la vez. Un hijo real de `/subagent` puede ser una fila `provider · model` (`_child_title`), y `_run_subagent` la limpia en el `finally`. Cambiar de chat está bloqueado mientras genera. El reloj del usuario es `sent_at` local al enviar, no un backfill de `updated_at`. Presencia es solo lectura de `handshake.py agents`. No abras `agents.json`, `leases.json` ni `identity_tokens.json`. No imprimas IDENTITY_TOKEN ni LEASE_TOKEN. Acciones de bridge negadas: `bridge.connect`, `bridge.send`, `bridge.lease.claim`, `bridge.lease.release`, `bridge.wake`. `bridge.peek` es BLOCKED_BY_DESIGN. `_bridge_enabled` sigue en false. Si el bridge no está, la lista local de sesiones igual abre. Classic se queda dentro de la raíz de `discover_workspace_identity`. `enabled: false` gana. No cambies IsySentinel, los grants de Classic, las aprobaciones, el journal ni el sandbox, salvo el grant de host ya hecho para `cli-chat-proxy.grok.com`. No hay fallback sin sandbox. No hay `--share-net`. No hay herramienta `git_push`. `git_commit` no es quiet.

Quiet Classic salta el modal solo en mode classic, raíz que coincide, trust vigente, y para comandos si el ejecutable del sandbox existe: list/read/search/context.inject/write/restore/delete/move/command.run. Commits, secretos, credenciales, llamadas al provider, config y authority siguen preguntando.

Paleta: BG `#1a1a2e`, BG2 `#292a2e`, ACCENT `#e94560`, ACCENT2 `#9b5de5`, TEXT `#e0e0e0`, MUTED `#9aa3ad`, GREEN `#4ade80`, YELLOW `#fbbf24`, RED `#f87171`, CYAN `#22d3ee`. El foco fino es `#9aa3ad`. El wordmark del header es `ISYCODE`. No pongas el hatch diagonal. La barra de comandos sigue: `#sidebar-button`, `#sessions-button`, `#providers-button`, `#role-button`, `#context-button`, `#inject-context-button`, `#settings-button`. `on_mount` consulta `#role-button`. Quiet chrome (doblar la barra dentro de Settings) no está pedido. Alturas del composer: input 5, composer 8. Hint: `Enter send · Shift+Enter newline · / commands · Esc back`. El test de 80×24 exige que `#composer-hint` no pise `#prompt-input` ni `#command-bar`.

Rail: `#side-panel` es `dock: right; width: 38`. Se muestra solo si el ancho es ≥ 100. `#main` es la columna a la izquierda. Iluminación del rail: punto de foreground, sin relleno. Inactive `○ ` MUTED; checking `··· ` bold yellow; on `● ` bold GREEN; off `● ` bold RED. Tab seleccionado: clase `rail-lit`. `_authority_capability_label` pinta `● ON` / `● OFF` en bold, sin fondo. El test quiere `enabled.plain == "Read workspace files  ● ON"`.

LSP install es solo display. Botón `lsp-install-hint`, etiqueta `Install commands`. El handler empieza: `ISyCode does not download language servers. Nothing was installed.` `discover_servers()` solo ve binarios en PATH. No hay acción `lsp.install`.

Providers: filas popular/unwired de kind `provider_unwired` no setean `ISYCODE_PROVIDER`. `chatgpt` sigue doblado bajo `openai`. Título del menú: `Select provider`.

Strings de UI del producto en inglés. Locale del host: `es_ES.UTF-8`.

Si mueves líneas de `ActionRequest` en `tui.py`, regenera `docs/security/m15-authority-coverage.json` con el dump oficial, sin editarlo a mano y sin `sort_keys`:

```python
json.dumps(authority_coverage_snapshot(), ensure_ascii=False, indent=2) + "\n"
```

El test `test_checked_in_snapshot_matches_live_catalog_and_owners` compara ese archivo con el catálogo vivo. El último dump de esta sesión midió 56358 bytes y luego el archivo puede haber cambiado si otro agente tocó `tui.py`. Regenera después de tu edición y corre el test. No des por bueno el byte count.

`secure_tui_direct_api_bypasses` es AST solo de `tui.py`. Cero `create_subprocess_exec`, `Popen`, `run`, `call`, `check_call`, `check_output` en el AST de `TUIApp`. Los helpers pueden hacer subprocess con argv fijo, sin shell y con timeout. Precedente: `grok_session.run_login`, llamado con `asyncio.to_thread`.

`choose_workspace_directory` y `choose_workspace_file` en `src/isycode/file_picker.py` siguen BLOCKED_BY_DESIGN. No enrutes el picker de harness por ahí.

## Fase A — idea box

Danny lo pidió. El diseño de Multi Harness lo deja fuera a propósito. Hazlo antes del grafo. Módulo nuevo `src/isycode/idea_box.py`. Tool `update_idea_box`. No es `update_tasks`. No tiene efecto de filesystem, ni acción de Authority, ni Owner, ni journal.

UI. Un rectángulo `border: round` siempre en la esquina superior derecha de la columna de chat, también cuando `#side-panel` está oculto. `#main` es el padre: al esconder el sidebar, `#main` se ensancha y un overlay top-right sigue en la esquina de la ventana. No lo docks en la raíz de la app (taparía el sidebar) ni como `dock: right` de altura completa. Tamaño fijo y chico. No tapes el composer. Visible aunque esté vacío: título `Idea box` y una línea de espera. Borde como `.external-review` (`border: round #514d5a; background: #303136`) o salvia `#8fbc8f`. Fondo `#1e1f22` o `#242529`.

Texto. Máximo unos 320 caracteres, printable, colapsa whitespace, rechaza vacío y claves de más. Redacta con `sanitize_historical_text` (`src/isycode/tool_history.py`): `api_key=` queda `[redacted]`. Resultado de la tool: `{"status":"shown"}`. Ese JSON sí vuelve al modelo como role `tool`.

Persistencia. Campo opcional `idea_box` en el estado de sesión. Hoy `ChatSessionStore.validate_state` (`chat_sessions.py`, cerca de la línea 289) solo permite `provider`, `model`, `role`, `context_path`, `draft`, `tool_history`, `conversation_summary`, `usage`. Hay que añadir `idea_box` a ese allowlist y a `_session_state`. Al cargar, rechaza lo que no sea `str` o lo que pase de 2000 caracteres. Resume lo muestra. `_clear_open_conversation` lo limpia. No añadas otras claves. Multi Harness, en la fase C, no debe borrar esta clave ni usar el estado de sesión para el transcript.

Nudge. `IDEA_NUDGE_SECONDS = 150`. `set_interval` de Textual dispara después del primer intervalo, no en t=0. Flag `_idea_nudge_due`. Campos nuevos: `_idea_box=""`, `_idea_nudge_due=False`, `_idea_nudge_timer=None`. Armar el timer solo si `provider_supports_tools`. Parar el timer en el `finally` de `_run_chat` (hoy cerca de la línea 9185, donde ya se anula `_chat_turn_task`). Aplicar el nudge solo en el siguiente request de provider del MISMO turno, y solo si la tool está en `chat_tools`. Un mensaje system, insertado en el índice 1. Prefijo exacto: `Idea box check, not a user message.` Antes de insertar, quita el nudge anterior cuyo role sea `system` y cuyo content empiece por ese prefijo. No lo copies a `_history`. El test debe poder afirmar que `'sent_at' not in json.dumps(app._history)` y que `_history` es solo role+content. No dispares una segunda llamada al modelo para el nudge. No canceles un stream largo para inyectarlo.

Texto del nudge, en inglés, un solo system message:

> Call update_idea_box with what you are doing, what is done, and the next concrete step. Current idea box: {texto o "empty"}. If you are repeating yourself, leaving the task, or stuck, stop and say what is blocked. This check adds no tools and no authority. Do not quote this check.

Oferta de la tool. Siempre que `provider_supports_tools`, aunque no haya workspace tools. El mismo sitio donde hoy se hace `chat_tools.append(CONTEXT_ACCESS_TOOL)` y `chat_tools.append(ASK_USER_TOOL)` (`_run_chat`, cerca de 8835). Una frase en el system prompt, junto a la línea de `update_tasks` (cerca de 8910). El hijo no la recibe: `_run_subagent` arma `tools` solo con `CHAT_WORKSPACE_TOOLS` y, si hay write, EDIT/WRITE. No se la añadas. El despacho del hijo pasa por `_dispatch_chat_tool`; la tool igual no debe estar en la lista del child.

Despacho. En `_dispatch_chat_tool_impl`, el branch de `update_idea_box` va **antes** de `if name == TASK_TOOL_NAME`. El test `tests/test_agent_tasks.py::test_chat_routes_the_task_tool_without_any_owner` corta desde `if name == TASK_TOOL_NAME` hasta `action_id = TOOL_ACTIONS[name]` y exige `validate_tasks(arguments)` y que esa rebanada no contenga `Owner`. El nombre de la tool también tiene que entrar en el conjunto de nombres registrados (cerca de 8010) o cae en "unregistered". Y en el loop (cerca de 9099) un tool se niega cuando `not tools_active` salvo `request_context_access` y `ask_user`. `update_idea_box` tiene que ser la tercera excepción, porque se ofrece sin workspace tools.

`_dispatch_chat_tool` (cerca de 7976) siempre pinta `Tool duration · …`. Sáltatelo para esta tool. También sáltate la nota de tool-history (`record_tool_result` en el loop, cerca de 9086 y 9107) para esta tool. El resultado `{"status":"shown"}` sí se appende a `messages` como role `tool`.

Tests mínimos de la fase A, además de no romper los de tasks:

- vacío, claves extra, no-str y más de 2000 al importar: rechazo
- `api_key=` queda redactado
- el nudge no entra en `_history`
- resume muestra la caja; conversación nueva la limpia
- el child no tiene `update_idea_box`
- no aparece la línea Tool duration
- el slice AST de tasks sigue limpio
- cero subprocess nuevo en el AST de `tui.py`
- snapshot de cobertura regenerado si moviste `ActionRequest`

## Fase B — Multi Harness, PRs 1 a 19

El diseño manda. No reabras el censo. No añadas Gemini. No añadas `agent` (`~/.local/bin/agent` es symlink al mismo `cursor-agent`). No implementes una opción ADD: el clic no crea la feature.

Catálogo, en este orden: `crush`, `qwen`, `opencode`, `claude`, `codex`, `grok`, `hermes`, `fx`, `openclaw`, `pi`, `kimi`, `cursor`, `copilot`.

Sonda: argv `[ejecutable, "--version"]`, sin shell, timeout 3 s, las trece a la vez con `asyncio.to_thread`. Sin respuesta, esa carpeta queda cerrada aunque exista. Una sonda fallida no suma N. ISyCode no entra en N. El umbral es `N >= 4`. No es 5 y no es 13. No lo bajes a 2.

Hechos de esta máquina, 2026-10-02. No los trates como fixtures de test. Los tests usan fixtures. El home de Danny no es input de test. No metas cuerpos de transcript, URLs ni secretos en git.

| id | sonda | carpeta automática | hecho |
|---|---|---|---|
| crush | `crush` | `~/.crush` | binario ausente, carpeta existe, LOCKED |
| qwen | `qwen` | `~/.qwen` | binario ausente, carpeta existe, LOCKED |
| opencode | `opencode` | `~/.opencode` | contestó ~1.18.32. Datos también en `~/.local/share/opencode/opencode.db` y `~/.config/opencode`. Esos no son alias automáticos. Nunca leas credential, account, `auth.json`, `mcp-auth.json`. |
| claude | `claude` | `~/.claude` | contestó Claude Code 2.1.287 |
| codex | `codex` | `~/.codex` | contestó codex-cli 0.155.1 |
| grok | `grok` | `~/.grok` | contestó grok 1.0.46. Sesiones en `~/.grok/sessions/<urlencoded project>/<id>/` con `chat_history.jsonl`, `system_prompt.txt`, `updates.jsonl`. No leas `auth.json`. |
| hermes | `hermes` | `~/.hermes` | Hermes Agent v0.21.5. Skip auth, `.env`, `auth.json`, `auth.lock`, `nous_auth.json`, `install_id`. `web` solo tiene `web.backend`: unmapped. No cuenta como web_fetch. |
| fx | `fx` | `~/.fx` | 0.0.11. `credential_source` es SECRET. Skip `auth.json`, `chatgpt-auth.json` y locks. `permissions.json` es un approval; nunca copies skip-approval. |
| openclaw | `openclaw` | `~/.openclaw` | OpenClaw 2026.9.7. Skip `auth`, `gateway.auth`, y columnas sqlite con token/secret/password/credential/private_key/auth. `SOUL.md` / `IDENTITY.md` no son `project_instructions`. |
| pi | `pi` | `~/.pi` | 0.87.1. Hay otro binario en `~/.pi/agent/bin/pi`. Sonda solo el `pi` del PATH. `auth.json` SECRET. `models-store.json` es grande: model keys `NOT_DEMONSTRATED`. |
| kimi | `kimi` | `~/.kimi-code` | 2.0.2. No existe `~/.kimi`. Única excepción de nombre de carpeta. Skip `credentials/`, `oauth/`, `device_id`. `workspace-trust/` es NON_TRANSFERABLE. `services.moonshot_search` y `services.moonshot_fetch` son endpoint/secret, no web_fetch ni web_search. |
| cursor | `cursor-agent`, luego `cursor` | `~/.cursor` | `cursor-agent` contestó `2026.10.01-e373342` en `/home/danny/.local/bin/cursor-agent`. `cursor` ausente. `~/.cursor` existe y no es symlink. `display.mode` observado `zen` es layout, no `ui_theme`. `exploreSubagentModel` no se une a `default_model`. `permissions`, `approvalMode`, `sandbox`, `autoAcceptWebSearch`, `runEverythingSettingsPromptStreak` son non_transferable. Skip `statsig-cache.json` entero. `projects/` tenía un directorio y cero archivos: `prior_transcript` de Cursor queda `NOT_DEMONSTRATED`. No inventes un nombre de sesión. |
| copilot | `copilot` | `~/.copilot` | `command -v copilot` ausente. `gh extension list` vacío: `gh copilot` no es la sonda. Carpeta existe y sigue LOCKED hasta que `copilot --version` conteste. `trustedFolders` no se copia a WorkspaceTrust. El reader es fixture-only. JSONC: quita comentarios `//` y `/* */` sin evaluarlos, luego `json.loads`. |

Censo de huecos, solo raíces automáticas. Lo verificó el revisor contra la tabla de bordes:

| id | N | estado | nota |
|---|---|---|---|
| `user_skills` | 4 | ADD | Única fila ADD. Etiqueta `Missing in ISyCode`. El clic no crea un directorio de skills. Cursor no lo sube. |
| `provider_endpoint` | 4 | DO_NOT_MERGE | URL ajena no se copia ni se guarda. |
| `default_model` | 5 | ALIGNED | Sin botón de copiar: ningún borde vivo pasa `copy_requires`. `gemini` no es `google`. `openai` no es `chatgpt`. `managed:kimi-code` no es clave de PRESETS. |
| `prior_transcript` | 7 | ALIGNED | No es un write automático. Es el último PR. |
| `ui_theme` | 3 | WATCH | Claude, Pi, Kimi. Hermes `display.skin` y Grok `ui.auto_dark_theme` son otros nodos. Cursor `zen` no es el cuarto. |
| `reasoning_effort` | 3 | WATCH | Codex `model_reasoning_effort`, Hermes `agent.reasoning_effort`, FX `settings.json` `effort`. El summary de Grok y el `effort` de sesión de FX no se unen. |
| `enabled_plugins` | 3 | WATCH | Claude, Codex, OpenClaw. OpenCode `plugin[]` es `non_equivalent` y no sube N. |
| `web_fetch` | 0 | WATCH | Target `absent`. No es ADD. ISyCode no tiene la tool. |
| `web_search` | 0 | WATCH | Igual, nodo separado. `codex_connector.py` pone `web_search = "disabled"` y eso no es una tool de ISyCode. |

`CHAT_WORKSPACE_TOOLS` es solo `workspace_list`, `workspace_read`, `workspace_grep`, `workspace_search`. El chat también ofrece `request_context_access`, `ask_user`, y con workspace tools `update_tasks`, `delegate_subagent`, y edit/write. No añadas web fetch como parte del clic del grafo.

También cuadran, y no hay que "arreglarlos" subiéndolos a ADD: `folder_trust` N=3, `vim_mode` N=2, `approval_bypass` N=2, `sandbox_policy` N=2. `permission_mode` se omite porque el borde vivo es `unmapped`. `secret_skip` no es un Gap y no incrementa N.

Secretos que nunca se copian: API keys, OAuth, refresh tokens, cookies, account records, `providers.json`, installation ids, `agent_id`. Copiar config no concede authority, ni host de red, ni credencial, ni bypass de sandbox. yolo / skip-approval / dangerously-skip-permissions / sandbox / trustedFolders son NON_TRANSFERABLE y no encienden grants, Quiet Classic ni WorkspaceTrust.

El único writer de copia planeado es `save_provider_selection`, y solo cuando el provider id es exactamente una clave de PRESETS y el model id pasa `validate_state`. El botón pone `ISYCODE_PROVIDER` y `ISYCODE_MODEL` y luego llama a `save_provider_selection`. No construye `Provider`. No llama a `load_provider_key`. No escribe `state.model`. El texto de confirm dice que el chat abierto no cambia de modelo. La fila muestra `selected_*` y, si difiere, el archivo `preferences/provider.json`. En esta máquina no hay botón porque ningún borde pasa `copy_requires`.

Pantalla. Botón nuevo `Multi Harness` en la command bar, entrada en Settings, y `/harness`. Modal nuevo. No es el Sessions vivo. `#sessions-button` llama a `_show_chat_sessions`, que abre el WorkList. `ChatSessionsScreen` existe en `tui.py` y nadie en `src/` la construye. No la uses como precedente del Sessions real. El conteo de transcripts en la pantalla es `len` de `ChatSessionOwner.list_conversations`. No llames a `ChatSessionStore.list_sessions` desde `tui.py`.

Picker. Función nueva. Reutiliza `build_linux_directory_picker_command` y el `askdirectory` de Windows. No pases por `choose_workspace_directory`, `choose_workspace_file` ni `choose_sibling_workspace_folder`. Un `~/.grok` no es un sibling del workspace. Título Windows del picker de harness distinto del default `Choose sibling project folder`, para no cambiar el picker de siblings. Rechaza `/`, home, padres de home, `~/.config`, `~/.local` y `~/.local/share`. Un directorio de aplicación con nombre, debajo de esos padres, puede pasar tras confirm. `roots.json` es `{"version": 1, "roots": {harness id: absolute path}}`, modo 0600. Ids desconocidos se rechazan. Un override solo puede apretar un borde a `non_equivalent` o ignorar un id para sacarlo de N. No sigas symlinks.

Sondas y readers fuera de `tui.py`. La pantalla los llama con `asyncio.to_thread`. Cero subprocess en el AST de `tui.py`.

PRs, archivos y dependencias (el texto largo de allowlists está en el diseño; no lo acortes):

| PR | Archivos | Depende de |
|---|---|---|
| 1 Grafo y seed | `src/isycode/harness_graph.py`, `tests/test_harness_graph.py`, `tests/fixtures/harness/` | nada |
| 2 Sonda | `src/isycode/harness_probe.py`, `tests/test_harness_probe.py` | 1 |
| 3 Grok reader | `src/isycode/harness_readers/grok.py` + test + fixtures | 1, 2 |
| 4 Claude | `harness_readers/claude.py` | 1, 2 |
| 5 Codex | `harness_readers/codex.py` | 1, 2 |
| 6 OpenCode | `harness_readers/opencode.py` | 1, 2 |
| 7 Crush | `harness_readers/crush.py` | 1, 2 |
| 8 Qwen | `harness_readers/qwen.py` | 1, 2 |
| 9 Hermes | `harness_readers/hermes.py` | 1, 2 |
| 10 FX | `harness_readers/fx.py` | 1, 2 |
| 11 OpenClaw | `harness_readers/openclaw.py` | 1, 2 |
| 12 Pi | `harness_readers/pi.py` | 1, 2 |
| 13 Kimi | `harness_readers/kimi.py` | 1, 2 |
| 14 Cursor | `harness_readers/cursor.py`. Allowlist viva. Tests con fixtures, no con el home. | 1, 2 |
| 15 Copilot | `harness_readers/copilot.py`. Fixture-only. No abras `~/.copilot` hasta que el binario conteste. | 1, 2 |
| 16 Pantalla read-only | `tui.py`, `tests/test_harness_tui.py`, snapshot de cobertura si mueves ActionRequest | 1–15 |
| 17 Pick nativo | `choose_harness_folder` en `file_picker.py`, `validate_picked_root` en `harness_probe.py`, `harness_store.py`, `tui.py` | 16 |
| 18 Pantalla de huecos | sección del mismo modal | 16 |
| 19 Copia de `default_model` | guard en `harness_graph.py` + helper que llama `save_provider_selection` | 16 |

Crush y Qwen no son pick-only para siempre. Si un día `crush --version` o `qwen --version` contestan, el reader lee esa raíz automática. Hoy, sin binario, no hay raíz automática. OpenCode automático (`~/.opencode`) no devuelve settings semánticos; un root elegido a mano sí puede leer su allowlist. `~/.config/opencode` no es alias.

Decisiones que el revisor ya obligó a cerrar en el documento. No las reabras:

1. `reasoning_effort` es N=3 WATCH. Grok summary y FX session effort no se unen. `isycode_target` es el literal `absent` o un símbolo, no prosa.
2. Sessions abre WorkList. `ChatSessionsScreen` no se construye.
3. Listar sesiones desde `tui.py` pasa por el owner, no por `ChatSessionStore`.
4. Copiar el modelo setea el env y `save_provider_selection`. No construye `Provider`.
5. Crush y Qwen leen la raíz que la sonda desbloquee. No se quedan pick-only.
6. `roots.json` tiene un solo esquema: version 1 y mapa de raíces.
7. La etiqueta de borde `missing here` no se usa si nadie la produce. Sigue el vocabulario del diseño ya revisado.
8. OpenCode `plugin[]` es un solo borde, `non_equivalent` a `enabled_plugins`.
9. El umbral ya no dice "4 o 5". Es `N >= 4`.
10. Hay fila de condición para `copyable` cuando `copy_requires` falla: ALIGNED y sin botón. Ese es `default_model` en esta máquina.
11. `permission_mode` queda `unmapped`, N=0, hasta un fixture revisado. Un valor de denylist pasa a `approval_bypass` sin imprimir el string crudo.
12. El mapa de PR 3 incluye `ui.vim_mode`, `sandbox_profile` y `ui.fork_secondary_model`, no solo los cuatro que el primer borrador listaba.
13. `project_instructions` leído desde `context_path` no es "el archivo existe". Solo `AGENTS.md` se une, como file-role. Cuerpos de SOUL/IDENTITY/USER no entran al grafo.
14. Las trece sondas corren juntas. Una colgada se mata a los 3 s y no suma los timeouts en el modal. Cada línea dice `Checking {Harness}…` hasta que esa sonda vuelve.
15. Copilot JSONC tiene algoritmo de lectura. No es "abre el JSON y reza".
16. El picker de Linux no reutiliza los strings de error de context-file. `choose_harness_folder` atrapa `FilePickerUnavailable` y habla de carpeta de ese harness.
17. La pantalla no es el idea box.

El diseño no es un milestone y no marca G0–G6 APROBADO. No escribas otra nota de bypass de CI. No rerunas `astra-m0-m6-probe/`. No mandes un RESULT al bridge diciendo que el dashboard se construyó.

## Fase C — PR 20, contrato del issue 19

El párrafo de PR 20 en `grok-design-doc-2bbe6015.md` se queda corto. El revisor lo marcó `open` el 2026-10-02. Implementa **esto**, no aquella frase de "pinta y `record(..., state=None)`" sola.

Qué está mal en el párrafo viejo. Pintar la columna y llamar a `ChatSessionOwner.record` con `state=None` y sin id no mete el texto en el chat abierto. `_run_chat` manda `self._history` al modelo. `_mount_user_turn` y `_append` solo montan widgets; no appenden a `_history`. Resume reconstruye `_history` desde `session.messages` y después pinta. `record` crea un transcript nuevo cuando `session_id` es `None`, y solo appende cuando el caller pasa un id existente. El id devuelto es lo que `_persist_chat_message` guarda en `_active_chat_session_id`. Doscientas llamadas con `session_id=None` son doscientas conversaciones nuevas. Create y append usan las dos la acción `session.create`, así que "doscientos receipts de session.create" no distingue nada. `_start_new_conversation` ya tiene un id vía `manage("state", ...)`. Grabar con `None` deja ese id apuntando a la sesión vacía: el siguiente turno real persiste ahí y los mensajes importados quedan en otro archivo. `_persist_chat_message` no sirve tal cual: pasa `state=self._session_state()`, y `record` reemplaza `session.state` cuando `state` no es `None`. Si las sesiones están apagadas, "se queda en memoria" también exige appender a `_history`. El modelo no ve widgets solos. `record` puede devolver `ERROR` o `NOT_VERIFIABLE`. Parar solo en `DENY` no alcanza.

Contrato que sí implementas:

- Caps: 200 mensajes, 8000 caracteres cada uno, 200000 en total. Sanitiza al persistir. Confirma antes. Es una copia de texto, no este agente ni este proceso. No ejecutes el contenido. No escanees el disco. No corras esto si `_loop_task` está activo.
- Por cada mensaje acotado: appende `{role, content}` a `self._history`. Un role user se pinta con `_mount_user_turn`. Un role assistant se pinta como `_resume_chat_session` monta `RichMarkdown`, no con `_append`.
- Llama a `record(self._active_chat_session_id, role, content, state=None)` solo si `_sessions_enabled()` es true. Tras el primer `ALLOW`, guarda el id devuelto en `_active_chat_session_id`.
- No llames a `_persist_chat_message`. No pases `_session_state()` ni un state dict extranjero. No añadas claves nuevas al estado de sesión. La clave `idea_box` de la fase A, si ya existe, se queda; este PR no la usa y no la borra.
- Si las sesiones están apagadas: solo `_history` y los widgets.
- Para si `outcome.decision` no es `ALLOW`. Muestra `outcome.reason`. En `NOT_VERIFIABLE` el write puede haber ocurrido: conserva ese mensaje y no lo reintentes en una segunda sesión.
- La primera línea visible dice que es una copia, no el mismo proceso y no el mismo agente. Esa línea también está en `_history`. La línea `Tool or system text was not imported.` es un mensaje de display con role user y no se ejecuta.
- No leas cuerpos de request-dump de Hermes, eventos de FX, jsonl de Pi, ni `state.json` de Kimi dentro del grafo. Este PR lee texto de transcript de fixture, bajo los caps. Sqlite de OpenClaw no es fuente.
- El conteo de la pantalla del grafo sigue siendo `len` de `list_conversations`.

## Qué encontró la revisión, en corto

Needs revision. Issues 1–18 `addressed`. Ninguno es `wontfix`. Issue 19 `open`. Ningún subagente de diseño modificó el fuente de ISyCode ni hizo commit. El pueblo, el arreglo de los dos tests y la guía sí están en el árbol sucio, hechos en esta misma sesión por el agente que escribe este handoff, no por los subagentes del diseño.

Fortalezas que el revisor contrastó con este checkout y que debes conservar: catálogo de trece, sonda `--version`, secretos y bypass fuera de la copia, N ≥ 4, `web_fetch` y `web_search` separados en N=0 WATCH, listado por el owner, contrato de copia de provider, esquema de roots, y las etiquetas de borde. También contrastó `save_provider_selection`, el allowlist de ocho claves de `validate_state` (más `idea_box` solo si la fase A ya lo añadió), Quiet Classic, `discover_servers`, el snapshot `json.dumps(..., ensure_ascii=False, indent=2) + "\n"` sin `sort_keys`, y que un `bwrap` ausente no es un fallback sin sandbox.

## Verificación antes de decir que terminaste

Fase A:

```bash
cd "/home/danny/Development/ISyCo Git/ISyCode"
./.venv/bin/python -m pytest -q tests/test_agent_tasks.py tests/test_idea_box.py \
  tests/test_secure_tui_surfaces.py::test_secure_tui_persists_chat_sessions_only_through_the_owner \
  tests/test_action_coverage.py::test_checked_in_snapshot_matches_live_catalog_and_owners \
  --tb=short
```

`tests/test_idea_box.py` lo creas tú. El nombre puede variar; los asserts de arriba no.

Fase B y C: los tests de cada PR del diseño, más el AST de subprocess en `tui.py`, más el snapshot si `tui.py` movió `ActionRequest`. No declares la suite de 1157 verde si no la corriste. Si la corres y algo ajeno al WIP falla, no lo "arregles" revirtiendo archivos de otros agentes: repórtalo.

No pushees el WIP "para ver CI". El audit dijo que pushear el WIP de entonces rompía CI en las dos superficies de sesión. Esas dos ya están verdes. El resto del árbol sucio no se recertificó.
