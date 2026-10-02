# Alcances de filesystem con `.isyroot` como ancla semántica

## Estado

Propuesta de diseño. La arquitectura general fue aprobada; esta especificación
queda pendiente de revisión del usuario antes de preparar el plan de
implementación.

## Intención y criterios acordados

- `.isyroot` identifica el proyecto lógico activo y sirve para asociar su
  configuración, conversaciones e historial. No es una frontera de
  descubrimiento ni concede acceso por sí mismo.
- ISyCode puede descubrir la ruta de lanzamiento, sus directorios ascendentes
  y proyectos hermanos que el sistema operativo haga visibles. Descubrir una
  ruta solo revela metadatos mínimos; no habilita leer su contenido.
- Leer, inyectar contexto, editar o ejecutar en otra carpeta requiere una
  autorización explícita. El agente puede pedirla mediante un diálogo que
  indique la ruta exacta y el alcance solicitado. La persona puede aprobar una
  vez o recordar el permiso.
- Los permisos recordados se guardan en el estado privado de ISyCode para ese
  usuario y equipo. No se crean ni se modifican `.isyroot`, archivos de
  configuración o archivos de Git en la carpeta autorizada. Cada equipo
  solicita su propio consentimiento.
- ISySentinel y sus dueños de ejecución siguen comprobando cada acción. Los
  grants de IsyMotron y los permisos del sistema operativo son capas separadas;
  ninguna autorización de ISyCode los reemplaza.

## Modelo de identidad, descubrimiento y acceso

El arranque conserva la resolución de identidad actual: el `.isyroot` válido
más cercano a la ruta de lanzamiento identifica el workspace activo; sin
marcador, se usa la ruta de lanzamiento como identidad temporal. La identidad
se incluye en sesiones, receipts y configuración propia del proyecto, pero no
determina por sí sola qué rutas puede consultar un dueño de acción.

El descubridor de rutas es una capacidad de navegación, no una autoridad. Puede
recorrer los ancestros de la identidad activa y enumerar metadatos básicos de
directorios visibles, además de localizar candidatos hermanos bajo esos
ancestros. No recorre recursivamente todos los árboles, no lee archivos y no
ejecuta comandos durante el descubrimiento. La navegación hacia un ancestro
puede mostrar nombres de directorio; para listar su contenido o abrir una
carpeta hija se requiere un alcance aprobado para esa ruta.

Una carpeta seleccionada que contiene otro `.isyroot` conserva su propia
identidad semántica. Adjuntarla no mezcla su configuración, sesiones, permisos
ni historial con el workspace activo. Las rutas montadas o compartidas se
tratan como filesystem visible del equipo anfitrión y requieren autorización
local en ese equipo. ISyCode no descubre ni autoriza máquinas remotas por red.

## Registro central de alcances

Un servicio central de alcances privados reemplaza las comprobaciones
independientes de “dentro del `.isyroot`” como criterio de acceso. Mantiene
registros ligados a la identidad del workspace activo, con:

- ruta canónica y nombre legible para la interfaz;
- identidad estable del directorio existente, al menos dispositivo e inode
  cuando el sistema los ofrece;
- acciones permitidas, separadas en listar/buscar/leer/contexto, editar y
  ejecutar comandos;
- modo de duración: una sola petición o permiso recordado;
- identificador aleatorio de registro para invalidar aprobaciones abiertas si
  se elimina y vuelve a registrar una carpeta;
- fecha de autorización y estado revocado/disponible.

El registro reside en el directorio privado de estado de ISyCode, con permisos
de sistema operativo restrictivos, escritura atómica, versión de esquema y
validación estricta al cargar. No se lee desde el repositorio, `.isycode/`,
`.gitignore`, archivos de instrucciones del agente ni una carpeta autorizada.
La política ausente, malformada, con permisos inseguros o incompatible falla
cerrada. El registro es local al usuario y equipo; no se sincroniza ni se
exporta como consentimiento portátil.

