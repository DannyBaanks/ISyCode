# Integración nativa de Telegram en ISyCode

Fecha: 2026-11-24. Estado: diseño para revisión; implementación todavía no aprobada.

## Intención y decisiones del usuario

Danny quiere que cada usuario conecte su propio bot de Telegram a su instalación de ISyCode, cree sesiones y converse con un agente real de manera asíncrona, viendo respuestas, actividad de herramientas, comandos, resultados y el razonamiento que el proveedor exponga. Eligió un servicio local independiente que siga trabajando al cerrar la TUI. La integración pertenece al producto ISyCode; no al Bridge del monorepo ni a OpenISy.

Este documento concreta las decisiones restantes como propuesta del implementador. No afirma que el usuario haya aceptado individualmente esos detalles.

## Situación comprobada

El repositorio activo está en `/home/danny/Development/ISyCo Git/ISyCode`. Su CLI pasa por `launcher.py`; `headless.py` responde una vez y sólo ofrece herramientas sin aprobación, por lo que envolver `isycode -p` no satisface esta petición. El ciclo completo y su streaming están principalmente en `tui_app_chat.py`, y el despacho de herramientas en `tui_app_tools.py`.

Existen `ChatSessionOwner`/`ChatSessionStore`, `StateIndex`, `ProviderNetworkOwner`, owners de archivos/comandos/Git, `ActionApprovalStore`, `AgentEventStore` y `TurnEventStream`. Los providers exponen, cuando está disponible, un tipo de chunk `reasoning`. Mobile Host tiene emparejamiento y un catálogo de acciones remotas, pero su implementación inspeccionada no ofrece un agente completo reutilizable.

Hay cambios ajenos sin commit en el checkout, incluidos chat, streaming, providers, Authority y sesiones. La implementación debe partir de una rama/worktree aislado del baseline elegido, preservar esos cambios y comprobar compatibilidad; no incorporarlos ni sobrescribirlos accidentalmente. Los gates del roadmap de ISyCode siguen aplicando y no se darán por aprobados por este trabajo.

El cierre anterior del bot del monorepo está en `c2075b34`. Se mantiene: no se reabre `/execute`, el capture antiguo ni `/registrar`. Ese bot no será una dependencia de la integración nativa.

## Enfoques considerados

1. **Controlar una TUI abierta.** Reutiliza su ejecución actual, pero requiere que siga abierta y convierte la interfaz visual en el host del bot. El usuario eligió la alternativa independiente.
2. **Servicio local nativo de ISyCode — elegido.** Mantiene sesiones, turnos, eventos y aprobaciones sin depender de una terminal. Requiere separar del renderizado la parte necesaria del ciclo del agente. Reutiliza los owners y contratos de ISyCode.
3. **Bot externo que lanza `isycode -p` por cada mensaje.** Menor arranque inicial, pero pierde la continuidad operacional, no ofrece comandos/ediciones aprobados y duplicaría controles. Se descarta.

## Experiencia propuesta

### Configuración local

Cada instalación configura un perfil de bot personal mediante una entrada nativa `isycode telegram`, con subcomandos de configuración, inicio, estado, parada y revocación. Los nombres finales pueden ajustarse al CLI existente. El servicio se inicia explícitamente y puede instalarse como servicio del usuario mediante una acción separada; instalar ISyCode no lo inicia automáticamente.

El token se introduce localmente y se guarda en el keyring del sistema por un owner de credenciales extendido explícitamente para Telegram. No se pasa por argumentos, mensajes, logs, journal ni transcripts. Si no hay keyring seguro, la configuración informa la limitación y se detiene: no crea un archivo de texto como fallback silencioso. Se requiere el ID numérico esperado y una confirmación de emparejamiento desde su chat privado. Un PIN de un solo uso, acotado y mostrado localmente, confirma presencia; ningún primer remitente recibe permisos.

El perfil registra bot ID comprobado, usuario/chat privado vinculado y aliases de workspaces elegidos localmente. No contiene claves de modelos ni amplía grants del workspace. Cada usuario ejecuta su propia instalación/perfil; esta versión no es un servidor público multiusuario. Se puede dar estructura de perfiles al almacenamiento sin exigir soporte de múltiples bots por cuenta en la primera entrega.

### Conversación desde Telegram

Comandos propuestos, en español, con botones para las acciones frecuentes:

