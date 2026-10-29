# Auditoría Codex TUI/CLI 0.160.0 para ISyCode

Fecha: 2026-10-03  
Alcance: instalación local de Codex, su CLI/TUI visible, app-server, esquema generado, inventario de tools del harness de esta tarea y el conector Codex ya existente en ISyCode.  
Resultado: evidencia para roadmap; no es un port de Codex ni autorización para reutilizar sus permisos.

## Piso de evidencia

La auditoría se hizo contra el binario local `codex-cli 0.160.0` en:

`/home/danny/.codex/packages/standalone/releases/0.160.0-x86_64-unknown-linux-musl/bin/codex`

La auditoría comparativa anterior de `docs/product/cli-competitive-audit.md` midió Codex 0.155.1. Este documento no la reemplaza: registra el delta visible de 0.160.0 y, sobre todo, qué puede aprovechar ISyCode sin convertir Codex en autoridad.

Se usaron `codex --help`, `codex help <subcommand>`, `codex features list`, `codex mcp list`, `codex app-server generate-json-schema --experimental`, el inventario de tools del harness actual y lectura del código de ISyCode. No se ejecutaron `update`, `delete`, `apply`, `cloud apply`, instalación de plugins, login MCP, login ChatGPT, comandos de shell del agente ni operaciones remotas. Un barrido de ayudas que contenía juntos nombres como `update`, `delete` y `apply` fue rechazado por la revisión automática; se sustituyó por `codex help <subcommand>`, que solo imprime ayuda.

## Qué expone Codex 0.160.0

La superficie principal medida incluye:

| Superficie | Evidencia local | Uso que interesa a ISyCode |
|---|---|---|
| TUI interactiva | `codex`, `resume`, `fork`, `agents`; selector de sesión y soporte de servidor remoto anunciados | Separar UI de runtime de sesión y hacer que la lista de trabajo represente tareas vivas |
| Headless | `codex exec`, JSONL, `--output-schema`, `--ephemeral`, `--worktree`, `--add-dir`, perfiles/config | Contrato de eventos único TUI/headless/móvil y salida estructurada opcional |
| Review | `codex review` y `exec review`; base/commit/uncommitted | Mantener review como intención separada de ejecución |
| Sesiones | `resume`, `fork`, `queue`, `archive`, `unarchive`, `delete`, `migrate-rollouts` | Lifecycle explícito, archivo reversible y migraciones dry-run |
| App server | `app-server`, daemon, proxy, JSON Schema/TypeScript generators; stdio/unix/ws | Runtime compartido versionado, sin acoplar UI y motor |
| Remoto | `remote-control start/stop/pair`; pairing manual de corta vida | Confirma el patrón ya usado por Mobile Host; no requiere otro sistema de pairing |
| MCP | list/get/add/remove/login/logout; list/get tienen JSON | Catálogo separado de invocación y credenciales |
| Plugins | add/list/remove + marketplaces; listado JSON | Lifecycle visible de extensiones, sin tratarlas como grants |
| Sandbox | `codex sandbox`, estado serializado, raíces legibles, red deshabilitable, permission profiles | Snapshot efectivo de sandbox como evidencia/diagnóstico |
| Diagnóstico | `doctor --json`, `debug models`, `debug prompt-input` | Prompt inspector redacted y diagnóstico reproducible |
| Features | `features list/enable/disable` con etapa + estado efectivo | Distinguir madurez de producto de autoridad |
| Exec server/cloud | servicio de ejecución y tareas cloud experimentales | Referencia de separación entre coordinación y ejecutor; fuera del Secure inicial |

`codex features list` no es solo un booleano: distingue estados como `stable`, `experimental`, `under development`, `deprecated` y `removed`, además del estado efectivo. Esa dimensión sirve para ISyCode porque una capacidad puede existir en el build y seguir sin estar disponible al usuario. No debe mezclarse con `ALLOW/DENY`, grants ni aprobación.

## App-server: el contrato es mucho mayor que lo que ISyCode permite

`codex app-server generate-json-schema --experimental` generó localmente el bundle del protocolo 0.160.0. Entre las familias visibles aparecen, entre muchas otras:

