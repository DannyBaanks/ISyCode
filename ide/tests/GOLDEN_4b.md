# GOLDEN 4b — verifier/contract_verifier.py multi-contrato (sandbox_interp + cpu)

**Estado de la pieza:** Verified — GOLDEN 4b corriendo.
**Fecha de la corrida:** 2026-08-05 (miércoles).
**Repo verificado:** `C:\Development\IsyVM\` (venv dedicado).
**Python:** 3.12.4 (`C:\Development\IsyVM\.venv\Scripts\python.exe`).
**pytest:** 9.1.1 (instalado en el venv dedicado).
**Codigo modificado:** `verifier/contract_verifier.py` (generalizado a multi-contrato).
**Archivo de tests:** `tests/test_contract_verifier.py` (extendido).
**Contrato verificado nuevo:** `contracts/vm.cpu.iesy` (5 leyes).

> **GOLDEN 4b generaliza `contract_verifier.py` de contrato unico a
> multi-contrato.** Cada par (contrato, codigo) se modela como
> `AuditTarget`. La completitud ley <-> checker se mantiene PER-CONTRATO
> (no global), para que un checker de sandbox no sea huerfano solo porque
> no existe ley homonima en `vm.cpu`. Regresion GOLDEN 3 (`vm.sandbox_interp`)
> garantizada: `run_all_checks()` sin args sigue devolviendo la lista plana
> de siempre.

## Comando corrido (solo GOLDEN 4b)

```powershell
cd C:\Development\IsyVM
.\.venv\Scripts\Activate.ps1
python -m pytest tests/test_contract_verifier.py -v
```

### Output literal

```
============================= test session starts =============================
platform win32 -- Python 3.12.4, pytest-9.1.1, pluggy-1.6.0 -- C:\Development\IsyVM\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Development\IsyVM
collecting ... collected 4 items

tests/test_contract_verifier.py::test_parser_extracts_4_law_names_sandbox PASSED [ 25%]
tests/test_contract_verifier.py::test_parser_extracts_5_law_names_cpu    PASSED [ 50%]
tests/test_contract_verifier.py::test_contract_holds_sandbox_interp      PASSED [ 75%]
tests/test_contract_verifier.py::test_contract_holds_cpu                 PASSED [100%]

============================== warnings summary ===============================
tests/test_contract_verifier.py::test_contract_holds_cpu
  C:\Development\IsyVM\verifier\contract_verifier.py:336: DeprecationWarning: ast.Num is deprecated and will be removed in Python 3.14; use ast.Constant instead
    (ast.Constant, ast.Num))

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warning.html
=================== 4 passed, 1 warning in 0.06s ===================
```

## Comando corrido (regresion GOLDEN 1 + 2 + 3 + 4a + 4b)

```powershell
python -m pytest tests/ -v
```

### Output literal (resumen)

```
============================= 33 passed, 1 warning in 0.11s ========================
```

Detalle por archivo de tests:

| Archivo                                  | Tests | Resultado |
|------------------------------------------|-------|-----------|
| test_bridge_isolation.py                 | 10    | 10 PASSED |
| test_contract_verifier.py               | 4     | 4 PASSED  |
| test_core_cpu.py                        | 10    | 10 PASSED |
| test_sandbox_interp.py                  | 9     | 9 PASSED  |
| **Total**                                | **33**| **33 PASSED** |

**Sin regresiones:** 10 GOLDEN 1 + 9 GOLDEN 2 + 4 GOLDEN 3+4b (2 sandbox + 2 cpu) + 10 GOLDEN 4a = 33 passed.

> La advertencia `DeprecationWarning: ast.Num` en la linea 336 de
> `contract_verifier.py` es NO bloqueante (Python 3.14 sigue en roadmap;
> el codepath cubre `ast.Constant` primero). No afecta la pasada actual.

## Resultado

- pytest solo GOLDEN 4b: `4 passed` (regresion sandbox 2/2 + cpu nuevo 2/2).
- pytest regresion: `33 passed`.
- **GOLDEN 4b Verified corriendo.**

## Arquitectura del verificador generalizado

### `AuditTarget` (Nuevo en 4b)

Cada contrato auditado se modela como un `AuditTarget` dataclass:

```python
@dataclass
class AuditTarget:
    name: str
    contract_path: Path
    audit_paths: List[Path]
    checkers: Dict[str, Callable[[str, ast.Module, dict], CheckResult]]