- `/inicio` y `/ayuda`: estado y acceso a sesiones/proyectos.
- `/proyectos`: workspaces habilitados localmente para ese perfil.
- `/nueva <alias>`: crea una sesión de ISyCode en ese workspace; el nombre es opcional mediante un paso posterior.
- `/sesiones`: lista conversaciones visibles para el perfil; permite abrir o continuar una.
- `/usar <id>`: selecciona una sesión mediante un ID opaco validado, preferiblemente con botones.
- Texto normal: encola un turno para la sesión activa, con acuse de aceptación y posición si hay otro turno en marcha.
- `/estado`: sesión, turno, cola, provider/modelo y última actividad.
- `/cancelar`: cancela el turno activo de esa sesión mediante la cancelación de ISyCode y confirma el resultado real.
- `/cola`: muestra y permite retirar mensajes todavía no iniciados. Reordenamiento y steering a mitad de herramienta quedan fuera de v1.
- `/detalle`: acceso al detalle del turno, comandos, resultados, diffs y errores sin saturar el chat.

Un mensaje editado en Telegram no cambia retroactivamente una instrucción aceptada. En v1 se ignoran ediciones para ejecución y se pide enviar una nueva instrucción. Grupos, canales, remitentes no vinculados y callbacks reenviados no acceden a sesiones ni disparan efectos.

Se ofrecen las sesiones del workspace mediante el owner nativo y sólo dentro de los workspaces habilitados. Abrir una conversación existente es una acción explícita: no se adivina un session ID ni se escribe directamente su JSON. Los transcripts son nativos y se pueden abrir después en la TUI. Si otra instancia cambia una conversación, se conserva la detección de divergencia y se exige recargar o bifurcar; no se fusionan dos escritores silenciosamente.

## Arquitectura

### Servicio y transporte

Un proceso por perfil toma un lock del sistema operativo y posee las tareas asíncronas de recepción, scheduler y entrega. Usa long polling saliente a Telegram; no necesita puertos públicos, webhooks, Gateway, Bridge, Tailscale ni el monorepo. Detecta el conflicto de otro consumidor sin eliminar webhooks ni apropiarse automáticamente del bot.

El adaptador Telegram sólo traduce mensajes, callbacks y eventos. No ejecuta shell ni herramientas del modelo. La biblioteca/transporte se decide al planificar, priorizando dependencias ya presentes y la API oficial; no se conserva la dependencia accidental del venv Windows antiguo.

Los mensajes aceptados se guardan antes del acuse. El offset de Telegram y la deduplicación se persisten con la aceptación/rechazo correspondiente, para que la reconexión no convierta un update repetido en un segundo turno. Las transiciones de estado usan almacenamiento transaccional privado bajo `StateIndex` — SQLite es la propuesta por cola, deduplicación y recibos, usando la biblioteca estándar. Todo dato durable deriva de StateIndex; no se añade otro árbol arbitrario de estado.

La política de concurrencia inicial es FIFO por sesión, un solo turno activo por sesión y un solo turno con efectos por workspace dentro del servicio. Diferentes workspaces pueden progresar concurrentemente con un límite configurable pequeño. La TUI externa sigue protegida por los locks, revisiones, previews y owners existentes: el scheduler del bot no promete exclusión global que no puede imponer.

### Runtime compartido

Introducir una API interna independiente de Textual para una sesión/turno del agente, con puertos de observación, preguntas y aprobaciones. Extraer sólo la parte necesaria del ciclo actual: mensajes de provider, continuidad, tool calls, cancelación y resultados. La TUI debe consumir el mismo núcleo para la parte extraída; no crear una segunda copia permanente de su loop.

El servicio usa `ProviderNetworkOwner`, `ChatSessionOwner` y los execution owners existentes. La extracción conserva los prompts y contratos de herramientas, contexto/compacción, sanitización histórica y metadatos de provider pertinentes. No utiliza `TUIApp.run_test`, pseudoterminales, automatización de teclado, parsing de pantallas ni clases de UI como runtime de producción.

La entrega se divide en unidades pequeñas: primero paridad del núcleo extraído, después servicio/sesiones/cola, después transporte y aprobaciones, y finalmente integración del setup/guía. Son etapas de implementación de una misma funcionalidad; no se presenta como terminado un bot que sólo responde consultas si faltan comandos aprobados, continuidad o eventos requeridos.

### Permisos y aprobación remota

Telegram es una integración explícita y apagada por defecto, incluso en Classic. Requiere acciones/grants propios para conectar, recibir instrucciones y exportar eventos a ese usuario/chat desde ese workspace, a través de un Telegram execution owner. El token, el emparejamiento y el alias de proyecto no conceden por sí mismos permiso de leer, editar, ejecutar ni publicar.

Cada herramienta recorre los mismos owners, Workspace Authority, Sentinel, sandbox y journal que en ISyCode. No hay aprobación automática universal ni ejecución del texto enviado como comando. La política Classic/Security que esté autorizada y demostrada se respeta; no se amplía su autonomía por estar en Telegram.

