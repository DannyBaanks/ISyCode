# ISyCode IDE

Native Qt interface, configurable API/local providers and persistent project
conversations. Distribution: `isycode-ide`; desktop entry: `isycode-ide`;
bundled TUI: `isycode-ide tui`. The official `isycode` command is not registered.

Owner guide: [GUIA.md](GUIA.md). Accepted design and implementation plan:
[docs/design/SPEC.md](docs/design/SPEC.md),
[docs/superpowers/plans/2026-10-10-isycode-ide.md](docs/superpowers/plans/2026-10-10-isycode-ide.md).
Progress and verification limits: [docs/implementation-progress.md](docs/implementation-progress.md).

The sections below preserve the original prototype documentation, including
historical Windows commands and installation names. Use the guide above for
the new IDE; historical test counts below are not verification of this branch.

## Original IsyVM v0.2.0 documentation

IsyVM es una **VM de contención** (sandbox) que vive **afuera de ISyCo**, como
carpeta hermana en `C:\Development\IsyVM\`.

Propósito: ejecutar cosas potencialmente peligrosas (código no confiable,
payloads raros, etc.) sin fugas al host — con promesas honestas por capa.

---

## Cómo correrlo (rápido)

```bat
cd C:\Development\IsyVM

:: Estado / identidad
isyvm.cmd whoami
isyvm.cmd status

:: Suite completa (69 passed, 1 platform skip)
isyvm.cmd test

:: Verificador de contratos multi-target
isyvm.cmd verify

:: Ejecutar Python filtrado (Layer_a — NO es boundary real)
isyvm.cmd run "x = 1 + 2"

:: CPU Harvard mínima
isyvm.cmd cpu "PUSH 3; PUSH 4; ADD; HALT"
```

## Instalación como `isycode`

Desde el checkout local:

```bat
cd C:\Development\IsyVM
.venv\Scripts\python.exe -m pip install -e .
```

Con el entorno virtual activado, el comando queda disponible como:

```bat
isycode
```

Sin argumentos abre la TUI existente. También acepta los comandos del CLI:

```bat
isycode plan "review the resident"
isycode code
isycode resident status
isycode agent run "inspect the workspace"
```

Para una instalación global o aislada, usar un entorno administrado por el
usuario (`venv` o `pipx`); ISyVM no instala dependencias ni modelos por su
cuenta.

Sin `isyvm.cmd`:

```bat
cd C:\Development\IsyVM
.venv\Scripts\python.exe -m engine.bootstrap test
.venv\Scripts\python.exe -m engine.bootstrap verify
```

Desde **ISyCo** (CLI unificado):

```bat
cd C:\Development\ISyCo
isyco shell
  /isyvm status
  /isyvm test
  /isyvm bootstrap