Los permisos anteriores de carpetas hermanas se conservan sin ampliarlos: una
adjunción de solo lectura continúa sin permiso de escritura o ejecución. El
plan de implementación definirá cómo leer y migrar sus registros actuales sin
recrear ni elevar grants automáticamente.

## Solicitud y revocación de permisos

Cuando una herramienta del agente necesita una carpeta sin alcance vigente,
ISyCode muestra un diálogo nativo de confirmación con la ruta completa, su
identidad detectada y cada acción solicitada. Lectura/contexto, edición y
ejecución aparecen como opciones distintas; ninguna viene seleccionada por
defecto. La persona puede conceder solo una vez o marcar “recordar en este
equipo”. El diálogo permite cancelar; cancelar no cambia el registro.

La solicitud del agente es una petición, no un permiso. El agente no puede
crear registros, marcar “recordar”, modificar el nivel pedido después de la
confirmación ni elegir otra ruta con una aprobación anterior. Al aprobar, el
registro queda vinculado a la ruta y a la identidad observada durante el
diálogo. Antes de actuar, ISyCode vuelve a comprobar esa identidad. Si la
carpeta desapareció, se reemplazó, cambió de identidad o la ruta atraviesa un
enlace simbólico, la acción se deniega y pide una nueva selección humana.

La interfaz de permisos permite inspeccionar y revocar alcances recordados.
Revocar impide nuevas acciones en ese alcance, incluso cuando el modo del
workspace sea Classic. Una petición ya preparada deja de ser válida si cambia
el registro que la respaldaba. No hay creación automática de carpetas, archivos
de marcador ni reglas de Git como parte de una concesión.

## Recorrido obligatorio de una acción

Cada dueño de filesystem recibe una petición inmutable que conserva el
workspace semántico activo, la ruta objetivo exacta y el identificador de
alcance concedido. Workspace Authority comprueba que el alcance existe y que
permite esa acción; ISySentinel vuelve a evaluar sus Systembilities antes de
que el dueño actúe. El dueño resuelve la ruta dentro de ese alcance, aplica
las reglas de contenido sensible y registra el receipt en el journal privado.
Un ID de alcance proporcionado por el modelo nunca se acepta como prueba de
autorización: el backend lo resuelve contra el registro privado actual.

El mismo contrato se aplica al navegador de archivos, lectura, búsqueda,
inyección de `AGENTS.md`/contexto, escritura, Git cuando opere sobre una raíz
adjunta y ejecución de comandos. Los controles existentes para `.git`, claves,
tokens, archivos `.env`, enlaces simbólicos y otros nombres sensibles se
mantienen; ampliar el ámbito no hace visibles esos datos.

Los permisos son capacidades específicas, no una escalera implícita:

- lectura o contexto no concede edición;
- edición no concede ejecución;
- ejecución no concede red, acceso general al home ni lectura de secretos;
- cada comando continúa mostrando argv, directorio de trabajo y efectos, y
  requiere su aprobación por ejecución según el flujo vigente;
- borrar, mover, hacer commits, usar red y acceder a credenciales conservan
  sus grants y confirmaciones propias.

Para comandos, el sandbox monta solo las raíces que la petición necesita y que
la persona autorizó. Las raíces autorizadas para lectura se montan de solo
lectura; una raíz con grant de edición solo se monta escribible si el comando
aprobado lo requiere. Se vuelven a calcular las máscaras de datos sensibles
para cada raíz antes de ejecutar. La decisión, las raíces montadas y sus
identidades forman parte del digest de la petición revisada. Si bubblewrap u
otro aislamiento requerido no puede representar esos alcances con seguridad,
el comando se deniega; no se ejecuta sin sandbox.

## Integración por componente

- **Identidad (`config.py`):** conserva `.isyroot` como ancla semántica; no
  interpreta el marcador como grant.
- **Registro/Workspace Authority:** proporciona la única fuente de grants
  persistentes y de un solo uso, independiente de la ubicación de cada
  execution owner.
