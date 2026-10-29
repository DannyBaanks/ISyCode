# Sonda viva de Crush — evidencia 2026-10-03

Auditoría de Crush v0.96.1 ejecutada **desde dentro de una sesión Crush real** (este
documento se escribió corriendo en Crush) más un barrido del CLI con configuración y
datos aislados. Complementa M20 de [docs/ROADMAP.md](../ROADMAP.md); no habilita
capacidades ni sustituye ISySentinel. Precedentes: M17 (Pi) y M18 (Hermes) usan este
mismo formato de sonda.

## 1. Entorno y control

- Binario: `/home/danny/.local/node-v24.21.0-linux-x64/bin/crush`, paquete npm
  `@charmland/crush`, `crush version v0.96.1`, Linux x86_64.
- Aislamiento del barrido CLI: directorio propio
  `/tmp/crush-isycode-audit-20261003-95633/` con `CRUSH_GLOBAL_CONFIG` y
  `CRUSH_GLOBAL_DATA` apuntando a carpetas vacías del mismo, `--data-dir` y `--cwd`
  propios, y `crush.json` con `disable_default_providers`,
  `disable_provider_auto_update` y `disable_metrics` en true. **La red no estaba
  sandboxeada** (declarado); el control fue no invocar nada que la use.
- Script del barrido: `probe.py` en el mismo directorio; salida cruda:
  `cli-probes.json`, SHA-256
  `e8a2b2f37e3f3b08ac2993ec9b8586508c9b2c755e0d5df254d30830e8eb577f`.
- No se ejecutaron: `crush login`, `crush logout` (mutan credenciales),
  `update-providers` con fuente remota, ni la TUI interactiva.

## 2. Probes del CLI (resultado medido)

| Probe | Resultado |
|---|---|
| `crush --version` | `crush version v0.96.1`, exit 0. |
| `crush --help` + ayuda de `dirs`, `models`, `projects`, `run`, `server`, `session`, `stats`, `logs`, `login`, `logout`, `update-providers`, `completion` y `session list/last/show/rename/delete` | Todas exit 0. `run` documenta `--model`, `--reasoning-effort`, `--session`, `--continue`, `--quiet`, `--small-model`, stdin por pipe. |
| `crush dirs` (config aislado) | Imprime solo las rutas aisladas + `/etc/crush`, exit 0. Transparencia total de dónde vive la config. |
| `crush models` con providers deshabilitados | ERROR fail-closed `default providers are disabled and there are no custom providers`, exit 1. Sin fallback silencioso. |
| `crush projects --json` | `{"projects":[]}`, exit 0. |
| `session list/last/show --json`, `stats`, `logs --tail 2` | Mismo fail-closed exit 1: requieren providers inicializados; no degradan a datos parciales. |
| `crush run --quiet "…"` (providers deshabilitados) | Fail-closed exit 1 inmediato. **No cuelga** (contraste con el `pi --offline` medido en M17). |
| `crush --not-a-real-flag` | `Unknown flag`, exit 1. |
| `crush completion bash\|fish\|zsh\|powershell` | Scripts generados: 16093 / 9601 / 7712 / 10792 bytes, exit 0. |
| `crush models gemini-3.8-flash` (config real) | 8 coincidencias `provider/model` en 8 providers distintos, exit 0. |

## 3. Superficie medida desde dentro de la sesión (runtime real)

- **LSP semántico**: `lsp_definition` resolvió `main` en `handshake.py:1768`;
  `lsp_references` devolvió 2 referencias con línea/columna; `lsp_symbols`,
  `lsp_diagnostics`, `lsp_restart` operativos. `lsp_call_hierarchy` dio timeout
  (context deadline) en este host: **NOT_DEMONSTRATED**, no se afirma.
  `lsp_replace_symbol`/`lsp_rename` existen en el catálogo (no ejercitados aquí).
- **Trabajos de fondo**: `bash` en background devuelve ID (`00C`), `job_output`
  con `wait=true` bloquea hasta completar, `job_kill` terminó `010` al instante.
- **Herramientas propias del host**: `question` (formularios estructurados
  elección/sí-no/texto), `todos`, `crush_info` (estado de providers/LSP/MCP/skills
  sin secretos), `crush_logs` (líneas con nivel y `archivo.go:línea`), `jq` embebido
  (gojq), `agentic_fetch`, `sourcegraph`, `download`, `multiedit`.
