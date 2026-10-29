# Windows Command Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ejecutar comandos aprobados de ISyCode mediante aislamiento nativo Windows y conservar el mismo owner y política en Linux.

**Architecture:** Un contrato de ejecución se selecciona en composición. El adaptador Linux conserva Bubblewrap/seccomp; Windows combina LPAC y Job Objects. El owner común conserva staging, Authority, Sentinel, aprobación exacta, promoción y recibos.

**Tech Stack:** Python 3.12, ctypes Win32, pywin32 existente, asyncio, pytest y Bubblewrap/seccomp para regresión Linux.

**Spec:** [Diseño aprobado](../../platform-parity/WINDOWS-SANDBOX-DESIGN.md).

**Execution:** Implementación directa en esta sesión y revisión independiente final. Diseño y ejecución aprobados por el usuario el 2026-10-14.

**Estado de ejecución (2026-10-14):** Launcher nativo, recursos privados, contrato de adaptadores y owner común implementados como prototipo. Revisión independiente aplicada: rutas nativas, limpieza, junctions, registro previo a copia, asignación atómica al Job y regresiones de imports POSIX. Los checkboxes que agrupan aceptación no están cerrados: el control de escritura de 513 MiB falla y `NATIVE_ACCEPTED=False` permanece. La tarea 5 y la aceptación del objetivo siguen pendientes; no se declara entrega de ejecución Windows.

## Global Constraints

- Authority, IsySentinel, aprobación de la petición exacta, staging independiente, medición del diff, promoción mediante effect ledger y recibos siguen siendo responsabilidad del código común. El adaptador no concede permisos.
- Windows: **Less-Privileged AppContainer (LPAC) + Job Object**.
- No se conceden capacidades de red ni excepciones de loopback.
- No ampliar ACLs de Python instalado, Program Files, el repo original ni directorios personales.
- No reanudar un proceso aún sin contención. No ejecutar un fallback sin aislamiento.
- Los controles reales preceden a la habilitación. Ausencia de evidencia significa NOT_DEMONSTRATED.
- Trabajar solo en ISyCode; conservar el audit previo sin incorporarlo a esta implementación.

## Review Focus

- Quoting Win32 de argumentos Unicode, vacíos, con espacios y barras finales: conservar argv exactamente.
- Cancelación entre CreateProcess suspendido y asignación al Job: ningún proceso sin contención llega a ejecutarse.
- Fallo o muerte del owner durante limpieza: no borrar perfiles ajenos ni dejar hijos ejecutándose.
- Junctions y aliases hardlink de secretos: ningún acceso indirecto al árbol original.
- Reemplazo del runtime después de aprobar: rechazar identidad/digest diferentes antes de ejecutar.

---

### Task 1: Launcher LPAC y ciclo de vida de Job

**Files:** Crear `src/isycode/platform_windows_sandbox_process.py` y `tests/test_windows_sandbox_process.py`.

**Interfaces:** `WindowsSandboxProcess.launch(executable: Path, argv: tuple[str, ...], cwd: Path, env: dict[str, str], profile_sid: object, max_processes: int) -> WindowsSandboxProcess`; `read(size: int) -> bytes`, `wait(timeout: float | None) -> int`, `terminate_tree() -> None`, `close() -> None`.

- [ ] Escribir pruebas que fallan por ausencia del launcher: proceso benigno, argv exacto, hijo/nieto, fallo al asignar Job y cancelación durante preparación. Las pruebas reales usan un runtime privado y un perfil temporal propio.
- [ ] Ejecutar `.venv/Scripts/python.exe -m pytest tests/test_windows_sandbox_process.py -q`; guardar el fallo inicial.
- [ ] Implementar ctypes con firmas/tamaños explícitos; CreateProcess suspendido, SECURITY_CAPABILITIES sin capacidades y política LPAC; handles de E/S enumerados; Job KILL_ON_JOB_CLOSE, límite 256 y sin breakaway; asignar antes de ResumeThread. Fallos cierran handles y matan el proceso suspendido.
- [ ] Ejecutar las pruebas y comprobar desde un testigo externo que no sobreviven hijos tras timeout, muerte del owner o cierre del Job. Probar intento de breakaway.
- [ ] Commit local de launcher y pruebas; no integrar todavía en CommandRunOwner.

### Task 2: Perfil, scratch privado y runtime

**Files:** Crear `src/isycode/platform_windows_sandbox_resources.py` y `tests/test_windows_sandbox_resources.py`.

**Interfaces:** `WindowsSandboxResources.prepare(staging: Path, runtime: Path, masks: tuple[tuple[str, bool], ...]) -> WindowsSandboxResources`; atributos `profile_sid`, `runtime_root`, `scratch_root`, `environment`; `close() -> None`.

- [ ] Escribir controles negativos: runtime no autocontenido, perfil existente ajeno, junction, escape de scope, alias hardlink de secreto y runtime modificado. Escribir control positivo con runtime Python autocontenido privado.
- [ ] Ejecutar el módulo pytest y conservar fallos iniciales.
- [ ] Crear perfiles únicos, copiar runtime a un scratch separado; aplicar DACL por SID y nivel de integridad exclusivamente allí. No compartir hardlinks. Retirar secretos antes de conceder acceso. Proteger `.isyroot`. Crear entorno mínimo; presupuestar y limpiar también el storage del perfil.
- [ ] Verificar desde LPAC lectura denegada de secretos exteriores y escritura denegada de runtime/original. Fotografiar ACLs antes/después mediante logs y hashes para demostrar ausencia de cambios del host.
- [ ] Commit local con controles reales y cleanup idempotente de recursos propios.

