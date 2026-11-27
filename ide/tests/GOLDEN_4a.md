# GOLDEN 4a — core/cpu.py (CPU minima stack-based, separacion Harvard real)

**Estado de la pieza:** Verified — GOLDEN 4a corriendo.
**Fecha de la corrida:** 2026-08-05 (miércoles).
**Repo verificado:** `C:\Development\IsyVM\` (venv dedicado).
**Python:** 3.12.4 (`C:\Development\IsyVM\.venv\Scripts\python.exe`).
**pytest:** 9.1.1 (instalado en el venv dedicado).
**Contrato nuevo:** `contracts/vm.cpu.iesy` (5 leyes).
**Codigo nuevo:** `core/cpu.py`.
**Archivo de tests:** `tests/test_core_cpu.py`.

> **core/cpu.py demuestra separación Harvard real, no best-effort.** No
> reemplaza a Layer_a/b/c — es una cuarta pieza, con garantía
> estructural en vez de denylist. `verifier/contract_verifier.py`
> todavía NO verifica `vm.cpu.iesy` — eso es GOLDEN 4b.

## Comando corrido (solo GOLDEN 4a)

```powershell
cd C:\Development\IsyVM
.\.venv\Scripts\Activate.ps1
python -m pytest tests/test_core_cpu.py -v
```

### Output literal

```
============================= test session starts =============================
platform win32 -- Python 3.12.4, pytest-9.1.1, pluggy-1.6.0 -- C:\Development\IsyVM\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Development\IsyVM
collecting ... collected 10 items

tests/test_core_cpu.py::test_arithmetic_halts_with_expected_result PASSED [ 10%]
tests/test_core_cpu.py::test_loop_with_jz_and_memory_halts_with_expected_countdown PASSED [ 20%]
tests/test_core_cpu.py::test_unknown_opcode_rejected_statically PASSED   [ 30%]
tests/test_core_cpu.py::test_jump_out_of_bounds_rejected_statically PASSED [ 40%]
tests/test_core_cpu.py::test_memory_out_of_bounds_rejected_statically PASSED [ 50%]
tests/test_core_cpu.py::test_stack_underflow_on_pop_empty PASSED         [ 60%]
tests/test_core_cpu.py::test_division_by_zero PASSED                     [ 70%]
tests/test_core_cpu.py::test_step_limit_exceeded_on_infinite_loop PASSED [ 80%]
tests/test_core_cpu.py::test_stack_overflow_on_unbounded_push_loop PASSED [ 90%]
tests/test_core_cpu.py::test_invalid_operand_type_rejected_statically PASSED [100%]

============================= 10 passed in 0.12s ==============================
```

## Comando corrido (regresión GOLDEN 1 + 2 + 3 + 4a)

```powershell
python -m pytest tests/ -v
```

### Output literal

```
============================= test session starts =============================
platform win32 -- Python 3.12.4, pytest-9.1.1, pluggy-1.6.0 -- C:\Development\IsyVM\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Development\IsyVM
collecting ... collected 31 items

