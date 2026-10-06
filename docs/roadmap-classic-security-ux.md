# Roadmap ejecutable: Classic seguro, Security explícito y UX de uso diario

Fecha: 2026-10-02. Estado: **M0, M1, M2, M3, M4, M5 y M6 en revisión; M6A–M10 pendientes**. Ninguna puerta está APROBADA.
Este documento define el destino y sus puertas de aceptación; publicarlo no supera ninguna puerta.
La evidencia de M0 está en [docs/evidence/classic-security-ux/M0/db6c86314ce73ddb19e776f03db4a25eb08c9eb4/](evidence/classic-security-ux/M0/db6c86314ce73ddb19e776f03db4a25eb08c9eb4/gate.yaml). No aprueba G0.
La evidencia de M1 está en [docs/evidence/classic-security-ux/M1/256234565d8fb8c5e0e1f950348f28e823d72e86/](evidence/classic-security-ux/M1/256234565d8fb8c5e0e1f950348f28e823d72e86/gate.yaml). No aprueba G1 ni abre Classic autónomo.
Los IDs `M0`–`M10` (incluido `M6A`) son locales a este roadmap, no los del [roadmap histórico](ROADMAP.md).
Para esta evolución de Classic/Security prevalece esta dirección de producto; las descripciones actuales del README siguen describiendo el software disponible.

## 1. Objetivo, baseline y límites

**Classic debe permitir entrar al proyecto y trabajar con fluidez**, con autonomía para efectos seguros y recuperables dentro del workspace confiable.
No debe ser Security con muchos permisos activados pero una confirmación en cada edición o comando.
Security conserva activación explícita, mínimo privilegio y revisión restrictiva.
Ambos usan **el mismo kernel**: Workspace Authority, Systembilities, IsySentinel, execution owners y recibos.
Cambian los perfiles de autoridad y aprobación, no la contención ni las garantías de verificación.

Referencias de experiencia: fluidez de OpenClaw, opciones de OpenCode, jerarquía y acabado visual de Crush, protección de ISyCo ante errores y borrados en cascada.
Son referencias de producto, **no paridad verificada**, dependencias obligatorias ni autorización para copiar implementaciones o marca.
M0 debe comprobar primero qué existe aquí y después comparar alternativas mantenidas, licencias, costes y compatibilidad.

| Dimensión | Baseline inspeccionado: `9dda3f9` | Objetivo pendiente |
| --- | --- | --- |
| Classic | Preset de grants; ediciones, comandos y commits conservan aprobación por acción | Operaciones ordinarias acotadas autónomas; confirmación al cruzar fronteras reales |
| Security | Grants explícitos y owners con aprobación donde corresponda | Mantener mínimo privilegio y ninguna herencia silenciosa de Classic |
| Comandos | Bubblewrap/seccomp; workspace escribible; no fallback inseguro | Efectos en staging aislado, medidos y reconciliados antes de promoción |
| Recuperación | Checkpoints de herramientas de escritura; `/undo` no cubre efectos de comandos | Recuperación transaccional común, sin perder trabajo previo o concurrente |
| Interfaz | TUI Textual, tareas, diffs, sesiones, permisos | Flujo consistente, baja fricción, accesibilidad y comportamiento medidos |
| Pruebas | Suite actual y evidencia histórica | Pruebas adversariales y de producto ligadas a puertas y al SHA exacto |