- **MCP**: 2 servers conectados (gateway ISyCo 31 tools; playwright 25), listados
  con estado desde `crush_info`.
- **Skills**: 24 registradas, carga diferida (`loaded 0/24` hasta invocar).

## 4. Contratos documentados y verificados contra la ayuda local

- **`crushrc`**: config en Bash real con verbos `provider/model/mcp/lsp/hook/
  permissions/option`, `source`, `remove/reset`, y `CRUSH_VERSION` para
  feature-detection. La propia doc lo declara **trusted code** (se ejecuta bash
  completo al cargar). `crush.json` legacy se fusiona con precedencia
  project-local > global.
- **Hooks `PreToolUse`**: matcher regex por tool, JSON en stdin + env vars, exit
  0 (envelope `decision/allow/deny`, `halt`, `reason`, `context`,
  `updated_input` shallow-merge), exit 2 = deny, exit 49 = halt de turno;
  agregación deny-wins, halt sticky, en orden de config; compatible con el
  formato de hooks de Claude Code.
- **Slots de modelo**: `large` (principal) y `small` (resúmenes/auto-summarize),
  seleccionables por sesión; `model add` con `--context-window`,
  `--default-max-tokens`, precios input/output/cache y `--reasoning-effort`.
- **Workspace compartido**: `crush server` + workspaces con clave `--cwd`,
  clientes por SSE; señales `IsBusy` y `AttachedClients` en el selector de
  sesiones; flags first-wins; teardown al desconectar el último stream.
- **update-providers**: refresco de catálogo desde URL/local/embebido
  (catwalk/hyper). **No se corrió** con fuente remota.

## 5. Qué NO se probó (y no se afirma)

TUI interactiva; llamada real a un modelo vía `crush run`; `crush server`
sirviendo; hooks ejecutándose en vivo; `stats` con datos reales de proyectos;
login/logout; auto-discovery de modelos locales (ollama/llamacpp/lmstudio/
litellm/omlx); el workspace compartido con dos clientes. Todo eso queda
**NOT_DEMONSTRATED** en esta sonda.

## 6. Contraste con ISyCode (estado del repo al 2026-10-03)

Ya existe en ISyCode (no reabrir como hueco): `ask_user` tipado y acotado
(`src/isycode/agent_questions.py`, la respuesta no es autoridad), TasksPanel
(`src/isycode/tui.py:745`), `doctor` local con `network_tested:false`, LSP real
con búsqueda de símbolos + diagnósticos post-edición (`src/isycode/lsp.py`),
ciclo de comandos con timeout/cancel/kill de grupo (`src/isycode/command_runner.py`),
headless `isycode -p --json` con exit codes, sesiones con owners/export/import/fork
(`src/isycode/session_owner.py`), MCP local con aprobaciones, skills empaquetadas
con hash, config con owner y precedencia, checkpoints/undo, uso/presupuesto
(`src/isycode/usage.py`).

Huecos medidos que alimentan M20: slot `small` ausente (el compact reusa el modelo
seleccionado, `src/isycode/tui.py:9569–9577`); sin CLI `--json` de gestión
(sesiones/modelos/stats/dirs); LSP local sin references/call-hierarchy/rename
(las ops semánticas solo existen remotas y read-only vía Gateway); sin hooks
pre-ejecución nativos; sin comando de transparencia de config; sin señales
busy/attached en el selector de sesiones.

## 7. Tabla de claims

| Claim | Estado |
|---|---|
| Crush v0.96.1 instalado y ejecutable en este host | CURRENT (probado) |
| CLI fail-closed sin providers configurados | CURRENT (probado, exit 1) |
| Aislamiento de config/datos vía env + `--data-dir` | CURRENT (probado con `dirs`) |
| `crush run` no cuelga sin providers | CURRENT (probado, contrasta con M17) |
| Call hierarchy LSP | NOT_DEMONSTRATED (timeout en este host) |
| TUI/server/login/hooks en vivo/stats reales | NOT_DEMONSTRATED (no ejecutados) |
| Evidencia cruda inmutable | `cli-probes.json` SHA-256 `e8a2b2f3…` en `/tmp/crush-isycode-audit-20261003-95633/` |

**Alcance:** inspiración de producto para M20 bajo owners/gates de ISyCode. No es
una propuesta de copiar implementación, marca ni arte de Charm/Crush.
