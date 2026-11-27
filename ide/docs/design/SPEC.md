# ISyCode IDE — diseño aceptado

La GUI nativa Qt es la interfaz gráfica de ISyCode. Conserva el backend de
IsyVM y toma la TUI oficial como referencia de comportamiento, sin reemplazar
su núcleo. El idioma inicial es español y la vista inicial, Conversación.

## Distribución

- Tema carbón, acento cian, logo del gato y tipografía legible.
- Barra superior: proyecto, provider con identidad visual, modelo y PLAN/CODER.
- Navegación izquierda: Conversaciones, Archivos, Cambios, Herramientas,
  Pruebas, Evidencia, Sistema, GitHub, Providers, Ajustes y Terminal.
- Conversación conserva el estilo del primer mockup aprobado.
- Código + chat muestra el editor grande y un chat compacto a la derecha.
  Cambiar de vista no crea otra sesión ni pierde el borrador.
- Paneles redimensionables; las pantallas de configuración tienen espacio
  suficiente. No encajar formularios grandes en un cajón estrecho.
- Tarjeta de cambios: archivos, diff, revisar, aprobar y rechazar.
- Tarjeta de comandos: Permitir una vez, Permitir siempre este comando y
  Rechazar. La autorización permanente es exacta y revocable por proyecto.
- Terminal manual en una columna distinta al chat/editor; el agente no la usa.

## Comportamiento

Providers API, locales y suscripciones deben mostrar su estado real.
Configurado no equivale a conectado. Modelo, endpoint y autenticación forman
parte de cada turno y no cambian mientras se ejecuta. Las credenciales API
usan keyring o memoria de la sesión; no se escribe un nuevo almacén en texto
plano. Los tokens de suscripciones siguen bajo el control de su conector.

Las conversaciones persisten con mensajes y eventos, separados de las
sesiones técnicas del residente. GUI y TUI comparten servicios sin depender
de widgets Qt.

Las escrituras del agente se preparan como propuestas. Rechazar no escribe;
aprobar comprueba los hashes originales. PLAN, policy, herramientas habilitadas
y aislamiento se comprueban antes de ejecutar, incluso con un permiso previo.

Los comandos del agente se ejecutan en Linux aislado sin red, sobre una copia
temporal del proyecto, excluyendo archivos ocultos, nombres comunes de secretos,
.git y enlaces. Esa exclusión no detecta secretos embebidos en el código.
No hay fallback al host. Los cambios resultantes pasan por propuestas. Cancelar
detiene también los procesos descendientes. Runtime A restringido no se
presenta como una frontera de seguridad equivalente a este aislamiento.

## Nombre y compatibilidad

Distribución `isycode-ide`, entrada `isycode_ide`, comando `isycode-ide` para
la GUI y `isycode-ide tui` para la TUI incluida. Se conservan los alias
`isyvm` e `isycode-app`; no se registra `isycode`, perteneciente a la TUI oficial.
Estado global `~/.isycode-ide`, estado de proyecto `.isycode-ide`, keyring propio.
Migración aditiva e idempotente con manifiesto y SHA-256; conserva el origen y
exige una acción explícita para importar credenciales.

## Referencias visuales

Los PNG de `mockups/` son referencias, no capturas de funcionalidad implementada.
`mockups/manifest.json` conserva su procedencia y SHA-256. `github-sync.png`
propone la ampliación GitHub siguiendo el estilo anterior.

## GitHub y carpetas locales — ampliación pedida el 10 de octubre

Si `gh` puede autenticar una petición al usuario activo de github.com, mostrar
su identidad y los repositorios propios accesibles, públicos y privados.
No inferir autenticación de la existencia del binario, de un token guardado o
del exit 0 de `gh auth status --json`. No mostrar ni importar el token de gh.

Cada repositorio puede vincularse a una o varias carpetas/worktrees mediante
una acción explícita y comprobación de su remoto. No identificar un repo por
el nombre de su carpeta. Mostrar rama local, upstream, ruta y, por separado:

- commits detrás y por delante de su upstream;
- modificaciones staged/unstaged, archivos sin seguimiento y conflictos;
- fecha de la última consulta al remoto; sin conexión significa estado antiguo
  o desconocido, nunca cero commits detrás;
- sin clonar, sin upstream, HEAD separado e historia incompleta cuando aplique.

**Comprobar remotos** actualiza la información remota sin sustituir archivos de
trabajo. **Actualizar carpeta · Pull** revisa primero rama, hashes y manifiesto
de archivos afectados y solo realiza avance directo con carpeta limpia.
Si hay divergencia, cambios locales, conflictos, submódulos no soportados o
un cambio de base desde el preview, detener la actualización y mostrar la causa.
No stash, reset, rebase, cambio de rama, eliminación ni push automáticos.

Una rama al día puede contener archivos locales modificados. Mostrar ambos
estados evita prometer que toda la carpeta es idéntica a GitHub. La referencia
visual nueva usa datos de ejemplo; los contadores reales se calculan desde Git.
El recordatorio se muestra en la vista y en el proyecto vinculado al entrar;
no se crea una automatización externa ni se realiza pull en segundo plano.

## Fuera de v1

MCP externo opcional, navegador, rebase/merge avanzado y marketplace.
