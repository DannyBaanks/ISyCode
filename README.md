# ISyCode

**Un agente de terminal local-first para trabajar desde una TUI enfocada en el workspace.** ISyCode reúne chat, sesiones, archivos, providers y herramientas en una interfaz de teclado, y mantiene separadas la identidad del proyecto y la autoridad para leerlo.

> Estado: producto en desarrollo. Algunas rutas ya tienen evidencia de ejecución real; otras son parciales o todavía no están conectadas. Esta página distingue ambas cosas.

## La TUI

Las capturas muestran la TUI real de Textual con un workspace temporal de demostración. El texto del chat es estático: no se llamó a un provider, Gateway, herramienta MCP ni comando de shell. El árbol de archivos queda bloqueado porque la captura no tiene un grant de lectura.

| Overview | Archivos | Navegación semántica |
| --- | --- | --- |
| ![TUI: overview](docs/screenshots/01-overview.png) | ![TUI: archivos y límite de autoridad](docs/screenshots/02-files.png) | ![TUI: menú de ramas](docs/screenshots/03-command-palette.png) |

## Qué ofrece

- **Chat en terminal:** conversación con streaming y cancelación con `Esc`; el alcance actual de APIs cloud con clave es OpenAI, NVIDIA NIM, Nebius, Groq y OpenRouter. Ollama y llama.cpp permanecen como endpoints locales opcionales, fuera de la validación de APIs cloud.
- **Workspace con límite explícito:** encuentra el `.isyroot` más cercano o usa el directorio de inicio como fallback. Guarda `launch_dir` y `workspace_root` por separado.
- **Explorador integrado:** árbol, búsqueda acotada, selección y preview gated. Copiar ruta está deshabilitado hasta que `clipboard.copy` tenga owner; los pickers nativos de Context, README y broker también quedan bloqueados en Secure mientras `desktop.file_picker` no tenga owner. La identidad `.isyroot` no es un permiso: la lectura exige grants aplicables y el host de archivos disponible.
- **Sesiones:** en workspaces recurrentes puedes activar **Save conversations** en Settings → Authority. Cada mensaje se guarda mediante el owner `chat_sessions` (Workspace Authority, IsySentinel y receipt) en tu carpeta privada de estado, fuera del proyecto, con API keys, tokens Bearer y similares redactados antes de escribir. **Sessions** lista las conversaciones y permite reanudarlas o empezar una nueva. Sin ese permiso, o en ejecuciones temporales, la conversación vive solo en memoria. Borrar conversaciones guardadas todavía no está disponible.
- **Integraciones visibles:** estados de MCP, Skills, LSP, Gateway, Mobile Host y Bridge; los elementos descubiertos se distinguen de los que se pueden invocar.
- **Roles:** agentes conversacionales de ISyCode y los ocho motores operativos de ISyCo aparecen en catálogos separados. Se transfiere el flujo, propósito y guardrails del motor; elegir un rol no ejecuta sus comandos ni le concede permisos.
- **CLI por intención:** `isycode cli` abre ramas semánticas para explorar las acciones disponibles sin ejecutar shell arbitrario. En la instalación integrada de ISyCo, `isyco cli` deriva al mismo navegador.
- **Búsqueda y ayuda:** `Ctrl+F` busca en la consola actual; `/` y `Ctrl+P` abren el navegador de Skills, Models, MCP, LSP, Files, Roles, Providers, Sessions, Workspace y Commands.
- **Providers y claves:** selector de provider/modelo. Si el provider elegido no tiene llave, ISyCode abre un campo enmascarado para pegarla; también desde Settings → API keys. La llave se guarda en el keyring del sistema operativo para tu usuario (todos los workspaces), nunca en el proyecto, el journal ni el historial. Guardar y quitar llaves pasa por el owner `credentials`: el primer uso pide permiso por servicio y cada guardado o borrado pide confirmación. Sin un keyring seguro (común en Linux sin escritorio) no se guarda nada y ISyCode indica qué variable de entorno usar. Una clave no concede permiso de red.

## Estado comprobable

### Demostrado en ejecución

