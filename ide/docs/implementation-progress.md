# ISyCode IDE — progreso

Plan: `docs/superpowers/plans/2026-10-10-isycode-ide.md`.
Spec: `docs/design/SPEC.md`.

## Cierre — 2026-10-11 UTC

Tasks 1–9 completas para el alcance v1 del plan. La suite completa del árbol
final terminó con **203 passed**, exit 0; log y SHA-256 públicos en
`docs/verification/full-suite-delivery-0540.*`. El reviewer independiente examinó
`71d25cf..9728919`; sus cuatro hallazgos Critical/Important y el Minor se
corrigieron en una pasada. Once regresiones RED→GREEN y una guarda adicional
para cambios de upstream; detalles y rulings en `docs/verification/final-review.md`.

El AppImage final `dist/ide-20261011T051159Z-237f93/` pasó self-check Qt/namespaces.
Launcher `/home/danny/.local/bin/isycode-ide`, entrada de menú e icono propios
instalados aditivamente; checks de launcher/TUI/accounts y desktop validados.
Evidencia, fuentes y hashes en `docs/verification/release-installation.json`
y `package-manifest.json`. Capturas reales de la versión final en
`qt-release-final/`; escala 2 en `qt-hidpi-final/`. Proyectos/contenido de ejemplo.

Ruling de finishing-a-development-branch: conservar rama `codex/isycode-ide`
y checkout `ISyCode-IDE`, conforme a la decisión inicial de preservar IsyVM y
al alcance de entrega local. No se requiere elegir integración para usar el
producto instalado; no se publica ni se mezcla el original. Se preserva el
workspace de la skill y la evidencia porque el contrato prohíbe su borrado.

Cuentas/generación OAuth/API reales y repos privados del usuario:
**NOT_DEMONSTRATED**. Las conexiones se configuran en Providers; no se deduce
login ni entitlement de tener un CLI instalado. V1 no incluye merge/rebase,
MCP externos, browser ni marketplace. Todas las secciones siguientes documentan
el progreso histórico; sus pendientes anteriores se resuelven en este cierre.

## Decisiones

- Ruling: crear un worktree `ISyCode-IDE` con snapshot de los cambios previos;
  conservar `IsyVM` intacto. Evita un movimiento destructivo del checkout.
  Coste: el directorio antiguo continúa existiendo hasta decidir su retiro.
- Ruling: conservar Qt nativo; las recomendaciones web de image-to-code no
  aplican a este producto. Coste: capturas y revisión visual requieren Qt.
- Ruling: no añadir ni ejecutar tests sin petición del usuario, conforme a la
  instrucción del desarrollador; prevalece sobre TDD de la skill. El plan de
  verificación queda registrado; no marcar fases como verificadas por ello.
- Ruling: conservar el workspace de la skill y evidencia; su limpieza automática
  está subordinada al presupuesto de eliminación cero del contrato de usuario.

## Dependencias entre fases

1 → 2/3/5: las rutas nuevas y la escritura atómica se comparten.
2 → 3/6/7: configuración pública separada de secretos y snapshot por turno.
3/4/5 → 7: eventos tipados alimentan tarjetas; widgets no conceden autoridad.
4 → 5: cambios en la copia aislada se convierten en propuestas.
6 → 4: conectores solo pueden invocar herramientas del host habilitadas.

## Estado

- Preparación: worktree creado en rama `codex/isycode-ide`; snapshot de origen
  `71d25cfdd5c90d9201e08f68ac54df9342697cbd`.
- Plan y referencias: guardados en este checkout.
- Implementación y revisión final: en curso.
- Verificación automatizada y cuentas reales: NOT_DEMONSTRATED.

## Implementación de este tramo

- Entrada `isycode_ide`, distribución `isycode-ide` y nombre Qt ISyCode IDE;
  alias antiguos conservados sin registrar el comando oficial `isycode`.
- Rutas globales/proyecto propias, escrituras atómicas y bloqueo de metadata.
  Migración explícita de providers y estado conocido del proyecto, con hashes,
  conflictos y origen conservado. Credenciales y permisos no se migran.
- Broker keyring/memoria; eliminado el fallback nuevo en texto plano. Importador
  API compartido que descarta OAuth y no expone valores en resultados.
- Catálogo API/local, formularios editables, consulta de modelos cancelable,
  diagnóstico HTTP sin bodies sensibles y configuración capturada por turno.
- Clientes por event loop, cierre y cancelación; modelo seleccionado respetado;
  streaming estructurado OpenAI/Anthropic y protocolo de herramientas Google.
