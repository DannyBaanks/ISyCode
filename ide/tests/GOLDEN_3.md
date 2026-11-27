# GOLDEN 3 — contract_verifier (cumplimiento determinista de contrato)

**Estado de la pieza:** Verified — GOLDEN 3 corriendo.
**Fecha de la corrida:** 2026-08-05 (miércoles).
**Repo verificado:** `C:\Development\IsyVM\` (venv dedicado).
**Python:** 3.12.4 (`C:\Development\IsyVM\.venv\Scripts\python.exe`).
**pytest:** 9.1.1 (instalado en el venv dedicado).
**Contrato verificado:** `contracts/vm.sandbox_interp.iesy` (4 leyes).
**Codigo auditado:** `sandbox/interp.py`.
**Implementacion verificada:** `verifier/iesy_parser.py`, `verifier/contract_verifier.py`.
**Archivo de tests:** `tests/test_contract_verifier.py`.

> Esta pieza verifica SOLO el cumplimiento del contrato
> `vm.sandbox_interp.iesy` contra `sandbox/interp.py`. No implica que
> Layer_a sea un boundary de seguridad — eso sigue siendo Layer_c_OS,
> pendiente de verificación. No modifica GOLDEN_2 ni marca nada
> como Active/Trust_Boundary por su cuenta — solo reporta cumplimiento
> del contrato que ya existe.

## Comando corrido (CLI standalone)

```powershell
cd C:\Development\IsyVM
.\.venv\Scripts\Activate.ps1
python -m verifier.contract_verifier
```

### Output literal

```
[OK] static_verify_before_exec: verify_program() en linea 118, exec() en linea 120
[OK] explicit_deny_lists: BANNED_IMPORT_MODULES, BANNED_CALL_NAMES, BANNED_ATTR_NAMES son frozenset literal a nivel modulo
[OK] restricted_builtins_only: run_program inyecta {'__builtins__': SAFE_BUILTINS} explicito
[OK] no_boundary_claim: todas las menciones de aislamiento/proteccion estan negadas explicitamente (ventana de 4 lineas)

PASS (4/4)
```

Exit code: `0`. Reporte generado en `tests/CONTRACT_VERIFICATION.md`.

## Comando corrido (pytest — solo GOLDEN 3)

```powershell
python -m pytest tests/test_contract_verifier.py -v
```

### Output literal

```
============================= test session starts =============================
platform win32 -- Python 3.12.4, pytest-9.1.1, pluggy-1.6.0 -- C:\Development\IsyVM\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Development\IsyVM
collecting ... collected 2 items

tests/test_contract_verifier.py::test_parser_extracts_4_law_names PASSED [ 50%]
tests/test_contract_verifier.py::test_contract_holds PASSED              [100%]

============================== 2 passed in 0.02s ==============================
```

## Comando corrido (pytest — regresión GOLDEN 1 + 2 + 3)

```powershell
python -m pytest tests/ -v
```

### Output literal

```
============================= test session starts =============================
platform win32 -- Python 3.12.4, pytest-9.1.1, pluggy-1.6.0 -- C:\Development\IsyVM\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Development\IsyVM
collecting ... collected 21 items

tests/test_bridge_isolation.py::test_pass1_read_existing_bootstrap_contract PASSED [  4%]
tests/test_bridge_isolation.py::test_pass2_list_contracts_nonempty_and_all_iesy PASSED [  9%]
tests/test_bridge_isolation.py::test_pass3_read_capability_contract_runtime_exe PASSED [ 14%]
tests/test_bridge_isolation.py::test_pass4_list_contracts_atoms_subdir PASSED [ 19%]
tests/test_bridge_isolation.py::test_peligrosa_1a_path_escape_system32 PASSED [ 23%]
tests/test_bridge_isolation.py::test_peligrosa_1b_denied_segment_git PASSED [ 28%]
tests/test_bridge_isolation.py::test_peligrosa_1c_subdir_no_autorizado PASSED [ 33%]
tests/test_bridge_isolation.py::test_peligrosa_1d_extension_no_iesy PASSED [ 38%]
tests/test_bridge_isolation.py::test_peligrosa_1e_capability_inexistente PASSED [ 42%]
tests/test_bridge_isolation.py::test_peligrosa_1f_invariante_no_compile_call PASSED [ 47%]
tests/test_contract_verifier.py::test_parser_extracts_4_law_names PASSED [ 52%]
tests/test_contract_verifier.py::test_contract_holds PASSED              [ 57%]
tests/test_sandbox_interp.py::test_runs_simple_safe_program PASSED       [ 61%]
tests/test_sandbox_interp.py::test_print_allowed_in_safe_builtins PASSED [ 66%]
tests/test_sandbox_interp.py::test_import_os_detected PASSED             [ 71%]
tests/test_sandbox_interp.py::test_import_subprocess_detected PASSED     [ 76%]
tests/test_sandbox_interp.py::test_open_call_detected PASSED             [ 80%]
tests/test_sandbox_interp.py::test_eval_call_detected PASSED             [ 84%]
tests/test_sandbox_interp.py::test_dunder_subclasses_escape_detected PASSED [ 89%]
tests/test_sandbox_interp.py::test_dunder_import_builtin_detected PASSED [ 95%]
tests/test_sandbox_interp.py::test_getattr_bypass_detected PASSED        [100%]

