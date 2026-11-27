# GOLDEN 1 — bridge isolation

**Estado de la pieza:** Verified — GOLDEN 1 corriendo.
**Fecha de la corrida:** 2026-08-05 (miércoles).
**Repo verificado:** `C:\Development\IsyVM\` (venv dedicado, ver uid abajo).
**Python:** 3.12.4 (`C:\Development\IsyVM\.venv\Scripts\python.exe`).
**pytest:** 9.1.1 (instalado en el venv dedicado via `pip install pytest`).
**Archivo de tests:** `tests/test_bridge_isolation.py`.

> Importante: este Verified alcanza SOLO a la pieza GOLDEN 1 (bridge isolation).
> **NO** hace Active la Layer_c_OS, que sigue `Documented — pending
> verification` segun `contracts/vm.isolation.iesy`. **NO** hace Active
> toda IsyVM. Las capas (a)/(b)/(c) siguen con sus Status individuales.

## Comando corrido

```powershell
cd C:\Development\IsyVM
C:\Development\IsyVM\.venv\Scripts\python.exe -m pytest tests/test_bridge_isolation.py -v
```

## Output textual de pytest -v (literal, copiado de consola)

```
============================= test session starts =============================
platform win32 -- Python 3.12.4, pytest-9.1.1, pluggy-1.6.0 -- C:\Development\IsyVM\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Development\IsyVM
collecting ... collected 10 items

tests/test_bridge_isolation.py::test_pass1_read_existing_bootstrap_contract PASSED [ 10%]
tests/test_bridge_isolation.py::test_pass2_list_contracts_nonempty_and_all_iesy PASSED [ 20%]
tests/test_bridge_isolation.py::test_pass3_read_capability_contract_runtime_exe PASSED [ 30%]
tests/test_bridge_isolation.py::test_pass4_list_contracts_atoms_subdir PASSED [ 40%]
tests/test_bridge_isolation.py::test_peligrosa_1a_path_escape_system32 PASSED [ 50%]
tests/test_bridge_isolation.py::test_peligrosa_1b_denied_segment_git PASSED [ 60%]
tests/test_bridge_isolation.py::test_peligrosa_1c_subdir_no_autorizado PASSED [ 70%]
tests/test_bridge_isolation.py::test_peligrosa_1d_extension_no_iesy PASSED [ 80%]
tests/test_bridge_isolation.py::test_peligrosa_1e_capability_inexistente PASSED [ 90%]
tests/test_bridge_isolation.py::test_peligrosa_1f_invariante_no_compile_call PASSED [100%]

