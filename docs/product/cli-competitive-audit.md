# Auditoría comparativa de CLIs de agentes

Fecha: 2026-09-27
Alcance: capacidades visibles de Codex CLI, Claude Code, Crush, OpenCode, OpenClaw e ISyCode, con foco en qué debe completar ISyCode para servir como TUI diaria y host de ISyCode Móvil.

## Método y alcance

Se consultaron `--version`/`--help` de las instalaciones locales que exponen esos comandos y documentación oficial de cada producto. No se iniciaron sesiones, no se leyeron archivos de credenciales ni se modificó configuración de otros productos. Esta es una auditoría de interfaz/capacidades anunciadas, no una prueba de comportamiento interactiva de esos CLIs.

Versiones detectadas localmente:

| Producto | Evidencia local consultada | Versión |
| --- | --- | --- |
| Codex CLI | `--version` / `--help` | `0.155.1` |
| Claude Code | `--version` / `--help` | `2.1.283` |
| Crush | No estaba disponible como ejecutable | No verificable |
| OpenCode | `--version` / `--help` | `1.18.32` |
| OpenClaw | `--version` / `--help` | `2026.9.5` |

La comparación refleja las instalaciones consultadas el 2026-09-27; las versiones pueden cambiar. La captura aportada por el usuario sirve como referencia visual de Crush, no como evidencia de una instalación ejecutable.

## Comparación funcional

Leyenda: **Sí** = capacidad de producto documentada o visible en la ayuda local; **Parcial** = está presente, pero el alcance/flujo no equivale al objetivo de ISyCode; **No** = la auditoría de ISyCode no encontró implementación utilizable; **—** = no es el foco principal del producto.

| Capacidad | Codex CLI | Claude Code | Crush | OpenCode | OpenClaw | ISyCode hoy |
| --- | --- | --- | --- | --- | --- | --- |
| TUI de terminal enfocada en código | Sí | Sí | Sí, su referencia visual | Sí | Sí, conectada a Gateway/runtime | Sí, Textual; falta testigo visual de release |
| Leer/editar archivos y ejecutar herramientas | Sí, shell dentro de sandbox y política | Sí, herramientas con permisos | Sí, herramientas de código y bash | Sí, herramientas y permisos por patrón | Sí, herramientas tipadas, según perfil/sandbox/canal | **Parcial**: chat tiene list/read/name-search tipados tras grants; no escribe ni ejecuta shell |
| Aprobación y límites de ejecución | Sandbox por modo + política de aprobación | Modos manual/plan/auto y allow/deny | Permisos allow/deny y aprobación de herramientas | `ask/allow/deny`, patrones por herramienta y permisos externos | Aprobación de ejecución separada, allowlist y política efectiva host/Gateway | **Bloqueador M15**: gate cubre provider requests y herramientas de lectura; faltan owners restantes y receipts persistentes |
| Contexto de repo e instrucciones | `AGENTS.md`, configuración y perfiles | `CLAUDE.md`, memoria, settings | `AGENTS.md` y archivos de contexto configurables | `AGENTS.md`/instrucciones de proyecto y agentes | Skills, agentes, memoria y contexto según gateway | **Parcial**: `.isyroot`, launch dir y botón de contexto; integración con decisión M15 incompleta |
| LSP | No es una superficie central de CLI; depende del harness/editores | LSP integrado, se puede omitir en `--bare` | Sí; contexto y capacidades LSP | Sí; herramientas LSP | No es una función central uniforme, depende de plugins/tools | **Parcial**: Pyright `workspace/symbol` con sandbox y handshake demostrado; otros servidores/funciones siguen pendientes |
| MCP | Sí: listar/agregar/login/logout | Sí: stdio/HTTP/SSE y OAuth | Sí: stdio/HTTP/SSE y OAuth | Sí: transporte y OAuth | Plugins/tools propios; MCP depende de plugins/bridges disponibles | **Parcial**: Gateway MCP permite listado y llamada manual con grant/aprobación; otros catálogos solo se descubren |
| Skills, plugins, hooks y extensiones | Skills/plugins; capacidades cambian por superficie | Skills, plugins, hooks y agentes personalizados | Skills, hooks preliminares, configuración extensible | Plugins, agentes y skills | Sistema amplio de plugins, skills, canales y tools | **Catálogos parciales**; sin ciclo común seguro de activación. L1 sigue separado/no invocable |
| Proveedores/modelos y cambio de modelo | Modelos Codex y proveedores locales OSS; configuración por perfil | Selección de modelo, fallback, gateways/terceros según configuración | Amplia selección de proveedores/modelos, incluso custom/local | Catálogo amplio de proveedores, credenciales y modelos | Provider por agent/configuración; CLI puede sobrescribir modelo | **Parcial**: providers, selector y vault existen; faltan OAuth, prueba de conexión y estado completo por sesión |
| Sesiones | Resume, fork, queue, archive, delete | Continue/resume/fork, background/attach | Varias sesiones por proyecto/contexto | Crear/listar/fork, retomar, export/import, abort; HTTP server | Sesiones por agente/Gateway, archivo, compactación y búsqueda | **Parcial**: create/list/resume; falta rename/export/fork/search/delete completo en TUI |
| Headless/API/automatización | `exec`, JSONL, sandbox, app-server experimental | `-p`, JSON/stream-json, límites por turnos/presupuesto | `run`, `serve`, comandos de sesiones/estadísticas | `run`, `serve` HTTP, ACP, export/import | Gateway, agent headless, canales y nodos remotos | **Parcial**: `isycode`/`isyco cli`; Mobile Host solo pairing/status/runtime inventory, sin sesiones de runtime |
| Subagentes/roles | Agentes y forks; capacidades disponibles por producto/config | Agentes especializados y subagentes | Agentes/herramientas de sesión | Agentes primarios/subagentes con permisos configurables | Agentes aislados, routing y equipos | **Diferenciador en potencia, no operativo aún**: catálogo de 8 roles OpenISy y motores; no equivale a despachar cada motor desde chat |
| Telemetría, auditoría, costo y diagnóstico | Doctor, sesiones, cloud, JSONL/servidor según modo | Verbose/debug, presupuesto en print, background logs | Logs, estadísticas y avisos | Stats por sesión/modelo/tool, debug y logs | Auditoría de identidad, estado Gateway, approval snapshots, trayectorias | **Parcial**: algunos estados/receipts; falta diagnostics/redacción/actividad unificada y costo confiable |
| Remoto/móvil/canales | Remote app-server experimental/cloud | Cloud/attach según cuenta y CLI | Server compartido entre clientes | Server HTTP, Web UI, attach | **Fortaleza principal**: un Gateway enruta canales, nodos y sesiones | **Diferenciador de producto**: Mobile Host está iniciado; falta runtime real, stream, cancelación, approvals y administración |