============================= 21 passed in 0.34s ==============================
```

Sin regresiones: 10 GOLDEN 1 + 9 GOLDEN 2 + 2 GOLDEN 3 = 21 passed.

## Resultado

- CLI standalone: exit code `0`, `PASS (4/4)`.
- pytest solo GOLDEN 3: `2 passed` (test_parser_extracts_4_law_names + test_contract_holds).
- pytest regresión: `21 passed`.
- `CONTRACT_VERIFICATION.md` regenerado en disco.
- **GOLDEN 3 Verified corriendo.**

## Tabla de las 4 leyes / checkers

| Ley del contrato | Checker | Resultado | Que valida |
|-----------------|---------|-----------|------------|
| `static_verify_before_exec` | `check_static_verify_before_exec` | PASS | `run_program` llama a `verify_program(...)` (linea 118) antes de `exec(...)` (linea 120) |
| `explicit_deny_lists` | `check_explicit_deny_lists` | PASS | `BANNED_IMPORT_MODULES`, `BANNED_CALL_NAMES`, `BANNED_ATTR_NAMES` son `frozenset({...}`) literal a nivel módulo |
| `restricted_builtins_only` | `check_restricted_builtins_only` | PASS | `SAFE_BUILTINS` es dict literal a nivel módulo y `run_program` inyecta `{'__builtins__': SAFE_BUILTINS}` a `exec(...)` |
| `no_boundary_claim` | `check_no_boundary_claim` | PASS | Todas las menciones de `aisla`/`protege`/`isolat`/`protect`/`boundary` en `sandbox/*.py` están negadas explícitamente (ventana de 4 lineas) |

## Completitud bidireccional ley <-> checker

- El contrato declara 4 leyes.
- El verificador registra 4 checkers.
- Coincidencia exacta: 4/4.
- Huérfanos en cualquier dirección = FAIL. Hoy: 0 huérfanos.

## Contenido de tests/CONTRACT_VERIFICATION.md (generado, no editado a mano)

```markdown
# CONTRACT_VERIFICATION.md -- generado por verifier/contract_verifier.py

Contrato: `contracts\vm.sandbox_interp.iesy`
Codigo auditado: `sandbox\interp.py`
Resultado global: PASS

| Ley | Resultado | Detalle |
|-----|-----------|---------|
| static_verify_before_exec | PASS | verify_program() en linea 118, exec() en linea 120 |
| explicit_deny_lists | PASS | BANNED_IMPORT_MODULES, BANNED_CALL_NAMES, BANNED_ATTR_NAMES son frozenset literal a nivel modulo |
| restricted_builtins_only | PASS | run_program inyecta {'__builtins__': SAFE_BUILTINS} explicito |
| no_boundary_claim | PASS | todas las menciones de aislamiento/proteccion estan negadas explicitamente (ventana de 4 lineas) |

Este reporte certifica cumplimiento del contrato existente. No certifica que Layer_a sea un boundary de seguridad -- eso sigue siendo Layer_c_OS, pendiente de verificacion.
```

## Cómo funciona el verificador (resumen determinista)

1. `verifier/iesy_parser.py::extract_law_names(CONTRACT_PATH)` lee
   `contracts/vm.sandbox_interp.iesy`, localiza la seccion `Laws:`
   (match exacto de `l.strip() == "Laws:"`), y para cada linea que
   matchea `^\s*-\s*Nombre:\s*(\S+)\s*$` appenda el nombre. Devuelve
   `["static_verify_before_exec", "explicit_deny_lists",
     "restricted_builtins_only", "no_boundary_claim"]` en orden.
2. `verifier/contract_verifier.py::run_all_checks()`:
   - Calcula `law_set = set(law_names)` y `checker_set = set(CHECKERS.keys())`.
   - Genera FAILs por simetría: cada ley sin checker y cada checker sin ley.
   - Lee `INTERP_PATH.read_text()`, le hace `ast.parse(source)`.
   - Para cada ley en orden, ejecuta su checker `(source, tree) -> CheckResult`.
   - Acumula todos los `CheckResult` (no raise-al-primero — misma
     disciplina que `sandbox/interp.py::verify_program`).
3. `write_report()` regenera `tests/CONTRACT_VERIFICATION.md` (overwrite).
4. `main()` imprime un OK/XX por ley y la linea final `PASS (4/4)` o
   `FAIL (n/4)`. Exit 0 si todo PASS, 1 si no.

Cada checker es **determinista**: misma entrada → mismo veredicto. Sin
LLM, sin heurística probabilística, sin razonamiento libre sobre
prosa. Lo que el checker valida está escrito a mano porque verificar
semánticamente prosa libre no es tratable (rigor COBOL: nada implícito,
pero tampoco pretender que el parser "entiende" las reglas).

## Que queda pendiente (NO cubierto por GOLDEN 3)

- **Extension a otros contratos** (`vm.isolation.iesy` con 7 leyes,
  `vm.bridge_isyco.iesy` con 4 leyes) → GOLDEN 3b futuro si se decide.
- **GOLDEN 4 — core/cpu.py** (carpeta `core/` aun vacia con `.gitkeep`).
- **Layer_b_WASM** (`sandbox/wasm_membrane.py`) — fuera de alcance.
- **Layer_c_OS** (`sandbox/os_membrane.py`) — fuera de alcance; sigue
  `Documented — pending verification`.
- No se invoco `Engine.execute` ni nada de ISyCo (el verificador solo
  lee `sandbox/interp.py` en disco).

## Reproducibilidad

```powershell
cd C:\Development\IsyVM
.\.venv\Scripts\Activate.ps1
python -m verifier.contract_verifier
python -m pytest tests/test_contract_verifier.py -v
python -m pytest tests/ -v
```

Salida esperada: CLI `PASS (4/4)` exit 0; `2 passed`; `21 passed`.
