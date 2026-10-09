# Guía rápida de ISyCode

## El comando para abrirlo

Desde la carpeta del proyecto que quieres explorar:

```bash
isycode
isycode cli
```

`isycode` abre la TUI. `isycode cli` abre el navegador de acciones.

Al iniciar la TUI aparece la imagen original del pueblo nocturno como header
panorámico a todo el ancho disponible del chat, con un máximo de 36 filas.
Conserva las proporciones del faro y la luna: en ventanas anchas se recorta la
parte inferior, no se estira la imagen. Si falta altura se reduce para dejar
visibles el compositor, el modelo y las columnas de estado. Usa bloques de
medio carácter y color real; no necesita soporte de imágenes ni librerías de
imagen en ejecución. Tras el primer mensaje queda en el historial y se desplaza
hacia arriba con el chat.

**Multi Harness** en la barra inferior, en ⚙ Settings o con `/harness` abre
tarjetas por herramienta: versión, ajustes revisados y acciones disponibles.
El mapa de diferencias está plegado al final. La vista es de solo lectura;
**Esc** o **Close** la cierran. Al elegir una carpeta o copiar un modelo se
muestra la confirmación correspondiente antes de guardar cambios.

Ramas del navegador de acciones:

```text
ISYCO CLI · COMMANDS BY INTENT
▼ Agent
├── › Chat
├── › Plan
├── › Help
└── › Choose role
▼ Workspace
├── › Browse files
└── › Workspace overview
▼ Integrations
├── › ISyCode integrations
└── › Refresh catalogs
▼ Providers
├── › Choose provider
└── › Provider status
▼ Session
├── › New conversation
└── › Session status
▼ Settings
├── › Commands and shortcuts
└── › Select chat role
Choose a branch
Agent / Workspace / Integrations
```

Filtra por nombre o descripción en **Search actions…**. Usa ↑/↓ para moverte, ←/→ para plegar/desplegar ramas, Enter para inspeccionar una hoja y **Open selected** para abrirla. Esc limpia la búsqueda y luego cierra el navegador. `Browse files` abre el árbol limitado al workspace donde ejecutaste el comando. Ninguna hoja lanza una shell.

Dentro del prompt, **Enter** envía. **Shift+Enter**, **Ctrl+J** y **Alt+Enter** agregan una línea. **Ctrl+Enter** ya no envía.

Si el modelo todavía está respondiendo, **Enter** en un mensaje normal lo deja en la cola (máximo 8). Con el envío vacío, **Enter** sobre el mensaje seleccionado de la cola intenta steer: si el proveedor no lo confirma, el texto vuelve a su sitio. **Esc** devuelve el texto de la cola al borrador y no pisa un borrador que ya tenías.

**Ctrl+S** cambia la Idea Box por ShellBox, en el mismo hueco. Ahí ves los procesos de esta sesión que ya aprobaste. Enter o Espacio abre la lista; Stop cancela solo el proceso elegido. No hay shell libre ni camino sin sandbox. Textual desactiva IXON, así que Ctrl+S no congela la terminal.

Seleccionar texto con el ratón lo copia si en Authority está activo *Copy selected text to the clipboard*. El modelo no tiene esa herramienta. El 2026-10-04, en este escritorio con X11 y `xclip`, la copia devolvió `ALLOW` y la lectura de vuelta coincidió. El journal guarda el tamaño, no el texto.

La Idea Box ocupa el 60% del ancho, encima del prompt. Mientras hay un turno, el gato de la izquierda camina; al terminar vuelve a dormir y la frase de estado queda en su última fila, sin tapar el dibujo. La barra lateral usa secciones plegables en cajas separadas.

Las respuestas del asistente y de Roundtrip se muestran con parser Markdown de terminal: `#`/`##` crean encabezados, `**texto**` se resalta en negritas, las listas conservan su estructura, los acentos graves simples marcan código en línea y los bloques con tres acentos graves reciben resaltado de sintaxis. **Esc** cancela la respuesta activa y descarta su salida parcial; si no hay generación activa, vuelve/cierra el menú o enfoca el composer sin borrar el borrador.