- **IsySentinel y Systembilities:** validan el alcance asociado a la ruta,
  acción y owner en cada petición. Las Systembilities siguen siendo puras y no
  ejecutan ni modifican la petición.
- **Navegador y selectores:** usan navegación de ancestros/árboles autorizados;
  el selector nativo y las solicitudes del agente terminan en el mismo flujo de
  consentimiento y registro.
- **Lectura, escritura y Git:** resuelven rutas con el registro central y sus
  propios owners, approvals y receipts. No se introduce acceso directo al
  filesystem desde la TUI o el modelo.
- **Sandbox de comandos:** monta solo las raíces exactas de la petición,
  respetando permisos de solo lectura/escritura y máscaras por raíz.
- **IsyMotron:** sigue siendo runtime opcional, no autoridad de seguridad. Si
  sus permisos reales o los del sistema anfitrión no permiten una ruta, ISyCode
  informa el bloqueo sin fingir que el grant local la habilitó.

## Fallos y límites

La falta de consentimiento, una ruta fuera de los alcances, un registro privado
ilegible, una discrepancia de identidad, un enlace simbólico, un error de
canonicalización o una máscara sensible incompleta producen DENY sin lectura
ni efecto. Los errores de sandbox no se degradan a ejecución directa. La UI
debe distinguir entre “ruta descubierta”, “permiso local pendiente”, “permiso
concedido”, “permiso revocado” y “bloqueo del anfitrión/IsyMotron”.

El descubrimiento nunca promete ver carpetas que el sistema operativo no pueda
enumerar, y no confiere acceso a otra computadora. Una carpeta de red montada
puede aparecer en el selector nativo, pero requiere consentimiento propio en
cada equipo y conserva las restricciones del montaje y del sistema anfitrión.

## Fuera de alcance

- Compartir grants entre máquinas, usuarios o repositorios.
- Modificar IsyMotron para convertirlo en la autoridad de ISyCode.
- Lectura recursiva automática de ancestros, siblings o todo el home.
- Crear `.isyroot`, rutas inexistentes, configuración del proyecto o reglas de
  Git para registrar un permiso.
- Cambiar los grants de red, credenciales, Gateway, MCP, sesiones o
  coordinación Bridge.
- Eliminar o elevar automáticamente permisos históricos de carpetas adjuntas.

## Criterios de aceptación

1. `.isyroot` sigue identificando el workspace activo, pero por sí solo no
   habilita lectura ni acciones; sus ancestros pueden descubrirse sin leer
   contenido.
2. Descubrir un directorio hermano muestra únicamente metadatos permitidos y
   no hace que el agente pueda leerlo antes de la aprobación.
3. Una solicitud del agente identifica ruta y capacidades exactas; cancelar
   no deja grants, y una concesión de una sola vez no sirve para otra petición.
4. Un permiso recordado se guarda solo en estado privado local; no aparece en
   Git, `.isycode/`, los archivos de instrucciones ni el otro equipo.
5. Lectura, contexto, edición y ejecución se comprueban por separado por
   Workspace Authority, Sentinel y el execution owner correspondiente.
6. Reemplazar/mover una carpeta, cambiar su identidad o revocar el grant
   invalida autorizaciones preparadas anteriormente.
7. Enlaces simbólicos, archivos sensibles, secretos, raíces fuera del grant,
   estado privado inválido y fallos de aislamiento siguen denegados.
8. Ejecución de comandos monta exclusivamente raíces autorizadas y vuelve a
   enmascarar sensibles por cada raíz; nunca continúa directamente ante un
   fallo del sandbox.
9. Las carpetas adjuntas actuales no obtienen permisos más amplios durante la
   compatibilidad o migración.
10. La TUI identifica por separado descubrimiento, permiso local, revocación y
    restricciones del anfitrión; las pruebas usan árboles temporales y no
    acceden a datos reales del usuario.
