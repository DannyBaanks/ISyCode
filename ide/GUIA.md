```bash
/home/danny/.local/bin/isycode-ide /ruta/al/proyecto
```

La GUI Qt ya se abrió y capturó con proyectos de prueba en modo offscreen.
El AppImage también arrancó y comprobó Qt y namespaces con un proyecto temporal.
La generación con cuentas reales sigue NOT_DEMONSTRATED.
El AppImage está instalado con launcher e icono propios. Busca **ISyCode IDE**
en el menú de Ubuntu. También existe el entorno editable `.venv` de este checkout.

# ISyCode IDE — guía de uso

## Regla de oro

Configurar un provider no demuestra que esté conectado. Consulta su catálogo
y revisa el resultado. Las claves nuevas usan keyring o memoria de la sesión;
no se guardan en un nuevo JSON sin cifrar.

## Instalar y abrir

En este host ya se instaló `/home/danny/.local/bin/isycode-ide`, con entrada
`/home/danny/.local/share/applications/isycode-ide.desktop`. La ruta y SHA-256 del AppImage instalado están en
`/home/danny/Development/ISyCode-IDE/docs/verification/package-manifest.json`.
El launcher usa extracción para funcionar sin FUSE. Conserva esa carpeta del
paquete mientras uses el launcher. Su self-check, TUI/help y accounts/help
terminaron con exit 0; evidencia con SHA-256 en `docs/verification/`.

Para instalar otro build sin sustituir archivos existentes:

```bash
.venv/bin/python packaging/install_ide.py /ruta/al/ISyCode-IDE-x86_64.AppImage --name isycode-ide-nuevo
```


Desde `/home/danny/Development/ISyCode-IDE`, crea un entorno propio e instala
la distribución `isycode-ide` con el extra `ui`. No instala el comando `isycode`
de la TUI oficial. Se conservan `isyvm` e `isycode-app` como alias de compatibilidad.