Cuando una acción requiere revisión, el agente queda en `waiting-permission` y Telegram muestra la acción concreta: workspace, comando/cwd/argumentos o diff, efectos y controles Aprobar/Rechazar. El resumen nunca reemplaza el material completo que se está aprobando; si no cabe, se entrega un detalle/archivo legible y se exige revisar ese detalle antes de habilitar la aprobación. Exportar ese contenido está dentro del grant explícito de Telegram del workspace.

El callback contiene sólo un identificador opaco, vinculado en el servidor a perfil/bot, usuario/chat, workspace, sesión, turno, preview, digest y expiración. Nunca contiene un token de `ActionApprovalStore`. Se compara contra la petición y estado actuales al pulsar; si cambiaron, requiere nueva revisión. La decisión es de un solo uso y se consume atómicamente. Se emite entonces la aprobación nativa efímera, dentro del proceso, y se pasa al owner. Una respuesta repetida o caducada no ejecuta nada. Cualquier reinicio invalida solicitudes de aprobación pendientes y exige un preview nuevo; no se persisten ni restauran tokens nativos.

Revocar un perfil corta nuevas instrucciones y exportaciones, invalida callbacks y cancela lo pendiente. El turno activo se cancela en una frontera segura; una acción ya iniciada puede terminar y su resultado queda registrado localmente. No se promete deshacer efectos ya realizados. El proceso no necesita enviar un último mensaje remoto tras la revocación.

## Observabilidad y entrega asíncrona

Eventos con identidad de sesión/turno y secuencia: inicio, acuse de cola, texto parcial/final, razonamiento exportado por el provider, inicio/progreso/fin de herramienta, comandos/stdout/stderr/código de salida, cambios, pregunta al usuario, solicitud/respuesta de aprobación, cancelación y error. Reutilizar los contratos de eventos existentes donde encajen y versionar explícitamente cualquier ampliación.

El razonamiento mostrado es sólo el contenido que el proveedor entrega como salida disponible, equivalente al que ISyCode puede mostrar. No se inventa razonamiento ni se intenta extraer pensamiento oculto. Si no existe, el detalle indica que ese proveedor no lo expuso. Es contenido observable, nunca un canal de autorización o control.

La interfaz edita un bloque de progreso de forma agrupada y envía resultados significativos, con acceso al detalle. No envía un mensaje por token. Un límite de frecuencia/tamaño evita saturación y respeta las respuestas de rate limit. Los mensajes largos se separan con límites correctos de Telegram; los detalles completos pueden ir como archivos de texto/diff cuando estén autorizados. Botones y entidades sólo vienen del renderizador, no de Markdown sin escapar producido por el modelo.

Los eventos durables y recibos de entrega permiten recuperar mensajes pendientes y detalle tras una desconexión sin repetir herramientas. La entrega de Telegram es al menos una vez; se puede duplicar un mensaje si Telegram lo aceptó pero la confirmación no quedó guardada. Las herramientas no se reejecutan para reconstruir la UI. Tokens y patrones conocidos de credenciales se redactan; no se promete que una expresión regular detecte cualquier secreto arbitrario. El usuario habilita conscientemente la exportación del contenido de ese workspace al servicio Telegram.

## Reinicio, cancelación y recuperación

- Turnos todavía en cola permanecen pendientes, con sus IDs originales y deduplicación.
- Un turno que estaba activo al caer el servicio queda interrumpido/incierto, conservando eventos, transcript y recibos; no se repiten herramientas con efectos automáticamente. La continuación requiere petición explícita del usuario y reconstrucción desde estado verificable.
- Las aprobaciones pendientes caducan al reiniciar. No se intenta reutilizar callbacks anteriores.
- Cerrar la TUI no afecta al servicio; parar el servicio sí cancela su trabajo de manera explícita. El proceso vive hasta parada/revocación; no es un watcher temporal dejado por el agente implementador.
- Cancelar un turno no descarta silenciosamente los mensajes siguientes de la cola. La UI los muestra y permite mantenerlos o retirarlos antes de continuar.

## Alcance inicial y exclusiones

Debe funcionar: bot personal, emparejamiento privado, workspaces registrados localmente, creación/continuación de sesiones, conversación multivuelta, cola FIFO, herramientas locales existentes con permisos y aprobaciones, preguntas al usuario, eventos y detalle, cancelación, reconexión, recuperación sin replay de efectos, status/stop/revoke y guía de operación.