## Qué aprender de cada CLI

### Codex CLI

- El flujo nativo combina agente, ejecución y límites: sandbox elegido por workspace, política de aprobación y un camino de automatización JSONL/headless.
- Buen patrón para ISyCode: que el modo de trabajo y el alcance autorizado sean visibles y seleccionables; que `resume`, `fork`, `queue`, `archive` y `delete` formen un ciclo real de sesión.
- No copiar el bypass de sandbox como modo normal. En ISyCode, `ALLOW` debe salir de IsySentinel + Workspace Authority y aplicarse en el owner de ejecución.

### Claude Code

- Destaca en `CLAUDE.md`/memoria, comandos de sesión, `--name`, subagentes, hooks, plugins y control explícito de permisos.
- Buen patrón: contexto por proyecto visible y explicable; agente especialista con instrucciones separadas; hooks como eventos con entrada/salida tipadas.
- No anunciar un hook, skill o agente como activo solo porque aparece en catálogo. Requiere dueño de ejecución y decisión verificable.

### Crush

- Es la referencia más directa para el TUI: selector y cambio de modelos conservando contexto, múltiples sesiones por proyecto, LSP y MCP visibles, panel lateral y buen uso del espacio terminal.
- Buen patrón: la barra lateral refleja estado de MCP/LSP de runtime, no solo config; la sesión conserva contexto al cambiar de modelo.
- En el host actual no pude verificar una instalación ejecutable. Tratar la captura del usuario y la documentación de Crush como referencia de diseño, no como auditoría local de funciones.

### OpenCode

- Combina TUI y servidor HTTP/ACP; tiene control de sesiones amplio (fork, abort, diff, revert, share, summarize, permisos), proveedores/credenciales, agentes, plugins, MCP y estadísticas.
- Buen patrón: API de host versionable como base para Mobile Host y clientes alternos; estado de sesión y permiso observable; exportación portable y métricas por modelo.
- ISyCode debe evitar que `serve` exponga autoridad sin la misma política que el TUI: el host móvil y cualquier API necesitan usar el mismo owner y gates.

### OpenClaw

- Es más una plataforma de agentes y comunicación que un coding TUI: Gateway central, agentes aislados, routing entre canales, sesiones compartidas, nodos móviles/remotos y una superficie grande de operación.
- Buen patrón para ISyCode Móvil: API del host es dueño de identidad, sesión, cancelación, estado y approvals; el cliente móvil presenta el flujo pero no concede permisos.
- No copiar su alcance de canales o visibilidad global por defecto: ISyCode necesita separar host local, `.isyroot`, sesión y grants, y mantener deny-by-default.

## Brechas de ISyCode priorizadas

Orden sugerido para cerrar el producto diario sin convertir el chat en una vía lateral de permisos:

### P0 — Hacer que una acción ocurra de verdad, con un único gate

