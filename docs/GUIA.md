# Guía rápida de ISyCode

## El comando para abrirlo

Desde la carpeta del proyecto que quieres explorar:

```bash
isyco cli
```

Ramas disponibles en el navegador:

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

Dentro del prompt de ISyCode, **Enter** envía el mensaje y **Shift+Enter** agrega una línea. **Ctrl+Enter** también envía.

Las respuestas del asistente y de Roundtrip se muestran con parser Markdown de terminal: `#`/`##` crean encabezados, `**texto**` se resalta en negritas, las listas conservan su estructura, los acentos graves simples marcan código en línea y los bloques con tres acentos graves reciben resaltado de sintaxis. **Esc** cancela la respuesta activa y descarta su salida parcial; si no hay generación activa, vuelve/cierra el menú o enfoca el composer sin borrar el borrador.

`/review <texto>` ofrece una revisión aislada con GPT-6 Luna vía OpenAI API. Antes de enviar, muestra exactamente el texto y pide confirmación. El revisor no tiene herramientas; la respuesta queda aparte. **Cancel review** o **Esc** interrumpe la conexión/stream y descarta cualquier salida parcial; no se reintenta ni se libera el único intento de la sesión. **Iterate with this review** prepara la respuesta como borrador para el modelo principal; todavía debes editarla o presionar Enter. El límite de salida es 1,200 tokens y solo se permite una revisión por sesión TUI. Si detecta un proxy configurado, ISyCode cancela el envío en lugar de saltárselo; aplica igual al chat cancelable.

La barra inferior tiene **Sidebar**, **Sessions**, **Providers**, **Role**, **Context** y **⚙**. El engranaje reúne las opciones y todos los atajos. `Ctrl+F` busca texto en toda la salida del chat; usa Enter o los botones para recorrer coincidencias y **Esc** para cerrar. Al escribir `/` solo se abre una paleta con diez ramas: Skills, Models, MCP, LSP, Files, Roles, Providers, Session, Workspace y Commands. Elige una rama para ver su lista; puedes desplazarte y volver con **Esc**. En Models, `Load account models` consulta los IDs del provider activo solo después de elegirlo; seleccionar uno cambia el modelo de esta sesión.

En **Context → Choose AGENTS.md…**, el selector de archivos de Linux te deja elegirlo sin escribir ruta. El archivo debe estar dentro del workspace y pasa por el grant `workspace.context.inject` de Workspace Authority e IsySentinel.
`/readme` abre el selector nativo de Linux, deja escoger un README del workspace y lo previsualiza tras el grant de lectura y Sentinel.

**Providers** selecciona los presets de ISyCode. NVIDIA NIM usa `nvidia/nemotron-3-ultra-550b-a55b`; OpenAI usa `gpt-6-luna`. ISyCode guarda provider/modelo (sin secretos) en su estado privado. Las claves nuevas se guardan en el keyring del sistema; las variables `ISYMOTRON_*` y el almacén antiguo siguen como compatibilidad. Una API key no concede acceso a red: autoriza el host desde Settings → Authority & Security antes de enviar prompts. OAuth descubierto desde un catálogo externo es metadata; ISyCode todavía no inicia ese flujo. **Role** separa agentes de chat de los ocho motores operativos de ISyCo. Cada motor operativo carga su flujo, alcance, comandos y reglas en el contexto del rol; el motor de lenguaje es el provider/modelo de ISyCode. La TUI no ejecuta esos comandos desde el chat ni concede autoridad al rol.

Mobile Host es el sustrato del motor de ISyCode Móvil y permanece apagado hasta que lo inicies desde **⚙ Settings → Mobile host status** con su grant y aprobación explícitos. Escucha solo en `127.0.0.1:8765` desde Secure. El PIN aparece localmente, dura cinco minutos y se usa una sola vez; al canjearlo, el host emite una credencial temporal, registra su receipt y conserva solo el hash. Settings → Private access puede proponer `/isycode` hacia este host mediante Tailscale Serve; debes revisar y aprobar esa ruta por separado. La ruta no activa Funnel ni reemplaza otros handlers. Los adapters aún no permiten sesiones remotas, streaming, cancelación ni approvals. El contrato está en `docs/mobile-host-v1.md`.

Si ISyCode está instalado desde otro checkout, define su ruta antes de abrir:

```bash
export ISYCODE_ROOT="/ruta/a/ISyCode"
isyco cli
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

## Regla de seguridad

Descubrir un MCP o una skill no concede permiso para invocarlo. Files es de solo lectura, parte de `.isyroot` y requiere grants explícitos de ISyCode evaluados por IsySentinel. Una key no concede acceso a red; los catálogos/Gateway también requieren grants de host. La interfaz nunca debe convertir un plan del modelo en autoridad.

## Comandos observados

### `isyco cli`

Ejecutado desde el checkout de ISyCode; abre el navegador interactivo anterior. Salir con `q` o `Esc`.

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
| `isyco` muestra los roles | Es el CLI existente de motores OpenISy. | Usa `isyco cli` para abrir ISyCode; no reemplaces el ejecutable. |
| El chat informa que falta una API key | No hay credencial del provider seleccionado. | Configura su variable (`OPENAI_API_KEY`, `NEBIUS_API_KEY`, `NVIDIA_NIM_API_KEY`) antes de pedir chat o plan. |
| LSP muestra que no hay adapters | ISyCode todavía no tiene adapter LSP configurado. | No indica una falla del TUI; los MCP aparecen por separado. |

Trampas frecuentes: ejecuta `isyco cli` desde el workspace correcto para que Files capture ese directorio; un MCP/skill visible sigue sin permiso de ejecución; y `isyco` sin `cli` continúa mostrando los motores por rol existentes.