Comandos de preparación ejecutados desde este checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -e '.[ui]'
```

`venv` terminó sin salida (exit 0). Extracto de la salida real de instalación:

```text
Successfully built isycode-ide
```

La instalación terminó con exit 0. Su salida completa y SHA-256 se conservan
en `.superpowers/sdd/2026-10-10-isycode-ide/install.log` y `installation.json`.
Las capturas reales de Qt se conservan en `docs/verification/qt-release-final/` y
`docs/verification/qt-hidpi-final/`;
usan archivos ficticios y se distinguen de los mockups de diseño.

## Configurar un provider

1. Abre Providers desde el menú o `Ctrl+P`.
2. Elige OpenAI, Anthropic, Google, un servicio compatible o uno local.
3. Introduce un nombre, el endpoint y el método de autenticación.
4. Introduce la clave si corresponde. No pegues tokens OAuth en este campo.
5. Pulsa **Consultar modelos**, o escribe el identificador manualmente.
6. Guarda la conexión y selecciónala en la barra superior.

Anthropic adapta la opción de temperatura a la firma del SDK instalado. Si
el SDK no la admite, se usa su valor por defecto. Las peticiones API no siguen
redirecciones con la clave; configura directamente el endpoint correcto.

**Consultar modelos** usa el borrador del formulario sin guardarlo ni enviar
un prompt. El servicio local debe estar iniciado. La consulta no demuestra
generación, límites de contexto ni compatibilidad con herramientas.

Dejar la clave vacía al editar conserva la existente. La pantalla indica
keyring, memoria de sesión o ausencia de clave. Si indica memoria, tendrás
que introducirla de nuevo al reiniciar. Importar `auth.json` copia solo
registros API; no configura automáticamente los endpoints ni importa OAuth.

## Conversaciones

La navegación izquierda abre pantallas completas. **Conversación** conserva
chat al centro, proyecto/conversaciones a la izquierda y Editor/Cambios/Diff a
la derecha. **Código + chat** amplía el editor y coloca el mismo chat en una
columna compacta. Los botones superiores o `Ctrl+1` / `Ctrl+2` cambian la vista
sin crear otra sesión ni vaciar el borrador. `Ctrl+K` abre la paleta de acciones.
En ventanas pequeñas la navegación usa iconos con tooltip.

**Providers** abre su pantalla mediante `Ctrl+P`. **Sistema** agrupa estado,
políticas y memoria local. **Ajustes** configura la vista inicial, si se recuerda
la última vista y la fuente del editor; también ofrece migración explícita.
Los paneles siguen pudiendo abrirse en una ventana desde el menú: se mueve el
mismo widget y se devuelve al cerrarla. El contexto mostrado es una estimación
por longitud de texto, sin inventar un límite de tokens para el modelo.

La distribución y sus pantallas se capturaron a 1024×768, 1366×768 y
1920×1080, también con escala 2. Las capturas usan datos de ejemplo.

El panel **Conversaciones** permite crear otra o reabrir el historial del
proyecto. La GUI reabre la más reciente al arrancar. La TUI incluida consume
el mismo almacén y muestra el historial de la más reciente. `/sessions` abre
el selector; `/resume <ID>` reabre otra; `/clear` empieza una nueva sin borrar
las anteriores. Al reabrir se restauran el provider y modelo guardados. Si la
conexión falta o cambió su protocolo, se bloquea el envío hasta elegir un
reemplazo explícito. Elegirlo enviará el historial a esa conexión.

No cambies de proyecto o conversación con un turno en ejecución. **Detener**
cancela la tarea del agente y su petición HTTP. Los turnos fallidos/cancelados
conservan la respuesta parcial. El historial de chat se almacena en SQLite,
separado de las sesiones técnicas del residente.

La TUI se comprobó con el driver local de Textual y un proyecto de prueba:

```bash
isycode-ide tui chat --dir /ruta/al/proyecto
```

## Migrar desde IsyVM

La migración es explícita, aditiva y conserva los archivos antiguos. No copia
claves, permisos de comandos ni tokens de suscripciones. Los conflictos dejan
los datos de destino intactos y aparecen en el resultado y el manifiesto.

Migración comprobada con orígenes y conflictos de prueba:

```bash
isycode-ide migrate
isycode-ide migrate --project /ruta/al/proyecto
```

El primero importa metadatos de providers de `~/.isyvm/config.yaml`. El segundo
copia modo, TODO, planes e historial técnico conocido de `.isyvm` al nuevo
`.isycode-ide`. El residente antiguo no se transforma en una conversación.
Cada archivo importado queda registrado con su SHA-256.

Estado global: `~/.isycode-ide`; proyecto: `.isycode-ide`; keyring: `isycode-ide`.
`ISYCODE_IDE_HOME` permite seleccionar otro estado global.

## Herramientas y cambios

En **Tool calls → Gestión de Tools**, los switches guardan la configuración
del proyecto. El agente consulta esa configuración al ofrecer herramientas al
modelo y antes de ejecutarlas. Desactivar una escritura mientras espera tu
aprobación bloquea su aplicación. Los switches afectan al agente; el botón
**Guardar** del editor es una acción explícita de la persona y consulta la
política y el hash de origen.

En CODER, `write` y `edit` preparan primero una propuesta de texto UTF-8
(hasta 2 MB). La tarjeta del chat muestra el diff y la base SHA-256:

1. Revisa la ruta y el cambio completo.
2. Pulsa **Aprobar una vez** o **Rechazar**. La TUI incluida muestra un modal
   equivalente; Esc rechaza.
3. Consulta el resultado de la herramienta: aprobar no garantiza aplicar.
   Un archivo cambiado desde el preview produce una propuesta obsoleta.
4. El panel **Cambios** conserva diff, base y estado después del turno.

Cada escritura de archivo es atómica. Los cambios de comandos se agrupan en un
Changeset con hasta 100 archivos y 10 MB. Se comprueban todas sus bases antes
de escribir, pero un fallo de disco intermedio puede dejar una aplicación parcial.
El journal conserva los recibos. **Preparar recuperación** muestra otro diff
para devolver archivos existentes a su contenido anterior; exige aprobación.
Los archivos nuevos se conservan, nunca se borran como recuperación automática.
Una propuesta pendiente no se aplica automáticamente al reiniciar.

Si el editor detecta que otro proceso modificó el archivo, conserva el texto
sin guardar y bloquea el guardado obsoleto. Conserva tu borrador antes de volver
a abrir el archivo. El agente no puede acceder a `.git`, `.isyvm` o
`.isycode-ide` mediante las herramientas de archivos.

`python` legado está **no disponible**. Usa `run_command` con una lista argv,
o abre **Pruebas**, introduce argumentos JSON y pulsa **Revisar y ejecutar**.
El perfil obligatorio usa bwrap, namespaces Linux, red separada, entorno limpio
y copia en tmpfs. Si las capacidades fallan, no se ejecuta en el host.

**Permitir siempre este comando** guarda un permiso exacto por proyecto:
ejecutable y hash, argv, cwd y hash del perfil. Se revoca desde **Ajustes**.
Cambiar cualquiera de esos campos necesita otra decisión. El permiso no salta
PLAN, policy ni herramientas desactivadas; los archivos modificados en la copia
siempre requieren una aprobación separada. **Detener** termina el proceso aislado.

El perfil inicial monta herramientas de `/usr`; no monta el venv del usuario,
`node_modules`, `.git`, metadatos ni archivos ocultos. Excluye nombres comunes de
credenciales y claves. Eso no detecta secretos pegados en archivos de código:
revisa qué contiene el proyecto antes de ejecutar. Copia máxima: 50 MB/5000
archivos; salida 1 MB; cambios UTF-8 de hasta 2 MB por archivo. No aplica borrados,
binarios, enlaces ni cambios de permisos. Los límites de memoria/CPU son por
proceso; RLIMIT_NPROC es un techo de 4096 hilos por UID, no una cuota de cgroup
del comando. El kernel se comparte con el host.

El verificador disponible inspecciona contratos internos del IDE (`all`,
`sandbox_interp`, `cpu`); no ejecuta pruebas del proyecto. Añadir integraciones
personalizadas sigue pendiente de un adaptador ejecutable; registrar un JSON
Schema no crea una herramienta funcional.

Los controles de aprobación, rechazo, base obsoleta, permiso permanente,
recuperación parcial y persistencia se probaron con proyectos de prueba.
Los recibos indican ejecución y aplicación; no prueban que el código sea correcto.

## GitHub y carpetas locales

La vista **GitHub** consulta la sesión de GitHub CLI al pulsar **Verificar gh y
cargar repositorios**. Debe existir una sesión válida de `gh` para github.com;
la presencia del ejecutable no muestra una cuenta como verificada. La lista
consulta repositorios propios accesibles, incluidos privados, por páginas.
No copia ni exporta tokens de gh. Tiene un límite visible de 10 000 repositorios.

1. Selecciona un repositorio y pulsa **Vincular carpeta local**. Elige la raíz
   de su checkout o worktree. El vínculo se comprueba por el remoto, no por el
   nombre de la carpeta. No se escanea todo tu home.
2. Pulsa **Comprobar remoto**, o **Comprobar todas las carpetas vinculadas**.
   Se consulta GitHub y se descargan objetos/referencias de la rama con upstream;
   los archivos de trabajo siguen intactos. Se muestra la hora de comprobación.
3. Revisa los commits detrás/por delante y, por separado, staged, sin preparar
   y sin seguimiento. Tener cero commits pendientes no significa no tener
   cambios locales. **Ver diferencias** compara las dos revisiones.
4. Para actualizar, pulsa **Actualizar carpeta · Pull** y revisa su manifiesto:
   A = nuevo, M = modificado, D = eliminado. Solo **Aplicar actualización revisada**
   aplica esos cambios; Cancelar conserva la carpeta. Se vuelve a consultar la
   base y el remoto antes de aplicar. Un cambio desde el preview requiere otra revisión.

La operación usa avance directo (`--ff-only`), sin reset, stash, rebase, cambio
automático de rama, push o limpieza. Cambios locales, divergencia, conflictos,
HEAD separado, historia shallow y upstream ausente bloquean el pull automático.
También se bloquea si una adición del remoto coincide con contenido local
ignorado. Se conservan sus bytes; la operación usa `--no-overwrite-ignore`.
Filtros Git personalizados/LFS, URLs reescritas, submódulos y metadatos privados
versionados requieren revisión manual en esta versión. Los hooks de Git se
deshabilitan en las operaciones del panel; no cambia la configuración global.

El agente y las operaciones Git del panel esperan mutuamente dentro de esta
ventana. Otros programas pueden cambiar la carpeta; las guardas vuelven a
comprobar su base, sin prometer exclusión contra procesos externos. Cerrar el IDE
espera a que termine una actualización ya iniciada. Un fallo deja un recibo
`review_required` en `~/.isycode-ide/git-sync/`; conserva la carpeta y revísala
manualmente. Nunca se intenta arreglar un fallo con `reset`.

Las guardas y el avance directo se probaron con Git real en repos locales de
prueba y una frontera de red simulada. Cuentas/repos reales: NO PROBADOS. El diseño
`docs/design/mockups/github-sync.png` usa datos ficticios. Comportamiento de CLI:
[autenticación gh](https://cli.github.com/manual/gh_auth_status),
[avance directo Git](https://git-scm.com/docs/git-merge).

## Referencia de estados

| Estado | Significado y acción |
|---|---|
| Sin comprobar | Metadatos guardados o borrador modificado; consulta el catálogo. |
| Catálogo consultado | El endpoint respondió; la generación aún no se comprobó. |
| Falta clave | Introduce una clave API o elige un endpoint local sin autenticación. |
| Credenciales rechazadas | Revisa la clave y los permisos en el servicio. |
| Catálogo no soportado | Introduce el modelo manualmente. |
| Tiempo agotado / error de red | Revisa endpoint, red y servidor local. |
| Solo memoria | La clave desaparecerá al cerrar el proceso. |
| Turno activo | Otra GUI/TUI está usando esa conversación. |
| Turno interrumpido | El proceso anterior terminó; puedes iniciar otro turno. |

## Suscripciones ChatGPT, Claude y Grok

1. Abre **Providers → Suscripciones** y selecciona la cuenta.
2. Elige el CLI oficial instalado y pulsa **Preparar conector**. Se guarda su
   ruta y SHA-256; una actualización requiere volver a prepararlo.
3. Pulsa **Comprobar sesión** o **Iniciar sesión oficial**. ChatGPT muestra un
   botón para abrir su dirección oficial. Claude/Grok abren el navegador mediante
   su CLI. Puedes cancelar la espera.
4. Elige un modelo del catálogo, o escribe su ID cuando no hay catálogo.
5. Guarda la conexión y selecciónala en la barra superior.

Los perfiles viven bajo `~/.isycode-ide/accounts/`, separados de las carpetas
habituales de los CLIs. Se usa el keyring propio de la carpeta Codex. No se
importa el login global ni se modifican las rutas globales del usuario. **Cerrar
sesión del IDE** pide al CLI cerrar solo este perfil. Claude requiere auth
`claude.ai`; un acceso API no se acepta como suscripción. Grok distingue sesión
guardada con fecha válida de servicio verificado; necesita un ID de modelo.

ChatGPT usa el app-server oficial con HTTP y herramientas dinámicas; el peer
se cierra al devolver una solicitud al host. Claude usa modo restringido,
herramientas nativas apagadas y una respuesta estructurada con propuestas;
esa respuesta aparece al completarse, sin simular streaming de tokens. El
transporte de sesión Grok procede del adaptador TUI y depende de un endpoint
sin contrato público estable. No hay fallback a una API de pago.

Para la TUI, usa la misma configuración guardada en la GUI o estos comandos:

```bash
isycode-ide accounts configure codex-subscription
isycode-ide accounts login codex-subscription
isycode-ide tui provider add chatgpt --provider codex-subscription --model auto --auth subscription
isycode-ide tui chat --provider chatgpt --model auto --dir /ruta/al/proyecto
```

`accounts inspect <tipo>` muestra estado sin valores de credenciales;
`accounts logout <tipo>` cierra el perfil. Los tipos son `codex-subscription`,
`claude-subscription` y `grok-subscription`. En pruebas se comprobó el handshake
sin login de Codex y el estado sin sesión de Claude. No se inició OAuth ni se
hizo generación con cuentas reales: **NOT_DEMONSTRATED**. Los CLIs deben
actualizarse manualmente; una versión que cambie el protocolo puede rechazarse.
La procedencia está en `docs/connectors/PROVENANCE.md`.

## Paquete independiente

La carpeta `dist/ide-<fecha>-<id>/` contiene el ejecutable de PyInstaller, un
AppDir y, si se seleccionó appimagetool, el AppImage. Cada build crea una carpeta
nueva y conserva los anteriores. No uses el script histórico `build_appimage.sh`.

```bash
.venv/bin/python packaging/build_ide.py --appimagetool /ruta/a/AppRun --runtime-file /ruta/al/runtime-x86_64
./ISyCode-IDE-x86_64.AppImage /ruta/al/proyecto
```

Si el equipo no tiene FUSE:

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./ISyCode-IDE-x86_64.AppImage /ruta/al/proyecto
```

