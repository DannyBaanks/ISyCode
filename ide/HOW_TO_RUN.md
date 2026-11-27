# Cómo correr IsyVM

## 1 minuto

```bat
cd C:\Development\IsyVM
isyvm.cmd test
```

Esperado: `69 passed, 1 skipped` (el skip corresponde a symlink en Windows sin privilegio).

## Instalar `isycode`

```bat
cd C:\Development\IsyVM
.venv\Scripts\python.exe -m pip install -e .
isycode --help
```

`isycode` sin argumentos abre la TUI; el entry point usa la misma arquitectura
de `isyvm.cmd`, no una CLI paralela.

### Ejecutarlo desde cualquier carpeta (global)

`isycode` usa la carpeta actual como workspace, así que se puede abrir en
cualquier proyecto:

```bat
C:\Development\IsyVM\.venv\Scripts\isycode.exe --help
```

Para que `isycode` funcione escribiéndolo directo en cualquier terminal
(como `opencode` o `claude`), añade el binario al PATH del usuario:

```bat
:: una sola vez
setx PATH "%PATH%;C:\Development\IsyVM\.venv\Scripts"
```

Abre una terminal NUEVA y ya puedes hacer:

```bat
cd C:\Development\MiProyecto
isycode          :: abre la TUI con MiProyecto como workspace
isycode run "x=1+2" --no-stream
isycode provider list
```

La instalación es editable: cualquier cambio en el código se refleja al
instante, sin reinstalar.

## Comandos útiles

| Comando | Qué hace |
|---------|----------|
| `isyvm.cmd whoami` | Resumen GOLDEN + límites honestos |
| `isyvm.cmd status` | Árbol + estado piezas |
| `isyvm.cmd test` | pytest completo (69 passed, 1 platform skip) |
| `isyvm.cmd verify` | contract verifier (multi-contrato) |
| `isyvm.cmd run "x=1+2"` | Python filtrado (Layer_a) |
| `isyvm.cmd cpu "PUSH 3; PUSH 4; ADD; HALT"` | CPU Harvard |
| `isyvm.cmd plan "goal"` | Enter PLAN mode and create JSONL plan |
| `isyvm.cmd code` | Enter CODER mode and approve current plan |
| `isyvm.cmd mode` | Show current mode and plan |
| `isyvm.cmd resident query "..."` | Structural guidance |

## Desde ISyCo

```bat
cd C:\Development\ISyCo
isyco shell
/isyvm status
/isyvm test
```

## Primera vez (venv)

Si no existe `.venv`:

```bat
cd C:\Development\IsyVM
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install pytest
isyvm.cmd test
```

## Hyper-V (Layer_c) — solo Danny

Layer_c_OS **no** la activa un agente. Requiere:

1. Hyper-V habilitado en Windows  
2. VM Ubuntu headless  
3. Checkpoint verificable  

Hasta entonces el boundary real de producción **no** está en Layer_a.
