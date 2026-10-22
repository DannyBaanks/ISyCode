# ADR 0010: Flow, el tercer modo de trabajo

- **Estado:** propuesto en el hito MF. No es aprobación de la puerta GF; la puerta se evalúa con evidencia ligada a un SHA.
- **Fecha:** 2026-10-22
- **SHA de partida:** `3d1cd2cb6fff06aa1b1e5c6c17fc9210f7a67b86` (rama del PR #69, que contiene `main` en `429be88`)
- **Plan:** [roadmap Classic/Security](../roadmap-classic-security-ux.md), hito MF
- **Decisiones del owner:** D1–D6 resueltas el 2026-10-22 (ver «Decisiones»).

## Contexto

Classic pide una aprobación por edición y por comando hasta que la persona confía en la carpeta (ADR 0005). Security lo apaga todo hasta conceder cada capacidad. Ninguno sirve a quien quiere describir una tarea y dejar que el agente trabaje: es la experiencia que ofrecen los modos «auto»/«YOLO» de otras herramientas.

Relajar Classic rompería su contrato publicado. Un bypass sin sandbox borraría las fronteras que M2–M6 demostraron. Flow es un tercer modo que reutiliza el mismo núcleo y quita **preguntas**, no **fronteras**.

## Decisión

`flow` se suma a `security | classic` en `WorkspaceAuthority.MODES`. No hay un segundo motor ni un segundo Sentinel:

1. **Autoridad.** El preset de Flow es el de Classic. Se aplica el mismo `effective_policy()` y las denegaciones explícitas (`enabled: false`) siguen ganando.
2. **Aprobación silenciosa.** Una única función `quiet_request(authority, request)` sustituye las dos consultas de `quiet_classic` (en `WorkspaceAuthority._trusted_quiet` y en la TUI). Esa función contesta «sí» solo cuando:
   - el modo es Classic con la carpeta de confianza (comportamiento actual, intacto), o
   - el modo es Flow y la acción está en `QUIET_FLOW_ACTIONS`, el root no es una carpeta amplia y, para comandos, el sandbox verificado existe.

   Cualquier error contesta «no»: se vuelve a pedir aprobación.
3. **Qué no pregunta Flow:** listar, leer, buscar, inyectar contexto, escribir, restaurar, borrar, mover y `workspace.command.run` dentro del sandbox, con su presupuesto de staging por defecto. Es la misma lista que Classic de confianza; Flow solo quita la ceremonia de confianza y añade la elección explícita del modo con advertencia.
4. **Qué sigue preguntando o negado en Flow:**
   - commit de archivos no atribuibles al turno (D3), push y publicación;
   - credenciales y secretos (`.env` y nombres sensibles siguen ocultos, D2);
   - provider y configuración del workspace;
   - cambios de autoridad y de modo;
   - MCP, Gateway, Bridge, Mobile Host, Tailscale y LSP;
   - red para comandos (D1);
   - un staging mayor que el predeterminado;
   - cualquier acción fuera de `QUIET_FLOW_ACTIONS`.
5. **Shell.** Los comandos ya corren como argv dentro de bubblewrap (sin red, sin capacidades, sin entorno del host, con secretos enmascarados y staging con promoción medida). `bash -c` y `sh -c` ya resuelven a programas del sistema. Flow cambia la instrucción al modelo («hay shell dentro del sandbox»), no la frontera: el aislamiento está en el sistema operativo, no en una lista de programas. Sin sandbox, Flow no ejecuta comandos y lo dice; no hay fallback al host.
6. **Red (D1).** Apagada por defecto. Un permiso de red de sesión, explícito, revocable y con caducidad, se ofrece solo donde el backend puede imponerlo. Su alcance real es «salida a la red para comandos en el sandbox durante esta sesión», sin entorno del host, sin secretos montados y sin capacidades. No se promete limitarlo a registros de paquetes porque el backend no puede imponerlo. Donde no se pueda demostrar (Windows hoy), la red sigue denegada.
7. **Turno recuperable.** Antes de cada mutación de un turno de Flow (escritura del owner o promoción de un comando), un `TurnJournal` fuera del checkout guarda la preimagen exacta (bytes y modo), con presupuesto propio. «Deshacer turno» restaura en orden inverso mediante un owner propio (`workspace.turn.undo`) que pasa por Authority, Sentinel, ledger y journal, y que verifica que cada archivo sigue con el hash que dejó el turno. Lo que cambió después lo reporta como conflicto y no lo sobrescribe. Si una preimagen no cabe en el presupuesto, ese efecto no se promueve en silencio: pide aprobación.
8. **Commits (D3).** En Flow, `git.commit` no pregunta solo si **todas** sus rutas son atribuibles al turno en curso. Una ruta es atribuible si:
   - su preimagen del `TurnJournal` coincide con `HEAD` (o no existía ni en `HEAD` ni en el disco), es decir, no tenía trabajo humano pendiente;
   - no estaba en el índice con otro contenido;
   - su contenido actual es el último que dejó el turno.

   El commit usa el owner Git de siempre (`git commit -- <rutas>`, sin hooks, con el diff revisado ligado al digest), nunca `git add .`. Cualquier ruta no atribuible devuelve la pregunta. Push y publicación siempre preguntan. Deshacer un turno con commit restaura los archivos y deja el commit en la historia; la UI lo dice.
9. **Cambio de modo en caliente (D5).** Un controlador espera o cancela el turno en curso, invalida las aprobaciones pendientes y los permisos de sesión (red), cambia el modo con `set_mode`, reconstruye los owners de la TUI y conserva conversación y vista. El cambio de modo solo lo hace la persona desde la UI; no es una acción del modelo.
10. **Predeterminado (D4).** El onboarding ofrece las tres opciones, con Classic seleccionado y marcado como recomendado.

## Caminos de ejecución inventariados (SHA de partida)

| Camino | Cómo pide aprobación hoy | Efecto de Flow |
| --- | --- | --- |
| Chat TUI: `workspace_edit`/`write`/`delete`/`move`/`undo` | `_request_is_quiet` → ventana; Authority `_trusted_quiet` | Silencioso en Flow; registrado en el turno |
| Chat TUI: `workspace_run` | ídem, más el sandbox | Silencioso en Flow con sandbox; preimágenes de la promoción en el turno |
| Chat TUI: lectura/búsqueda | sin aprobación por llamada | Igual |
| Git: status/diff | grant del preset | Igual |
| Git: commit / publicación | aprobación exacta del owner | Igual (sigue preguntando) |
| Headless (`headless.py`) | solo lecturas y git status/diff | Sin cambios: Flow no aplica sin persona |
| Iteración multi-agente (`iteration.py`) | solo `read_iteration` | Sin cambios |
| MCP / Gateway / Bridge / Mobile Host / LSP / Tailscale | grants explícitos y aprobación | Sin cambios |
| Credenciales / provider / config | owner propio, aprobación | Sin cambios |

## Amenazas consideradas

Se añaden al modelo del roadmap (sección 3):

- **Prompt injection sin preguntas** (un README pide «borra todo»). Mitigación: sandbox, presupuesto acumulativo del ledger, `TurnJournal` y deshacer turno; lo irreversible sigue preguntando.
- **Exfiltración por la salida de un comando** (la salida vuelve al modelo y al provider). Mitigación: sin entorno del host (`/proc/1/environ` vacío desde #70), secretos enmascarados y sin home. Riesgo residual: un archivo no sensible con un secreto dentro es legible, igual que en Classic.
- **Red concedida usada para exfiltrar.** Mitigación: apagada por defecto; con permiso, el sandbox sigue sin secretos montados. Riesgo residual declarado: lo que es legible en el workspace puede salir mientras dure el permiso.
- **Cambio de modo con aprobaciones vivas.** Mitigación: el controlador vacía el almacén de aprobaciones y los permisos de sesión antes de cambiar.
- **Metadata privilegiada** (`.git`, `.isyroot`, journal, políticas). Mitigación: igual que hoy, ni escritura ordinaria ni promoción.
- **Borrado masivo o fraccionado.** Mitigación: el mismo ledger compartido; Flow no sube límites.
- **Carpetas amplias** (home, raíz). Flow no se activa en silencio; las acciones vuelven a preguntar.

## Alternativas rechazadas

- **Relajar Classic.** Rompe el contrato de ADR 0005 y la promesa a quien ya lo usa.
- **Bypass total (sin sandbox o sin Sentinel).** No existe `bypass_all`.
- **Lista blanca de comandos.** Un test puede ejecutar código arbitrario; la frontera tiene que ser el sistema operativo.
- **Commit de todo lo que cambió (`git add .`).** Mezclaría trabajo humano sucio, staged o untracked con el del agente.
- **Reiniciar el proceso al cambiar de modo.** Pierde estado de la TUI y no aporta aislamiento: Authority relee la política en cada evaluación.

## Qué no hace

No aprueba GF, M9 ni M10. No abre MCP, credenciales ni push. No cambia headless. No ofrece Flow con comandos donde no hay sandbox verificado.