`isycode-ide --self-check` comprueba Qt y los namespaces Linux con un proyecto
temporal propio. No consulta cuentas. El paquete requiere Linux x86_64,
`bwrap`, `prlimit` y Python 3 del sistema para el broker de comandos. GitHub
necesita `git` moderno y `gh`; las suscripciones requieren sus CLIs oficiales.
El build se hizo en Ubuntu 24.04; otras distribuciones: NOT_DEMONSTRATED.

## Límites de esta entrega

- El Terminal es manual y usa el host. Runtime A restringe rutas por código y
  no ofrece la frontera de aislamiento de los comandos Linux.
- OpenAI, Anthropic, Google y Ollama tienen eventos estructurados. Sus modelos,
  credenciales y compatibilidad real deben comprobarse con la cuenta elegida.
- Las pruebas GitHub usan Git real con red/gh de prueba. No se consultaron ni
  actualizaron los repos reales del usuario.
- Las capturas son renders Qt con datos de ejemplo; los PNG de
  `docs/design/mockups/` son las referencias aprobadas. Ninguno demuestra una cuenta.
- MCP externo, navegador, Git avanzado y marketplace quedan fuera de v1.

Verificación y límites por capacidad: `docs/verification/README.md`.
Plan aprobado: `docs/superpowers/plans/2026-10-10-isycode-ide.md`.