Fuera de v1: grupos, bots públicos compartidos, alojamiento SaaS, administración de equipos, múltiples máquinas consumiendo el mismo bot, edición retroactiva de instrucciones, steering arbitrario durante herramientas, multimedia/voz y migración automática de secretos desde el bot abandonado. Las integraciones opcionales MCP/Gateway/etc. no se habilitan ni amplían por Telegram; las herramientas que no tengan adaptación completa se declaran no disponibles, sin simular éxito.

## Verificación y criterios de aceptación

1. Emparejar al ID esperado; otro usuario, grupo, callback repetido, vencido, reenviado o de otra sesión no produce una acción ni recibe datos.
2. Dos perfiles/usuarios y dos workspaces aislados no cruzan tokens, sesiones, colas, respuestas, eventos ni decisiones.
3. Crear sesión, varios turnos y reapertura desde TUI conservan transcript y estado nativos. La divergencia con otra instancia se detecta y preserva ambas continuidades.
4. Un provider controlado produce conversación, razonamiento disponible, llamadas de herramientas, resultados y preguntas, observables por el adaptador sin duplicar ejecución.
5. Una edición y un comando reales en workspace temporal recorren los owners/sandbox existentes; denegar no produce efecto y aprobar una petición distinta o antigua no sirve. No se debilita la autorización para hacer pasar pruebas.
6. Encolar durante un turno no bloquea recepción; acuse, orden FIFO y retiro de mensajes pendientes son verificables. Reiniciar después de un update repetido no crea otro turno.
7. Cortar red/rate limit reintenta la entrega sin repetir herramientas. Cancelación y caída del servicio dejan estado explícito y recibos; no reejecutan comandos inciertos.
8. La integración sigue trabajando al cerrar la TUI y se detiene/revoca de forma acotada. Classic no habilita Telegram silenciosamente.
9. Tokens sintéticos y URLs con token no aparecen en transcripts, journal, eventos, errores ni artefactos. Las pruebas usan estado temporal, servicios controlados y credenciales ficticias.
10. Regresión hermética de ISyCode, cobertura de acciones actualizada con su generador si cambian callsites/catalogo y validación de los gates afectados. Se reportan fallos previos sin esconderlos.

La aceptación local usa un transporte Telegram simulado y un provider controlado. Una prueba con Telegram real requiere configuración explícita del dueño; no se afirma conectividad real por pasar tests de transporte sustituido. Documentar comandos, salida cruda, códigos de salida, entorno y hashes; ningún contador de pruebas queda mantenido a mano en documentación.

## Decisiones delegadas al constructor

Organización exacta de módulos; protocolo interno de puertos; método concreto de extracción que minimice cambios a la TUI; librería Telegram después de comparar las dependencias presentes; esquema SQL y tamaño de lotes; límites iniciales y retención configurables; formato accesible del detalle; nombres exactos de CLI/acciones; adaptación del setup a los patrones visuales aceptados; matriz de pruebas específica y secuencia de commits. Ninguna de estas decisiones permite omitir los comportamientos y límites definidos arriba.

## Entrega y revisión

El producto se implementa en el repositorio ISyCode, con una rama aislada, pruebas y guía nativa. Este diseño se conserva inicialmente en el monorepo como artefacto revisable; se trasladará/copiará al repositorio del producto durante la implementación autorizada sin borrar el original. No se reactiva ni reemplaza un árbol de archivos del bot anterior, no se toca trabajo ajeno y no se publica una release ni un despliegue real automáticamente.


## Addendum de baseline para la implementación

Diseño aprobado por Danny el 2026-11-24. Antes de implementar se verificó el main remoto y local: `e88109b5d12df4d0acd679b40db792ca062563f6`. El checkout originalmente inspeccionado estaba en una rama histórica con cambios ajenos; el worktree nuevo no copia esos cambios.

En este baseline `headless.py` también tiene Flow y la enmienda v2 de ADR 0010 permite en Flow acciones nativas con alcance al equipo, incluidos comandos host. Esto corrige la descripción inicial de headless como exclusivamente de lectura. Sigue sin proporcionar el servicio durable multisesión y aprobaciones remotas que requiere este diseño. No se usará el antiguo prompt de headless como sustituto del agente compartido.

La integración conserva Classic, Security y Flow según la política nativa elegida localmente por la persona; no cambia de modo por una instrucción del modelo o del chat. Las referencias anteriores al sandbox describen Classic/Security y los caminos que lo exigen, no una reescritura del Flow v2 de Danny. El consentimiento local de Telegram muestra el modo y alcance actuales del workspace. Si el modo o la política cambia durante una revisión, se invalidan sus aprobaciones pendientes y se comprueba de nuevo el permiso de integración antes de continuar. Un cambio de modo nunca concede Telegram automáticamente.