`/review <texto>` ofrece una revisión aislada con GPT-6 Luna vía OpenAI API. Antes de enviar, muestra exactamente el texto y pide confirmación. El revisor no tiene herramientas; la respuesta queda aparte. **Cancel review** o **Esc** interrumpe la conexión/stream y descarta cualquier salida parcial; no se reintenta ni se libera el único intento de la sesión. **Iterate with this review** prepara la respuesta como borrador para el modelo principal; todavía debes editarla o presionar Enter. El límite de salida es 1,200 tokens y solo se permite una revisión por sesión TUI. Si detecta un proxy configurado, ISyCode cancela el envío en lugar de saltárselo; aplica igual al chat cancelable.

La barra inferior tiene **Sidebar**, **Sessions**, **Multi Harness** y **⚙**. Providers, Role y Context están en Settings. El engranaje reúne las opciones y todos los atajos. `Ctrl+F` busca texto en toda la salida del chat; usa Enter o los botones para recorrer coincidencias y **Esc** para cerrar. Al escribir `/` solo se abre una paleta con diez ramas: Skills, Models, MCP, LSP, Files, Roles, Providers, Session, Workspace y Commands. Elige una rama para ver su lista; puedes desplazarte y volver con **Esc**. Models pide el catálogo de la cuenta del provider activo al abrirse. Expandir otro provider pide el suyo sin cambiar el activo. El botón dice **Refresh account catalog**. Elegir un modelo lo guarda; al reiniciar se usa ese modelo, no el default del catálogo. Una imagen se acepta o se rechaza con las observaciones de ese modelo.

**Sessions** abre la lista de conversaciones de este workspace. El primer clic previsualiza; el segundo abre. **[×]** o **Ctrl+D** piden confirmación antes de borrar. Cancelar deja la conversación. El prefijo de cada fila es el nombre del modelo.

En **Context → Choose AGENTS.md…**, el selector de archivos de Linux te deja elegirlo sin escribir ruta. El archivo debe estar dentro del workspace y pasa por el grant `workspace.context.inject` de Workspace Authority e IsySentinel.
`/readme` abre el selector nativo de Linux, deja escoger un README del workspace y lo previsualiza tras el grant de lectura y Sentinel.

### Preparar contexto con archivos del workspace

En el chat puedes pedir, por ejemplo: «Empaqueta `src/isycode` y `tests` para revisar la arquitectura con un presupuesto de 20.000 tokens». La herramienta `workspace_pack` solo aparece cuando están activas las herramientas de lectura del workspace. Acepta rutas de archivos o directorios relativos al workspace actual; los directorios se recorren de forma recursiva.

Antes de leer el contenido, ISyCode muestra el inventario exacto, el tamaño total, una estimación local de tokens y el presupuesto solicitado. **Read and send once** autoriza solo ese paquete; **Cancel** o `Esc` cancela sin leer los contenidos. Cada lectura conserva sus grants, IsySentinel y recibo habituales. Los archivos son datos no confiables: pueden contener instrucciones maliciosas y no conceden autoridad.

Límites: 32 rutas seleccionadas, 200 archivos, 200 directorios recorridos, 128 KiB por archivo, 1 MiB total y presupuesto de 1 a 100.000 tokens estimados. El estimador local usa aproximadamente dos bytes UTF-8 por token; no es el tokenizer del provider ni una garantía de que el request quepa en su ventana. No se incluyen rutas sensibles (`.env`, claves, `.git`, `.isycode`), entradas ocultas halladas al recorrer un directorio ni directorios comunes de caché, dependencias y build; puedes seleccionar un archivo oculto no sensible por su ruta exacta. Esta primera versión no interpreta `.gitignore` ni `.ignore`, no comprime código con Tree-sitter, no agrega diffs/logs Git y no guarda un archivo de salida.
### Memoria privada del workspace

