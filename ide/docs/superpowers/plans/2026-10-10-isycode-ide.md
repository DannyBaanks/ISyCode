# Plan de implementación — ISyCode IDE

Goal: convertir la GUI existente en una herramienta de uso diario según el
diseño aprobado. Architecture: backend Python independiente de Qt; servicios
compartidos por GUI/TUI; autoridad del host sobre acciones del agente.
Tech stack: Python 3.11+, PySide6, httpx, SQLite, keyring, Linux bubblewrap.
Spec: ../../design/SPEC.md

## Restricciones globales

Preservar cambios previos y evidencia histórica. No borrar el repositorio de
origen. No sobrescribir routing/configuración de Codex o Claude del usuario.
No imprimir secretos ni inventar estados conectados. No ocupar el comando
`isycode`. No autorizar comandos por prefijo o comodín. No confundir sesiones
del residente con conversaciones completas. No presentar los mockups como
funcionalidad entregada.

## Task 1: Preparación, nombre y estado

Guardar especificación, mockups y procedencia; trabajar en `ISyCode-IDE` con
los cambios previos preservados. Añadir entrada `isycode_ide`, distribución y
comando propios. Definir rutas globales/de proyecto y escrituras atómicas.
Migración aditiva con hashes, conflictos visibles y origen intacto.
Entregable: instalación independiente y guía de compatibilidad.

## Task 2: Providers API y locales

ProviderService produce catálogo, configuración, autenticación, catálogo de
modelos y diagnóstico. Presets OpenAI-compatible; OpenAI, Anthropic, Google,
Ollama y endpoints locales. Validación y errores visibles; edición consistente;
sin reutilizar clientes httpx entre event loops Qt. SecretBroker usa keyring
o memoria y distingue ambos estados. Importación explícita solo de claves API,
no de OAuth como si fuera una clave. La UI consume el mismo servicio.

## Task 3: Conversaciones

ConversationService produce sesiones persistentes, contexto inmutable de turno,
mensajes/eventos y recuperación de turnos interrumpidos. Streaming estructurado
incluye argumentos fragmentados de herramientas. Cancelación HTTP efectiva.
GUI/TUI no pierden historial ni ejecutan dos turnos concurrentes en una sesión.

## Task 4: Herramientas y propuestas

ToolExecutionService produce catálogo real y ejecución común con PLAN/policy,
habilitación y aprobación. ProposalService produce Changeset con base SHA-256,
diff, aprobar/rechazar y rollback/journal de fallos parciales. No registrar una
herramienta ejecutable mediante un formulario que solo almacena JSON Schema.

## Task 5: Comandos aislados

Runtime Linux independiente con comprobación de capacidades, sin red, argv
sin shell automático, copia temporal que excluye secretos/metadatos/enlaces
externos, límites y cancelación del árbol de procesos. GrantStore persiste
ejecutable resuelto + argv + cwd + perfil por workspace. Permisos revocables
no saltan PLAN/policy/aislamiento. Pruebas del proyecto usan este runtime.

## Task 6: Suscripciones

Transportes restringidos de Codex y Claude con estado privado y herramientas
enrutadas al host; sin herramientas nativas que eludan aprobaciones. Grok por
transporte HTTP de sesión. Autenticación con CLI oficial y estados de expiración;
ningún fallback silencioso a API de pago. Documentar procedencia de adaptadores.
Pruebas reales de cuenta quedan pendientes si no hay sesión disponible.

## Task 7: GUI aprobada

Navegación y barra de provider/modelo; Conversación y Código + chat sobre la
misma sesión; tarjetas de cambios/comandos; pantallas completas de Providers,
Herramientas, Pruebas, Evidencia, Sistema, Ajustes y Terminal manual. Evitar
recortes y estados vacíos sin acción útil. Comparar renders Qt con los PNG.

## Task 8: Empaquetado y guía

AppImage, desktop ID, WM class, iconos y metadatos propios. GUIA.md en español;
documentar migración, cuentas, aislamiento, permisos, revocación y límites.
Revisión final de toda la rama y de los recorridos diarios.

## Task 9: GitHub y sincronización local (ampliación del usuario)

GitHubService usa gh oficial, verifica la identidad activa por una petición real
y lista repos propios accesibles. RepoLinkStore vincula identidad remota con
carpetas/worktrees elegidos, sin barrer el home ni inferir por nombres. GitSync
calcula ahead/behind frente al upstream de la rama actual y separa el estado
del árbol de trabajo. Mostrar desconocido/antiguo si no se pudo comprobar.

Pantalla GitHub acorde al diseño aprobado: lista buscable, cuenta verificada,
ruta/rama, commits entrantes y contadores; vincular/abrir carpeta, comprobar
remotos y actualizar con avance directo. Revisión concreta de los archivos
afectados antes de actualizar y revalidación de base al aplicar. Carpeta sucia,
divergencia, conflicto, HEAD separado, upstream ausente e historia incompleta
no habilitan un pull silencioso. No tocar routing de gh, sus tokens ni repos
reales al generar el mockup. Git avanzado queda fuera de v1.

Dependencia: servicios independientes de Qt; integración visual en Task 7;
guía y revisión final de Task 8 incluyen esta ampliación. El mockup es una
referencia de ejemplo, no un diagnóstico de los repos del usuario.

## Verificación prevista

Providers: modelos, actualizaciones, credenciales/expiración, fallos de red,
streaming y cancelación. Conversaciones: reinicio, interrupciones y concurrencia.
Autoridad: PLAN, herramientas desactivadas, cambios de argumentos, revocación.
Propuestas: base obsoleta, rechazo y fallo parcial. Aislamiento: red, secretos,
symlinks, rutas externas y procesos hijos. Migración: idempotencia y conflictos.
Qt: 1024×768, 1366×768, 1920×1080, HiDPI, teclado, separación de paneles y vistas.
GitHub: login ausente/expirado, listas privadas, varios clones/worktrees, upstream
distinto de main, ahead/behind fresco y antiguo, historia shallow, carpeta sucia,
divergencia, hooks/submódulos, pull con base cambiada y manifiesto de afectados.
Registrar salida cruda y SHA-256 cuando se ejecuten verificaciones; indicar
NOT_DEMONSTRATED para capacidades sin evidencia. No afirmar finalización del
plan mientras estos recorridos y la revisión final sigan pendientes.

## Review Focus

Autoridad duplicada entre UI/agente; conexiones que filtran tokens al error;
clientes cacheados entre loops; migración que sustituye datos; permisos amplios;
herramientas CLI nativas; cambios aplicados sobre una base distinta; estados
visuales optimistas; sesiones técnicas presentadas como chat; rutas heredadas.
GitHub: contador frente a la rama equivocada, considerar una carpeta modificada
como sincronizada, borrar trabajo al actualizar y ejecutar hooks inesperados.
