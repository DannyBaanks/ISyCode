# GOLDEN 2 — sandbox interp (Layer a filtro best-effort)

**Estado de la pieza:** Verified — GOLDEN 2 corriendo.
**Fecha de la corrida:** 2026-08-05 (miércoles).
**Repo verificado:** `C:\Development\IsyVM\` (venv dedicado).
**Python:** 3.12.4 (`C:\Development\IsyVM\.venv\Scripts\python.exe`).
**pytest:** 9.1.1 (instalado en el venv dedicado via `pip install pytest`).
**Archivo de tests:** `tests/test_sandbox_interp.py`.
**Implementacion verificada:** `sandbox/interp.py`, `sandbox/exceptions.py`.
**Contrato nuevo:** `contracts/vm.sandbox_interp.iesy` (supeditado a `vm.isolation.iesy`).

> **Esta pieza verifica el filtro best-effort de la capa (a). No implica
> que Layer_a sea un boundary de seguridad — eso sigue siendo Layer_c_OS,
> pendiente de verificación.**

## Comando corrido

```powershell
cd C:\Development\IsyVM
.\.venv\Scripts\Activate.ps1
python -m pytest tests/test_sandbox_interp.py -v
```

## Output textual de pytest -v (literal, copiado de consola)

```
============================= test session starts =============================
platform win32 -- Python 3.12.4, pytest-9.1.1, pluggy-1.6.0 -- C:\Development\IsyVM\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Development\IsyVM
collecting ... collected 9 items

tests/test_sandbox_interp.py::test_runs_simple_safe_program PASSED       [ 11%]
tests/test_sandbox_interp.py::test_print_allowed_in_safe_builtins PASSED [ 22%]
tests/test_sandbox_interp.py::test_import_os_detected PASSED             [ 33%]
tests/test_sandbox_interp.py::test_import_subprocess_detected PASSED     [ 44%]
tests/test_sandbox_interp.py::test_open_call_detected PASSED             [ 55%]
tests/test_sandbox_interp.py::test_eval_call_detected PASSED             [ 66%]
tests/test_sandbox_interp.py::test_dunder_subclasses_escape_detected PASSED [ 77%]
tests/test_sandbox_interp.py::test_dunder_import_builtin_detected PASSED [ 88%]
tests/test_sandbox_interp.py::test_getattr_bypass_detected PASSED        [100%]