En el chat interactivo, pide expresamente guardar o buscar algo; por ejemplo: «Guarda que este proyecto usa SQLite para los datos locales» o «Busca lo que recordamos sobre autenticación». Con herramientas de workspace activas, el modelo puede usar `memory_store`, `memory_recall`, `memory_update`, `memory_forget`, `memory_list_topics` y `memory_consolidate`. Los grafos de conocimiento usan `memoir_create`, `memoir_list`, `memoir_show`, `memoir_add_concept`, `memoir_link` y `memoir_search`.

Antes de cada operación aparece **Workspace memory · operación** con los argumentos y las opciones **Cancel** y **Approve once**. En lecturas, la confirmación avisa que los resultados pueden enviarse al modelo elegido; en escrituras, advierte que solo cambia la memoria local. `Esc` cancela. Revisa los argumentos y aprueba únicamente lo que pediste. `memory_forget` elimina permanentemente un recuerdo; `memory_consolidate` archiva los recuerdos fuente en vez de borrarlos.

La base SQLite vive en el estado privado de ISyCode, fuera del checkout, y cada ruta de workspace tiene su propia memoria. No se extraen recuerdos automáticamente ni se inyectan al iniciar una sesión o en prompts posteriores: recuperar información requiere pedirlo. Los recuerdos leídos son datos no confiables, pueden estar desactualizados y no conceden permisos. En `isycode -p`, estas operaciones no están disponibles porque ese modo no puede pedir aprobación.

**Providers** selecciona los presets de ISyCode. Si no hay un modelo guardado, NVIDIA NIM usa `nvidia/nemotron-3-ultra-550b-a55b` y OpenAI usa `gpt-6-luna`. ISyCode guarda provider/modelo (sin secretos) en su estado privado y ese guardado gana al default al volver a abrir. Las claves nuevas se guardan en el keyring del sistema; las variables `ISYMOTRON_*` y el almacén antiguo siguen como compatibilidad. Una API key no concede acceso a red: autoriza el host desde Settings → Authority & Security antes de enviar prompts. OAuth descubierto desde un catálogo externo es metadata; ISyCode todavía no inicia ese flujo. **Role** separa agentes de chat de los ocho motores operativos de ISyCo. Cada motor operativo carga su flujo, alcance, comandos y reglas en el contexto del rol; el motor de lenguaje es el provider/modelo de ISyCode. La TUI no ejecuta esos comandos desde el chat ni concede autoridad al rol.

Mobile Host es el sustrato del motor de ISyCode Móvil y permanece apagado hasta que lo inicies desde **⚙ Settings → Mobile host status** con su grant y aprobación explícitos. Escucha solo en `127.0.0.1:8765` desde Secure. El PIN aparece localmente, dura cinco minutos y se usa una sola vez; al canjearlo, el host emite una credencial temporal, registra su receipt y conserva solo el hash. Settings → Private access puede proponer `/isycode` hacia este host mediante Tailscale Serve; debes revisar y aprobar esa ruta por separado. La ruta no activa Funnel ni reemplaza otros handlers. Los adapters aún no permiten sesiones remotas, streaming, cancelación ni approvals. El contrato está en `docs/mobile-host-v1.md`.

Si ISyCode está instalado desde otro checkout, define su ruta antes de abrir:

```bash
export ISYCODE_ROOT="/ruta/a/ISyCode"
isycode
```

La búsqueda de la ruta vecina por defecto corresponde a este layout de desarrollo; en otra instalación configura `ISYCODE_ROOT`.

## Actualizar ISyCode

Desde cualquier carpeta:

```bash
isycode actualizar --check
isycode actualizar
```

En un checkout con cambios locales, el actualizador se detiene para conservarlos.
Si la rama local y la remota divergieron, primero previsualiza el merge y crea
uno conservando ambas historias. Si el único conflicto es el snapshot generado
`docs/security/m15-authority-coverage.json`, lo regenera con el código integrado.
Cualquier otro conflicto muestra sus rutas y detiene el merge. `--check` hace
fetch para comparar, pero no integra ni instala dependencias.