La inspección de GitHub confirmó [CI del baseline](https://github.com/DannyBaanks/ISyCode/actions/runs/36997683145) `completed/success`, SHA `9dda3f9ef58bbac739206b4e15505a3c82eaaa79`.
El resultado histórico comunicado de **1053 passed, 7 skipped** no se reejecutó para redactar este documento y no prueba ninguno de sus hitos futuros.
El workflow actual tiene tests Linux Python 3.10/3.12 y empaquetado; no valida todavía este protocolo de puertas.

No objetivos:

- Eliminar Sentinel, permitir shell host sin aislamiento o tratar `.isyroot` como un grant.
- Garantizar seguridad absoluta ante kernel comprometido, administrador host malicioso o hardware defectuoso.
- Reescribir toda la TUI, cambiar lenguaje/runtime, copiar otra CLI o habilitar integraciones por defecto.
- Usar prompts, listas de comandos prohibidos o backups solos como frontera de seguridad.
- Afirmar producción, soporte multiplataforma equivalente o provider vivo a partir de mocks.
- Implementar este plan en el cambio documental que lo publica.

## 2. Inventario inicial que hay que reutilizar y verificar

Rutas existentes inspeccionadas; son puntos de entrada, no certificación de cobertura completa.
Antes de modificar un área, leer sus contratos, tests y callsites efectivos.

| Área | Código existente | Evidencia/regresiones a extender |
| --- | --- | --- |
| Kernel y registro | [security.py](../src/isycode/security.py), [actions.py](../src/isycode/actions.py), [action_runtime.py](../src/isycode/action_runtime.py) | [test_security_contract.py](../tests/test_security_contract.py), [test_action_coverage.py](../tests/test_action_coverage.py) |
| Autoridad y aprobaciones | [workspace_authority.py](../src/isycode/workspace_authority.py), [approvals.py](../src/isycode/approvals.py) | [test_workspace_modes.py](../tests/test_workspace_modes.py), [test_action_approvals.py](../tests/test_action_approvals.py) |
| Ejecución y cambios | [command_runner.py](../src/isycode/command_runner.py), [workspace_write.py](../src/isycode/workspace_write.py) | [test_command_runner.py](../tests/test_command_runner.py), [test_file_delete_move.py](../tests/test_file_delete_move.py), [test_workspace_write.py](../tests/test_workspace_write.py) |
| Git y estado | [git_owner.py](../src/isycode/git_owner.py), [session_owner.py](../src/isycode/session_owner.py) | [test_git_owner.py](../tests/test_git_owner.py), [test_daily_sessions.py](../tests/test_daily_sessions.py) |
| Secretos y red | [credential_owner.py](../src/isycode/credential_owner.py), [chat_transport.py](../src/isycode/chat_transport.py) | [test_credential_owner.py](../tests/test_credential_owner.py), [test_provider_redirects.py](../tests/test_provider_redirects.py) |
| Bucle y recibos | [agent_loop.py](../src/isycode/agent_loop.py), [action_audit.py](../src/isycode/action_audit.py), [tool_history.py](../src/isycode/tool_history.py) | [test_agent_loop.py](../tests/test_agent_loop.py), [test_action_audit.py](../tests/test_action_audit.py), [test_tool_history.py](../tests/test_tool_history.py) |
| TUI y onboarding | [tui.py](../src/isycode/tui.py), [workspace_setup.py](../src/isycode/workspace_setup.py), [user_defaults.py](../src/isycode/user_defaults.py) | [test_daily_tui.py](../tests/test_daily_tui.py), [test_visual_tui.py](../tests/test_visual_tui.py), [test_user_defaults_mode.py](../tests/test_user_defaults_mode.py) |
| Continuidad y regresiones | [guía diaria](daily-use-readiness.md), [contrato de fronteras](design/isysentinel-security-boundaries.md) | [test_daily_security_regressions.py](../tests/test_daily_security_regressions.py), [test_session_continuity_tui.py](../tests/test_session_continuity_tui.py) |

## 3. Modelo de amenazas y decisiones de arquitectura

Activos: archivos tracked, dirty, staged, ignored y untracked; contenido sensible; autoridad; identidad del workspace; credenciales; historial; checkpoints; journal; disponibilidad y acciones externas.
Entradas no confiables: respuestas del modelo, repositorios, AGENTS/skills, salidas de herramientas, MCP, scripts/build hooks, paquetes y sesiones importadas.
Una instrucción incrustada nunca concede permisos ni modifica un presupuesto.

| Amenaza | Frontera exigida | Prueba mínima |
| --- | --- | --- |
| Borrado/rewrite masivo accidental | Staging transaccional + presupuesto acumulativo previo a promoción | Python y shell producen el mismo bloqueo que una herramienta tipada |
| Escape por links, renames o carreras | Resolución segura, mounts restringidos, identidad y revisión al promover | Symlink, hardlink, cambio de root y TOCTOU no alteran el host protegido |
| Autoelevación | Autoridad/metadata/backups fuera del dominio escribible del agente | Negar modificación directa e indirecta y consumo de aprobaciones ajenas |
| Exfiltración | Red por capacidad; secretos solo en owner/proveedor exacto | Denegar red desde procesos y redirecciones de credenciales |
| Fraccionar el daño | Ledger persistente compartido, reservas atómicas y límites por workspace | Mismo coste con N llamadas, reinicios y N workers |
| Crash/cancelación/retry | Estado durable, limpieza de árbol y reconciliación de resultados inciertos | Sin replay de efectos no verificados ni pérdida del trabajo humano |
| UI engañosa/inyección | Datos no confiables separados de autoridad; recibos verificados | Un texto «éxito» del modelo no vuelve verde una acción fallida |

El kernel y el OS forman parte de la base confiable declarada; documentar límites por plataforma y riesgos residuales.
Un backup no evita exfiltración y un sandbox con todo el checkout escribible no evita destruir ese checkout.
Los filtros de nombres sensibles son defensa adicional, no prueba suficiente contra contenido secreto arbitrario.

### Contrato de efecto común

Toda ruta (TUI, headless, tool, subprocess, Python, MCP, subagente y adapter) solicita un efecto inmutable con identidad de workspace, owner, alcance, digest de base, perfil, versión de política y operación/idempotencia.
La política clasifica lectura, mutación recuperable, destrucción, metadata privilegiada, credencial, red y publicación.
No se confía en el nombre de una herramienta ni en que `pytest` parezca inocuo: los tests pueden ejecutar código arbitrario.
IsySentinel sigue siendo puro y read-only; reserva/commit del presupuesto y ejecución pertenecen a owners coordinados transaccionalmente.
Una decisión caducada, desconocida, incompleta o con versión de política revocada no ejecuta.

### Aislamiento y promoción

- Elegir en M2 un backend existente adecuado (por ejemplo snapshot/overlay/COW más aislamiento de procesos), con ADR y prueba real.
- Un worktree Git por sí solo no aísla procesos, archivos ignorados, red, home ni metadata compartida.
- Shell, Python, compiladores y tests escriben únicamente en staging/scratch controlados, nunca directamente en el árbol fuente del usuario.
- Un proceso puede destruir su staging: antes de tocar el workspace real, el owner mide el diff completo, verifica límites, identidad y precondiciones.
- Evitar promoción por hardlinks compartidos; incluir archivos binarios, permisos, renames, directorios y archivos nuevos en el manifiesto.
- Bloquear dispositivos, sockets de host, mounts privilegiados y árboles de procesos que sobrevivan al owner; aislar recursos y acceso a red.
- No montar secretos, autoridad, journal ni backups; la lectura de archivos sensibles exige capacidad específica y no es implícita en Classic.
- `.git`, `.isyroot`, configuración de confianza, hooks y metadata de permisos no son escritura ordinaria. Git opera mediante owner privilegiado acotado.
- Si staging o protección de metadata no se puede demostrar, no habilitar comandos mutadores autónomos.

### Presupuestos y recuperación

El presupuesto mide **efectos**, no tokens ni pasos de razonamiento: rutas únicas tocadas, archivos eliminados, bytes originales destruidos/reemplazados, volumen nuevo y recursos de staging.
Debe tener límites por operación y acumulados por workspace/campaña de trabajo; reiniciar conversación no los reinicia.
Registrar también churn acumulado: editar repetidamente un mismo archivo no cuesta cero tras la primera edición.
M3 debe fijar valores finitos versionados con fixtures pequeños y grandes y justificar usabilidad; ausencia de límite significa DENY, no infinito.
Reservar de forma atómica antes de promover, contabilizar después y reconciliar reservas inciertas tras crash.
N workers comparten el mismo ledger; no se admite check-then-act sin exclusión/serialización.
Nueva sesión, cambio de herramienta, rename, root alias o proceso nuevo no crea saldo gratis.
Solo el usuario por un owner protegido puede ampliar/resetear un límite; nunca el modelo ni una tarea autodeclarada «nueva».

Preservar bytes y estado tracked/staged/dirty/untracked/ignored previos; no usar `git reset --hard`, `git clean` o stash destructivo como recuperación automática.
Checkpoints cifrados o protegidos según clasificación, fuera del sandbox y no borrables por procesos del proyecto.
Documentar retención, cuota y recuperación ante disco lleno; sin espacio durable suficiente no se empieza una mutación.
La promoción multiarchivo debe tener journal durable e intención antes de efectos, fsync/orden definidos, bloqueo y recovery determinista.
Si el filesystem no soporta atomicidad multiarchivo, no prometerla: demostrar recuperación tras cada punto parcial y evitar que ISyCode ejecute consumidores sobre estado incompleto.
Restaurar solo preimágenes propias con compare-and-swap; un conflicto con edición humana se conserva y se presenta, jamás se sobrescribe.

## 4. Reglas obligatorias de avance

El validador local de M1 ya corre en CI y rechaza un manifiesto ausente, inconsistente o autodeclarado APROBADO. La API de GitHub, leída de vuelta el 2026-10-02, exige en `main` los checks `Tests (Linux)`, `Tests (Linux, Textual 8)` y `Gate evidence`. `enforce_admins` está apagado, así que el propietario todavía puede pushear, y no se ensayó una PR de bypass. Eso no es un candado contra el admin ni una puerta APROBADA.
Cambiar este Markdown o marcar una casilla no desbloquea trabajo dependiente.

1. Estados permitidos: PENDIENTE, EN CURSO, BLOQUEADO, EN REVISIÓN, APROBADO y REABIERTO. Estado inicial de todos: PENDIENTE.
2. Para iniciar implementación de un hito, todas sus dependencias deben estar APROBADAS con evidencia del código aplicable.
3. Se permite investigación independiente y reparación de prerrequisitos fallidos; no contabilizarlo como avance aprobado del dependiente ni habilitarlo al usuario.
4. Cada gate pasa únicamente con todos sus IDs obligatorios PASS, artefactos verificables, entorno declarado y aceptación de revisor distinto del autor cuando esté disponible; si falta revisor, sigue EN REVISIÓN.
5. FAIL, UNKNOWN, SKIP, XFAIL o evidencia ausente en una prueba obligatoria **bloquean**. No retirar tests, relajar asserts ni convertir fallos en skips para obtener verde.
6. Un skip de plataforma solo es admisible para una capacidad explícitamente no soportada, deshabilitada y probada fail-closed; no equivale a aprobar esa capacidad.
7. No aceptar waivers silenciosos de seguridad. Una excepción documenta riesgo y responsable, pero no cierra el gate: reducir alcance/deshabilitar la función y repetir aceptación, o corregir.
8. El SHA, configuración, versión de política/backend y artefactos deben coincidir. Evidencia de una versión anterior no aprueba una modificación posterior sin análisis de impacto y rerun.
9. Regresión reabre el gate afectado y bloquea dependientes/releases. Congelar autonomía afectada, preservar estado/evidencia, revertir de forma compatible y repetir pruebas.
10. «Compila», «CI verde» o «el modelo dijo que terminó» no sustituyen las pruebas específicas, la revisión y los escenarios reales.

### Enforcement técnico que debe construirse en M1

Manifest versionado: ID de gate, dependencias, IDs de tests, resultados, SHA evaluado, entorno, digest/ubicación de artefactos y aceptación de revisión.
CI debe validar esquema, dependencias, cobertura de IDs, resultados y SHA; ausente/alterado/inconsistente falla.
El artefacto de ejecución se liga al SHA mediante CI, no mediante un archivo editable que se autodeclare aprobado.
Para no crear un ciclo de hash, una aceptación posterior referencia el SHA probado; CI comprueba cambios posteriores relevantes y exige nueva evidencia cuando aplique.
Proteger workflow/validator/manifests con revisión obligatoria y checks requeridos; verificar configuración remota, no solo YAML.
Release/packaging público debe depender de gates pertinentes y ambos jobs de tests; el workflow actual no satisface todavía esta exigencia.
Una PR de bypass deliberado debe fallar como prueba negativa. Si no hay permiso para configurar protección remota, registrar BLOQUEADO y no anunciar enforcement real.

## 5. Mapa de hitos y dependencias

| Hito | Entrega | Dependencias | Estado | Puerta |
| --- | --- | --- | --- | --- |
| M0 | Baseline, reuso, amenazas y entorno medido | Ninguna | APROBADO (G0, revisor Danny Baanks, evidencia 33b218df) | G0 |
| M1 | Política común, CI de gates y primera separación TUI | M0 | APROBADO (G1, revisor Danny Baanks, evidencia 33b218df) | G1 |
| M2 | Aislamiento real y staging de efectos | M1 | APROBADO (G2, revisor Danny Baanks, evidencia 33b218df) | G2 |
| M3 | Ledger de presupuestos y recuperación durable | M2 | APROBADO (G3, revisor Danny Baanks, evidencia 33b218df) | G3 |
| M4 | Confianza, perfiles Classic/Security y degradación | M3 | APROBADO (G4, revisor Danny Baanks, evidencia 8a280c17) | G4 |
| M5 | Egress, secretos e integraciones acotadas | M3 | APROBADO (G5, revisor Danny Baanks, evidencia 8a280c17) | G5 |
| M6 | Bucle, cancelación y retry reconciliado | M4, M5 | APROBADO (G6, revisor Danny Baanks, evidencia 8a280c17) | G6 |
| M6A | Agentes observables e instrucciones en cola | M6 | PENDIENTE | G6A |
| M7 | Flujos cotidianos completos | M6A | PENDIENTE | G7 |
| M8 | Pulido visual, teclado y accesibilidad | M7 | PENDIENTE | G8 |
| M9 | Matriz adversarial, dogfood y rendimiento | M8 | PENDIENTE | G9 |
| M10 | Release gradual y rollback ensayado | M9 | PENDIENTE | G10 |

M4 y M5 pueden avanzar en paralelo después de G3; prototipos visuales sin efectos pueden investigarse antes de M8, sin declarar G8 aprobado.
No abrir Classic autónomo antes de G4/G5/G6 según las capacidades implicadas.

### M0 — Baseline reproducible y decisiones de reuso

Trabajo: leer AGENTS, inventario anterior, estado Git y documentos; mapear cada owner y ruta de ejecución real.
Ejecutar baseline hermético; clasificar los skips existentes y separar evidencia offline de servicios vivos.
Comparar reutilización de owners/checkpoints/Textual y backends mantenidos antes de agregar infraestructura.
Registrar referencias OpenClaw/OpenCode/Crush con versión/URL/fecha y qué se observó realmente; no asumir equivalencia.
Entregar ADR con alternativas rechazadas, licencias, límites OS, amenazas y coste de migración; declarar fixture y máquina para métricas.

- `G0-01`: inventario enlaza cada capacidad a callsite y test; cualquier owner sin mapear falla.
- `G0-02`: `python -m pytest -q -m "not integration"` con SHA, salida, exit code y skips clasificados; fallo inexplicado bloquea.
- `G0-03`: medir flujo de lectura/edición/test/diff actual y contar aprobaciones; guardar transcripción sanitizada y latencias.
- `G0-04`: ADR de reutilización y threat model revisados; lista explícita de capacidades aún sin evidencia real.

Aceptación: revisor reproduce al menos un flujo y un test negativo; G0 no cambia permisos del producto.

### M1 — Una política y modularización incremental temprana

Trabajo: extender catálogo/Authority/owners, sin duplicar un segundo motor «Classic» en la UI.
Extraer de `tui.py` primero presentación de decisiones/recibos y coordinación de acciones a módulos pequeños con contratos explícitos.
Conservar puntos de entrada y pruebas de caracterización; migrar una superficie por cambio, sin reescritura big bang.
Definir perfiles versionados, taxonomía de efectos y autorización atada a digest/versiones; el preset no derrota denegaciones explícitas.
Implementar el enforcement de gates descrito arriba, distinguiendo pruebas de su infraestructura de puertas de producto pendientes.

- `G1-01`: mismo efecto por TUI/headless/tool tiene decisión equivalente; owner desconocido y checks vacíos/excepción deniegan.
- `G1-02`: revocación entre prepare/execute, digest cambiado, aprobación expirada/reutilizada y workspace distinto no producen efectos.
- `G1-03`: extracción inicial conserva snapshots/interacciones y no introduce imports de política desde componentes visuales.
- `G1-04`: CI rechaza manifest ausente, dependencias falsas, SHA ajeno, test omitido y bypass; check remoto obligatorio probado.

Aceptación: revisión del diagrama de llamadas y pruebas negativas, no solo conteo de tests; fallar G1 bloquea nueva autonomía.

### M2 — Shell y Python bajo la misma frontera de efectos

Trabajo: implementar backend seleccionado con probe operativo (no solo `which bwrap`), staging sin enlaces escribibles al original y manifiesto completo.
Restringir filesystem, red, descriptores heredados, environment, procesos, CPU, RAM y espacio; proteger metadata y secretos.
Medir efecto real al terminar; una etiqueta «read-only» no autoriza escrituras de subprocess.
Conectar herramientas tipadas y comandos a la misma promoción; no mantener un camino privilegiado por conveniencia.

- `G2-01`: fixtures shell, Python `os`/`pathlib` y herramienta tipada intentan borrar árbol y reescribir cientos de archivos; original intacto antes de promoción.
- `G2-02`: ataques symlink/hardlink/rename/TOCTOU, rutas `..`, root alias, submódulos y directorios montados no escriben fuera del staging autorizado.
- `G2-03`: `.git`, `.isyroot`, autoridad, vault, home sensible, journal y checkpoints inaccesibles para modificación; secretos no leíbles desde subprocess.
- `G2-04`: probe roto, namespaces denegados, backend ausente, disco lleno y salida excesiva terminan acotadamente; nunca fallback host.
- `G2-05`: tests legítimos con fixtures binarios, espacios y Unicode producen manifiesto correcto, sin pérdida de permisos/archivos.

Aceptación: al menos un ataque real ejecutado en sandbox del OS objetivo además de mocks; detallar qué OS carece de backend.

### M3 — Presupuesto persistente, promoción y recuperación

Trabajo: ledger fuera del checkout, identidad canónica, reservas serializables y reconciliación; límites finitos establecidos antes de autonomía.
Implementar promoción con precondiciones, backups protegidos y estados PREPARED/COMMITTING/COMMITTED/ROLLED_BACK/UNCERTAIN o equivalentes documentados.
No emitir éxito antes de verificación durable. Un journal fallido después del efecto produce estado incierto y detiene dependientes.
Capturar trabajo humano previo y detectar edición externa durante staging, promoción y undo.

- `G3-01`: mismo borrado masivo en 1 o 1000 llamadas, 3 reinicios y 8 workers alcanza idéntico límite sin excederlo; usar barreras para forzar carreras.
- `G3-02`: rename, alias, nueva sesión, ledger truncado/corrupto y reloj cambiado no resetean presupuesto ni habilitan efectos.
- `G3-03`: crash inyectado antes/después de cada paso durable recupera exactamente una transición o UNCERTAIN bloqueante; repetir 100 semillas registradas.
- `G3-04`: rollback conserva byte a byte dirty/untracked/ignored previos e índice staged; conflicto humano posterior queda intacto y visible.
- `G3-05`: backup lleno, ausente, corrupto o alterado no permite mutación sin recuperación; sandbox no puede borrar el ledger/backups.
- `G3-06`: solicitudes que exceden límite muestran alcance acumulado y requieren decisión humana específica; agente no puede ampliar ni resetear.

Aceptación: revisión independiente del orden de persistencia y ensayo de recuperación en filesystem declarado; una sola pérdida de trabajo falla G3.

### M4 — Confianza y modos sin fricción artificial

Trabajo: onboarding explica root real, modo, provider, envío de contexto y alcance de autonomía con lenguaje breve.
Carpeta desconocida, checkout importado, root movido o identidad ambigua no obtiene confianza automáticamente por contener AGENTS o `.isyroot`.
En proyecto ya confiable, Classic retoma el alcance vigente sin preguntas repetidas; permisos revocados prevalecen.
Classic permite leer/buscar/editar/crear/mover/borrar de forma recuperable dentro del presupuesto y ejecutar tests aislados sin modal por cada llamada.
Security parte apagado y requiere grants explícitos y aprobaciones de efectos según su perfil; cambiar a Classic es gesto humano, nunca tool del modelo.
Degradación granular: sin sandbox, mantener lecturas y ediciones tipadas que sí demuestren su frontera transaccional; deshabilitar comandos, no toda la app ni su contención.

- `G4-01`: tras onboarding, flujo ordinario de 10 lecturas, 5 ediciones pequeñas y 3 tests aislados tiene **0 aprobaciones por acción** en Classic.
- `G4-02`: exceder presupuesto, ampliar scope, leer secretos, cambiar autoridad o ejecutar sin backend bloquea o solicita frontera exacta; nunca aprobación genérica permanente.
- `G4-03`: mismo flujo en Security sin grants produce cero efectos; grants parciales habilitan solo su alcance; revocación funciona inmediatamente.
- `G4-04`: reabrir root confiable no repite onboarding; root distinto/importado y política inválida no heredan confianza.
- `G4-05`: ausencia de sandbox deja funcional el subconjunto demostrado y explica capacidades deshabilitadas sin sugerir bypass.

Aceptación: conteo de modales mediante harness y observación humana; «Turn on all tools» con modales por acción no pasa G4.

### M5 — Red, secretos y publicación externa

Trabajo: red cerrada para procesos de proyecto salvo capacidad específica; provider owner recibe solo su secreto y destino configurado.
No heredar todas las variables del host ni entregar keys a shell, tests, MCP o contenido del modelo.
Provider preseleccionado permite llamadas normales dentro de su scope, sin confirmación repetida; selección de un endpoint nuevo exige revisión de destino y datos.
Dependencias/downloads tienen capacidad separada, destino/recurso limitados y ejecución posterior aislada; no confundir instalar con conceder red universal.
Push, PR publicada, release, mensaje/email y escritura remota requieren confirmación humana del destino/contenido/digest o una autorización explícita equivalente, acotada y vigente.
Commit local se trata aparte: revisión del conjunto exacto y preservación del índice humano; no implica push.
Mantener grants independientes de Gateway/MCP/Bridge y no convertir leases ni credenciales en autoridad local.

- `G5-01`: key canario aparece únicamente en transporte de provider permitido; cero ocurrencias en subprocess, logs, recibos, sesiones o otro proveedor.
- `G5-02`: redirect entre origins, proxy, DNS rebinding y destino privado inesperado no amplían scope; capturar tráfico con fixture controlado.
- `G5-03`: `curl`, Python socket, build hooks y MCP no exfiltran desde sandbox ni usan provider como proxy genérico.
- `G5-04`: push/publicación/envío sin autorización no sale; cambiar payload/destino invalida aprobación; rechazar no genera efecto externo.
- `G5-05`: caída/revocación de servicio no activa otro provider, credencial, endpoint o owner implícitamente.

Aceptación: fixtures de red y secretos canario, nunca credenciales reales en artefactos; prueba viva opt-in solo con scope y gasto autorizados.

### M6 — Bucle fiable, cancelación y retry

Trabajo: separar render/stream del estado durable de operaciones; controlar lifecycle de subprocess y workers.
Esc cancela la petición, herramientas y descendientes; detener polling/retries y promover solo resultados verificados.
Retries de transporte no repiten efectos: persistir operation ID, reconciliar estado y usar idempotencia remota solo cuando esté documentada y probada.
No prometer exactly-once universal: sin soporte remoto o con respuesta perdida, mostrar UNCERTAIN y exigir reconciliación antes de repetir.
Tras restart, una tool note es historial no confiable, no una orden pendiente que se ejecuta sola.

- `G6-01`: cancelar durante stream, staging, promoción, hijo y nieto no deja procesos del trabajo; verificar desde fuera del sandbox.
- `G6-02`: perder respuesta después del efecto y reintentar/reabrir produce un solo efecto o bloqueo UNCERTAIN, nunca duplicación silenciosa.
- `G6-03`: kill del owner y restart conservan reserva/recibo y reconciliación; no descuentan saldo ni repiten publicación dos veces.
- `G6-04`: streams truncados/tool calls incompletos no ejecutan; retry preserva borrador nuevo y orden del transcript.
- `G6-05`: backoff acotado con jitter y cancelación, sin tormenta de reintentos; fallos de provider no cambian autoridad.

Aceptación: tabla de puntos de interrupción y estado final observado; efectos inciertos impiden dependientes aunque la TUI siga usable.

### M6A — Agentes en segundo plano observables y dirección durante el trabajo

Objetivo: ver qué hacen los agentes desde la sidebar y corregirlos mientras trabajan, sin esperar a que termine toda la tarea.
Reutilizar [subagents.py](../src/isycode/subagents.py), [subagent_screen.py](../src/isycode/subagent_screen.py), [agent_tasks.py](../src/isycode/agent_tasks.py) y sus contratos antes de crear otro supervisor.
Extender [test_subagents.py](../tests/test_subagents.py), [test_agent_tasks.py](../tests/test_agent_tasks.py) y [test_side_panel.py](../tests/test_side_panel.py); las pruebas adicionales de cola/eventos siguen pendientes.

**Actividad pública estructurada, no pensamiento privado.** El runtime emite eventos verificables de inicio, progreso público, herramienta, cambio, test, espera, error y finalización.
No capturar ni exigir chain-of-thought, ni fabricar «pensamientos» a partir de herramientas o tokens.
Un JSONL durable y sanitizado puede ser el registro; bus de eventos interno o SSE puede transportar novedades al renderer.
No analizar puntos finales de frases ni JSONL de razonamiento para decidir cuándo aceptar instrucciones.
Un token emitido no es contexto editable y un stream del provider no es un canal de control del runtime.

Contrato de evento versionado: `event_id`, `sequence`, `task_id`, `run_id`, `parent_run_id`, timestamp, tipo, estado y payload público acotado.
El owner produce eventos de efecto y verificación; el modelo puede aportar resumen público etiquetado, pero nunca certificar éxito por sí mismo.
La UI suscribe por cursor y reconstruye snapshot + deltas tras reconectar; detectar huecos, duplicados y eventos de otro run.
Persistir eventos antes de declararlos recibidos cuando el contrato prometa durabilidad; no prometer entrega durable de texto efímero.
Retención, rotación, cuota, redacción y backpressure se fijan explícitamente: agrupar progreso ruidoso, jamás perder estados terminales, errores o acuses sin avisar.
Si el log está corrupto o lleno, marcar estado degradado y aplicar fail-closed a efectos que requieren recibo; no bloquear Esc tras un buffer lleno.
Polling cada **1–5 s** es fallback configurable con cursor, backoff al estar inactivo y antigüedad visible, no el mecanismo preferido ni una garantía de entrega instantánea.

Sidebar: todos los hijos del trabajo actual, relación padre/hijo, nombre/objetivo, estado y última actividad pública.
Estados diferenciados: queued, running, waiting-input, waiting-permission, cancelling, cancelled, failed, uncertain y completed.
Cada fila se expande para herramientas y salidas redactadas/acotadas, archivos cambiados, tests reales, errores y coste reportado cuando exista; si falta coste mostrar «desconocido», no cero.
Acciones accesibles con teclado: abrir detalle, enviar corrección al hijo seleccionado y cancelar; mostrar destino inequívoco antes de enviar.
El padre sintetiza resultados de hijos sin confundir terminar un proceso con completar una tarea verificada.

**Cola neutral respecto al provider.** Mensaje persistente con `message_id`, secuencia, task/run destino, emisor, intención y contenido sanitizado; autoridad del emisor validada por runtime.
Distinguir tres acciones visibles: **siguiente turno** (no modifica trabajo activo), **corregir tarea activa** y **cancelar**.
La corrección se acepta durante el trabajo y se aplica en la primera frontera segura soportada: fin de herramienta, antes de la siguiente llamada al modelo o punto explícito de cooperación.
Durante generación solo interrumpir/cancelar y reanudar si el adapter lo soporta; si no, mantener «pendiente de frontera segura» con motivo visible.
Nunca insertar instrucciones dentro de argumentos JSON de una tool call en curso; descartar frames incompletos si se interrumpe.
El stop urgente es un canal prioritario de cancelación del árbol, no un mensaje que espera puntuación, polling o fin de una herramienta larga.

Acuses públicos separados: `queued` (persistido), `received` (runtime destino lo reconoce), `applied` (incorporado en frontera identificada) y `rejected` (motivo).
No llamar «aplicado» a algo solo dibujado en la UI. Registrar frontera/operation ID y mensaje consumido para evitar doble aplicación tras crash.
Orden por destino, dedupe por ID, política explícita para secuencias ausentes y replay idempotente tras restart; mensajes hacia run cerrado se rechazan o el usuario los redirige, nunca migran en silencio.
Padre/hijo no se atribuyen autoridad por enviar mensajes: revocación y grants se reevalúan al aplicar y antes del efecto.
Una corrección puede reducir alcance o cambiar intención; ampliar permisos, egress o presupuesto sigue requiriendo su frontera humana protegida.
Cancelar o corregir no deshace automáticamente una publicación ya enviada: conservar UNCERTAIN y reconciliar según M6 antes de reintentar.

- `G6A-01`: 8 agentes concurrentes publican 100 eventos cada uno; sidebar muestra todos, relación padre/hijo, estados correctos y detalle expandible sin mezclar runs.
- `G6A-02`: duplicar, desordenar, perder conexión y reiniciar entre persistencia/acuse/aplicación no pierde instrucciones aceptadas ni las aplica dos veces; huecos y rechazos son visibles.
- `G6A-03`: corrección durante stream JSON parcial no ejecuta JSON inválido ni fusiona argumentos; se aplica una vez en primera frontera soportada y se registra esa frontera.
- `G6A-04`: enviar siguiente-turno, corrección y stop produce comportamientos distintos; stop durante herramienta larga cumple G9-03 y limpia descendientes sin esperar al siguiente evento.
- `G6A-05`: revocar permiso mientras un mensaje espera impide el efecto; ruta a otro workspace/hijo no autorizado falla; efecto externo incierto no se reenvía automáticamente.
- `G6A-06`: canarios de secretos en errores, comandos y salidas no aparecen en JSONL/sidebar; carga de 10 000 eventos con consumidor lento respeta cuotas, conserva terminales/acuses y deja la UI cancelable.
- `G6A-07`: en entorno local fijado en M0, 100 muestras: display de evento p95 ≤1 s y acuse received de cola p95 ≤1 s con bus operativo. Aplicación en la primera frontera segura soportada, sin prometer ≤1 s para herramientas largas.
- `G6A-08`: fallback polling medido cumple intervalo configurado + latencia de transporte medida; UI muestra antigüedad, pending y reconexión. Backoff e intervalo efectivo nunca se ocultan al usuario.

Aceptación: trazas sanitizadas correlacionan event/message/task/run IDs, emisión, persistencia, recepción, frontera y render; ensayar provider sin interrupción y adapter con interrupción real por separado.
Un mock no acredita soporte mid-generation de un proveedor. Registrar garantías de cada adapter y degradar a cola en frontera segura donde no exista soporte.
La extracción modular del panel/cola continúa M1; el pulido visual se integra en M8 y el stress/latencias se repiten en M9.

### M7 — Trabajo cotidiano de extremo a extremo

Trabajo: conectar leer/grep, editar/crear/mover/borrar, test/build/lint, diff/undo, git y sesiones mediante los contratos ya aprobados.
Exponer resultados y decisiones del owner al agente sin hacerle inferir éxito de texto informal.
MCP/LSP/skills opt-in muestran estado real y no cambian permisos; proyectos grandes reciben resultados navegables sin bloquear la TUI.

- `G7-01`: fixture repo sucio: diagnosticar fallo, editar 3 archivos, ejecutar tests, revisar diff y undo; preservar trabajo inicial y cero modales ordinarios en Classic.
- `G7-02`: mover/borrar dentro de presupuesto y provocar cascada excesiva; primero recuperable, segundo bloqueado antes de promoción.
- `G7-03`: repetir workflow en Security con grants parciales; sin permiso no ejecutar y explicar acción habilitable exacta.
- `G7-04`: diff/commit selecciona solo archivos autorizados, mantiene cambios staged ajenos y no ejecuta hooks fuera de contención.
- `G7-05`: tools disabled, LSP ausente, MCP caído y provider sin tool support producen diagnóstico honesto y no falso «listo».

Aceptación: transcripción sanitizada + hashes inicial/final + journal + salida de tests; mocks y provider vivo se etiquetan separados.

### M8 — UX pulida y accesible

Trabajo: continuar modularización por componentes (composer, transcript, diffs, tareas, navegación), sin mover política a widgets.
Jerarquía: conversación dominante, composer estable, estado compacto, detalles expandibles; panel Tasks colapsable con tarea actual y progreso verificable.
Diffs muestran agregado/eliminado, archivo y efecto; cambios autónomos dejan recibo y undo visible, no modal artificial.
Confirmaciones de frontera muestran por qué, qué cambiará y alcance; rechazo por defecto y sin aceptar por teclas arrastradas.
Teclado completo, foco visible, ayuda contextual, copy seguro y scroll que respeta lectura anterior; distinguir error/bloqueado/incierto/éxito sin depender solo del color.

- `G8-01`: recorrido completo solo teclado, sin foco atrapado; Esc cancela correctamente, Enter no acepta frontera accidentalmente.
- `G8-02`: capturas y resize real a 80×24, 120×40 y 200×60; composer/acciones esenciales visibles, sin overlap ni pérdida del borrador.
- `G8-03`: tema por defecto con contraste objetivo ≥4.5:1 para texto normal y ≥3:1 para indicadores; documentar colores efectivos y límites del terminal.
- `G8-04`: 1000 eventos de herramientas mantienen orden, scroll manual, selección y estado de Tasks; ningún resultado fallido se muestra completado.
- `G8-05`: recibos compactos expanden decisión, paths seguros, presupuesto restante y recuperación; canarios de secretos ausentes incluso en errores.

Aceptación: snapshots automatizados más revisión en terminal real; un snapshot aislado no prueba foco, teclado ni resize.

### M9 — Matriz adversarial, rendimiento y dogfood

Trabajo: ejecutar puertas sobre release candidate con backend real; agregar fixtures pequeños/grandes, dirty/untracked, sin Git, symlinks y concurrent workers.
Matriz mínima: Classic/Security × backend operativo/ausente/roto × Python 3.10/3.12 Linux; smoke Windows/macOS y fallback explícito donde no haya backend validado.
Incluir red caída, journal/ledger corruptos, disco lleno, provider lento, crash y salida hostil/inyección ANSI.
Entorno de referencia a declarar antes de medir: OS/kernel/filesystem/backend/terminal, CPU, RAM, storage, versiones, tamaño repo y red/provider.
Objetivo inicial local: Linux, 4 cores, 8 GiB RAM, SSD, 10 000 archivos/100 MiB; M0 registra hardware real equivalente y diferencias, sin inventar mediciones.

- `G9-01`: todos los IDs anteriores vigentes PASS; cero skips críticos, escapes, pérdidas de trabajo o filtraciones de canarios.
- `G9-02`: 30 arranques warm: p95 a composer usable ≤2 s; interacción teclado p95 ≤100 ms; no atribuir latencia del provider a la UI.
- `G9-03`: 30 cancelaciones: p95 reconocimiento UI ≤250 ms y árbol terminado ≤2 s; documentar timeout duro y estado incierto excepcional.
- `G9-04`: soak ≥2 h y ≥100 ciclos con 3 restarts: sin procesos huérfanos ni pérdida; RSS final ≤baseline warm +25% y ≤500 MiB en fixture declarado.
- `G9-05`: 5 participantes realizan 3 tareas: ≥4/5 terminan cada una sin ayuda, mediana onboarding ≤2 min con credencial ya disponible, cero modales ordinarios tras trust.
- `G9-06`: al menos un flujo vivo con provider autorizado; registrar modelo/latencias/errores/coste disponible, sin extrapolar soporte a todos los providers.

Aceptación: raw measurements, percentiles y metodología, no solo promedios; objetivos son futuros y no resultados obtenidos.
Si no hay participantes, backend o credencial autorizada, gate correspondiente sigue BLOQUEADO; no sustituir humanos por un modelo sin cambiar y revisar alcance.
Una meta inviable exige revisión explícita previa de alcance/criterio y nueva medición, nunca rebajar después para pintar verde.

### M10 — Publicación gradual y rollback demostrado

Trabajo: validar migraciones de autoridad, ledger, sesiones y checkpoints; opt-in de autonomía al principio, sin cambiar silenciosamente workspaces Security.
Preparar release notes de capacidades y plataformas realmente verificadas, limitaciones y recuperación; integraciones no validadas permanecen deshabilitadas.
Feature flag protegido puede apagar autonomía sin perder backups ni registro; no puede saltar gates ni activar ejecución host.
Ensayar rollback del binario y estado: si schema no admite downgrade, modo read-only y migración explícita, no corrupción ni reset.

- `G10-01`: instalar/actualizar/cancelar actualización desde versión anterior conserva grants, revocaciones, sesiones y trabajo sucio.
- `G10-02`: rollback ensayado con operación UNCERTAIN conserva evidencia y permite reconciliar; versiones incompatibles fallan cerradas.
- `G10-03`: CI/protección de release impide publicar con un gate obligatorio fallido/reabierto o evidencia vieja; ensayar bloqueo.
- `G10-04`: revisor coteja release candidate, artefactos, SHA y alcance; seguridad y UX firman aceptación y riesgos residuales visibles.

Aceptación: release solo con G10 aprobado. Si aparece regresión, detener rollout, reabrir puerta, deshabilitar capacidad afectada y repetir gates impactados.

## 6. Evidencia y aceptación por hito

Ruta de evidencia: `docs/evidence/classic-security-ux/<hito>/<sha>/`. M0 ya tiene una carpeta para el SHA medido. Los hitos siguientes no. Esa carpeta no certifica la puerta. No guardar secretos, home completo ni dumps de credenciales.
Los nuevos archivos de tests/validator son entregables futuros: elegir sus rutas al implementar y registrar comando/node ID exacto.
Cada caso debe probar también ausencia de efectos indebidos, no únicamente que salió un mensaje de error.
Conservar checksums del workspace y procesos/tráfico cuando sean relevantes; nunca usar datos personales para fixtures.

```yaml
hito: Mx
puerta: Gx
estado: EN_REVISION
sha_evaluado: <commit completo>
fecha_utc: <fecha>
autor: <identidad>
entorno: <OS, kernel, filesystem, sandbox, Python, Textual, terminal, hardware>
perfil_y_politica: <modo, trust, version, limites y grants sin secretos>
dependencias: <gates, SHA y enlaces a aceptaciones>
casos:
  - id: Gx-01
    prueba: <ruta::node_id o protocolo manual reproducible>
    comando: <invocacion exacta sanitizada>
    esperado: <efecto permitido y efectos que deben estar ausentes>
    observado: <resultado, exit code, duracion, hashes antes/despues>
    resultado: <PASS|FAIL|UNKNOWN|SKIP>
    artefactos: <enlaces + digests de logs/capturas/recibos>
    correlacion: <event/message/task/run IDs y frontera segura, si aplica>
regresion: <suite, resultado y skips explicados>
riesgos_residuales: <limites y capacidades no soportadas>
rollback_ensayado: <procedimiento, evidencia y compatibilidad>
revision: <identidad distinta, fecha, SHA revisado, aprobado/rechazado y razones>
```

Checklist del revisor: verificar dependencias, reproducir un positivo y un negativo crítico, revisar tests contra amenazas y callsites, buscar bypass de shell/Python, inspeccionar evidencia sin secretos, comprobar preservación de trabajo humano y probar rollback.
Registrar discrepancias y devolver a EN CURSO/BLOQUEADO; un autor no declara revisión independiente en nombre de otro.
Los artefactos CI y aceptación viven ligados al código probado; el mero fichero YAML anterior no es certificación.

## 7. Handoff para cualquier agente y siguiente paso

**Próximo paso: G0, G1, G2, G3, G4, G5 y G6 siguen EN REVISIÓN. Ninguna puerta está APROBADA. Los push del producto de M6 (`a495361`) y de su evidencia (`c339060`) imprimieron `Bypassed rule violations`: los tres checks siguen exigidos y `enforce_admins` sigue apagado. El propietario pidió seguir con la implementación; eso no convierte estas puertas en APROBADO. La evidencia de M6 está en [docs/evidence/classic-security-ux/M6/a495361cf04393c20278192155e9dffcdd60e5e2/](evidence/classic-security-ux/M6/a495361cf04393c20278192155e9dffcdd60e5e2/gate.yaml). El siguiente trabajo de producto es M6A (agentes observables e instrucciones en cola). M6 no abrió el bucle de agente.**

```text
Trabaja en ISyCode siguiendo docs/roadmap-classic-security-ux.md.
1. Lee AGENTS.md, git status/branch/remotes y las instrucciones aplicables.
2. Preserva cambios ajenos; identifica baseline y evidencia del ultimo gate.
3. Selecciona el primer hito cuyas dependencias esten APROBADAS.
   M0, M1, M2, M3, M4, M5 y M6 están EN REVISIÓN: no los marques APROBADOS ni los reabras como si no hubiera evidencia.
4. Reutiliza owners y contratos existentes; verifica fuentes antes de proponer duplicados.
5. Ejecuta sus IDs de aceptacion y regresiones pertinentes con SHA y entorno.
6. Si falla una prueba obligatoria, para dependientes y corrige o registra BLOQUEADO.
7. Guarda evidencia sanitizada y solicita revision del resultado concreto.
8. Solo tras aceptacion verificable cambia estado; no confundas docs con implementacion.
9. Para agentes/colas, verifica G6A: actividad publica, acuses y frontera segura;
   nunca uses pensamiento privado ni puntuacion como canal de control.
10. Reporta archivos, pruebas reales, riesgos, rollback y siguiente hito habilitado.
No elimines tests, no ocultes skips, no uses shell host como fallback y no borres trabajo humano.
```

Antes de cada entrega:

- [ ] Dependencias y SHA comprobados; alcance y exclusiones explícitos.
- [ ] Cambios pequeños; modularización incremental; ningún bypass de owners.
- [ ] Pruebas positivas, negativas, crash/concurrencia y evidencia requerida completas.
- [ ] Dirty/untracked/staged preservados; secretos ausentes; estado incierto visible.
- [ ] Revisor acepta el gate; limitaciones/rollback documentados.
- [ ] Si hay regresión, gate REABIERTO y dependientes/releases bloqueados.
- [ ] Commit solo de archivos propios; publicación conforme a autorización y sin force push.

La confianza se gana con límites comprobables y recuperación real, no con prometer que el agente nunca se equivocará.