### Task 3: Contrato de plataforma y conservación Linux

**Files:** Crear `src/isycode/platform_sandbox.py`, `src/isycode/platform_posix_sandbox.py`, `src/isycode/platform_windows_sandbox.py` y `tests/test_platform_sandbox.py`. Modificar `src/isycode/command_runner.py`.

**Interfaces:** Descriptor inmutable `SandboxIdentity(backend: str, executable: str, runtime_digest: str)`; `SandboxBackend.identity() -> SandboxIdentity | None`, `resolve_program(root: Path, name: str) -> str`, `start(staging: Path, program: str, argv: tuple[str, ...], cwd: str, masks: tuple[tuple[str, bool], ...], timeout_s: int) -> SandboxProcess`. Proceso común asíncrono: `read(size: int) -> bytes`, `wait() -> int`, `terminate_tree() -> None`, `close() -> None`.

- [ ] Escribir pruebas contractuales: indisponibilidad explícita, resolución válida/denegada, fallo de preparación sin ejecución, lectura de salida y cancelación completa. Mantener wrappers públicos usados por las pruebas existentes.
- [ ] Ejecutar nuevos tests para observar fallos y ejecutar `tests/test_command_runner.py` como control Linux antes del traslado.
- [ ] Mover resolución/argv/arranque Bubblewrap al adaptador POSIX sin cambiar sus restricciones. Seleccionar adaptador en composición; envolver launcher Windows de tareas 1/2 con asyncio.to_thread y cierre garantizado.
- [ ] Ejecutar contratos en ambos OS. Confirmar que el backend Windows permanece indisponible si runtime o controles de aislamiento no satisfacen el contrato.
- [ ] Commit local tras regresión Linux.

### Task 4: Identidad aprobada, owner y promoción

**Files:** Modificar `src/isycode/action_runtime.py`, `src/isycode/command_runner.py`; crear `tests/test_command_runner_windows.py`; ampliar `tests/test_platform_sandbox.py`.

**Interfaces:** CommandPreview incorpora identidad del backend/runtime a parámetros serializados; CommandProcessSystembility valida contra `SandboxBackend.identity()` y resolución del programa. CommandRunOwner usa `start()` y operaciones comunes del proceso.

- [ ] Escribir tests de rechazo por identidad/digest cambiado, petición modificada, permiso revocado, preimage obsoleta y cancelación sin promoción. El control positivo exige aprobación y recibo verificable.
- [ ] Ejecutar tests nuevos en rojo, conservando controles de Authority/Sentinel existentes.
- [ ] Integrar backend en preview y ejecución; eliminar suposiciones `/workspace` de validación común mediante el contrato. Conservar límites existentes de timeout/salida, diff, RTK y journal; revalidar identidad inmediatamente antes del arranque.
- [ ] Ejecutar flujo nativo real: programa escribe en staging, se mide diff y solo se promueve con grants vigentes y preimages válidas. Confirmar recibo y recuperación. No cambiar UI ni reglas de aprobación.
- [ ] Commit local de integración después de pasar ambos OS.

### Task 5: Aceptación adversarial y operación humana

**Files:** Crear `tests/test_windows_sandbox_acceptance.py` y `docs/platform-parity/WINDOWS-SANDBOX-GUIA.md`; actualizar `docs/platform-parity/INVENTORY.md`, `REPORT.md`, `hashes.json` y `.github/workflows/platform-parity.yml`.

**Interfaces:** Controles reales consumen el owner integrado; logs únicos bajo `docs/platform-parity/evidence/` con comandos, entorno, exit y hashes. La guía documenta runtime soportado, preparación, diagnóstico, cancelación, limpieza y fallos.

- [ ] Implementar matriz del diseño: TCP/UDP/loopback con testigo de tráfico; archivos/registro exteriores; UNC/dispositivos; secretos; hijos/breakaway; timeout; owner crash; cleanup; cambios concurrentes y revocaciones. Sembrar archivos de prueba, nunca usar secretos reales.
- [ ] Ejecutar `.venv/Scripts/python.exe -m pytest tests/test_windows_sandbox_acceptance.py tests/test_command_runner_windows.py tests/test_platform_sandbox.py -q` y suite Linux de command_runner en contenedor con usuario no-root. Guardar resultados completos sin sumar pruebas solapadas como casos únicos.
- [ ] Incorporar a CI únicamente pruebas que el runner pueda demostrar; separar aceptación real de simulaciones. Mantener indisponible cualquier capacidad con controles fallidos.
- [ ] Redactar guía con comandos ejecutados y trampas; actualizar inventario según resultados y regenerar hashes incluyendo fuentes nuevas.
- [ ] Solicitar revisión independiente del diff; resolver hallazgos con regresión específica. Verificar `git diff --check` y hashes antes del commit final. No avanzar release ni declarar paridad total por este solo sandbox.

## Condiciones para detener integración

Si LPAC no carga el runtime privado con permisos mínimos, o un control de
escape/red/terminación falla, conservar la capacidad indisponible y evidencia
del fallo. No resolverlo ampliando permisos del host. Revisar el diseño antes
de cambiar esa frontera. Los demás pendientes del inventario siguen siendo
tareas separadas; este plan cubre únicamente comandos y su árbol de procesos.