## Icono y retirada de la instalación antigua

El menú usa una ruta absoluta al PNG del gato neón en
`/home/danny/.local/share/icons/hicolor/256x256/apps/isycode-ide.png`.
La imagen original adjunta coincide byte por byte con `ui/assets/isycode.png`
y con el recurso del AppImage instalado. El instalador crea ahora la entrada
con ese enlace directo, sin depender de que el icono ya esté en la caché.

A petición del usuario se retiraron únicamente la entrada antigua
`/home/danny/.local/share/applications/isycode.desktop` y su ejecutable
`/home/danny/Applications/ISyCode.AppImage`. La TUI `isycode`, las conversaciones,
la configuración y los directorios fuente se conservan. `IsyVM/.git` sigue
respaldando este worktree y no es un programa instalado que deba desinstalarse.

Se actualizaron las cachés del escritorio/iconos. Si una ventana abierta sigue
mostrando el engranaje en el dock, guarda tu trabajo y vuelve a abrir ISyCode IDE.
El manifiesto de retirada y la comprobación real de GNOME/GIO están en
`docs/verification/old-gui-removal-result-20261011.json` y
`icon-desktop-final-20261011.json`; los logs de verificación llevan SHA-256.

## Navegación e iconos de archivos

**Conversación** muestra el chat y el historial del proyecto. El inspector
aparece cuando abres un archivo. **Archivos** muestra el editor grande con
chat compacto a la derecha. Cambiar entre ambas vistas conserva la conversación,
el borrador del mensaje y las ediciones sin guardar.