## Preferencias de un proyecto

En la TUI abre **⚙ Settings → Initialize this workspace's .isycode/**. Solo se
ofrece para un proyecto con `.isyroot` propio. ISyCode muestra un diff y pide
aprobación para `.gitignore` y `.isycode/config.json`; necesita grants de lectura
y escritura existentes y, si es un repo Git, permiso `git.status`. Si `.isycode/`
ya está versionado o Git no puede comprobarlo, la operación se detiene sin tocar
el índice. En carpetas sin Git se crea solo la configuración local y se avisa
que no se instaló una regla de ignore.

**Workspace preferences** guarda rol, pasos del agente, longitud de respuesta y
presupuesto del chat para ese proyecto. No guarda permisos, claves ni estado
operativo. Para comandos `/`, ISyCode busca primero tus comandos en
`~/.config/isycode/commands/`, después `.isycode/commands/` y por último el
formato anterior `.isycode-commands/`. **Copy legacy workspace commands…** los
migra mostrando el diff y conserva los originales. Todo comando es texto de
prompt; cada acción solicitada sigue pasando por sus owners, Authority e
IsySentinel.

## Atajos y estados nuevos (2026-10-06)

| Tecla o gesto | Qué hace |
|---|---|
| `Ctrl+P` | Paleta de comandos semántica. |
| `Ctrl+Shift+F` | Busca en TODAS las conversaciones guardadas (título y mensajes). Enter abre la elegida. |
| Botón `modelo ▾` (barra inferior) | Abre el selector de provider/modelo. |
| Carpeta `▸ GLM · N models` | El catálogo de modelos se agrupa por familia (GLM, GPT, Qwen, DeepSeek…). Ábrela para ver las variantes. |
| Pantalla `Review N proposed changes` | Cuando el modelo propone varios archivos de una vez, una sola pantalla los revisa todos. `Approve all` aplica cada archivo con su propia aprobación de un solo uso; si un archivo cambia antes de aplicarse, se reabre su revisión individual. |
| `Trust folder this session · s` | En la revisión de un archivo: confía la carpeta solo hasta cerrar ISyCode. No se guarda nada; en modo Security no aparece. |
| `Always allow…` | La versión persistente (se guarda en Workspace folders). |
| Settings → `High contrast display` | Superficies negro puro y bordes claros (≥7:1 en el texto). Aplica al instante. |
| Settings → `ASCII-only display` | Cambia ✓/✗/●/○ por `[x]`/`[ ]`/`[ON]`/`[OFF]` y el banner por texto plano, para terminales sin Unicode. |
| `/help tour` | Tour guiado de ocho líneas dentro del chat. |
| Primera corrida: `Quick Start` | Una pantalla deja el workspace listo (recurrente + Classic + confirmación de coding tools). `Custom setup` lleva paso a paso. |

Regla de oro de las aprobaciones: ninguna aprobación crea un permiso duradero. Batch, session trust y quiet Classic emiten permisos de un solo uso ligados al contenido exacto; todo queda en el journal (Settings → Action journal).

## Regla de seguridad

Descubrir un MCP o una skill no concede permiso para invocarlo. Files es de solo lectura, parte de `.isyroot` y requiere grants explícitos de ISyCode evaluados por IsySentinel. Una key no concede acceso a red; los catálogos/Gateway también requieren grants de host. La interfaz nunca debe convertir un plan del modelo en autoridad.