============================= 10 passed in 0.13s ==============================
```

## Lista de PASS positivos (4) — verde

| #  | Test                                              | Resultado | Que certifica |
|----|---------------------------------------------------|-----------|---------------|
| 1  | test_pass1_read_existing_bootstrap_contract       | PASSED    | `read_contract("bootstrap/bootstrap.iesy")` lee texto raw con `Identity:` y `Version:` |
| 2  | test_pass2_list_contracts_nonempty_and_all_iesy   | PASSED    | `list_contracts()` devuelve al menos un `.iesy` y todos terminan en `.iesy` |
| 3  | test_pass3_read_capability_contract_runtime_exe   | PASSED    | `read_capability_contract("cap.runtime.exe")` lee `.iesy` via routes.json |
| 4  | test_pass4_list_contracts_atoms_subdir            | PASSED    | `list_contracts("bridge_core/contracts/bootstrap/atoms")` lista solo `.iesy` |

## Lista de PASS peligrosas (6) — intentos de fuga rechazados en verde

| #   | Test                                       | Resultado | Que certifica (fuga que detecta) |
|-----|--------------------------------------------|-----------|----------------------------------|
| 1a  | test_peligrosa_1a_path_escape_system32     | PASSED    | `read_contract("../../../../Windows/System32/cmd.exe")` levanta IsolationViolation (path fuera de ISYCO_ROOT) |
| 1b  | test_peligrosa_1b_denied_segment_git       | PASSED    | `read_contract("../.git/config")` levanta IsolationViolation (deny segment `.git` / inexistente) |
| 1c  | test_peligrosa_1c_subdir_no_autorizado     | PASSED    | `list_contracts("bridge_core/cli")` levanta IsolationViolation (`bridge_core/cli` no esta en ALLOWED_DIRS_REL) |
| 1d  | test_peligrosa_1d_extension_no_iesy        | PASSED    | `read_contract("bootstrap/Bootstrap_Law.md")` levanta IsolationViolation (no es `.iesy`) |
| 1e  | test_peligrosa_1e_capability_inexistente   | PASSED    | `read_capability_contract("cap.inexistente.xxx")` levanta IsolationViolation (no en routes.json) |
| 1f  | test_peligrosa_1f_invariante_no_compile_call | PASSED  | El codigo fuente de `bridge/isyco_reader.py` NO contiene `compile(`, `eval(`, `exec(`, `import os`, `import subprocess`, `__import__` — invariantes de no-fuga |

## Resumen

- **10 passed, 0 failed, 0 errored, 0 skipped** en 0.13s.
- 4 PASS positivos (lecturas legitimas funcionan).
- 6 PASS peligrosas (intentos de fuga detectados y rechazados con
  `IsolationViolation`).
- **GOLDEN 1Verified corriendo.**

## Ajustes aplicados durante GOLDEN 1 (transparencia)

Durante la corrida se detecto un conflicto entre el bridge aprobado original
y el test aprobado `test_peligrosa_1c`:

- El bridge aprobado tenia `_ALLOWED_SUBDIRS` como set de **nombres sueltos**
  (`bridge_core`, `contracts`, `capabilities`, `docs`) y `_vet` solo revisaba
  `rel.parts[0]` (el primer segmento relativo). Bajo esa implementacion,
  `list_contracts("bridge_core/cli")` pasaba `_vet` (primer segmento
  `bridge_core` esta en allowlist) y, como `bridge_core/cli` no contiene
  `.iesy`, devolvia `[]` **sin raise** — el test `1c` esperaba
  `IsolationViolation` y hubiera fallado.

- Decision del usuario (compose en vivo): "Ajustar `_vet` (revisar todos
  los segmentos relativos)" + "Enumerar paths exactos legibles (mas
  estricto)".

- Implementacion aplicada: `_ALLOWED_SUBDIRS` (nombres) se reemplazo por
  `_ALLOWED_SUBDIR_RELS` (enumeracion explicita de paths relativos a
  ISYCO_ROOT). `_vet` ahora exige que el path objetivo caiga bajo uno de
  esos directorios canonicales (o sea exactamente ese directorio). Asi
  `bridge_core/cli` queda rechazado porque no cae bajo ningun dir
  autorizado.

- El contrato `contracts/vm.bridge_isyco.iesy` se actualizo para reflejar
  el cambio: se reemplazo `ALLOWED_SUBDIRS` (nombres) por `ALLOWED_DIRS_REL`
  (paths relativos enumerados) y se anadio una nota explicando el ajuste.

- `contracts/vm.isolation.iesy` NO se altero (sus leyes
  `explicit_allowlist`, `no_path_escape`, `no_capability_invocation`,
  `no_hosts_builtins` siguen cumpliendose: son mas estrictas con el nuevo
  `_vet`).

- `bridge/isyco_reader.py` NO introduce `os`, `subprocess`, `importlib`,
  `builtins.open`, `eval`, `exec`, `compile`, `ctypes`, `pickle`, `marshal`
  (verificado por `test_peligrosa_1f`).

## Que queda pendiente (NO cubierto por GOLDEN 1)

- **GOLDEN 2 — sandbox interp + prueba peligrosa "intento importar os"**
  (carpeta `sandbox/` aun vacia con `.gitkeep`).
- **GOLDEN 4 — core/cpu.py** (carpeta `core/` aun vacia con `.gitkeep`).
- **Layer_c_OS**: sigue `Documented — pending verification`. NO marcar
  Active. Para activarla: ver con ojos propios Hyper-V arriba + Ubuntu
  booteado + checkpoint restaurando (ver `isyco_vm/README.md`).
- **Trust_Boundary_operational hoy**: Layer_b_WASM si se activa, si no,
  NINGUNO. No cambio.
- No se invoco `Engine.execute` ni nada de ISyCo (el bridge es solo lectura).

## Reproducibilidad

```powershell
cd C:\Development\IsyVM
C:\Development\IsyVM\.venv\Scripts\python.exe -m pytest tests/test_bridge_isolation.py -v
```

Salida esperada: `10 passed in <1s`.