- SQLite de conversaciones y servicio compartido GUI/TUI; historial de mensajes
  y wire separado del residente, turno único por sesión y estado interrumpido.
- Panel para reabrir conversaciones en Qt; guardas al cambiar sesión/proyecto;
  nueva conversación espera a que termine la cancelación anterior.
- Ruling: bloquear el transporte Claude CLI legado hasta implementar el conector
  restringido — sus herramientas nativas eluden la autoridad del IDE — coste:
  la suscripción Claude no se puede usar en este tramo; Anthropic API sí queda
  configururable y no se presenta como equivalente a una suscripción.

Análisis estático: las fuentes Python cambiadas fueron leídas por `ast.parse`,
sin ejecutar la aplicación. Esto no demuestra comportamiento ni integración.
No hay fases marcadas completas ni afirmación de tests pasados.

Instalación: entorno `.venv` propio y paquete editable con extra `ui` instalados
con exit 0. Log completo y hash en el workspace de la skill. Los hashes de los
archivos preservados del checkout original siguen coincidiendo con el snapshot.
No se lanzó la GUI ni se probaron conexiones reales.

Siguiente trabajo: transporte Ollama/Google con eventos completos; revisión de
persistencia/eventos y TUI; propuestas y pipeline de autoridad común; comandos
aislados y grants; conectores; shell visual aprobado; empaquetado y validación.

## Segundo tramo: autoridad y propuestas

- `ToolExecutionService` comparte las consultas de política, modo y runtime
  entre agente y acciones explícitas del editor. El callback de Qt observa y
  solicita la decisión; no ejecuta una escritura directamente.
- Switches persistentes por proyecto y catálogo derivado de las herramientas
  implementadas. Se consultan al ofrecer herramientas y al ejecutarlas; una
  escritura vuelve a consultar switch/policy tras esperar aprobación.
- `ProposalService` prepara diff y base SHA-256 antes de mostrar la aprobación;
  los argumentos que recibe el callback son otra copia. Cambiarlos no altera
  la propuesta que se aplica. Identificadores de aprobación creados por el host.
- Aplicación atómica de un archivo con journal de estados y comprobación de base;
  rechazo/cancelación conservados. Panel Cambios para inspeccionar el historial.
- Modal de revisión en la TUI incluida; Qt muestra ruta/base y aprobación única.
  Las tarjetas pendientes se desactivan al terminar el worker.
- Guardado del editor consulta política y hash de su snapshot; lectura conserva
  CRLF para calcular el hash de los bytes originales. Recargas del agente
  respetan el texto sin guardar. Cambiar provider actualiza también el modelo
  real de la TUI; cambiar modo durante un turno conserva el modo capturado.
- Metadatos del host excluidos de read/write/glob/grep. `python` no se ofrece ni
  ejecuta hasta tener runtime aislado. `verify` inspecciona contratos internos;
  no presenta éxito de ejecución como prueba de corrección del proyecto.
- Ruling: Guardar del editor identifica actor HOST y consentimiento explícito;
  PLAN y switches controlan al AGENTE. Política y comprobaciones de ruta/base
  siguen aplicándose al editor. Coste: distinción documentada entre ambos actores.

Evidencia estática: `.superpowers/sdd/2026-10-10-isycode-ide/authority-static.json`
registra SHA-256 de las fuentes leídas por `ast.parse`, sin importar ni ejecutar
la app. No se añadieron ni ejecutaron tests. Comportamiento GUI/TUI:
NOT_DEMONSTRATED. Sin borrados ni movimientos de archivos.

Task 4 sigue en curso: pendiente agrupar varios archivos con recuperación de
fallos parciales y eventos persistentes por propuesta/turno. El servicio actual
solo garantiza la operación de un archivo frente a participantes del lock;
no es un CAS contra un proceso hostil que muta el sistema de archivos en carrera.
Task 5 y permisos permanentes de comandos siguen pendientes; no se muestra
un botón funcional de permiso permanente hasta tener su runtime y GrantStore.

## Ampliación GitHub

El usuario pide continuar hasta acabar y añade repos propios de GitHub con gh
verificado, vínculos a carpetas y aviso de commits pendientes de pull. Se añade
Task 9 al plan y su comportamiento al spec. El diseño conserva la referencia
Conversación aprobada y añade una vista GitHub. Datos del mockup ficticios.

- Ruling: generar un mockup singular, conforme al pedido «un mockup», en vez
  de tres alternativas de la skill ideate. Conservar estilo aprobado; no abrir
  otro proceso de selección que detenga las fases ya autorizadas. Coste: menos
  alternativas visuales; el usuario puede ajustar esta vista al verla.