El explorador, los resultados de búsqueda, la cabecera del editor y las propuestas
usan SVG de vscode-icons para Python, JS, TS, React, Markdown, JSON, YAML, Rust,
Go, C/C++, Java, HTML/CSS, shell, TOML, Docker, Git e imágenes. Carpetas y archivos
desconocidos tienen un icono genérico. La TUI usa etiquetas ASCII literales
en las propuestas y el workspace (`[PY]`, `[JS]`, `[DIR]`, etc.) y en los estados
de herramientas (`[OK]`, `[ERR]`, `[TOOL]`); no requiere Nerd Fonts.

Los recursos originales y sus atribuciones se incluyen en
`ui/assets/vscode-icons/NOTICE.md`, `README.md`, `LICENSE` y `manifest.json`.
El proyecto upstream distingue código MIT, iconos CC BY-SA e iconos de marcas
bajo sus licencias de copyright. Los iconos de navegación son Tabler (MIT),
con licencia y procedencia en `ui/assets/tabler/`. El logo del gato se conserva.

## Información de GitHub

Abre **GitHub** y verifica `gh`. Al elegir un repositorio propio se consulta
su descripción, visibilidad, rama principal, lenguaje, estrellas y forks.
Las pestañas muestran muestras recientes de PRs abiertos, issues abiertos,
commits de la rama principal y ejecuciones de Actions (todas las ramas), hasta
30 entradas por sección. Esto no representa un total de PRs/issues. Si una
sección falla o faltan permisos, aparece como no disponible; no significa cero
resultados ni CI correcta. **Actualizar actividad** vuelve a consultar estos datos.

