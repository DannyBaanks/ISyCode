# Windows Bounded Scratch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar un proveedor Windows de scratch acotado por un volumen VHD fijo, manteniendo el owner compartido y la ejecución del producto bloqueada hasta aceptación real.

**Architecture:** Un operador prepara un volumen NTFS dedicado de capacidad total <=512 MiB. El adaptador Windows verifica volumen, imagen y configuración, retiene handles durante cada ejecución y usa ese volumen para runtime/workspace/temp; el núcleo conserva Authority, Sentinel, aprobación exacta, medición, promoción y recibos. La aplicación no eleva, adjunta, formatea ni redimensiona discos.

**Tech Stack:** Python 3.12, ctypes Win32/VirtDisk, pywin32, pytest; sin dependencias nuevas ni servicio privilegiado. Primera versión: VHD fijo clásico, no VHDX/dinámico/diferencial.

**Spec:** [WINDOWS-STORAGE-DESIGN.md](../../platform-parity/WINDOWS-STORAGE-DESIGN.md), aprobado por el usuario el 2026-10-14 después del commit `6bb7b1b`.

**Execution:** Directa en esta sesión, método conservado del trabajo anterior, con revisión independiente final. El usuario aprobó el plan el 2026-10-14 con «SI AHORA SI SGAMOS :)». Aprobar el plan no significa que un volumen ya esté provisionado ni autoriza formatear discos existentes.

**Progress (2026-10-14):** Tareas 1/2 implementadas en `cf4637e`/`04ef1bb`; tareas 3/4 implementadas y verificadas en la continuación. Los checkboxes originales conservan el checklist completo: no implican aceptación por publicación. Tarea 5 tiene tests y guía; provisión y ejecución sobre VHD real quedan `NOT_DEMONSTRATED`, al igual que sus controles de sparse/compresión, dispositivos y remontaje real. `NATIVE_ACCEPTED=False` permanece. La recuperación schema1 y los procesos/owner nativos se verifican por separado; el proveedor sintético de tests no certifica cuota.

**Interface ruling:** `StorageConfig.registered_identity` se añadió como campo opcional para vincular el registro privado con cada apertura, además de la identidad exacta aprobada. Los DTOs y parámetros anteriores permanecen; las pruebas directas históricas de recursos usan `storage_lease=None`, pero el backend del producto siempre requiere proveedor y aprobación vinculada. Los commits finales agrupan integración/revisión/evidencia; las selecciones solapadas no se suman como aceptación.

## Global Constraints

**Operator continuation:** El usuario autorizó explícitamente «K ENTONCES PREPARALA».
Se preparó una imagen nueva con helper administrativo separado del producto/tests
y se registró configuración privada como usuario normal. La primera aceptación
real produjo 13 FAIL en arranque LPAC; provisión ya no está pendiente, pero cuota
y activación siguen abiertas. La política de raíz privada no se relajó para
ocultar el fallo del loader. Detalles y evidencia en REPORT.md.

- Un núcleo y el owner actual; no duplicar src ni conceder grants desde el proveedor.
- Techo: `536870912` bytes (512 MiB), capacidad total del filesystem, no solo espacio libre. Es más estricto que el límite por archivo Linux; runtime/metadata reducen el espacio para proyectos.
- Configuración explícita, GUID persistente y valores medidos. Ninguna ruta C:/D: o letra de unidad incorporada en código.
- No fallback a scratch ordinario, Docker, WSL, otra unidad o ejecución sin aislamiento.
- No cambios en cuotas del host, drivers, servicios, ACLs de otros perfiles o binarios instalados.
- Mantener los controles LPAC/Job y carpeta/registro propios de solo lectura. No heredar handles de volumen o backing file.
- La aplicación funciona sin administrador. Si las consultas necesarias no funcionan como usuario normal, el proveedor queda indisponible.
- Provisión manual por el operador: solamente una imagen nueva elegida explícitamente; inspección de su dispositivo antes de seleccionar/formatear en Administración de discos. No ejecutar esa preparación desde los tests ni desde la app.
- `NATIVE_ACCEPTED=False` permanece en esta entrega. Cuota verificada por sí sola no cierra IPC/dispositivos/Internet, otros runtimes ni paridad completa.
- Evidencia: comando, entorno, salida cruda, exit y SHA-256; logs únicos. Simulación != volumen real.

## Review Focus