- Contadores de rama y cambios locales se muestran por separado. Pull es una
  acción explícita con avance directo y revisión de archivos; no se interpreta
  «1:1» como permiso para resetear, limpiar o eliminar datos del usuario.

### Implementación GitHub

Catálogo paginado mediante la identidad activa de gh, vínculos explícitos por
remoto, inspección del upstream, comprobación individual/de todas las carpetas,
commits entrantes y comparación de archivos. La actualización prepara un
manifiesto, requiere consentimiento concreto y revalida base/remoto antes de
`merge --ff-only`. Tiene journal previo a la operación y conserva fallos como
`review_required`, sin reset de recuperación. Cuenta cambiada, filtros Git,
submódulos, metadatos versionados y checkouts no soportados producen un estado
visible. El worker es cancelable para consultas; cerrar espera una actualización
ya iniciada. Agente y operación Git del panel se esperan dentro de esta ventana.

La GUI incluye el panel y la apertura de una carpeta vinculada con guarda de
borradores. Su integración en el shell visual final sigue en Task 7. No se
consultó ninguna cuenta ni se hizo fetch/pull en repositorios reales durante
este trabajo. `.superpowers/sdd/2026-10-10-isycode-ide/github-static.json` registra
solo lectura AST y SHA-256 de fuentes. Comportamiento y recorridos:
NOT_DEMONSTRATED. No se añadieron ni ejecutaron tests.

## Shell Qt aprobado — implementación

`DesktopShell` incorpora navegación fija adaptable, proyecto/conversaciones,
chat e inspector Editor/Cambios/Diff. Conversación y Código + chat reordenan los
mismos widgets y conservan sesión/borrador. Providers y GitHub tienen pantallas
amplias; las pantallas técnicas tienen cabeceras comunes. Sistema agrupa estado,
policy y residente; Ajustes permite preferencias y migración explícita.

Iconos vectoriales coherentes y paleta carbón/cian. Barra con gato, proyecto,
identidad/tipo de provider, modelo y selección PLAN/CODER. Se conserva préstamo
de paneles a ventanas. Los datos GitHub del proyecto aparecen con fecha y estado.
El medidor usa estimación de texto sin un denominador de contexto inventado;
el residente no se muestra como un servicio online sin evidencia.

- Ruling: sustituir el antiguo contrato visual de un único botón en la barra
  por el shell y los selectores aprobados por el usuario. No conservar recortes
  del cajón antiguo como límite del nuevo diseño. Coste: los tests históricos
  de la estructura visual requieren revisión cuando se autorice verificarlos.

Task 7 sigue en curso: comparación Qt/PNG, recorridos, estados y tarjetas de
comandos/propuestas agrupadas pendientes. Lectura de fuente por AST únicamente;
no se ejecutó Qt, no se añadieron tests, comportamiento NOT_DEMONSTRATED.

## Verificación habilitada tras continuar el trabajo

La instrucción más reciente del desarrollador requiere ejecutar checks
apropiados al cambio y permite tests necesarios. Sustituye la restricción
previa de no ejecutar tests sin petición. Se conserva aquella decisión como
historia del tramo anterior; ahora se comprueban los nuevos servicios y Qt
con estado privado y repos de prueba. Los resultados se registrarán con
salida completa, comando y SHA-256; ninguna fase se declara completa por AST.

## Propuestas agrupadas, comandos y verificaciones locales

Changeset inmutable con comprobación previa de todas las bases, journal antes
y después de cada archivo y recuperación explícita mediante otra propuesta.
Los archivos nuevos permanecen. Eventos de propuesta/decisión persistidos en
SQLite y resúmenes de decisiones visibles al reabrir la GUI.

Runtime Linux obligatorio con namespaces, tmpfs y entradas filtradas; salida
del comando convertida en otra propuesta. Grants exactos y revocables; nunca
autorizan aplicar archivos. Pruebas usa la autoridad común, sustituyendo su
ejecución anterior directa en el host.

- Ruling: RLIMIT_NPROC 4096 por UID — el límite de 128 contaba los hilos ya
  existentes del escritorio y fallaba con EAGAIN antes de ejecutar. Control
  con el mismo perfil y 4096 funcionó. Coste: techo por UID amplio; no es una
  cuota agregada por comando ni una garantía de recursos basada en cgroups.