1. Terminar **M15** antes de activar herramientas en el chat: contrato `ActionRequest`/`Decision`/`Receipt`, IsySentinel puro deny-by-default, Workspace Authority por root, Systembilities, aprobación humana y owner de ejecución.
2. Implementar un primer tool loop tipado usando únicamente capacidades registradas (por ejemplo read/search ya estrechados); bloquear shell libre hasta que exista adapter de proceso con límites y confirmaciones.
3. Renderizar llamada, argumentos redactados, aprobación, resultado y receipt en el transcript; una llamada fallida o cancelada no puede aparentar éxito.
4. Retener la corrección anti-falsa-llamada: JSON que imita bash jamás se interpreta como ejecución.

### P1 — Cerrar los flujos que todas las CLIs diarias dan por sentados

1. Ciclo de sesiones usable: renombrar, fork, export/import con redacción, buscar, archivar/eliminar con confirmación y recuperar una sesión con provider/model/role/contexto.
2. Completar Provider + Credential Vault: conectar/desconectar, validar, cambiar modelo sin perder contexto, endpoint compatible/local, fallback explícito, timeout/límites y estado que distinga autenticado/conectado/autorizado.
3. Diagnóstico integrado: `doctor`, logs redactados, estado de Gateway/MCP/LSP/Bridge/Mobile Host, errores accionables y evidencia sobre qué se probó.
4. UX de contexto: descubrir AGENTS/AGENT desde workspace y permitir inyectar/quitar fuentes fuera del cwd sin ampliar root ni grants; indicar archivo y estado de lectura.

### P2 — Paridad de extensibilidad, después del gate

1. Unificar MCP/skills/plugins en estados **discovered → configured → connected → permitted → invocable**; agregar MCP OAuth y los transports compatibles con una historia de permisos por tool.
2. LSP real: detectar/configurar/arrancar adapters, handshake, diagnostics y status; apagar/reiniciar sin congelar chat.
3. Integrar los 8 roles OpenISy con sus motores y ownership. Mostrar nombre del rol, motor disponible y runtime que lo ejecuta; no convertir la selección del rol en una capacidad.
4. Bridge opt-in para coordinación/PR inbox/lease. Siempre indicar que el lease no autoriza acciones y que Bridge no es policy engine.

### P3 — Diferenciadores que elevan ISyCode por encima de un clon de CLI

1. Mobile Host: migrar de pairing/status al contrato versionado de sesiones, stream, cancelación, aprobación, revocación y catálogo real de runtimes; TUI y móvil usan el mismo backend.
2. `.isyroot` selecciona el sandbox lógico; Authority configura grants por root y IsySentinel decide cada acción. El marcador vacío no otorga lectura/escritura.
3. Gateway/MCP semántico como tool nativo solo cuando el contrato remoto y ambos perímetros —Sentinel local y Gateway HTTP Sentinel— den permiso; nunca convertir Docker o `uvx` en ejecución implícita.
4. L0/L1 y Roundtrip permanecen como capacidades opcionales detrás de sus propios gates, receipts, consentimiento y límites. No forman parte de la paridad mínima.

## Veredicto

ISyCode ya tiene piezas de experiencia que los otros no combinan en la misma dirección: roles/motores OpenISy, `.isyroot`, un plan explícito de ISySentinel/Workspace Authority, Gateway semántico y Mobile Host. Pero varias son **inventario, scaffolding o prototipo**, no capacidades listas para usuario.

La brecha grande frente a Codex/Claude Code/Crush/OpenCode es una experiencia de agente completa dentro del chat: el modelo no puede pedir una herramienta tipada que ISyCode ejecute con seguridad; hoy, deliberadamente, no ejecuta. La brecha grande frente a OpenClaw/OpenCode como host es lifecycle/streaming de sesiones y clientes remotos. La brecha de Crush es LSP y que la barra lateral represente estado real.

Por tanto, “100%” no significa igualar todas las funciones de cinco productos. Para ISyCode significa cerrar P0, P1 y el subconjunto de P2 necesario para el flujo elegido, y mantener P3 como ventaja de producto bajo la misma autoridad.

## Fuentes primarias

- [Codex CLI y sandboxing oficial](https://developers.openai.com/pt-BR/docs/sandboxing) — referencia de sandbox/approval; la instalación también se inspeccionó mediante `codex --help` y `codex exec --help`.
- [Claude Code CLI oficial](https://docs.anthropic.com/en/docs/claude-code/cli-usage) — comandos, sesiones, modo plan, MCP y salida programática.
- [Crush oficial](https://github.com/charmbracelet/crush) — providers/modelos, sesiones, LSP, MCP, skills/configuración.
- [OpenCode providers](https://opencode.ai/docs/providers), [agents/permissions](https://opencode.ai/docs/agents), [CLI/server](https://dev.opencode.ai/docs/cli/) — providers, permisos y operaciones de sesión/host.
- [OpenClaw features](https://docs.openclaw.ai/concepts/features), [exec approvals](https://docs.openclaw.ai/tools/exec-approvals), [session tools](https://docs.openclaw.ai/session-tool) — Gateway, canales, agentes, approvals y sesiones.