1. GUID/alias o backing file sustituido entre revisión y arranque: rechazar, no ejecutar ni promover (tareas 1/3/4).
2. Volumen válido con datos/permisos ajenos o configuración pública: no reparar ni borrar automáticamente (tareas 2/3).
3. VHD adjunto que no corresponde al volumen, imagen dinámica o filesystem distinto: no aceptar etiqueta o tamaño como identidad (tarea 1).
4. Volumen lleno/desaparecido, cambio de capacidad o cancelación durante copia: conservar originales y registrar incertidumbre (tareas 3/4/5).
5. Reboot/remount/letra cambiada y ejecuciones concurrentes: resolver por GUID, aislar por SID y recuperar solo una raíz pedida (tareas 3/5).

## File Map

- Crear `src/isycode/platform_windows_sandbox_volume.py`: DTOs, límite/validación y lease del proveedor.
- Crear `src/isycode/platform_windows_sandbox_volume_api.py`: consultas Win32/VirtDisk de solo lectura, ctypes/handles y ABI.
- Crear `src/isycode/windows_sandbox_storage_cli.py`: inspección y registro explícito de configuración; ningún montaje/formato.
- Modificar `platform_windows_sandbox.py`, `platform_windows_sandbox_resources.py`, `platform_windows_sandbox_recovery.py`: integración de lease, identidad y recuperación.
- Crear `tests/test_windows_sandbox_volume.py`, `tests/test_windows_sandbox_volume_api.py`, `tests/test_windows_sandbox_storage_cli.py`, `tests/test_windows_sandbox_volume_acceptance.py`; adaptar fixtures Windows existentes.
- Crear `docs/platform-parity/WINDOWS-STORAGE-GUIA.md`; actualizar inventario, reporte, CI y manifiesto.

---

### Task 1: Identidad de volumen y consultas nativas

**Files:** Crear los módulos `platform_windows_sandbox_volume.py` y `platform_windows_sandbox_volume_api.py` y sus tests.

**Interfaces:** DTOs frozen `StorageConfig(volume_guid: str, backing_file: Path, max_bytes: int)` y `StorageIdentity(volume_guid: str, volume_serial: int, image_identifier: str, backing_file_id: str, capacity_bytes: int, max_bytes: int)`. `VolumeObservation(identity: StorageIdentity, filesystem: str, device_id: int, fixed: bool, attached_matches: bool, private_root: bool, private_backing: bool)`. `inspect_volume(config: StorageConfig) -> VolumeObservation`; `validate_observation(config, observation) -> StorageIdentity`.
Errores de identidad/política/API se normalizan a `StorageUnavailableError(OSError)`; el CLI captura esa excepción sin habilitar ni reparar recursos. Fixtures `valid_config`/`valid_observation` comparten GUID/identificadores sintéticos, capacidad/max 536870912, NTFS, device VHD, fixed/attached/private True; no llaman al SDK.
El módulo API produce `open_volume_handles(config: StorageConfig) -> VolumeHandleSet`; el holder posee `.root: Path`, `.observation: VolumeObservation`, `.refresh() -> VolumeObservation` y `.close() -> None`. inspect_volume abre/consulta/cierra; la tarea 3 conserva el holder hasta cierre del lease. `inspect_image(path: Path) -> ImageObservation` produce DTO frozen con `image_identifier: str`, `device_id: int`, `fixed: bool`, `virtual_bytes: int`, `physical_device: str | None`, `backing_file_id: str` para inspección anterior al formato; imagen no adjunta devuelve None y no inventa un número de disco.

- [ ] Escribir tests de validación: aceptar DTO NTFS/VHD fijo con 536870912 bytes; rechazar 536870913, GUID incorrecto, zero/negative/bool, FAT/ReFS, físico/ISO/VHDX, dinámico/diferencial, privacidad inválida y backing no correspondiente. Fixtures sintéticos declarados.