La tarjeta **Carpeta local** mantiene la sincronización separada: vincula una
carpeta y pulsa **Comprobar remoto** para conocer rama/upstream, commits delante
y detrás, y cambios locales. **Ver commits que llegarán** despliega los entrantes.
**Revisar Pull** conserva la revisión y los controles existentes antes de un
avance directo. La actividad remota por sí sola nunca habilita Pull. Los filtros
de carpetas pendientes usan la última comprobación local y no hacen fetch solos.

Tras actualizar el ejecutable, guarda tu trabajo y vuelve a abrir ISyCode IDE.

## Progreso del agente y Detener

El indicador bajo el compositor distingue la espera de respuesta del modelo,
la recepción de texto, la recepción de argumentos de una herramienta, su
ejecución y la espera de tu aprobación. Muestra el paso del agente y los segundos
en la fase actual. Si pasan 15 segundos sin otro evento, lo dice explícitamente;
ese aviso no confirma que el modelo esté pensando ni diagnostica un bloqueo.
Solo se muestra el texto que realmente envía el provider. La actividad de
razonamiento del provider puede actualizar el estado, pero no se presenta su
razonamiento privado como respuesta.

**Detener** solicita cancelación una sola vez y cambia a **Deteniendo el agente**.
La herramienta interrumpida muestra **detenida** y el historial conserva la
respuesta parcial. El compositor se habilita cuando acaba la cancelación.

Las búsquedas `glob` recorren directorios por partes, no siguen enlaces a
directorios y excluyen los metadatos del host. Tienen un máximo de 20 000
entradas inspeccionadas, 200 coincidencias, 12 KB de salida y 10 segundos.
Al alcanzar un límite devuelven `SEARCH_LIMIT`, no una lista supuestamente
completa. Abre la carpeta concreta del proyecto o pide un patrón más acotado.

Estas correcciones se empaquetaron tras una revisión de sintaxis. La cancelación
en la sesión real de NVIDIA/Nemotron y la regresión visual de esta versión
siguen **NOT_DEMONSTRATED** hasta repetir el recorrido E2E.

## Vista del proyecto para el modelo