```

One-shot:

```bat
isyco shell -c "/isyvm test"
```

---

## Modelo de aislamiento (honesto)

| Capa | Qué es | Boundary real? | Estado |
|------|--------|----------------|--------|
| **Layer_a** Interprete Python filtrado | pre-linter best-effort | **NO** | Siempre activo |
| **Layer_b** WASM (wasmtime/wasmer) | runtime previsto | **NO** | Stub / unavailable |
| **Layer_c** OS (Hyper-V Ubuntu) | VM real + checkpoint | **SÍ** target | Documented — Danny debe verificar con ojos |

**Runtime operacional hoy:** Layer_a best-effort local únicamente.  
**Trust boundary target:** Layer_c_OS (Hyper-V) — requiere activación manual de Danny.

---

## Estado GOLDEN (2026-08-06)

| Pieza | Estado | Tests |
|-------|--------|------:|
| GOLDEN 1 bridge isolation | **Verified** | 10 |
| GOLDEN 2 sandbox interp | **Verified** | 9 |
| GOLDEN 3 contract_verifier | **Verified** | 4 |
| GOLDEN 4a core/cpu Harvard | **Verified** | 10 |
| GOLDEN 4b multi-contrato | **Verified** | (suite total **33/33**) |
| GOLDEN 5 agent-bridge spike | Documentado, **NO Active** | N/A |
| Layer_c_OS Hyper-V | Documented — pending Danny | — |

The GOLDEN baseline covers the original containment/CPU/verifier slice. The
agent CLI is a separate local prototype with provider and tool-loop tests.
Layer A is a best-effort local runtime, not a secure VM or production sandbox.

---

## Árbol

```
IsyVM/
  engine/bootstrap.py     ← CLI principal
  isyvm.cmd               ← launcher Windows
  core/cpu.py             ← ISA mínima Harvard
  sandbox/interp.py       ← Layer_a filtro Python
  verifier/               ← contract_verifier multi-target
  bridge/                 ← lectura aislada hacia ISyCo
  contracts/*.iesy        ← leyes
  tests/                  ← GOLDEN 1..5 docs + pytest
```

---

## Qué SÍ hace hoy

- Aislar lectura del bridge ISyCo (GOLDEN 1)
- Filtrar/ejecutar Python restringido (GOLDEN 2) — **no confiar como jail**
- Verificar contratos `.iesy` vs código (GOLDEN 3 + 4b)
- Correr programas ISA en CPU Harvard (GOLDEN 4a)
- CLI unificado + integración `isyco shell /isyvm`

## Qué NO hace / no miente

- No es un jail perfecto solo con Layer_a
- No activa Hyper-V sola (Danny)
- GOLDEN 5 es bitácora experimental del bridge multi-agente, no pieza Active
- No invoca engines de lenguajes de ISyCo
- `~/.isyvm/secrets.json`, when used as a keyring fallback, is plaintext
  development storage and must not be treated as encrypted.

## Provider Boundaries

- OpenAI, Anthropic, Google, NVIDIA-compatible, and Ollama providers use the
  IsyVM agent loop and its advertised tools.
- The `claude` provider is classified as `EXTERNAL_AGENT / EXTERNAL_LOOP`:
  it delegates to the official `claude -p` CLI, which owns its own tool loop.
  It is not presented as full IsyVM policy control.
- Bash is not advertised as an agent tool. Layer B and Layer C are unavailable
  until implemented; requests that require them fail explicitly instead of
  falling through to Layer A.

## Structural Resident

ISyVM includes an optional, read-only structural resident. It is not a coding
agent and never receives write, delete, exec, shell, git, network, policy, or
runtime tools. The host owns its persistent records under:

```text
.isyvm/resident/
  self_map.jsonl
  decisions.jsonl
  changes.jsonl
  constraints.jsonl
  config.json
  sessions/<session-id>.jsonl
```

The resident provides compact architectural guidance; it does not make
implementation decisions. Its default provider configuration is disabled and
does not download models or make network calls. A provider can be injected for
local/fake experiments through the existing provider boundary.

```bat
isyvm.cmd plan "modify the resident query guidance"
isyvm.cmd plan add modify core/agent/run.py "preserve tool protocol"
isyvm.cmd mode
isyvm.cmd code
isyvm.cmd resident scan
isyvm.cmd resident status
isyvm.cmd resident query "modify core/runtime/base.py"
isyvm.cmd resident verify
```

`plan` switches to PLAN mode and can create a JSONL plan artifact. `code`
switches to CODER mode and records approval of the current plan. PLAN mode
does not advertise or authorize write, edit, or Python tools; CODER mode still
passes every operation through policy and the Layer A workspace boundary.

---

## Contratos

- `contracts/vm.isolation.iesy`
- `contracts/vm.bridge_isyco.iesy`
- `contracts/vm.sandbox_interp.iesy`
- `contracts/vm.cpu.iesy`

Tras `isyvm.cmd verify` se regenera `tests/CONTRACT_VERIFICATION.md`.