```python
def test_capacity_one_byte_over_policy_refused(valid_config, valid_observation):
    oversized = replace(valid_observation, identity=replace(
        valid_observation.identity, capacity_bytes=536870913))
    with pytest.raises(StorageUnavailableError):
        validate_observation(valid_config, oversized)
```
- [ ] Ejecutar `.venv\Scripts\python.exe -m pytest -q tests/test_windows_sandbox_volume.py`; observar rojo por interfaz ausente antes de implementación.
- [ ] Implementar DTOs/validador y wrappers de lectura. Usar GetVolumeNameForVolumeMountPoint/GetVolumeInformation/GetDiskFreeSpaceEx, GetStorageDependencyInformation con HOST_VOLUMES, OpenVirtualDisk con GET_INFO y GetVirtualDiskInformation (Identifier/Size/ProviderSubtype), GetVirtualDiskPhysicalPath. Correlacionar dependencias e identidad de la imagen; medir file ID por handle. No interpretar una cadena/configuración como prueba de VHD fijo.
- [ ] Rechazar enlaces/hardlinks de imagen, backing UNC/remoto y alias de raíz. Solo aceptar GUID de volumen completo y dependencia VHD directa inequívoca. Vincular rutas devueltas por APIs, no construir una ruta física a partir de una letra o número supuesto. Binders usan SDK/constants y verifican layout x64/tamaños/buffers; respuestas truncadas/ambiguas/error => indisponible.
- [ ] Ejecutar ambos archivos de tests: falsificaciones/errores API con fakes, más rechazo de un volumen físico real de este host mediante consulta de solo lectura. Un positivo VHD real queda para tarea 5; no declararlo desde mocks.
- [ ] Commit local de los dos módulos y tests una vez verdes.

### Task 2: Configuración privada y guía de preparación

**Files:** Crear `windows_sandbox_storage_cli.py`, `tests/test_windows_sandbox_storage_cli.py`, `docs/platform-parity/WINDOWS-STORAGE-GUIA.md`.

**Interfaces:** `load_storage_config(path: Path) -> StorageConfig`; `register_storage_config(config: StorageConfig, destination: Path) -> StorageIdentity`; `main(argv: list[str] | None = None) -> int`. Comandos `inspect-image --image <archivo>`, `inspect-volume --image <archivo> --volume-guid <GUID>`, `register --image <archivo> --volume-guid <GUID> --config <archivo>`. Registro JSON schema `isycode.windows-bounded-storage/1`, max_bytes fijo 536870912, GUID/imagen y identidad medida. Selección host explícita mediante `ISYCODE_WINDOWS_SANDBOX_STORAGE_CONFIG`; no descubrir configuración desde un proyecto sin confianza.

- [ ] Escribir tests: configuración ausente/broad ACL/reparse/schema/campos desconocidos rechazados; JSON malformado nunca se usa; register no escribe cuando inspección falla y nunca llama Attach/format; configuración existente distinta no se sobreescribe. Registro privado atómico/readback con WindowsStorage.
Nombres mínimos: `test_failed_inspection_never_writes_config` exige `not destination.exists()`; `test_register_never_calls_disk_mutators` usa spies que fallan si se intenta attach/format; `test_existing_different_config_preserved` exige bytes iniciales intactos.
- [ ] Ejecutar `.venv\Scripts\python.exe -m pytest -q tests/test_windows_sandbox_storage_cli.py`; observar rojo.
- [ ] Implementar CLI/modelo strict con inspección de tarea 1. El registro no concede Authority ni habilita el sandbox. No añadir comandos de attach/format/detach/delete ni elevación.
- [ ] Escribir guía del operador: elegir imagen nueva y ubicación con >=512 MiB más 1 GiB de margen; crear VHD **fijo clásico** de 512 MiB con Administración de discos; inspeccionar asociación imagen/dispositivo antes de seleccionar ese disco; formatear solo ese nuevo volumen NTFS. Establecer propietario del volumen/imagen al SID del usuario que ejecutará ISyCode y DACL user/SYSTEM únicamente. Verificar con el inspector ordinario antes de register. Registrar rutas/GUID reales y outputs cuando el operador lo ejecute, no inventarlos.
- [ ] Documentar remontaje, cambio de letra, abortos de preparación y desmontaje manual solo después de terminar procesos/handles; jamás borrar imagen/datos automáticamente. Si una API no permite verificar la asociación sin privilegios, registrar bloqueo y mantener indisponible.
- [ ] Ejecutar tests y `--help` sin privilegios; confirmar que solo inspección/registro existen. Commit local.

### Task 3: Lease, asignación y recuperación acotadas

**Files:** Ampliar `platform_windows_sandbox_volume.py`; modificar resources/recovery; ampliar sus tests.