Abre una carpeta concreta con **Ctrl+O**. El IDE no permite iniciar el agente
con la carpeta personal completa ni con `/` como proyecto.
El botón **Árbol** de la barra superior (o **Ctrl+B**) permite volver a mostrar
los archivos después de minimizar ese panel, sin cambiar de pantalla.

El contexto inicial incluye una vista de la raíz, sin contenidos de archivos.
La herramienta **project_tree** expande una carpeta mediante una ruta relativa,
como `src`. Devuelve directorios y archivos con tipos ASCII, una versión de la
lista y `next_offset` para pedir otra página. Cada página contiene hasta 60
entradas por defecto (máximo solicitado: 100) y unos 12 000 caracteres de filas.
Si cambia la versión entre páginas, vuelve a solicitar desde offset 0.
`truncated` y `scan_limited` distinguen una página parcial de un límite de lectura.

El árbol lateral y el descubrimiento del agente comparten el filtro: omiten
dependencias, cachés, salidas `build`/`dist`/`target`, metadatos, enlaces y archivos ocultos, salvo `.gitignore`,
`.gitattributes` y `.editorconfig`. Esta vista se reconstruye al consultarla;
no representa un índice congelado ni necesariamente las carpetas expandidas
en tu pantalla. Es una ayuda de contexto, no una nueva frontera de seguridad.
Las políticas y aprobaciones existentes siguen autorizando lecturas, cambios
y comandos. Leer contenido requiere una llamada **read** explícita.

Un **glob** general (`*`, `**` o `**/*`) devuelve la vista de la raíz,
identificada como no recursiva. Los patrones específicos mantienen resultados
acotados. **grep** busca ahora texto literal dentro de un archivo o una carpeta
del proyecto: hasta 30 líneas coincidentes, 12 000 caracteres de resultados y
2 000 archivos revisados. No interpreta expresiones regulares. Archivos binarios,
no UTF-8 o mayores de 1 MB se omiten y se contabilizan; una búsqueda parcial
o con archivos omitidos no demuestra ausencia global de coincidencias.

El buscador lateral trabaja por lotes y muestra si su resultado es una muestra
acotada. En el chat, el descubrimiento aparece como **Árbol del proyecto** con
su número de entradas y estado parcial, sin añadir el JSON a la respuesta del
asistente. Los detalles técnicos siguen disponibles en la tarjeta.
Esta capa de estructura es propia del IDE; no incorpora ni copia RTK.
La integración optativa de RTK para salida de comandos queda pendiente.
La comprobación E2E de esta nueva vista sigue **NOT_DEMONSTRATED**.


## Razonamiento del provider y diagnóstico del turno

Al recibir texto en `reasoning_content` o `reasoning`, el chat muestra **Razonamiento del modelo**:
pulsa ese encabezado para desplegarlo. Se actualiza mientras llegan fragmentos y queda separado
de la respuesta y las herramientas. **Copiar** sigue copiando solamente la respuesta.
Si el provider no envía ese texto, el IDE mantiene el estado de actividad sin inventarlo.
No se modifica la configuración del provider para forzar thinking ni se aumenta max_tokens.
El campo público de streaming aparece en el [ejemplo oficial de NVIDIA](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b/build).

La vista conserva como máximo 32 KB UTF-8 por turno. El historial privado del proyecto conserva
una copia acotada como evento, incluso en cancelaciones/errores normales. Al reabrir la conversación
se muestra como bloque guardado al final del historial; no se vuelve a enviar como respuesta al modelo.
Un cierre abrupto del proceso puede perder ese evento pendiente. No es evidencia de acciones realizadas.

Una vista completa y vacía significa **sin entradas visibles bajo el filtro del IDE**;
no prueba ausencia de archivos ocultos. Tras tres páginas idénticas dentro del turno,
el host solicita una respuesta final sin herramientas. Los cambios exitosos de archivos/comandos
reinician ese contador. Si el modelo sigue llamando herramientas, se detiene con un código explícito.