- Ruling: comprobar atributos efectivos de filtros Git en los árboles actuales
  y entrantes — registrar LFS globalmente no significa usarlo en cada repo.
  Coste: Git check-attr --source requiere soporte moderno; versiones sin él
  rechazan el preview de pull en lugar de invocar filtros sin revisión.
- Ruling: las pruebas locales aquí siguen la solicitud de auditoría y §12 del
  contrato AGENTS del usuario. Las reglas históricas anteriores se conservan
  como registro del tramo donde todavía no se ejecutaban pruebas.

Verificación 10 octubre: `ide-authority-github-qt-020524.log` registra 21 tests
con exit 0. Comando/SHA-256 en el JSON homónimo del workspace privado. Incluye
aislamiento real (red/env/home/escritura), permiso permanente con rechazo de
archivos, fallos de namespaces sin fallback, Git real con red de fixture,
actualización sin hooks, base cambiada y widgets Qt offscreen. El sondeo fallido
del límite anterior permanece en `linux-profile-233953.log`. No se consultaron cuentas reales.

Capturas Qt reales con archivos ficticios: anchos 1024, 1366 y 1920, vistas
Conversación, Código y Providers. Detectaron y corrigieron la bandera hidden
del panel de conversaciones y selección de navegación obsoleta. Revisión del
resto de menús, HiDPI, cancelación de descendientes y casos adversariales amplios
siguen pendientes; Task 4/5/7/9 no se declaran totalmente completas todavía.

Ollama y Google ya usan streaming estructurado, tras reproducir el fallback
anterior con tests HTTP de fixture. Google conserva thoughtSignature y Ollama
su wire nativo de herramientas. Fuentes: documentación oficial Ollama Streaming
y Google Thought signatures. Generación en servicios/cuentas reales pendiente.

## Cierre de implementación local

Task 6: conectores privados Codex/Claude/Grok, preparación del ejecutable,
login/logout/inspección explícitos y conexión guardada desde Qt o accounts CLI.
Codex usa HTTP oficial en su perfil propio, sin modificar el routing global.
Transporte app-server probado con proceso fixture: solicitud dinámica devuelta
al host, acción nativa rechazada, cuenta API rechazada y cancelación con reap.
Inspección sin sesión de los CLIs instalados: sin autenticación. Generación
y OAuth con cuentas reales: NOT_DEMONSTRATED.

Task 3: selector /sessions, /resume y /clear aditivo en TUI; el arranque muestra
historial. Estado compartido y metadatos de autenticación conservados al cambiar
el modelo. Migración comprobada contra idempotencia, conflictos y origen intacto.

Task 7: pantallas Qt capturadas en tres tamaños y escala 2. Un timer de copiar
podía ejecutar su callback después de destruir la respuesta; reproducción
RED y reparación mediante QTimer con parent. Los widgets de chat/editor se
conservan al cambiar vista.

Task 8: builder aditivo con output nuevo, identidad/desktop/icono propios,
PyInstaller + AppDir + AppImage. El paquete comprobó Qt y namespaces Linux
sin cuentas. Appimagetool anterior instalado no tenía SquashFS legible; se
conservó y se descargó otra copia oficial en el build propio, comprobando el
digest SHA-256 publicado por GitHub. Runtime también fijado por digest.

- Ruling: tests históricos migrados a los contratos aprobados de configuración
  vacía, nombre/estado propio y shell nuevo, manteniendo controles de paths,
  PLAN y host approval. El transporte Claude legado permanece deshabilitado.
- Ruling: todas las pruebas ahora usan estado global y keyring fixture por
  test. La primera suite histórica usaba credenciales de prueba en el namespace
  nuevo; su log privado queda preservado. Ningún login global se importa.
- Ruling: Grok presenta sesión almacenada sin prometer validación del servidor;
  su transporte depende de la compatibilidad del endpoint de sesión TUI.
- Ruling: cuentas reales no disponibles en perfiles propios: se entrega setup
  explícito y controles locales; OAuth/generación real quedan NOT_DEMONSTRATED,
  como admite Task 6. No llamar a modelos ni usar tokens globales para simularlo.

Suite completa local: 179 passed (raw/hash en docs/verification/full-suite-0310.*).
Revisión final independiente pendiente antes del cierre de la rama.

Recorrido completo Qt con servidor HTTP SSE local de prueba: prompt, solicitud
de write, aprobación/rechazo, respuesta posterior, recibo y reapertura del
historial. Ambas decisiones pasaron y conservaron el contrato del host.
Git fixture adicional: detached, sin upstream, shallow, divergencia, filtros,
cuenta expirada y varios worktrees. Suite posterior: 188 passed.