```

- `name`: identificador del contrato (`"sandbox_interp"`, `"cpu"`).
- `contract_path`: ruta al `.iesy` con las leyes.
- `audit_paths`: codigo a auditar (lista, cada uno se parsea con `ast`).
- `checkers`: `Dict[ley_nombre, callable]` que recibe `(source, tree, extra)`
  y retorna `CheckResult(law, result, detail)`. PER-CONTRATO, no global.

### `DEFAULT_AUDIT_TARGETS` (orden determinista)

La lista de targets auditados por defecto es fija y ordenada:

1. `sandbox_interp` — contrato `vm.sandbox_interp.iesy`, audita
   `sandbox/interp.py`, `sandbox/exceptions.py`, `sandbox/__init__.py`.
2. `cpu` — contrato `vm.cpu.iesy`, audita `core/cpu.py`.

### API publica (retrocompat + nueva)

```
DEFAULT_AUDIT_TARGETS         -> List[AuditTarget]             (registry)
run_all_checks()              -> List[CheckResult]             (retrocompat GOLDEN 3, lista plana de sandbox_interp)
run_all_checks_for(name)      -> Dict[str, List[CheckResult]]  (key=target name)
                                              name="cpu"      -> solo cpu
                                              name="sandbox_interp" -> solo sandbox
                                              name="all"      -> todos