| Código | Significado / siguiente paso |
|---|---|
| PROVIDER_TOKEN_LIMIT | Se agotó max_tokens; salida parcial. Revisar límite en la configuración del provider. |
| PROVIDER_TOOL_ARGUMENTS | Argumentos incompletos o inválidos; esa respuesta no se ejecutó. |
| PROVIDER_TIMEOUT | Se agotó el tiempo de espera; se conserva lo recibido. |
| PROVIDER_TRANSPORT | Falló la conexión; se conserva lo recibido. |
| PROVIDER_HTTP_… | Estado HTTP del provider; revisar disponibilidad/configuración. |
| PROVIDER_STREAM_INCOMPLETE | Flujo cortado sin respuesta completa. |
| PROVIDER_EMPTY_ANSWER | El provider terminó sin respuesta textual; el razonamiento no la sustituye. |
| AGENT_REPEATED_DISCOVERY | El modelo insistió en herramientas después de repetir la vista. |
| AGENT_INTERNAL_ERROR | Error interno; el historial guarda fase, paso y ubicaciones de código acotadas. |

Los diagnósticos omiten cuerpos HTTP, credenciales y el texto de excepciones SDK.
Los turnos anteriores a esta versión sólo conservaron el mensaje genérico; su causa terminal
no puede reconstruirse con certeza desde esa captura. No confundir una denegación de PLAN con
un fallo del explorador: PLAN bloquea comandos y cambios aunque el modelo los solicite.

Entrega: análisis de sintaxis/diff y empaquetado; **NOT_DEMONSTRATED** para el nuevo flujo
con Nemotron real, restauración del bloque y regresión visual. Sin nuevas pruebas automatizadas
ni solicitudes de inferencia a la cuenta durante esta entrega.


## Tarjetas de herramientas sin JSON a la vista

El chat y **Herramientas** pasan los eventos por un formateador determinista de presentación.
La tarjeta muestra el destino mientras trabaja y un resumen del **resultado recibido** al terminar.
Ejemplos de formato (ilustrativos, no nuevas ejecuciones):

- `Carpeta: core · no encontrada`, sólo cuando el runtime confirma ausencia.
- `Carpeta: raíz del proyecto · sin entradas visibles`, sólo con página vacía completa.
- `Carpeta: src · 4 elementos en esta página · vista parcial`, si el resultado está truncado.
- `Archivo: README.md · no encontrado`, según el código de la lectura.
- `Residente: 3 referencias registradas · 2 restricciones`; esa consulta no comprueba existencia en disco.
- `Comando: … · bloqueado en PLAN`, cuando el host deniega la ejecución.

**Detalles** conserva nombre técnico, argumentos originales, stdout/stderr, código de salida y evidencia.
Las vistas de stdout/stderr que ya estaban limitadas a 4000/2000 caracteres ahora se identifican
como acotadas. El resumen se calcula antes de ese recorte. Nada de este formateador modifica la
salida enviada al modelo, los permisos, las aprobaciones o las evidencias del host.
No traduce o reescribe la respuesta ni el razonamiento del modelo.

Entrega: sintaxis, diff y empaquetado. **NOT_DEMONSTRATED** para la nueva presentación en E2E
con Nemotron y revisión visual. Sin nuevas pruebas automatizadas ni llamadas de inferencia.


## Logos en Providers y barra superior

La barra muestra el logo del provider identificado junto al nombre de la conexión.
El catálogo, **Mis conexiones**, el encabezado de conexión y el selector de
suscripciones usan los mismos SVG. Incluye NVIDIA, OpenAI/ChatGPT, Anthropic,
Claude, Gemini, Grok, Groq, Ollama, LM Studio, Mistral, DeepSeek y OpenRouter.

Los logos de color mantienen su identidad y los monocromos usan un tono claro.
Un endpoint compatible desconocido conserva el icono genérico. El logo identifica
la marca; el estado de conexión se consulta por separado. Los SVG y su licencia
MIT de Lobe Icons están incluidos en el paquete, sin descargas al abrir el IDE.

Cierra y vuelve a abrir **ISyCode IDE** para cargar una versión instalada nueva.
Los menús de conversaciones y el despliegue de las listas provider/modelo siguen
en el plan de interfaz; esta actualización se centra en los iconos.
