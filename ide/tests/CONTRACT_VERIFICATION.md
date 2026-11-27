# CONTRACT_VERIFICATION.md -- generado por verifier/contract_verifier.py (GOLDEN 3 + GOLDEN 4b)

Cada seccion corresponde a un AuditTarget (par contrato/codigo).
Completitud bidireccional ley <-> checker por target.

## Target: sandbox_interp
Contrato: `contracts\vm.sandbox_interp.iesy`
Resultado: **PASS**

| Ley | Resultado | Detalle |
|-----|-----------|---------|
| `static_verify_before_exec` | PASS | verify_program() en linea 118, exec() en linea 120 |
| `explicit_deny_lists` | PASS | BANNED_IMPORT_MODULES, BANNED_CALL_NAMES, BANNED_ATTR_NAMES son frozenset literal a nivel modulo |
| `restricted_builtins_only` | PASS | run_program inyecta {'__builtins__': SAFE_BUILTINS} explicito |
| `no_boundary_claim` | PASS | todas las menciones de aislamiento/proteccion estan negadas explicitamente (ventana de 4 lineas) |

## Target: cpu
Contrato: `contracts\vm.cpu.iesy`
Resultado: **PASS**

| Ley | Resultado | Detalle |
|-----|-----------|---------|
| `harvard_separation` | PASS | todos los JMP/JZ usan arg literal int en Instruction(...) |
| `fixed_instruction_set` | PASS | OPCODES es frozenset literal; validate_program rechaza opcodes desconocidos |
| `bounded_execution` | PASS | MAX_STEPS y MAX_STACK definidas; run() respeta ambos limites |
| `no_host_capability` | PASS | cpu.py no importa os/subprocess/io; OPCODES no contiene opcodes de I/O |
| `deterministic_halt` | PASS | todas las excepciones son CPUFault nombradas; HALT retorna CPUResult; sin raise generico |

## Resultado global: **CONTRACT HOLDS**

Este reporte certifica cumplimiento del contrato existente. No certifica que ninguna capa sea un boundary de seguridad -- eso sigue siendo Layer_c_OS, pendiente de verificacion.
