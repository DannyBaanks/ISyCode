# OpenISy / opencode — sonda viva 2026-10-03

**Estado:** sonda de CLI hecha. Nada de esta lista está implementado en ISyCode por haber corrido OpenISy. No se editó `docs/ROADMAP.md` (lease `codex-tui-roadmap-audit`). No bloquea M16. No se copia código ni marca.

**Hipótesis nula:** el wrapper `openisy` y el binario `opencode` son la misma superficie. **Falsada.**

## Qué se ejecutó

| Superficie | Qué es | `--version` |
|---|---|---|
| `/home/danny/.opencode/bin/openisy` | wrapper de 622 bytes. Fuerza `OPENCODE_EXPERIMENTAL_L1=1` y ejecuta `OpenISy/packages/opencode/src/index.ts` con bun | `1.18.31` exit 0 |
| `/home/danny/.opencode/bin/opencode` | binario de 185165952 bytes, 2026-09-21. Sin `l1`, `ir`, `session-guides` ni `--safe-mode` en `--help` | `1.18.32` exit 0 |
| `packages/opencode/package.json` | versión declarada del fork | `1.18.25` (no es lo que imprime el CLI) |

El `1.18.31` es el fallback de `packages/core/src/installation/version.ts` cuando `OPENCODE_VERSION` no está inyectado (`bun run` desde fuente). El binario es otro build. Comparten `~/.local/share/opencode`. Un `opencode` en PATH no es este fork.

Checkout: `/home/danny/Development/ISyCo/OpenISy`, rama `l0l1`, HEAD `80c7433`. No se corrió `upgrade`, `uninstall`, `plugin`, `pr`, `login`, `l1 seam`, `l1 activate`, ni un prompt.

## Probes

| Probe | Resultado medido |
|---|---|
| `openisy --help` | Exit 0. Ayuda en **stderr**, stdout vacío. Comandos de fork ausentes en el binario: `l1`, `ir`, `session-guides`, `--safe-mode`. |
| `--not-a-real-flag` | Exit 1. stdout y stderr vacíos. sha256 `e3b0c442…` (archivo vacío). No dice "unknown option". |
| `l1 list` | Exit 0. Una tool: `vm-plan` v0.1.0 generation=1, gates validate/test/probe/seal = pass, effects=[], activated_at=2026-09-11T17:50:04.916Z. Texto en stderr. sha256 `e4a12151…`. |
| `l1 doctor` | Exit 0. project root `ISyCo/.opencode/l1`, global `~/.local/share/opencode/l1`. ACTIVE_GENERATIONS 1, REJECTED 0, INCOMPLETE_TX 0. sha256 `b29bf891…`. |
| `--safe-mode l1 list` | Exit 0. Sigue imprimiendo `vm-plan`. El banner de `opencode-mobile` desaparece. Safe-mode no es un apagado de L1 para este inspector. |
| `mcp list` | Exit 0. Conectó de verdad: `isyco-gateway` y `playwright`, ambos `connected`. Listar no es inerte. |
| `agent list` | Exit 0. 15 agentes. `build (primary)` abre con `permission * / allow / *`. `doom_loop` es ask. El resto del blob son allows de `external_directory`. No se cita entero. |
| `debug skill` | Exit 0. 22 skills. 1 built-in (`customize-opencode`). 8 desde `~/.agents/skills` (tavily). 13 desde `~/.claude/skills`. El cuerpo completo va en el JSON. |
| `session-guides list` | Exit 0. stderr `[]`. |
| `ir symbols` sobre `handshake.py` | Exit 0. JSON en stderr. engine=python, symbols=368, edges=476, diagnostics=0, `degraded` presente y null. sha256 `aec4939f…`. |
| `models` | Exit 0. 646 modelos en **stdout** (al revés que `l1 list`). openrouter 390, huggingface 78, nvidia 57, opencode 42, opencode-go 29, nebius 21, openai 16, xai 13. sha256 `2bd06437…`. |
| `stats` | Exit 0. 203 sesiones, 22722 mensajes, 13 días, $211.05. Es el data dir compartido, no un ledger solo del fork. |
| `providers list` | Exit 0. 7 credenciales (tipo oauth/api, sin valor) y `NVIDIA_API_KEY` en entorno (nombre, no valor). No se imprimió secreto. |
| `debug paths` | data/config/state bajo `opencode`, no bajo `openisy`. |