tests/test_bridge_isolation.py::test_pass1_read_existing_bootstrap_contract PASSED [  3%]
tests/test_bridge_isolation.py::test_pass2_list_contracts_nonempty_and_all_iesy PASSED [  6%]
tests/test_bridge_isolation.py::test_pass3_read_capability_contract_runtime_exe PASSED [  9%]
tests/test_bridge_isolation.py::test_pass4_list_contracts_atoms_subdir PASSED [ 12%]
tests/test_bridge_isolation.py::test_peligrosa_1a_path_escape_system32 PASSED [ 16%]
tests/test_bridge_isolation.py::test_peligrosa_1b_denied_segment_git PASSED [ 19%]
tests/test_bridge_isolation.py::test_peligrosa_1c_subdir_no_autorizado PASSED [ 22%]
tests/test_bridge_isolation.py::test_peligrosa_1d_extension_no_iesy PASSED [ 25%]
tests/test_bridge_isolation.py::test_peligrosa_1e_capability_inexistente PASSED [ 29%]
tests/test_bridge_isolation.py::test_peligrosa_1f_invariante_no_compile_call PASSED [ 32%]
tests/test_contract_verifier.py::test_parser_extracts_4_law_names PASSED [ 35%]
tests/test_contract_verifier.py::test_contract_holds PASSED              [ 38%]
tests/test_core_cpu.py::test_arithmetic_halts_with_expected_result PASSED [ 41%]
tests/test_core_cpu.py::test_loop_with_jz_and_memory_halts_with_expected_countdown PASSED [ 45%]
tests/test_core_cpu.py::test_unknown_opcode_rejected_statically PASSED   [ 48%]
tests/test_core_cpu.py::test_jump_out_of_bounds_rejected_statically PASSED [ 51%]
tests/test_core_cpu.py::test_memory_out_of_bounds_rejected_statically PASSED [ 54%]
tests/test_core_cpu.py::test_stack_underflow_on_pop_empty PASSED         [ 58%]
tests/test_core_cpu.py::test_division_by_zero PASSED                     [ 61%]
tests/test_core_cpu.py::test_step_limit_exceeded_on_infinite_loop PASSED [ 64%]
tests/test_core_cpu.py::test_stack_overflow_on_unbounded_push_loop PASSED [ 67%]
tests/test_core_cpu.py::test_invalid_operand_type_rejected_statically PASSED [ 70%]
tests/test_sandbox_interp.py::test_runs_simple_safe_program PASSED       [ 74%]
tests/test_sandbox_interp.py::test_print_allowed_in_safe_builtins PASSED [ 77%]
tests/test_sandbox_interp.py::test_import_os_detected PASSED             [ 80%]
tests/test_sandbox_interp.py::test_import_subprocess_detected PASSED     [ 83%]
tests/test_sandbox_interp.py::test_open_call_detected PASSED             [ 87%]
tests/test_sandbox_interp.py::test_eval_call_detected PASSED             [ 90%]
tests/test_sandbox_interp.py::test_dunder_subclasses_escape_detected PASSED [ 93%]
tests/test_sandbox_interp.py::test_dunder_import_builtin_detected PASSED [ 96%]
tests/test_sandbox_interp.py::test_getattr_bypass_detected PASSED        [100%]