- **TUI real:** arranque, paneles Overview/Files, árbol bloqueado sin grant y paleta semántica. Las capturas de arriba son del renderer de la aplicación.
- **Pyright LSP:** handshake `initialize` y búsqueda `workspace/symbol` reales en un workspace temporal; pruebas negativas bloquearon sockets y escritura. Es una integración acotada a búsqueda de símbolos, no un LSP completo.
- **Broker semántico local:** build y arranque Docker con health check mediante el owner de ISyCode. El contenedor usa red interna sin puerto publicado, montaje read-only, capabilities eliminadas, `no-new-privileges`, límites de recursos y sin credenciales. `definition` respondió con Jedi; `symbols/search` reportó honestamente fallback. Una ruta no permitida devolvió 404.
- **Cancelación de chat/review y streaming:** el transporte cancela la tarea activa y conserva las respuestas parciales como parciales, fuera del historial utilizable.

Los testigos de Pyright y Docker se ejecutaron sobre datos temporales. No prueban acceso autorizado al workspace de cada usuario ni una operación en el Gateway de producción.

### Implementado con configuración y grants

- Provider chat/model requests pasan por los controles locales de red; requieren credencial y host autorizado.
- `.isyroot`, directorio de lanzamiento, conversación en memoria, paleta, selector de providers/roles, búsqueda de consola y Settings.
- Files/context se leen mediante owners nativos de ISyCode, grants explícitos de Workspace Authority e ISySentinel; `.isyroot` limita el árbol pero nunca concede acceso.
- Once operaciones semánticas read-only del Gateway con payloads tipados, revisión explícita y gates locales/remotos independientes.
- Gateway MCP: listar herramientas y flujo manual para revisar payload y aprobar una llamada individual.
- **Acceso privado opcional por Tailscale:** Settings descubre el cliente local bajo un owner read-only. El wizard ofrece la guía oficial o una instalación automatizada de paquetes Ubuntu/Debian en tres pasos aprobados, login de navegador sin guardar credenciales y una ruta Tailscale Serve privada `/isycode` hacia Mobile Host en loopback `:8765`. Grants por workspace y ejecutable, IsySentinel, aprobación fresca y receipts siguen siendo obligatorios; no se usa `serve reset` ni Funnel. La ruta no se habilita automáticamente. Ver [evidencia y límites de Tailscale](docs/superpowers/specs/2026-09-29-private-tailnet-setup-design.md) y el [contrato Mobile Host](docs/mobile-host-v1.md).
- Lectura de archivos y consultas de símbolos Pyright pasan por owners y permisos específicos cuando se configuran. En Secure están bloqueados la inyección por picker de `AGENTS.md`/`AGENT.md`, el selector de README, la selección de carpeta para broker y copiar ruta porque sus acciones de picker/clipboard aún no tienen owners. Las utilidades nativas se conservan como código, pero no se invocan desde la TUI.
- Mobile Host tiene owner para iniciar loopback con Authority/Sentinel y pairing con PIN de un solo uso, grants por `.isyroot` y receipt antes de devolver la credencial. La ruta Tailscale muestra y verifica el target Mobile Host; el listener y la ruta live permanecen apagados hasta las aprobaciones de la TUI.

“Implementado” significa que hay un flujo en el código; cada integración puede seguir necesitando instalación, credencial, grants y configuración externa. Mira las columnas de evidencia de la [matriz de features](docs/product/tui-feature-matrix.md).

### Parcial o pendiente