============================= 9 passed in 0.02s ==============================
```

## Tabla de los 9 casos (2 positivos + 7 peligrosos)

| #  | Test                                       | Resultado | Categoria | Que certifica |
|----|--------------------------------------------|-----------|-----------|---------------|
| 1  | test_runs_simple_safe_program              | PASSED    | Positivo  | Programa sin builtins peligrosos ejecuta y devuelve namespace correcto (`result == 30`) |
| 2  | test_print_allowed_in_safe_builtins        | PASSED    | Positivo  | `print` esta en SAFE_BUILTINS y se ejecuta sin raise |
| 3  | test_import_os_detected                    | PASSED    | Peligroso | `import os` + `os.system(...)` levanta `UnsafeOperationDetected` (BANNED_IMPORT_MODULES) |
| 4  | test_import_subprocess_detected            | PASSED    | Peligroso | `import subprocess` levanta (BANNED_IMPORT_MODULES) |
| 5  | test_open_call_detected                    | PASSED    | Peligroso | `open(...)` levanta (BANNED_CALL_NAMES) |
| 6  | test_eval_call_detected                    | PASSED    | Peligroso | `eval(...)` levanta (BANNED_CALL_NAMES) |
| 7  | test_dunder_subclasses_escape_detected     | PASSED    | Peligroso | `().__class__.__bases__[0].__subclasses__()` levanta (BANNED_ATTR_NAMES — vector real rexec/Bastion) |
| 8  | test_dunder_import_builtin_detected        | PASSED    | Peligroso | `__import__('os')` levanta (BANNED_CALL_NAMES) |
| 9  | test_getattr_bypass_detected               | PASSED    | Peligroso | `getattr((), '__class__')` levanta (BANNED_CALL_NAMES — bypass via string) |

## Resumen

- **9 passed, 0 failed, 0 errored, 0 skipped** en 0.02s.
- 2 PASS positivos (programa seguro ejecuta, `print` permitido).
- 7 PASS peligrosos (cada vector de escape conocido detectado y
  rechazado con `UnsafeOperationDetected` antes de `exec()`).
- **GOLDEN 2 Verified corriendo.**

## Regresión: GOLDEN 1 + GOLDEN 2 juntos (19/19)

Confirmado que agregar `sandbox/` no rompe el bridge. Comando corrido:

```powershell
C:\Development\IsyVM\.venv\Scripts\python.exe -m pytest tests/test_bridge_isolation.py tests/test_sandbox_interp.py -v
```

Resultado: `19 passed in 0.04s`. Sin regresiones.

## Verificación de invariantes (cumplimiento de contrato)

- **Law `static_verify_before_exec`**: `run_program()` llama
  `verify_program()` en linea 110 antes de `exec()` en linea 113. No
  existe atajo. Compliance OK.
- **Law `explicit_deny_lists`**: `BANNED_IMPORT_MODULES`,
  `BANNED_CALL_NAMES`, `BANNED_ATTR_NAMES` son `frozenset` literales en
  el codigo (lineas 27-41). Ninguna heuristica/ML. Compliance OK.
- **Law `restricted_builtins_only`**: `run_program` inyecta
  `{"__builtins__": SAFE_BUILTINS}` (linea 112), nunca los builtins
  reales del host. `SAFE_BUILTINS` es dict literal (lineas 43-49).
  Compliance OK.
- **Law `no_boundary_claim`**: grep en `sandbox/*.py` y
  `tests/test_sandbox_interp.py` por las palabras "aisla", "protege",
  "protect", "isolat". Todas las ocurrencias estan **negando** la
  afirmacion ("NO boundary de seguridad", "NO es un sandbox real",
  "no una promesa de aislamiento"), nunca afirmándola. Compliance OK.
- **`vm.isolation.iesy` v0.2.0**: NO se modifico (ley `layer_a_best_effort_only`
  sigue en pie — sandbox/interp.py nunca afirma aislar, solo filtrar).

## Vectores cubiertos por el filtro (7 peligrosos)

1. **Import module** (`os`, `subprocess`) — atrapado por `visit_Import` /
   `visit_ImportFrom`.
2. **Llamada peligrosa** (`open`, `eval`) — atrapado por `visit_Call`
   cuando `node.func` es `ast.Name` o `ast.Attribute`.
3. **Introspeccion via dunders** (`__class__`, `__bases__`, `__subclasses__`)
   — atrapado por `visit_Attribute`. Este es el vector real que rompio
   rexec/Bastion en Python 3.0.
4. **`__import__` builtin** — atrapado por `visit_Call` (es un `Name`).
5. **`getattr` bypass via string** (`getattr((), '__class__')`) —
   atrapado por `visit_Call` porque `getattr` esta en `BANNED_CALL_NAMES`.
   Sin este entry, el filtro que solo mira `ast.Attribute` seria
   eludible pasando el atributo como string.

## Lo que este filtro **NO** sostiene (honestidad del contrato)

- No es boundary de seguridad real. Un interprete Python en el mismo
  proceso que el host tiene superficie de ataque residual: objetos
  vivos alcanzables por introspeccion no listados aquí, integer
  overflows en CPython, deserializacion via representaciones, etc.
- El boundary de confianza OPERACIONAL hoy es **Layer_b_WASM si se
  activa, si no NINGUNO**. El TARGET es **Layer_c_OS** (pending
  verification).
- Este filtro cumple el rol honesto de **capa (a)**: pre-linter
  best-effort pre-ejecucion, complementario a `exec()` con
  `SAFE_BUILTINS`.

## Que queda pendiente (NO cubierto por GOLDEN 2)

- **GOLDEN 4 — core/cpu.py** (carpeta `core/` aun vacia con `.gitkeep`).
- **Layer_b_WASM** (`sandbox/wasm_membrane.py`) — fuera de alcance.
- **Layer_c_OS** (`sandbox/os_membrane.py`) — fuera de alcance; sigue
  `Documented — pending verification`.
- No se invoco `Engine.execute` ni nada de ISyCo (el sandbox es
  standalone sobre el source string que se le pasa, no toca el bridge).

## Reproducibilidad

```powershell
cd C:\Development\IsyVM
C:\Development\IsyVM\.venv\Scripts\python.exe -m pytest tests/test_sandbox_interp.py -v
```

Salida esperada: `9 passed in <1s`.