**Interfaces:** `BoundedStorageProvider(config: StorageConfig).open(expected: StorageIdentity | None = None) -> StorageLease`. `StorageLease.root: Path`, `.identity: StorageIdentity`, `.assert_unchanged() -> None`, `.close() -> None`; contexto síncrono. Retener handles no heredables de raíz e imagen/identidad hasta cierre y verificar de nuevo sin liberar esos handles. `WindowsSandboxResources.prepare(..., expected_runtime_digest=None, *, storage_lease: StorageLease | None = None)`; None conserva únicamente el uso experimental directo existente, nunca fallback desde el backend del producto.

- [ ] Escribir tests: raíz exclusiva por ejecución, dos SIDs sin lectura cruzada, falta de espacio rechazada antes de datos/perfil, sustitución/capacidad alterada rechazada antes de launch, volumen desaparecido y cancelación sin promoción, handles cerrados en fallo. Snapshot de ACLs del padre antes/después: preparar scratch no repara la raíz ni otras carpetas.
Nombres mínimos: `test_cancelled_prepare_closes_lease_and_keeps_original`, `test_substituted_volume_refused_before_copy`, `test_root_acl_unchanged_after_allocation`, `test_schema2_recovery_refuses_wrong_volume`; asserts originales/ACL intactos, ningún launch y ninguna eliminación fuera de la raíz pedida.
- [ ] Ejecutar `.venv\Scripts\python.exe -m pytest -q tests/test_windows_sandbox_volume.py tests/test_windows_sandbox_resources.py tests/test_windows_sandbox_recovery.py`; observar fallos nuevos sin ocultar controles anteriores.
- [ ] Implementar open/lease y asignación de scratch en la raíz GUID verificada. Revalidar volumen del directorio creado antes de copiar. Usar el preflight existente sobre **esa** raíz: bytes de staging+runtime+64 MiB de margen; un preflight no es reserva ni cuota. No copiar secretos antes de privacidad/identidad verificadas.
- [ ] Extender ownership.json a schema `isycode-native-scratch/2` para provider/StorageIdentity junto a PID/birth/SID/fase; escribirlo antes de copiar/perfil. `recover_owned_scratch(root, *, storage_config: StorageConfig | None = None) -> str` exige configuración/identidad medida para schema2; schema1 histórico sigue limitado a su frontera existente. No sweeps, desmontajes ni recuperación ACTIVE/UNKNOWN.
- [ ] Ejecutar tests de creator death y preparación fallida, schema1/2, metadata insegura, SID alterado y GUID/remount diferente. Los controles unitarios sintéticos no certifican capacidad física; marcarlo en su fixture.
- [ ] Commit local tras resultados verdes.

### Task 4: Integración en identidad aprobada y ciclo del owner

**Files:** Modificar `platform_windows_sandbox.py`; ampliar `tests/test_platform_sandbox.py`, `tests/test_command_runner_windows.py`, `tests/test_windows_sandbox_volume.py`. No reestructurar CommandRunOwner ni el adaptador POSIX.

**Interfaces:** Backend `windows-lpac-job/2`; `WindowsSandbox.identity()` añade DTO de storage serializado en campos JSON primitivos, además de runtime SHA/capabilities. `start(..., identity=...)` abre un lease que coincide exactamente con la identidad aprobada. NativeProcess conserva lease/resources; finish verifica terminación y volumen; close limpia resources y finalmente cierra lease incluso si falla limpieza.

- [ ] Escribir tests: sin configuración válida executable() es None incluso con flag experimental; cambio de configuración/identidad entre preview y start no ejecuta; falta de grant/aprobación exacta sigue DENY; cuota no crea grants; volumen cambiado impide finish/promoción; cierre fallido informa incertidumbre sin recibo de éxito.
Nombres mínimos: `test_storage_config_required_even_with_acceptance_flag`, `test_approved_storage_identity_change_never_launches`, `test_volume_change_prevents_promotion`, `test_storage_close_failure_never_returns_success_receipt`; asserts None/DENY/no launch/originales intactos/no receipt según caso.
- [ ] Ejecutar selección de tests afectados y observar rojo antes de integrar.
- [ ] Integrar carga explícita de tarea 2, proveedor de tarea 3 y revalidación sin fallback. Mantener handles durante medida/promoción; no trasladar aprobación, permisos ni ledger al proveedor. En cleanup intentar todas las liberaciones y conservar propiedad recuperable cuando corresponda.
- [ ] Adaptar fixtures del prototipo que hoy habilitan NATIVE_ACCEPTED temporalmente: inyectar proveedor sintético **solo desde tests**, etiquetado como no-prueba de cuota; ninguna bandera o ruta insegura de test se introduce en código del producto. Tests de cuota real usan el proveedor real, no este fake.
- [ ] Ejecutar suite Windows de proceso/recursos/registro/recuperación/owner y snapshot Authority. Ejecutar selección Linux no-root `linux-sandbox-current.sh` si el diff modifica contrato o núcleo compartido; de lo contrario conservar su evidencia previa sin afirmar rerun.
- [ ] Commit local tras checks verdes. NATIVE_ACCEPTED continúa False.