- `thread/start`, `thread/list`, `thread/read`, `thread/search`, `thread/fork`, `thread/archive`, `thread/unarchive`, `thread/delete`, `thread/compact/start`;
- `thread/queue/add|list|update|delete|reorder|start`;
- `thread/name/set`, `thread/settings/update`, `thread/turns/list`, `thread/timeline/list`;
- `turn/start`, `turn/steer`, `turn/interrupt`;
- `model/list`, `review/start`, `permissionProfile/list`;
- familias `plugin/*`, `process/*`, `fs/*`, configuración, MCP, memoria, realtime y OAuth.

La existencia de un método en ese schema no demuestra que esté habilitado por cuenta, build o configuración. Sí demuestra que el protocolo que rodea al subconjunto usado por ISyCode cambia y crece, por lo que conviene verificar compatibilidad de forma explícita.

## ISyCode ya tiene la frontera correcta

`src/isycode/codex_connector.py` ya implementa un transporte oficial y estrecho hacia `codex app-server --listen stdio://`:

- exige un ejecutable absoluto seleccionado y un `CODEX_HOME` dedicado propiedad de ISyCode;
- rechaza reutilizar `~/.codex`;
- fuerza un home/config privado y un entorno reducido;
- deshabilita shell, exec unificado, multi-agent, plugins, hooks, apps, browser/computer use, web, image generation, code mode, memories, skill/tool search, `view_image`, `apply_patch` y otras capacidades nativas;
- mantiene una allowlist de requests de protocolo (`initialize`, cuenta/modelos, login controlado, `thread/start`, `turn/start`);
- si el modelo pide una dynamic tool declarada por ISyCode, devuelve la solicitud al owner de ISyCode y termina la conexión antes de permitir que Codex la ejecute;
- rechaza requests nativos no autorizados y falla cerrado.

La prueba local contra el binario 0.160.0 real inicializó ese conector con éxito usando un home nuevo en `/tmp`. `account/read` devolvió `authenticated=false`; no se reutilizó la sesión Codex existente. Es evidencia de compatibilidad de transporte, no de un login ni de una llamada de modelo.

Los tests de `tests/test_codex_connector.py` usan un app-server falso local, no credenciales ni el Codex instalado, y cubren el entorno endurecido, argv exacto, login en memoria, URLs de auth, dynamic tools, frames inválidos, timeouts/cancelación y rechazo de acciones no autorizadas.

## Tools de esta tarea: qué revela la propia TUI

El registro directo de tools de este harness expuso 19 entradas antes de carga diferida: ejecución/entrada de terminal, recursos MCP, preguntas al usuario, patch, imágenes, goals, reloj, browser/computer-use, web, image generation y `tool_search`, entre otras. Ese número pertenece a esta sesión/configuración; no es una constante de Codex.

`tool_search` cargó bajo el namespace `codex_tui` ocho operaciones de control de tareas:

- `list_threads` y `list_archived_threads`;
- `read_thread`;
- `set_thread_title`;
- `fork_thread`;
- `set_thread_archived`;
- `send_message_to_thread` para follow-up en background;
- `wait_threads` para esperar hasta ocho tareas y detectar completed/approval/user-input.

Eso aporta una idea concreta: el board de ISyCode puede evolucionar de “lista de conversaciones” a “vista de trabajo vivo” sin darle autoridad adicional al modelo. Leer estado, esperar o renombrar no debe ejecutar efectos del workspace; mandar un follow-up solo agrega input a una tarea ya existente y tampoco concede permisos.

## TUI visual: evidencia y límite

La prueba interactiva mínima alcanzó a renderizar la pantalla inicial de Codex 0.160.0 en un repo temporal, mostrando versión, cwd y composer. Después abortó con `Read-only file system (os error 30)` cuando el proceso quiso escribir estado bajo el home Codex de este sandbox.

Por tanto: **render inicial DEMONSTRATED; interacción completa de la TUI NOT_DEMONSTRATED en esta auditoría**. La lista de comandos y métodos de este documento proviene de ayuda CLI, schema generado y tool registry, no de fingir que se navegó toda la TUI.

## Qué sí conviene adaptar