- **ISySentinel / M15:** `security.py` agrega decisiones puras; Workspace Authority conserva grants por root. Los owners locales enlazan material de request, Authority/Sentinel y receipts en el journal privado. Esta rama incorpora owners de Mobile Host para start y pairing; el snapshot M15 está actualizado y la suite completa pasa localmente (324 pruebas). En el Gateway separado siguen pendientes el checker estructural, HTTPS/proxy de despliegue y una operación remota con ambos gates. Ver [auditoría Gateway](docs/security/m15-gateway-audit-2026-09-28.md). Las acciones sin owner permanecen DENY.
- **Herramientas del modelo:** con un provider que soporta tool calls y los grants del workspace, el chat usa un bucle nativo de agente (25 pasos por prompt y hasta 8 llamadas por respuesta; pasos y longitud de respuesta se cambian en Settings → My defaults; Esc detiene todo el turno, incluido un comando en marcha). Cuando la conversación ya no cabe, ISyCode resume los mensajes antiguos con el mismo provider (petición autorizada y con receipt como cualquier otra), recorta resultados de herramientas antiguos dentro de un turno largo, y `/compact` lo hace a mano; la conversación guardada conserva el transcript completo. Herramientas: con `workspace_list`, `workspace_read`, `workspace_search` y `workspace_grep` (búsqueda literal en contenido), todas por Workspace Authority e IsySentinel con receipt. Si activas **Edit workspace files** en Settings → Authority, el modelo también puede proponer cambios con `workspace_edit` (reemplaza un fragmento exacto) o `workspace_write` (contenido completo, puede crear carpetas nuevas): ISyCode muestra el diff exacto y solo escribe si lo apruebas; `/undo` enseña el diff inverso del último cambio y lo restaura si lo apruebas. La escritura es atómica, no sigue symlinks, rechaza rutas sensibles y archivos de más de 128 KiB, y no sobrescribe si el archivo cambió después de la revisión. Solo funciona en POSIX (Linux y macOS). Si activas **Run commands in a sandbox** (necesita bubblewrap, libseccomp y python3 en Linux), el modelo puede pedir `workspace_run` y tú `/run <programa> [args]`: cada comando exacto se aprueba por separado, corre sin shell dentro de bubblewrap con la red bloqueada por seccomp, las rutas sensibles (`.git`, `.env`, claves…) ocultas, `.isyroot` de solo lectura y solo el workspace escribible, con límite de tiempo y 64 KiB de salida. Classic nunca lo activa. Los cambios hechos por un comando no se deshacen con `/undo`. No hay borrar ni mover archivos como herramienta. **Git:** con **See git status and diffs** el modelo usa `git_status`/`git_diff` (y tú `/git`, `/diff [ruta] [--staged]`); con **Create git commits**, `git_commit` y `/commit <mensaje>` muestran archivos, mensaje y diff exactos y solo crean el commit si lo apruebas. Los hooks nunca corren, no se hace push, se ignora la config del sistema, los archivos sensibles quedan ocultos y un repo cuyo `.git/config` define programas (fsmonitor, filtros, pager, textconv, credential helpers, includes…) se rechaza. Classic incluye ver status/diff, pero no los commits. **Contexto y comandos propios:** `@ruta/archivo` en un mensaje adjunta ese archivo del workspace (lectura autorizada y con receipt, máx. 5). Los comandos `/nombre` se definen como prompts Markdown en `~/.config/isycode/commands/<nombre>.md` (tuyos) o `.isycode-commands/<nombre>.md` (del workspace, leídos con el permiso de lectura); `$ARGUMENTS` se sustituye por lo que escribas después. Un comando es solo texto: no concede permisos. **Modo no interactivo:** `isycode -p "pregunta"` (o por stdin con `-p -`, y `--json` para salida estructurada) responde una vez y sale. Usa los mismos owners, IsySentinel y journal; como nadie puede aprobar nada, solo ofrece las herramientas de lectura y `git_status`/`git_diff` que el workspace ya tenga permitidas. Código de salida 3 si una petición se deniega. **MCP local:** declara servidores stdio en `~/.config/isycode/mcp.json` (`{"servers": {"nombre": {"command": ["programa", "arg"], "env": {"CLAVE": "valor"}}}}`, nunca desde el repo). `/mcp` los lista y `/mcp start <nombre>` pide permiso para ese ejecutable y aprobación del comando exacto; mientras corre, sus herramientas aparecen para el modelo como `mcp__<servidor>__<herramienta>` y cada llamada muestra los argumentos exactos y pide aprobación. Corren con tus permisos (con red), en la carpeta del workspace y con un entorno mínimo, y se detienen al salir. Descripciones y resultados se tratan como datos no confiables. **Claude nativo:** el provider `anthropic` habla la API Messages de Anthropic con el SDK oficial (instálalo con `pip install 'isycode[anthropic]'` y guarda `ANTHROPIC_API_KEY`); el modelo por defecto es `claude-opus-5-5` con thinking adaptativo (resumen visible en el bloque de razonamiento) y effort `medium`. Los bloques de thinking se devuelven intactos dentro de un turno de herramientas, con `prefix_mismatch_behavior: drop_block` por si ISyCode recorta el contexto, y las negativas del modelo usan `fallbacks: "default"` del lado del servidor. Una negativa o una llamada a herramienta cortada por longitud nunca se ejecuta.
- **Gateway en vivo:** el cliente/owner semántico está conectado en ISyCode, pero falta demostrar una operación contra el Gateway real con grant local, scope remoto e IDs de workspace coincidentes.
- **MCP general:** solo Gateway MCP tiene el flujo manual de invocación. Los otros catálogos son descubrimiento; no activan Skills ni llaman herramientas por sí solos. El bucle de tools del modelo solo expone las herramientas locales del workspace.
- **LSP:** Pyright ofrece `workspace/symbol`; Rust Analyzer se detecta como no soportado. No hay todavía diagnósticos, autocompletado ni navegación completa.
- **Mobile Host:** aún faltan sesiones remotas, streaming, cancelación, approvals, adapters operativos y administración completa de credenciales.
- **Providers:** OAuth todavía no está implementado. Los métodos OAuth leídos de un catálogo externo son metadatos.
- **Tailscale real:** el flujo de owners/UI y la preservación de configuración pasan pruebas offline y un smoke visual temporal. El target de `/isycode` ahora es Mobile Host `127.0.0.1:8765`, pero no se inició el listener ni se cambió Serve; la conectividad de tailnet permanece **NOT_DEMONSTRATED**. El installer queda limitado a Ubuntu/Debian compatible; las demás plataformas muestran pasos manuales.
- **OpenISy L0/L1:** sus contratos se documentan como integración futura; el ciclo de staging, activación, worker aislado, receipts y rollback no está integrado en ISyCode.
- **Auditoría duradera y release:** hay journal hash-chain con verificador read-only e inspector; el journal rota en segmentos de 4 MB encadenados (un segmento alterado, faltante o reordenado se detecta), así que ya no bloquea el workspace al llenarse; la cadena puede verificarse, pero payloads de request/result no se conservan para recomputar sus digests. Faltan diagnósticos unificados, settings completos, accesibilidad/rendimiento y reconciliación final de owners.