### Task 5: Volumen real, agotamiento y evidencia

**Files:** Crear `tests/test_windows_sandbox_volume_acceptance.py`; actualizar guía/inventario/reporte/hash-script/CI. Conservar el control histórico que escribió 513 MiB fuera de cuota.

**Interfaces:** Pruebas reales toman `ISYCODE_WINDOWS_SANDBOX_STORAGE_CONFIG` del operador, validan proveedor y usan un workspace de prueba vacío. Ausencia de volumen => skip con NOT_DEMONSTRATED, nunca PASS. Los tests potencialmente disruptivos (desmontaje/resize) requieren volumen sacrificial y operación explícita del operador; los fallos simulados permanecen separados.

- [ ] Escribir prueba real negativa de escritura: un programa LPAC intenta 513 bloques de 1048576 bytes, captura exit !=0, tamaño observado <=536870912, capacidad medida constante y originales intactos. Preflight preserva >=1 GiB libre en el volumen que contiene la imagen. Registrar output y cleanup. No llenar un disco físico.
`test_fixed_volume_blocks_513_mib` ejecuta el control directamente sobre recursos privados con WindowsSandboxProcess (sin promoción del owner); comprueba `process.wait(60) != 0`, bytes de `budget.bin` <=536870912 y lease sin cambio de identidad. La promoción aprobada es un control benigno separado; no cambiar la semántica compartida del owner sobre exit no-cero.
- [ ] Añadir pequeños archivos hasta agotamiento, truncación/sparse/temp, escritura al backing file/raíz/metadata/perfil/registro y apertura de dispositivos de volumen. Exigir denegación o límite físico para cada ruta, con testigos positivos del host donde apliquen.
- [ ] Añadir comandos benignos Unicode/espacios con aprobación/receipt, cancelación/owner death, concurrencia y recuperación exacta. Probar remount/alias/capacidad/volumen desaparecido mediante fakes y, donde el operador lo permita, volumen real separado; documentar cuál clase produjo cada resultado.
- [ ] Ejecutar `.venv\Scripts\python.exe -m pytest -q tests/test_windows_sandbox_volume_acceptance.py -s` como usuario normal sobre volumen provisionado. Si no está disponible, completar código/tests unitarios pero dejar aceptación y activación abiertas, con requerimiento operativo exacto para el operador.
- [ ] Registrar comandos, OS/SDK/Python, exit, salida, límites y SHA-256; preservar manifiesto anterior. CI ejecuta unitarios/native existentes; aceptación VHD solo en runner expresamente provisionado, no scripts administrativos automáticos.
- [ ] Pedir revisión independiente del diff, resolver hallazgos con controles específicos y verificar hashes + git diff --check antes de commit. No sumar suites solapadas ni cerrar IPC/dispositivos/Internet o paridad general mediante este solo cambio.

## Self-review and handoff

El plan cubre proveedor/configuración, identidad/privacidad, raíces escribibles,
lease/recuperación, integración de aprobación y aceptación real. Cada punto de
Review Focus tiene pruebas en su tarea. Los DTOs son la única forma serializada
de identidad; handles no viajan en ActionRequest. La elección inicial de VHD
fijo clásico reduce compatibilidad a una superficie demostrable. El requisito
de preparación administrativa se mantiene fuera de la aplicación y los tests.

No se ha implementado ni provisionado nada por escribir este plan. Revisar el
plan antes de ejecutar; conservar el método directo ya elegido.

Fuentes de API: [GetStorageDependencyInformation](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-getstoragedependencyinformation),
[GetVirtualDiskPhysicalPath](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-getvirtualdiskphysicalpath),
[GetVirtualDiskInformation](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-getvirtualdiskinformation).