write_report()                -> None                          (CONTRACT_VERIFICATION.md, una seccion por target)
```

### Completitud bidireccional ley <-> checker (PER-CONTRATO)

Invariante verificada por `test_contract_holds_*`:
- Cada ley listada en el `.iesy` (via `extract_law_names`) tiene un
  checker homonimo en `target.checkers`.
- Cada checker en `target.checkers` corresponde a una ley del `.iesy`.
- Si se rompe la bidireccionalidad, el test falla con mensaje explicito
  indicando que ley o checker esta huerfano.

## Contrato vm.cpu.iesy — 5 leyes (verificadas automaticamente)

Output literal de `run_all_checks_for("cpu")`:

| Ley                      | Resultado | Detail (checker determinista) |
|--------------------------|-----------|-------------------------------|
| `harvard_separation`     | PASS      | todos los JMP/JZ usan arg literal int en `Instruction(...)` |
| `fixed_instruction_set`  | PASS      | `OPCODES` es `frozenset` literal; `validate_program` rechaza opcodes desconocidos |
| `bounded_execution`      | PASS      | `MAX_STEPS` y `MAX_STACK` definidas; `run()` respeta ambos limites |
| `no_host_capability`     | PASS      | `cpu.py` no importa `os`/`subprocess`/`io`; `OPCODES` no contiene opcodes de I/O |
| `deterministic_halt`     | PASS      | todas las excepciones son `CPUFault` nombradas; `HALT` retorna `CPUResult`; sin `raise` generico |

## Contrato vm.sandbox_interp.iesy — 4 leyes (regresion GOLDEN 3)

`run_all_checks()` (retrocompat, sin args) sigue devolviendo la lista
plana de siempre — 4 resultados `PASS`:

| Ley                                | Resultado |
|------------------------------------|-----------|
| `static_verify_before_exec`        | PASS      |
| `explicit_deny_lists`             | PASS      |
| `restricted_builtins_only`        | PASS      |
| `no_boundary_claim`               | PASS      |

> Este es el cierre formal: antes de 4b el verificador era single-contrato
> (hardcodeado a `vm.sandbox_interp.iesy`). Ahora `contract_verifier.py`
> es agnostico del contrato y `DEFAULT_AUDIT_TARGETS` es el punto de
> extension para futuros targets (`vm.isolation.iesy`, `vm.bridge_isyco.iesy`
> ya existen en `contracts/`, pending de su propio GOLDEN).

## Tabla de los 4 tests del archivo (regresion + nuevo)

| #  | Test                                                | Resultado | Categoria  | Que certifica |
|----|-----------------------------------------------------|-----------|------------|---------------|
| 1  | test_parser_extracts_4_law_names_sandbox            | PASSED    | Regresion 3 | `iesy_parser` extrae las 4 leyes de `vm.sandbox_interp.iesy` (`static_verify_before_exec`, `explicit_deny_lists`, `restricted_builtins_only`, `no_boundary_claim`) |
| 2  | test_parser_extracts_5_law_names_cpu                | PASSED    | Nuevo 4b    | `iesy_parser` extrae las 5 leyes de `vm.cpu.iesy` (`harvard_separation`, `fixed_instruction_set`, `bounded_execution`, `no_host_capability`, `deterministic_halt`) |
| 3  | test_contract_holds_sandbox_interp                 | PASSED    | Regresion 3 | `run_all_checks()` sin args sigue dando 4/4 PASS en sandbox_interp (no se rompio retrocompat) |
| 4  | test_contract_holds_cpu                             | PASSED    | Nuevo 4b    | `run_all_checks_for("cpu")` da 5/5 PASS — bidireccionalidad ley<->checker PER-CONTRATO cubierta |

## Contexto de esta pieza (que paso antes)

GOLDEN 4a (mismo dia) construyo `core/cpu.py` con separacion Harvard real
y contrato `vm.cpu.iesy` -- pero `verifier/contract_verifier.py` seguia
hardcodeado a solo sandbox_interp, asi que las 5 leyes de cpu se
verificaban a mano por inspeccion en el markdown de 4a. El verificador
no tenia la generalidad para aceptar un contrato nuevo sin reescribir.

**GOLDEN 4b cierra esa cuenta:** el verificador pasa a ser multi-contrato
con `AuditTarget`, las 5 leyes de `vm.cpu` se verifican deterministamente
en pytest, y la regresion de GOLDEN 3 (las 4 leyes de sandbox_interp)
sigue dando 4/4 PASS sin tocarla. Extension a futuros contratos
(`vm.isolation.iesy`, `vm.bridge_isyco.iesy`) sera solo agregar otro
`AuditTarget` a `DEFAULT_AUDIT_TARGETS` con sus checkers — no reescribir
el verificador.

## Lo que GOLDEN 4b NO hace (por diseño)

- **No verifica `vm.isolation.iesy` ni `vm.bridge_isyco.iesy`:** esos
  contratos existen en `contracts/` pero no tienen `AuditTarget` ni
  checkers aun. Es trabajo de un GOLDEN futuro (3b/3c hipoteticos).
- **No marca `Layer_c_OS` Activa:** sigue `Documented — pending verification`.
- **No construye un oraculo con LLM** para interpretar la prosa `Regla:`
  de los `.iesy` — eso lo sigue escribiendo un humano/agente en el checker
  Python. El verificador es determinista, no LLM-based.
- **No cambia el contrato verificado en runtime** — `contract_verifier.py`
  no modifica los `.iesy` ni el codigo auditado. Es solo lectura del codigo
  y del contrato.

## Prohibiciones respetadas (4b)

- x No modifique `sandbox/interp.py`, `sandbox/exceptions.py`, ni
  `sandbox/__init__.py` (GOLDEN 3 intacto).
- x No modifique `core/cpu.py` (GOLDEN 4a intacto — solo se agrego como
  audit target, no se toco el codigo).
- x No modifique los `.iesy` existentes (`vm.sandbox_interp.iesy`,
  `vm.cpu.iesy`) — solo se leyeron.
- x No marquee `Layer_c_OS` Activa.
- x No commitee nada.

## Que queda pendiente (no bloqueante para 4b)

- **GOLDEN 3b/3c futuro:** checkers para `vm.isolation.iesy` y
  `vm.bridge_isyco.iesy` — cuando se agreguen, basta con nuevo
  `AuditTarget` y checkers, el verificador ya lo soporta.
- **`DeprecationWarning: ast.Num`** (linea 336 de `contract_verifier.py`)
  — no bloqueante hoy (codepath cubre `ast.Constant` primero), pero
  mover a solo `ast.Constant` antes de Python 3.14.
- **`GOLDEN_4b.md` (este archivo)** — recien escrito en esta sesion;
  trabajo tecnico ya estaba cerrado antes de este doc (pytest 33/33).

## Reproducibilidad

```powershell
cd C:\Development\IsyVM
.\.venv\Scripts\Activate.ps1
python -m pytest tests/test_contract_verifier.py -v
python -m pytest tests/ -v
```

Salidas esperadas: `4 passed`; `33 passed`.
