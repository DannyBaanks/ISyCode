# Telegram personal de ISyCode (implementación local, opt-in)

El frontend vive en ISyCode: un proceso local independiente de Textual, con polling saliente al Bot API y sesiones nativas. No requiere Bridge, Gateway, Tailscale, un webhook público ni una terminal simulada. Instalar ISyCode no inicia el servicio. No se ofrece como bot público o multiusuario.

## Configuración local

Necesitas un bot personal creado con BotFather, el ID **numérico** de tu usuario de Telegram (no el username), un keyring seguro disponible y un workspace con la política nativa que tú elijas. El token se introduce sólo por el prompt local sin eco. No lo pongas en argumentos, variables de entorno, chats o archivos. Si falta el keyring se rechaza la configuración; no hay fallback de texto plano.

Ejemplos para una instalación que ya incluye esta rama (los valores de ID y ruta son marcadores):

```sh
isycode telegram --help
isycode telegram --profile personal configure --user-id 123456789 --workspace /ruta/al/proyecto --alias proyecto
isycode telegram --profile personal status
isycode telegram --profile personal serve
```

`configure` verifica el ID de bot con getMe, rechaza un webhook existente y presenta un PIN efímero. Envía `/pair PIN` desde **el usuario y chat privado esperados**. Sólo después de verificar el PIN y una segunda confirmación local se guardan la credencial y los grants explícitos de conexión, recepción y exportación. La configuración no altera el modo Security/Classic/Flow, no habilita herramientas que éste deniega y no inicia el servicio. Si existe una denegación explícita de credenciales, revísala en los controles de autoridad nativos antes de volver a configurar. Un perfil usado no se reempareja con otro usuario; el historial queda aislado y se elige otro nombre de perfil.

`serve` ocupa el primer plano hasta Ctrl+C o una parada local; usa un lock del SO por perfil y comprueba nuevamente el bot. La segunda instancia o el conflicto con otro consumidor se rechazan; no se elimina un webhook ajeno. La TUI puede cerrarse sin detener este proceso. Un servicio de usuario del sistema es una decisión separada: si se desea, configurar localmente un unit/servicio con el ejecutable absoluto de ISyCode y `telegram --profile personal serve`. **Instalación y arranque en segundo plano reales: NO PROBADO.**

Para agregar otro workspace, detén primero el proceso y confirma el alcance localmente:

```sh
isycode telegram --profile personal stop
isycode telegram --profile personal status
isycode telegram --profile personal workspace add otro /ruta/al/otro/proyecto
isycode telegram --profile personal serve
```

`status` reporta el estado del perfil y si el lock está ocupado. `stop` solicita la parada en el estado privado, sin matar PIDs ni procesos ajenos. Los comandos de control local no necesitan conocer el token. `revoke` solicita parada, cancela los mensajes aún no iniciados, invalida revisiones y retira los grants de ese peer y la credencial local mediante el owner nativo; si el keyring o el grant de revocación falla, el perfil sigue deshabilitado y la eliminación de la credencial no se considera verificada. No borra el historial ni revoca el token en BotFather.

```sh
isycode telegram --profile personal revoke
```

## Conversación remota

| Comando | Acción |
|---|---|
| `/inicio`, `/ayuda`, `/proyectos` | Ayuda y aliases autorizados localmente. |
| `/nueva proyecto` | Crea y selecciona una sesión nativa. |
| `/sesiones`, `/usar ID` | Lista las conversaciones visibles del workspace y selecciona una sesión validada. |
| Texto normal | Encola una instrucción; no se interpreta como shell. |
| `/estado`, `/cola` | Muestra sesión, modelo guardado e identidades de turnos en cola. |
| `/retirar ID` | Retira un mensaje aún en cola de la sesión seleccionada. |
| `/cancelar` | Solicita cancelación del turno activo, con resultado durable posterior. |
| `/continuar` | Habilita pendientes después de una interrupción; no repite el turno incierto. |
| `/detalle ID-DE-TURNO` | Recupera eventos de un turno de la sesión seleccionada. |
| `/respuesta ID texto` | Contesta la pregunta concreta del agente; no otorga permisos. |

Las revisiones de efectos muestran el material exacto, sus identidades y controles Aprobar/Rechazar. Una revisión de otro perfil, sesión, turno, mensaje, política, caducada o repetida no otorga una aprobación nativa. Un cambio concurrente del transcript en otra TUI rechaza la continuación en lugar de fusionarlo silenciosamente. No se habilitan herramientas opcionales que carecen de una adaptación verificada.

Los eventos se guardan en SQLite privado bajo StateIndex. La recepción, los workers y la entrega son independientes; el scheduler permite hasta dos workspaces activos y un solo turno activo por workspace dentro de ese servicio. El progreso se agrupa en un mensaje editable por turno. Los resultados completos pueden recuperarse de los eventos, con límites de tamaño y redacción de patrones conocidos de secretos; sólo se muestra razonamiento que realmente expone el proveedor. La exportación a Telegram es una transferencia de contenido a un servicio externo: el grant local es explícito, pero no garantiza detectar secretos arbitrarios. La entrega es al menos una vez; puede repetirse una notificación si la respuesta de Telegram se perdió, nunca se repite automáticamente la herramienta para reconstruirla.

## Pruebas locales y límites de aceptación

La integración tiene pruebas herméticas con transporte Telegram y proveedor controlados, keyring de prueba y workspaces temporales. Incluyen edición real aprobada y rechazada, pregunta, FIFO, concurrencia, divergencia nativa, comando Flow temporal durante desconexión, reinicio y no replay, revocación, deduplicación, locks, límites de texto y recibos. Los resultados crudos y el contexto de verificación están en [evidence](evidence/).

Desde el checkout, con las dependencias de desarrollo instaladas y un directorio de estado aislado:

```sh
state=$(mktemp -d)
ISYCODE_STATE_HOME="$state/state" XDG_STATE_HOME="$state/xdg" PYTHONPATH=src \
  python -m pytest tests/test_telegram_service.py tests/test_telegram_cli.py \
  tests/test_telegram_state.py tests/test_telegram_owner.py tests/test_telegram_transport.py \
  tests/test_agent_runtime.py tests/test_agent_tools.py -q -p no:cacheprovider
```

**NO PROBADO:** emparejamiento real con Telegram, proveedor real, keyring real del usuario, despliegue como servicio, Windows/macOS, aceptación completa del repositorio. La integración comparte el paso del proveedor y las herramientas/owners; todavía falta demostrar paridad integral de contexto, compacción, steering y demás comportamiento del loop TUI. El resultado local no autoriza publicación ni activar el bot existente. Ver [ACCEPTANCE.md](ACCEPTANCE.md).

Referencias oficiales: [Telegram Bot API](https://core.telegram.org/bots/api) y [Bots FAQ](https://core.telegram.org/bots/faq).