Aviso de pares (grit): si otros agentes usan [grit](https://github.com/rtk-ai/grit) en este workspace, la tarjeta de aprobación de una edición puede mostrar qué símbolos tienen reclamados (`Peer claims (grit, advisory only)`). Es solo un aviso de coordinación: no bloquea ni autoriza nada y requiere tus grants explícitos. Detalles y evaluación en [docs/grit-peer-claims.md](grit-peer-claims.md).

## Comandos observados

### `isycode`

Abre la TUI en la carpeta actual.

### `isycode cli`

Abre el navegador de acciones por intención. Salir con `q` o `Esc`.

### `isyco --help`

```text
isyco — motores por rol (OpenISy). Un rol, un namespace, un motor.
version: phase1-v1 | root: (sin ancla .iesyroot: corre dentro del repo)

Uso: isyco <rol> <comando> [args...]   |   isyco <rol> --help
     isyco cli                              navegador semántico de ISyCode

Roles (como evo --workloads lista engines):
  historian        motor de staleness: status/register/show/chronicle
  maintainer       doctor --check, sticky registry (fix con gate --yes)
  orchestrator     barridos del bridge (watch dry-run; sweeps con --apply)
  researcher       evidence-pack: build/verify de evidencia
  planner          plan new/verify/list
  coder            guard: pre (blast radius) / post (corre prueba)
  librarian        cite-check: verifica citas ruta:linea
  devils-advocate  verdict-log: query de veredictos (solo lectura)

Exits: passthrough del motor | 2 uso/gate | 3 motor pendiente.
```

## Cómo leerlo y problemas comunes

| Estado o salida | Significado | Qué hacer |
|---|---|---|
| Árbol `Agent / Workspace / Integrations` | El navegador semántico inició. | Elige una acción y pulsa **Open selected**. |
| `no encuentro el checkout de ISyCode` | La ruta vecina no existe en este layout. | Configura `ISYCODE_ROOT` con el checkout correcto. |
| `isyco` muestra los roles | Es el CLI de motores OpenISy, no ISyCode. | `isycode` abre la TUI. `isycode cli` abre el navegador. |
| El chat informa que falta una API key | No hay credencial del provider seleccionado. | Configura su variable (`OPENAI_API_KEY`, `NEBIUS_API_KEY`, `NVIDIA_NIM_API_KEY`) antes de pedir chat o plan. |
| La cola dice que el modelo no permite steer | El intento no se confirmó. | El texto vuelve a la cola. Esc lo recupera si el borrador está vacío. |
| ShellBox dice que no hay sandbox | Falta bubblewrap, libseccomp o python3. | Los comandos siguen apagados. No hay ejecución sin sandbox. |
| Una imagen se rechaza | El modelo guardado tiene una observación `images=false`. | Elige un modelo con visión o quita la imagen. El default del catálogo no decide. |
| LSP muestra que no hay adapters | ISyCode todavía no tiene adapter LSP configurado. | No indica una falla del TUI; los MCP aparecen por separado. |

Trampas frecuentes: ejecuta `isycode` o `isycode cli` desde el workspace correcto para que Files capture ese directorio; un MCP/skill visible sigue sin permiso de ejecución; y `isyco` sin más argumentos sigue siendo el CLI de motores OpenISy.

## Tarjetas de comandos

Los comandos nuevos del chat muestran dos filas de salida en una tarjeta.
El borde superior identifica el comando y el inferior muestra su estado.
Pulsa Enter o Espacio con la tarjeta enfocada, o haz clic en su borde, para
ver la salida retenida completa y el recibo. La búsqueda abre las tarjetas
con coincidencias ocultas. Un aviso de límite significa que el owner no
retuvo más salida; expandir no recupera esos bytes.

La confirmación usa opciones grandes: Rechazar está enfocado inicialmente.
Las tarjetas cambian la presentación; no conceden permisos ni ejecutan
comandos por sí mismas.


Para ejecutar y leer el soak G9-04, consulta [la guía del soak](soak-g9.md). El progreso de un worker no equivale al resultado final del gate.


Pruebas M9: [flujo real G9-06](g9-live.md) y [protocolo con cinco participantes G9-05](usability-g9/GUIA.md). Los datos humanos no se sustituyen por resultados del modelo.