============================= 31 passed in 0.06s ==============================
```

**Sin regresiones:** 10 GOLDEN 1 + 9 GOLDEN 2 + 2 GOLDEN 3 + 10 GOLDEN 4a = 31 passed.

## Resultado

- pytest solo GOLDEN 4a: `10 passed`.
- pytest regresión: `31 passed`.
- **GOLDEN 4a Verified corriendo.**

## Tabla de los 10 casos (2 positivos + 8 peligrosos)

| #  | Test                                                | Resultado | Categoria | Que certifica (ley del contrato) |
|----|-----------------------------------------------------|-----------|-----------|----------------------------------|
| 1  | test_arithmetic_halts_with_expected_result          | PASSED    | Positivo  | Programa valido (`PUSH PUSH ADD PUSH MUL HALT`) ejecuta y deja `stack == [14]` (deterministic_halt) |
| 2  | test_loop_with_jz_and_memory_halts_countdown       | PASSED    | Positivo  | Loop con `JZ`/`MEMORY`/`JMP` cuenta regresiva hasta 0 y halta (harvard_separation: saltos a indices literales) |
| 3  | test_unknown_opcode_rejected_statically            | PASSED    | Peligroso | Opcode `NOPE` fuera de `OPCODES` levanta `UnknownOpcode` en `validate_program()` antes de `run()` (fixed_instruction_set) |
| 4  | test_jump_out_of_bounds_rejected_statically         | PASSED    | Peligroso | `JMP 99` (programa de 2 instrucciones) levanta `JumpOutOfBounds` en `validate_program()` (harvard_separation) |
| 5  | test_memory_out_of_bounds_rejected_statically      | PASSED    | Peligroso | `STORE 9999` (> MEM_SIZE) levanta `MemoryOutOfBounds` en `validate_program()` |
| 6  | test_stack_underflow_on_pop_empty                   | PASSED    | Peligroso | `POP` sobre stack vacio levanta `StackUnderflow` en runtime (deterministic_halt) |
| 7  | test_division_by_zero                                | PASSED    | Peligroso | `DIV` con divisor 0 levanta `DivisionByZero` en runtime (deterministic_halt) |
| 8  | test_step_limit_exceeded_on_infinite_loop           | PASSED    | Peligroso | `JMP 0` (loop infinito) levanta `StepLimitExceeded` al hitting `max_steps` (bounded_execution) |
| 9  | test_stack_overflow_on_unbounded_push_loop          | PASSED    | Peligroso | `PUSH 1; JMP 0` (crece stack sin limite) levanta `StackOverflow` (bounded_execution) |
| 10 | test_invalid_operand_type_rejected_statically       | PASSED    | Peligroso | `PUSH "no-es-int"` levanta `InvalidOperand` en `validate_program()` (fixed_instruction_set) |

## Contrato vm.cpu.iesy — 5 leyes

| Ley | Semantica | Cubierta por tests |
|-----|-----------|-------------------|
| `harvard_separation` | Saltos siempre a indice literal; ningun opcode deriva destino desde datos | 2, 4 |
| `fixed_instruction_set` | Solo opcodes en `OPCODES` (frozenset cerrado); desconocido rechazado en `validate_program()` | 3, 10 |
| `bounded_execution` | `MAX_STEPS` y `MAX_STACK` hard limits; excederlos levanta fault nombrada | 8, 9 |
| `no_host_capability` | Opcodes: aritmetica, stack, memoria 256, ctrl flujo. Sin I/O/import/fs/red/subprocess | (estrucural, verified por inspeccion de `OPCODES`) |
| `deterministic_halt` | Termina en HALT (CPUResult) o CPUFault nombrada; nunca excepcion generica | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 |

## ISA-IsyVM v0.1 (referencia,extraída de core/cpu.py)

- **Opcodes (13):** `PUSH`, `POP`, `DUP`, `SWAP`, `ADD`, `SUB`, `MUL`, `DIV`, `JMP`, `JZ`, `STORE`, `LOAD`, `HALT`.
- **Encoding:** `Instruction(op: str, arg: Optional[int])` NamedTuple.
- **Stack:** `list`, `MAX_STACK = 1024`.
- **Memoria:** 256 celdas int, `MEM_SIZE = 256`.
- **Pasos:** `MAX_STEPS = 100_000` (default; `run()` acepta `max_steps=` override).
- **Faults nombradas:** `CPUFault` base + 8 subclases (`UnknownOpcode`, `InvalidOperand`, `JumpOutOfBounds`, `StackUnderflow`, `StackOverflow`, `MemoryOutOfBounds`, `DivisionByZero`, `StepLimitExceeded`).

## Verificación manual de cumplimiento del contrato (GOLDEN 4a — no automatizada)

> Esta verificacion se hace a mano en este markdown, igual que en
> GOLDEN 2 lo hice antes de que existiera el verificador automatico
> (GOLDEN 3). Cuando llegue GOLDEN 4b, `verifier/contract_verifier.py`
> se generalizara a multi-contrato y agregara checkers automaticos
> para estas 5 leyes — aca solo se documenta cumplimiento inferido por
> inspeccion.

- **`harvard_separation`**: `JMP`/`JZ` usan `arg` (literal del programa) como destino — ver `core/cpu.py` lineas `next_pc = arg` (en `JMP`) y `if v == 0: next_pc = arg` (en `JZ`). Ningun branch setea `next_pc` desde el stack o la memoria. `validate_program()` verifica `0 <= arg < n` antes de ejecutar. **Compliance OK.**
- **`fixed_instruction_set`**: `OPCODES` es `frozenset` literal nivel-modulo (13 entries). `validate_program()` chequea `if instr.op not in OPCODES: raise UnknownOpcode(...)` por cada instruccion. `run()` no puede llegar al ciclo fetch-decode-execute con un opcode invalido. **Compliance OK.**
- **`bounded_execution`**: `MAX_STEPS` y `MAX_STACK` constantes nivel-modulo. `run()` checkea `if steps >= max_steps: raise StepLimitExceeded(...)` al inicio del loop y `if len(stack) >= MAX_STACK: raise StackOverflow(...)` en `PUSH`/`DUP`/`LOAD`. **Compliance OK.**
- **`no_host_capability`**: `OPCODES` = `{PUSH, POP, DUP, SWAP, ADD, SUB, MUL, DIV, JMP, JZ, STORE, LOAD, HALT}`. Ninguno es I/O, import, fs, red, o subprocess. `core/cpu.py` no importa `os`/`sys`/`subprocess`/`io`/`socket` (verificado por inspeccion del header del archivo: solo `dataclasses`, `typing`, `__future__`). **Compliance OK.**
- **`deterministic_halt`**: Toda fault levantada es subclase de `CPUFault` (8 nombradas); `HALT` retorna `CPUResult(...)`. No hay `raise Exception(...)` generico en `core/cpu.py` (verificado por inspeccion). **Compliance OK.**

## Lo que GOLDEN 4a NO hace (por diseño, delpendiente de 4b)

- **`verifier/contract_verifier.py` sin cambios**: sigue hardcodeado a `vm.sandbox_interp.iesy` + `sandbox/interp.py`. Su CLI sigue dando `PASS (4/4)` para sandbox_interp y **no verifica** `vm.cpu.iesy`. Eso es contrato de GOLDEN 4b.
- **`CONTRACT_VERIFICATION.md` sin cambios**: sigue reportando solo sandbox_interp (regenerado por GOLDEN 3, sin tocar en 4a).
- **No marca Layer_c_OS Activa** — sigue `Documented — pending verification`.
- **No afirma que el CPU "aísla" o es boundary de security** — es una pieza interna con garantia acotada (Harvard), no equivalente a Layer_c_OS.

## Prohibiciones respetadas (5)

- ✅ No modifique `verifier/` (sigue hardcodeado a `vm.sandbox_interp.iesy` — es 4b).
- ✅ No modifique `sandbox/`, `bridge/`, ni los `.iesy` existentes.
- ✅ No agregue opcodes de I/O, red, filesystem ni subprocess a `core/cpu.py` (los 13 opcodes son aritmetica + stack + memoria + ctrl de flujo unicamente).
- ✅ No marque `core/cpu.py` como boundary de seguridad de ISyCo en general — es pieza interna de IsyVM con garantia acotada.
- ✅ No commitee nada.

## Que queda pendiente

- **GOLDEN 4b**: generalizar `verifier/contract_verifier.py` a multi-contrato + checkers para `vm.cpu.iesy`, confirmando regresión 4/4 en sandbox_interp y pase limpio de cpu.
- Extension a otros contratos (`vm.isolation.iesy`, `vm.bridge_isyco.iesy`) → GOLDEN 3b futuro.
- **Layer_b_WASM** (`sandbox/wasm_membrane.py`) — fuera de alcance.
- **Layer_c_OS** (`sandbox/os_membrane.py`) — fuera de alcance; sigue `Documented — pending verification`.

## Reproducibilidad

```powershell
cd C:\Development\IsyVM
.\.venv\Scripts\Activate.ps1
python -m pytest tests/test_core_cpu.py -v
python -m pytest tests/ -v
```

Salidas esperadas: `10 passed`; `31 passed`.