Plugin `opencode-mobile` v1.4.0 escribe a stdout en casi todo subcomando y se salta si no es `serve`.

## Ya cubierto; no reabrir

M3 ya pide que MCP/skills reflejen estado real. Esta sonda añade que `mcp list` conecta. M9 ya deja L1 al final. M10/M14 ya cubren navegación semántica; `ir symbols` es un witness de que el CLI del fork responde, no un hueco nuevo. M17 ya dice que una skill no es un grant; aquí solo se midió que el fork carga skills de Claude y de `~/.agents`.

## No copiar

- El binario `opencode` como si fuera OpenISy. No tiene L1 ni IR.
- `--auto` ("auto-approve permissions that are not explicitly denied"). Es el bypass. No entra a Secure ni a Classic.
- `permission: * allow *` del agente `build` como preset de ISyCode.
- Tratar `mcp list` como lectura. Arranca servidores.
- El split stdout/stderr. Un headless de ISyCode no puede heredar "el resultado va a stderr y el banner del plugin a stdout".
- Safe-mode como garantía de que L1 no se ve. El inspector sigue listando la generación activa.
- `stats` / `auth.json` compartidos con el binario upstream como si fueran contabilidad de ISyCode.

## Trabajo candidato, sin duplicar M17–M19

- [ ] Si ISyCode invoca OpenISy, el contrato nombra el wrapper `openisy`, no `opencode`. Versión esperada = la que imprime el wrapper, y se registra que `package.json` puede mentir.
- [ ] Un listado de MCP en ISyCode no conecta. Conectar es otra acción, con estado `configured` distinto de `connected`.
- [ ] L1, si se muestra, es evidencia de gates (validate/test/probe/seal), no un grant. Rollback y disable no se disparan solos. Safe-mode de ISyCode, si existe, tiene que ocultar la tool del catálogo ejecutable; el inspector puede seguir viendo el disco.
- [ ] `ir` es lectura. Un símbolo resuelto no autoriza editar el archivo. `degraded` null no se promociona a "completo".
- [ ] Agentes y skills descubiertos se muestran como contexto. No se importa su `permission`.

## Criterios si algo de esto se implementa

- Invocar `opencode` del PATH no cuenta como haber llamado al fork.
- Un listado no abre un socket ni un proceso de MCP.
- Una tool L1 activa no aparece como ejecutable en ISyCode solo porque `l1 list` la imprimió.
- Un flag desconocido no sale en silencio: mensaje y exit distinto de 0.

## NOT_DEMONSTRATED

TUI, `openisy run` con prompt, `l1 seam`, activación nueva, rollback, `session-guides sync`, export de una sesión, que `--safe-mode` quite L1 del registry de tools de una sesión (solo se midió el subcomando `l1 list`).

## Hashes de esta sonda

| Archivo | sha256 |
|---|---|
| `/tmp/oisy-l1list.err` | `e4a121518f2a9c4694f837b04435185a2e88cfd9852fea8159921f09f018a2e8` |
| `/tmp/oisy-doctor.err` | `b29bf891ecf2ac3121cd06d0d291f247a0d4ff738503fda54c1ed11421364a02` |
| `/tmp/oisy-badflag.err` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `/tmp/oisy-ir.err` | `aec4939ffa8a356a7b2143b6fcb5d423185dba4ab85f9c50b18fe5cc3a0dd3b9` |
| `/tmp/oisy-models.out` | `2bd06437db94e53aab2cbd93dcac42f8dc7923bb1bb7c45c9aedb551489fbd82` |
| `/tmp/oc-bin.err` | `b594ad32674bf8008017157833ab87316170523ed23dbd10c37ae9931d2ba178` |

Siguiente experimento: repetir `l1 list` y un `ToolRegistry` bajo `--safe-mode` dentro de una sesión, no solo el inspector. Hasta entonces no se afirma que safe-mode descargue L1 del runtime.