### P0 — contrato del provider Codex

1. Versionar el subconjunto de app-server que ISyCode consume. Generar el schema del binario instalado en CI/probe y comparar que los métodos/campos requeridos por `CodexConnector` siguen existiendo. Un cambio incompatible deja Codex en estado `unsupported`, sin abrir más métodos como fallback.
2. Añadir un prompt inspector local y redacted inspirado en `debug prompt-input`: mostrar exactamente qué bloques de system/developer/context/skills/tool schemas entrarán al provider, sus tamaños y cualquier truncado. No llama al modelo y no muestra secretos.
3. Añadir `strict config` para detectar claves desconocidas/obsoletas en configuración de ISyCode. El modo limpio puede omitir preferencias cosméticas, comandos o skills de usuario, pero nunca Authority, Sentinel, owners, grants o reglas de seguridad.

### P1 — runtime de tareas

4. Hacer del Work board una API tipada de tareas vivas: list/read/status/title/fork/archive/unarchive/follow-up/wait. Reutilizar el contrato de eventos previsto en M17 y el substrate de Mobile Host; no crear otra autoridad.
5. Hacer `archive/unarchive` el ciclo reversible ordinario. `delete` sigue siendo una acción destructiva explícita, scoped y aprobada. Archivar una tarea no borra receipts ni historial.
6. Permitir salida final validada contra JSON Schema en headless para OpenISy/automatización, sin que el schema pueda activar tools o ampliar grants.

### P2 — diagnóstico y evolución

7. Registrar un snapshot normalizado del sandbox efectivo en receipts/diagnóstico: roots, ejecutable, red y límites. Los permission profiles son plantillas de UX/configuración; la autoridad efectiva sigue saliendo de ISyCode.
8. Añadir metadata de lifecycle (`stable`, `experimental`, `under-development`, `deprecated`, `removed`) separada de `enabled` y de la decisión Authority/Sentinel.
9. Diseñar futuras migraciones de sesiones como `inspect`/dry-run primero, aplicación explícita después, con reporte por sesión y límites de I/O. Nunca reescribir silenciosamente todo el historial al arrancar.

## Ya cubierto: no abrir tickets duplicados

- La cola visible y su cancelación ya están en M17; Codex `queue` solo refuerza esa dirección.
- `/compact`, árbol/fork de conversación y contrato común de eventos ya están en M17.
- Exposición `direct/deferred/hidden` ya está en M17; el `tool_search` medido aquí sirve como evidencia de utilidad, no como segundo feature.
- `isycode doctor --json` ya existe; conviene extender el mismo comando.
- ISyCode ya tiene búsqueda/rename/fork/export/import/delete de conversaciones.
- Mobile Host ya usa pairing propio; no portar `remote-control pair`.
- ISyCode ya soporta carpetas adicionales con grants por carpeta; no copiar `--add-dir` como bypass.
- El conector Codex ya existe y ya impide herramientas nativas; no reemplazarlo por una ejecución irrestricta del CLI.

## Qué no copiar

- `--dangerously-bypass-approvals-and-sandbox` ni equivalentes.
- `--ignore-rules` como forma de saltar Authority/Sentinel.
- confianza de hooks o plugins como autorización para efectos.
- shell/proceso/filesystem nativos del app-server como atajo para cerrar M6.
- permission profiles como grants.
- worktree como frontera de seguridad; puede ser comodidad futura, no sandbox.
- auto-review de Codex como sustituto de la decisión de Workspace Authority + IsySentinel de ISyCode.

## Gates para cerrar M19

- Un upgrade de Codex que rompa el schema requerido queda visible como incompatibilidad y no ensancha la allowlist.
- El prompt inspector funciona offline, redacta secretos y nombra cada fuente/truncado.
- Una tarea puede archivarse y restaurarse sin borrar transcript/receipts ni repetir efectos.
- Follow-up, fork y wait no alteran grants ni reejecutan acciones anteriores.
- El modo headless con output schema usa exactamente los mismos owners para tools que la TUI.
- Lifecycle de features y estado de authority se renderizan por separado.
- El snapshot de sandbox describe lo que se ejecutó; no se presenta como permiso.