## Modos: Classic y Security

Cada workspace elige su modo la primera vez que lo abres; puedes cambiarlo en Settings → Authority. En Settings → My defaults puedes fijar el modo con el que empiezan las carpetas nuevas (preguntar, Classic o Security); es solo una preferencia y no cambia el modo de los workspaces que ya usas.

| | Classic | Security |
|---|---|---|
| Leer y buscar archivos del workspace | incluido | lo activas tú |
| Proponer ediciones | incluido; cada cambio muestra el diff y pide *Apply* | lo activas tú; igual con diff y *Apply* |
| Chat con el provider elegido | incluido (solo hosts de providers conocidos o el endpoint configurado) | lo activas tú |
| Guardar y reanudar conversaciones (workspaces recurrentes) | incluido | lo activas tú |
| Guardar, usar y quitar API keys | incluido; guardar y quitar piden confirmación | lo activas tú por servicio |
| Gateway, MCP, LSP, broker, Tailscale, Mobile Host | permiso explícito | permiso explícito |
| Shell, borrar o mover archivos, archivos sensibles, `.isyroot` | no disponible | no disponible |

Classic es un preset de permisos implícitos de Workspace Authority, no un bypass: IsySentinel revisa cada acción, las aprobaciones por acción siguen y todo queda en el journal de acciones en ambos modos. Los workspaces que ya existían antes de los modos siguen en Security.

## Seguridad y límites

ISyCode separa tres conceptos:

1. **`launch_dir`:** la carpeta desde la que se invocó el programa.
2. **`workspace_root`:** el límite lógico detectado por `.isyroot`, o `launch_dir` si no hay marker.
3. **Autoridad:** los permisos efectivos concedidos para acciones concretas. El marker nunca concede acceso.

