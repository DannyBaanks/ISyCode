# ISyCode

**Un agente de programación para la terminal, local-first, donde cada acción pasa por permisos explícitos.** ISyCode reúne chat, archivos, git, comandos, MCP y providers en una TUI de teclado. Separa la identidad del proyecto (`.isyroot`) de la autoridad para tocarlo, y todo lo que el agente hace queda decidido por IsySentinel y registrado en un journal.

> **Estado:** en desarrollo. Esta página separa lo que ya se ejecutó de verdad de lo que está implementado y probado solo con dobles de prueba. Mira [Qué está probado](#qué-está-probado).


**Uso diario (2026-09-30):** recuperación manual con `/retry`, borradores y sesiones versionadas, `/context` para AGENTS.md, diagnóstico local `isycode doctor` y `/doctor`, y verificación explícita del proveedor con `/check`. Consulta [la guía y sus límites de verificación](docs/daily-use-readiness.md).

## Índice

- [La TUI](#la-tui)
- [Instalar y arrancar](#instalar-y-arrancar)
- [Modos: Classic y Security](#modos-classic-y-security)
- [Qué puede hacer el agente](#qué-puede-hacer-el-agente)
- [Comandos `/`](#comandos-)
- [Providers](#providers)
- [Configuración personal](#configuración-personal)
- [Seguridad y límites](#seguridad-y-límites)
- [Qué está probado](#qué-está-probado)
- [Integraciones](#integraciones)
- [Atajos](#atajos)
- [Roadmap y documentación](#roadmap-y-documentación)

## La TUI

Las capturas muestran la TUI real de Textual con un workspace temporal de demostración. El texto del chat es estático: no se llamó a ningún provider, Gateway, MCP ni comando. El árbol de archivos aparece bloqueado porque la captura no tiene permiso de lectura.

| Overview | Archivos |
| --- | --- |
| ![TUI: overview](docs/screenshots/01-overview.png) | ![TUI: archivos y límite de autoridad](docs/screenshots/02-files.png) |

## Instalar y arrancar

Desde el código fuente (Python 3.10 o posterior):

```bash
git clone https://github.com/DannyBaanks/ISyCode.git
cd ISyCode
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .            # añade '.[anthropic]' para usar Claude de forma nativa
isycode
```

Para lanzarlo desde cualquier proyecto con este checkout:

```bash
./scripts/install-path
cd /ruta/a/tu/proyecto
isycode
```

Otras formas de ejecutarlo:

| Comando | Qué hace |
| --- | --- |
| `isycode` | Abre la TUI en la carpeta actual |
| `isycode -p "pregunta"` | Responde una vez y sale ([modo no interactivo](#modo-no-interactivo)) |
| `isycode cli` | Navegador de acciones por intención; no ejecuta shell |
| `isycode --help` / `--version` | Ayuda y versión |

La primera vez que abres una carpeta, ISyCode pregunta si será un workspace **recurrente** (crea un `.isyroot` vacío y puede guardar conversaciones) o **temporal**, y qué **modo** usará. Las conversaciones recurrentes se guardan en `~/.local/state/isycode/` (o bajo `$XDG_STATE_HOME`), nunca dentro del proyecto.

### Paquetes precompilados

Al publicar un tag `vX.Y.Z`, CI ejecuta la suite hermética en Linux y, si pasa y coincide con la versión de `pyproject.toml`, construye paquetes nativos. Cada binario pasa un smoke check en su runner antes de adjuntarse a un GitHub Release en borrador con `SHA256SUMS`.

- **Windows x64:** ejecutable de consola `.exe` (ábrelo desde PowerShell o Terminal).
- **Linux x64:** AppImage (`chmod +x`) y `.deb` (`sudo apt install ./archivo.deb`), construidos sobre Ubuntu 22.04 (glibc 2.35 o posterior).
- **macOS ARM64:** `.pkg` y `.tar.gz`, sin firma ni notarización de Apple (Gatekeeper puede avisar). Intel Mac aún no está incluido.

Los paquetes instalan el comando `isycode`; no son una aplicación gráfica.

### Pruebas

```bash
python -m pytest -q -m "not integration"
```

Las pruebas contra un ISyCo Gateway vivo son opt-in porque hablan con un servicio real (`test_gateway_write_file` escribe y borra un archivo en él):

```bash
ISYCODE_LIVE_GATEWAY=1 python -m pytest -q test_gateway.py
```

## Modos: Classic y Security

Cada workspace tiene su modo. Lo eliges la primera vez que abres la carpeta (`Esc` = Security) y puedes cambiarlo en **Settings → Authority**. En **Settings → My defaults** puedes fijar el modo inicial de las carpetas nuevas; es solo una preferencia.

| | Classic | Security |
| --- | --- | --- |
| Leer y buscar archivos del workspace | incluido | lo activas tú |
| Proponer ediciones (diff + *Apply* en cada cambio) | incluido | lo activas tú |
| Chat con el provider elegido (solo hosts conocidos o el endpoint configurado) | incluido | lo activas tú |
| Guardar y reanudar conversaciones | incluido | lo activas tú |
| Guardar, usar y quitar API keys (guardar y quitar piden confirmación) | incluido | lo activas tú por servicio |
| Ver `git status` y diffs | incluido | lo activas tú |
| Commits, comandos en sandbox, MCP local, diagnósticos Pyright | permiso explícito | permiso explícito |
| Gateway, broker, Tailscale, Mobile Host | permiso explícito | permiso explícito |
| Borrar y mover archivos | permiso explícito | permiso explícito |
| Shell libre, archivos sensibles, editar `.isyroot` | no disponible | no disponible |

Classic es un preset de permisos implícitos de Workspace Authority, **no un bypass**: IsySentinel revisa cada acción, las aprobaciones por acción siguen y todo queda en el journal en ambos modos. El preset nunca se escribe en la política explícita. Los workspaces creados antes de los modos siguen en Security.

## Qué puede hacer el agente

Con un provider que soporta tool calls, el chat es un bucle de agente: el modelo pide herramientas, ISyCode las ejecuta a través de su execution owner y le devuelve el resultado. Cada herramienta aparece solo si su permiso está activo, y ninguna saltea IsySentinel ni el journal.

| Capacidad | Herramienta / comando | Permiso en Settings → Authority | ¿Pide aprobación cada vez? |
| --- | --- | --- | --- |
| Listar, leer y buscar por nombre | `workspace_list`, `workspace_read`, `workspace_search` | Read and search workspace files | no |
| Buscar texto dentro de archivos | `workspace_grep` | Read and search workspace files | no |
| Editar un fragmento exacto | `workspace_edit` | Edit workspace files | sí, con el diff exacto |
| Crear o reescribir un archivo (y sus carpetas) | `workspace_write` | Edit workspace files | sí, con el diff exacto |
| Borrar un archivo de texto | `workspace_delete` | Edit workspace files (fuera de Classic) | sí, mostrando todo lo que se borra |
| Mover o renombrar un archivo | `workspace_move` | Edit workspace files (fuera de Classic) | sí; nunca sobrescribe el destino |
| Deshacer el último cambio de ISyCode | `/undo` | Edit workspace files | sí, con el diff inverso |
| Ejecutar un programa (tests, build, linter) | `workspace_run`, `/run` | Run commands in a sandbox | sí, con el comando exacto |
| Ver rama, cambios y diffs | `git_status`, `git_diff`, `/git`, `/diff` | See git status and diffs | no |
| Crear un commit | `git_commit`, `/commit` | Create git commits | sí, con archivos, mensaje y diff |
| Herramientas de servidores MCP locales | `mcp__<servidor>__<herramienta>`, `/mcp` | se concede al arrancar el servidor | sí: al arrancar y en cada llamada |
| Revisar errores tras editar un `.py` | automático tras aplicar un cambio | Check Python files after edits | no (solo lectura) |
| Mostrar su plan de trabajo | `update_tasks` (panel **Tasks**) | ninguno: no es una acción | no |

**Todo de una vez:** en **Settings → Authority**, *Turn on all coding tools…* concede en un paso lectura, edición, mover, borrar, deshacer, comandos en sandbox, git y diagnósticos (lo que tu equipo soporte). Cada cambio, comando y commit sigue pidiéndote aprobación.

### Bucle y contexto

- **Sin límite de pasos por defecto:** el agente trabaja hasta responder, sin tope de llamadas por respuesta. Lo que decide qué puede hacer es IsySentinel, no un contador. `Esc` lo detiene cuando quieras. Si prefieres acotar cuántas peticiones al modelo (y cuánto gasto) usa un prompt, elige 10, 25, 50 o 100 pasos en **Settings → My defaults**.
- **`Esc` detiene todo el turno**: la petición al modelo, una herramienta o un comando en marcha.
- Cuando la conversación ya no cabe, ISyCode **resume los mensajes antiguos** con el mismo provider (una petición autorizada y con receipt, como cualquier otra) y recorta resultados de herramientas antiguos dentro de un turno largo. `/compact` lo hace a mano. La conversación guardada conserva siempre el transcript completo.
- `@ruta/archivo` en un mensaje adjunta ese archivo (hasta 5), leído con el permiso de lectura y marcado como datos, no instrucciones.

### Ediciones

`workspace_edit` reemplaza un fragmento exacto de un archivo; `workspace_write` propone el contenido completo y puede crear hasta 8 carpetas nuevas, que aparecen en la aprobación. La escritura es atómica, no sigue symlinks, rechaza rutas sensibles y archivos de más de 128 KiB, y **no sobrescribe si el archivo cambió después de la revisión**. Cada cambio guarda un checkpoint fuera del proyecto para `/undo`.

En Linux y macOS se usan descriptores que nunca siguen enlaces. En Windows se usan rutas verificadas: se rechazan symlinks y junctions en toda la ruta y se comprueba con la ruta final del handle que lo abierto está dentro del workspace. En escrituras queda una ventana mínima entre la última comprobación y el `rename`, documentada en [`isycode/winfs.py`](isycode/winfs.py).

### Comandos en sandbox

Necesita **bubblewrap, libseccomp y python3 en Linux**; sin ellos, la opción aparece como no disponible.

- Sin shell: se ejecuta exactamente el programa y los argumentos aprobados (sin pipes, redirecciones ni variables).
- **Red bloqueada** por seccomp, solo el workspace es escribible, `.isyroot` es de solo lectura y las rutas sensibles (`.git`, `.env`, claves…) quedan ocultas.
- Límite de tiempo (120 s por defecto, 600 s como máximo) y 64 KiB de salida.
- Si aparece un archivo sensible nuevo o cambia el programa después de revisarlo, no se ejecuta.
- Los cambios hechos por un comando no se deshacen con `/undo`.

### Git

Status, diffs y commits pasan por su propio owner. Los hooks nunca corren, no se hace push, se ignora la configuración del sistema y los archivos sensibles quedan fuera de status y diffs. Un repositorio cuyo `.git/config` define programas que git ejecutaría (fsmonitor, filtros, pager, textconv, credential helpers, includes…) se rechaza. Solo se admite una carpeta `.git` en la raíz del workspace.

### MCP local

Los servidores stdio se declaran **solo** en tu `~/.config/isycode/mcp.json`, nunca desde el repositorio, porque arrancar uno ejecuta un programa con tus permisos:

```json
{"servers": {"docs": {"command": ["npx", "-y", "some-mcp-server"], "env": {"API_TOKEN": "…"}}}}
```

`/mcp` los lista; `/mcp start docs` pide permiso para ese ejecutable y aprobación del comando exacto. Mientras corre, sus herramientas aparecen para el modelo y **cada llamada** muestra los argumentos exactos y pide aprobación. Los servidores corren con tu usuario (red incluida), en la carpeta del workspace y con un entorno mínimo, y se detienen al salir. Sus descripciones y respuestas se tratan como datos no confiables.

### Modo no interactivo

```bash
isycode -p "¿Dónde se valida el token?"
echo "Resume qué hace este proyecto" | isycode -p - --json
```

Responde una vez y sale. Usa los mismos owners, IsySentinel y journal que la TUI. Como nadie puede aprobar nada, **solo ofrece las herramientas sin aprobación** que el workspace ya tenga permitidas (lectura, búsqueda, `git_status`, `git_diff`). Códigos de salida: `0` bien, `1` error, `2` uso incorrecto, `3` petición denegada.

## Comandos `/`

`/` o `Ctrl+P` abren la navegación; `/help` lista todo.

| Comando | Qué hace |
| --- | --- |
| `/undo` | Deshace el último cambio de ISyCode, mostrando antes el diff |
| `/run <programa> [args]` | Ejecuta un comando en el sandbox (pide aprobación) |
| `/git`, `/diff [ruta] [--staged]` | Rama y cambios; diff |
| `/commit <mensaje>` | Commit de los archivos cambiados tras revisar el diff |
| `/mcp`, `/mcp start <nombre>`, `/mcp stop <nombre>` | Servidores MCP locales |
| `/compact` | Resume los mensajes antiguos para liberar contexto |
| `/providers`, `/provider` | Providers y modelos |
| `/session` | Workspace, provider y rol actuales |
| `/readme`, `/plan`, `/review` | Vista previa de README, plan vía IsyMotron (opcional), revisión externa |

**Comandos propios:** un archivo `~/.config/isycode/commands/<nombre>.md` (tuyo) o `.isycode-commands/<nombre>.md` (del workspace, leído con el permiso de lectura) crea `/<nombre>`. `$ARGUMENTS` se sustituye por lo que escribas después. Un comando es solo un prompt: no concede permisos.

## Providers

Selecciónalo desde **Providers** o con `ISYCODE_PROVIDER` / `ISYCODE_MODEL`. Si el provider elegido no tiene clave, ISyCode abre un campo enmascarado para pegarla (también en **Settings → API keys**). La clave se guarda en el keyring del sistema, nunca en el proyecto, el journal ni el historial; sin keyring seguro no se guarda nada y ISyCode indica la variable de entorno. Una clave no concede permiso de red: el host del provider se autoriza aparte (Classic lo incluye).

| Provider | Variable | Nota |
| --- | --- | --- |
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | Nativo con el SDK oficial: `pip install 'isycode[anthropic]'` |
| OpenAI | `OPENAI_API_KEY` | |
| NVIDIA NIM | `NVIDIA_NIM_API_KEY` | Probado con una clave real |
| Nebius | `NEBIUS_API_KEY` | Probado por el equipo |
| Groq | `GROQ_API_KEY` | |
| OpenRouter | `OPENROUTER_API_KEY` | |
| Ollama, llama.cpp | opcional | Endpoints locales |

**Claude nativo:** el provider `anthropic` usa la API Messages con el modelo `claude-opus-5-5` por defecto, thinking adaptativo (su resumen aparece en el bloque de razonamiento) y effort `medium`. Los bloques de thinking se devuelven intactos dentro de un turno de herramientas; si ISyCode recorta contexto, la API descarta los bloques afectados en vez de fallar (`prefix_mismatch_behavior: drop_block`). Si Claude rechaza una petición, el servidor puede reintentarla en otro modelo (`fallbacks: "default"`). Una negativa o una llamada a herramienta cortada por longitud nunca se ejecuta.

Los demás providers comparten el transporte compatible con OpenAI. Que exista el preset no implica que se haya validado una clave real de cada servicio. OAuth no está disponible todavía.

## Configuración personal

| Dónde | Qué |
| --- | --- |
| Settings → My defaults | Modo y tipo de las carpetas nuevas, rol por defecto, pasos del agente (sin límite, 10, 25, 50 o 100), longitud de respuesta |
| Settings → Authority | Permisos y modo de este workspace |
| Settings → API keys | Guardar o quitar claves |
| `~/.config/isycode/commands/*.md` | Tus comandos `/` |
| `~/.config/isycode/mcp.json` | Tus servidores MCP locales |

## Seguridad y límites

ISyCode separa tres conceptos:

1. **`launch_dir`:** la carpeta desde la que se invocó el programa.
2. **`workspace_root`:** el límite lógico que marca `.isyroot`, o `launch_dir` si no hay marker.
3. **Autoridad:** los permisos efectivos para acciones concretas. El marker **nunca** concede acceso.

Cada acción sigue el mismo camino: **intención → execution owner → Workspace Authority → IsySentinel → efecto → receipt**. IsySentinel es deny-by-default: agrega comprobaciones puras (Systembilities) y no ejecuta nada. Las acciones sin owner quedan denegadas. Las aprobaciones son de un solo uso y están ligadas al digest exacto de la petición. Decisiones y receipts van a un journal privado, encadenado por hash y rotado en segmentos de 4 MB (un segmento alterado, faltante o reordenado se detecta). El Gateway mantiene además su propia autenticación y sus scopes.

El inventario de owners y acciones se regenera en [`docs/security/m15-authority-coverage.json`](docs/security/m15-authority-coverage.json). Diseño y límites: [fronteras de seguridad](docs/design/isysentinel-security-boundaries.md), [contrato Mobile Host](docs/mobile-host-v1.md) y [decisión de runtime](docs/decisions/0001-runtime-boundary.md).

## Qué está probado

**Ejecutado de verdad:**

- **TUI:** arranque, paneles Overview/Files, árbol bloqueado sin permiso y paleta (las capturas de arriba).
- **Pyright LSP:** `initialize` y `workspace/symbol` reales en un workspace temporal; las pruebas negativas bloquearon sockets y escritura.
- **Broker semántico local:** build y arranque Docker con health check mediante el owner de ISyCode, en red interna, montaje read-only y sin credenciales.
- **Chat con NVIDIA NIM** tras autorizar el host; cancelación de chat y streaming.

**Implementado y probado solo con dobles de prueba** (la suite hermética lo cubre, pero no se ha ejecutado contra el sistema real):

- Comandos en sandbox: bubblewrap simulado; el bloqueo de sockets por seccomp sí es real.
- Diagnósticos tras editar: servidor LSP simulado, no Pyright.
- Provider Anthropic: el SDK real contra respuestas HTTP simuladas; sin llamadas a la API real.
- MCP local: servidor MCP simulado.
- Archivos en Windows: la lógica se prueba en Linux simulando la ruta final del handle; aún no se ha ejecutado en Windows.

**Parcial o pendiente:**

- **Gateway en vivo:** el cliente semántico y Gateway MCP están conectados, pero falta demostrar una operación contra el Gateway real con permiso local, scope remoto e IDs de workspace coincidentes. Estado en la [auditoría Gateway](docs/security/m15-gateway-audit-2026-09-28.md).
- **LSP:** solo Pyright (`workspace/symbol` y diagnósticos); sin autocompletado ni navegación completa.
- **Mobile Host:** faltan sesiones remotas, streaming, cancelación y approvals remotos.
- **Tailscale:** flujo de owners y UI probado offline; la conectividad real de tailnet sigue **NOT_DEMONSTRATED**.
- **Pickers nativos y portapapeles** (`desktop.file_picker`, `clipboard.copy`): bloqueados hasta que tengan owner.
- **No disponible todavía:** borrar o mover carpetas enteras, borrar archivos binarios o de más de 128 KiB, borrar conversaciones guardadas, OAuth, OpenISy L0/L1.

La [matriz de features](docs/product/tui-feature-matrix.md) detalla la evidencia por superficie.

## Integraciones

- **ISyCo Gateway:** define `GATEWAY_URL` y una clave con scope `isyco.semantic` (HTTPS fuera de loopback). También requiere un ID opaco coincidente entre Gateway e ISyCode; ese ID es un binding operativo, no prueba identidad del filesystem. Hay once operaciones semánticas read-only con payload tipado y revisión explícita, y un flujo manual para invocar una herramienta Gateway MCP con aprobación individual.
- **Acceso privado por Tailscale (opcional):** Settings descubre el cliente local. El wizard ofrece la guía oficial o una instalación automatizada en Ubuntu/Debian en tres pasos aprobados, login de navegador sin guardar credenciales y una ruta Tailscale Serve privada `/isycode` hacia Mobile Host en `127.0.0.1:8765`. Nunca usa Funnel ni `serve reset`. Ver [diseño y evidencia](docs/superpowers/specs/2026-09-29-private-tailnet-setup-design.md).
- **Mobile Host:** escucha en `127.0.0.1:8765`; arranque y pairing con PIN de un solo uso pasan por su owner. Un bind remoto exige certificado y llave TLS.
- **Catálogo externo OpenISy:** con `OPENISY_API_URL` lee estados y metadatos de MCP, Skills y providers; descubrir no activa ni invoca.
- **IsyMotron:** planner/runtime opcional para `/plan`. No es la autoridad de seguridad de ISyCode; sus grants nunca autorizan acciones del producto.
- **Roles:** agentes de ISyCode y los ocho motores de ISyCo en catálogos separados. Elegir un rol no ejecuta comandos ni concede permisos.

## Atajos

| Atajo | Acción |
| --- | --- |
| `Enter` / `Shift+Enter` | Enviar / nueva línea |
| `Esc` | Detener el turno del agente; si no hay operación, volver o cerrar menú |
| `/` o `Ctrl+P` | Navegación semántica |
| `Ctrl+F` | Buscar en la consola |
| `Ctrl+B` | Mostrar u ocultar el panel lateral |
| `F6` / `Shift+F6` | Files / Overview |
| `F7` / `Shift+F7` | Ancho del panel lateral |
| `Ctrl+L` | Volver al composer conservando el borrador |

El engranaje **Settings** incluye el mapa completo.

## Roadmap y documentación

La estrategia tiene dos etapas: primero **ISyCode Secure**, con acciones tipadas y permisos mínimos; después **ISyCode Full**, sumando capacidades con permisos explícitos. Full no desactiva IsySentinel: cada capacidad nueva necesita su owner, sus límites y su receipt.

Prioridades abiertas:

1. Cerrar los pendientes remotos de M15: checker estructural del Gateway, HTTPS/proxy de despliegue y una operación semántica real con permiso y scope.
2. Cerrar M16: sesiones recuperables, diagnósticos, cobertura UX y matriz con testigos reproducibles.
3. Validar en entornos reales lo que hoy solo tiene dobles de prueba (sandbox de comandos, Pyright, Claude, MCP, Windows).
4. Completar Mobile Host con adapters, sesiones y approvals.
5. Evaluar L0/L1 cuando la base de seguridad esté cerrada.

El release no se declara "daily-driver-ready" mientras M15 siga abierto.

- [Guía rápida en español](GUIA.md)
- [Roadmap por milestones](ROADMAP.md)
- [Matriz de features y evidencia](docs/product/tui-feature-matrix.md)
- [Comparativa con otras CLIs](docs/product/cli-competitive-audit.md)
- [Fronteras de IsySentinel](docs/design/isysentinel-security-boundaries.md)
- [Contrato Mobile Host v1](docs/mobile-host-v1.md)