Las acciones habilitadas pasan por Workspace Authority, IsySentinel, approval cuando corresponde y un execution owner compatible. Las capacidades sin owner permanecen bloqueadas. El Gateway mantiene además autenticación y scopes remotos independientes. Las decisiones y receipts conectados quedan en el journal privado; approvals de un solo uso se mantienen en memoria durante el proceso.

El diseño y límites están en [fronteras de seguridad](docs/design/isysentinel-security-boundaries.md), [contrato Mobile Host](docs/mobile-host-v1.md) y [decisión de runtime](docs/decisions/0001-runtime-boundary.md).

## Instalar y arrancar

Instalar desde fuente requiere Python 3.10 o posterior. Los paquetes precompilados incluyen el runtime. El TUI usa Textual y Rich; Pyright LSP y el broker Docker son integraciones opcionales.

Al publicar un tag `vX.Y.Z`, CI ejecuta la suite hermética en Linux y, si pasa y coincide con la versión de `pyproject.toml`, construye los paquetes nativos. Cada binario ejecuta un smoke check en su runner Windows, Linux o macOS antes de adjuntarse a un GitHub Release en borrador con `SHA256SUMS`. Las pruebas que requieren un Gateway activo o el checkout hermano de ISyCo se marcan como integración y no se ejecutan en los runners limpios.

- Windows x64: ejecutable de consola `.exe`.
- Linux x64: AppImage y `.deb`, construidos sobre Ubuntu 22.04 (glibc 2.35 o posterior).
- macOS ARM64: instalador `.pkg` y archivo `.tar.gz` con el ejecutable. Ambos quedan sin firma ni notarización de Apple; el `.pkg` puede mostrar avisos del sistema. Intel Mac no está incluido todavía.

El Release queda en borrador para revisión y publicación manual. La TUI se abre desde una terminal; estos paquetes instalan el comando `isycode`, no una aplicación gráfica.

Para instalar, Linux puede ejecutar el AppImage después de `chmod +x` o instalar el `.deb` con `sudo apt install ./archivo.deb`. En Windows, abre `isycode-*.exe` desde PowerShell o Terminal. En macOS, usa el `.pkg` o extrae el `.tar.gz` y coloca el ejecutable en una carpeta de tu `PATH`; los paquetes de macOS no están firmados ni notarizados y pueden mostrar avisos de Gatekeeper.

```bash
git clone https://github.com/DannyBaanks/ISyCode.git
cd ISyCode
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
isycode
```

Para iniciar desde cualquier proyecto con el launcher de este checkout:

```bash
./scripts/install-path
cd /ruta/a/tu/proyecto
isycode
```

`isycode cli` abre el navegador semántico. El wrapper `isyco cli` existe en la instalación integrada con el CLI de ISyCo; el paquete standalone instala `isycode` y no reemplaza ese comando del sistema.

En el primer arranque, se puede marcar el directorio como workspace recurrente. Aceptar crea un `.isyroot` vacío; rechazar mantiene la ejecución temporal. Las conversaciones recurrentes se guardan en `~/.local/state/isycode/isyrcodesessions/` o bajo `$XDG_STATE_HOME`.

### Pruebas

```bash
python -m pytest -q
```

Las pruebas contra un ISyCo Gateway vivo son opt-in porque hablan con un servicio real, y `test_gateway_write_file` escribe y borra un archivo en él. Con el Gateway corriendo:

```bash
ISYCODE_LIVE_GATEWAY=1 python -m pytest -q test_gateway.py
```

## Providers

Selecciona un provider desde **Providers** o configura `ISYCODE_PROVIDER` y `ISYCODE_MODEL`. Variables de credencial aceptadas:

| Provider | Variable |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| NVIDIA NIM | `NVIDIA_NIM_API_KEY` |
| Nebius | `NEBIUS_API_KEY` |
| Groq | `GROQ_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |

Las APIs cloud cubiertas actualmente son OpenAI, NVIDIA NIM, Nebius, Groq y OpenRouter; la compatibilidad del preset no implica que se haya validado una clave real de cada servicio. La captura de uso compartida por el usuario demuestra una respuesta real de NVIDIA NIM tras autorizar el host; Nebius ya había sido probado por el equipo. OpenAI, Groq y OpenRouter todavía no tienen evidencia de prueba real registrada. Ollama y llama.cpp siguen disponibles como endpoints locales opcionales, no como parte de la matriz de validación cloud. Cualquier otro proveedor/API queda abierto para propuesta por PR o issue. También se pueden guardar claves nombradas en el vault del sistema. Sin una clave, ISyCode arranca en estado no configurado. Antes de hacer una solicitud se debe autorizar el host del provider en **Settings → Authority & Security**. OAuth no está disponible todavía.

## Integraciones

- **ISyCo Gateway:** define `GATEWAY_URL` y una clave con scope `isyco.semantic`. Para rutas no locales usa HTTPS. La configuración también requiere un ID opaco coincidente entre Gateway e ISyCode; ese ID es un binding operativo, no prueba identidad física del filesystem.
- **Catálogo externo OpenISy:** define `OPENISY_API_URL`; puede leer estados/metadatos de MCP, Skills y providers, sujeto a autorización de host. Descubrir no activa ni invoca.
- **IsyMotron:** conserva un planner/runtime opcional para proponer planes. En el perfil Secure, las peticiones al provider requieren el grant de host de ISyCode y la ejecución heredada de planes está deshabilitada; sus grants nunca autorizan acciones del producto.
- **Mobile Host:** por defecto escucha en `127.0.0.1:8765`. El bind remoto exige certificado y llave TLS; pairing y health no significan que haya runtime remoto operativo.

## Atajos principales

| Atajo | Acción |
| --- | --- |
| `Enter` / `Shift+Enter` | Enviar / nueva línea |
| `Esc` | Cancelar stream activo; si no hay operación, volver/cerrar menú |
| `/` o `Ctrl+P` | Abrir navegación semántica |
| `Ctrl+F` | Buscar en la consola actual |
| `Ctrl+B` | Mostrar u ocultar panel lateral |
| `F6` / `Shift+F6` | Abrir Files / Overview |
| `F7` / `Shift+F7` | Ajustar ancho del panel lateral |
| `Ctrl+L` | Volver al composer conservando el borrador |

El engranaje **Settings** incluye el mapa completo de atajos.

## Roadmap

El orden de trabajo y los criterios de salida están en [`ROADMAP.md`](ROADMAP.md). Las brechas por superficie, evidencia y estado demostrado están en [`docs/product/tui-feature-matrix.md`](docs/product/tui-feature-matrix.md).

La estrategia tiene dos etapas: primero publicar **ISyCode Secure**, con el conjunto actual de acciones tipadas y permisos mínimos; después ampliar hacia **ISyCode Full** agregando capacidades y grants explícitos. Full no desactiva Sentinel ni convierte grants en ejecución arbitraria: cada capacidad nueva requiere su propio owner, límites y registro de resultado.

Prioridades abiertas:

1. Cerrar los pendientes remotos de M15: corregir el checker estructural del Gateway, verificar HTTPS/proxy de despliegue y demostrar una operación semántica con grant y scope; estado en [auditoría Gateway](docs/security/m15-gateway-audit-2026-09-28.md).
2. Cerrar M16: sesiones recuperables, configuración/diagnósticos, cobertura UX y matriz con testigos reproducibles.
3. Completar la operación real del Gateway semántico como parte del witness M15, con identidad, scopes y grants correctos.
4. Completar Mobile Host con adapters, sesiones/stream, cancelación y approvals.
5. Añadir las acciones de archivos y capacidades runtime únicamente detrás de owners tipados y permisos verificables.
6. Evaluar L0/L1 después de cerrar la base de seguridad; no se incluye como capacidad activa de esta versión.

El release no se declara “daily-driver-ready” mientras M15 siga abierto.

## Documentación

- [Guía rápida en español](GUIA.md)
- [Roadmap por milestones](ROADMAP.md)
- [Matriz de features y evidencia](docs/product/tui-feature-matrix.md)
- [Comparativa con otras CLIs](docs/product/cli-competitive-audit.md)
- [Fronteras de ISySentinel](docs/design/isysentinel-security-boundaries.md)
- [Contrato Mobile Host v1](docs/mobile-host-v1.md)
