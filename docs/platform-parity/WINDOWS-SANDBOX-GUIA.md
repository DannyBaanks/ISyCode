# Guía del sandbox Windows en desarrollo

Estado al 2026-10-14: adaptador LPAC + Job Object integrado y probado mediante
controles nativos. **Deshabilitado para comandos del producto**: falta imponer
el límite de escritura durante la ejecución. No equivale a paridad completa.

## Qué hay implementado

El mismo `CommandRunOwner` conserva Authority, Sentinel, aprobación de la
petición, staging, effect ledger y recibos. La composición selecciona el
adaptador. Linux conserva Bubblewrap/seccomp. Windows usa LPAC, un Job asignado
atómicamente al crear el proceso, handles de entrada/salida enumerados y cero
capacidades de red. `registryRead` permite cargar el runtime y crear hijos;
las ACLs siguen protegiendo claves privadas.

El prototipo Windows copia CPython de `sys.base_prefix`, sus módulos estándar
y DLLs a scratch privado. No modifica los binarios instalados, no busca
ejecutables en PATH y no copia `site-packages`. Su catálogo inicial acepta
`python`, `python3`, `py` y el ejecutable exacto de ese runtime. Otros programas
y dependencias requieren trabajo propio antes de declararse soportados.

La preparación rechaza staging mayor de 512 MiB y verifica espacio libre para
ambas copias más 64 MiB de margen antes de asignar scratch. Es una comprobación
inicial: no reserva ese espacio ni limita escrituras posteriores. La ronda
final de recursos/recuperación/owner aprobada pasó 18 controles, exit 0;
su salida está en `evidence/windows-sandbox-final-delta-20261014.txt`.

## Reproducir los controles

Desde la raíz de ISyCode, con la instalación fuente y las dependencias de test:

```powershell
& .\scripts\install-windows.ps1 -TestDependencies
& .\.venv\Scripts\python.exe -m pytest -q -rx `
  tests/test_windows_sandbox_process.py `
  tests/test_windows_sandbox_resources.py `
  tests/test_windows_sandbox_registry.py `
  tests/test_windows_sandbox_recovery.py `
  tests/test_windows_sandbox_acceptance.py `
  tests/test_platform_sandbox.py `
  tests/test_command_runner_windows.py
```

Las pruebas del owner habilitan la disponibilidad solo dentro de su fixture
y la restauran al terminar. La aplicación permanece deshabilitada. Hay un
control esperado fallido de presupuesto; una suite verde con ese XFAIL no
certifica que el sandbox pueda activarse.

Para observar ese fallo como fallo real:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -s --runxfail `
  tests/test_windows_sandbox_acceptance.py::test_execution_file_budget_blocks_513_mib
```

Salida observada: `exit_code=0`, `file_bytes=537919488`, `limit_bytes=536870912`;
pytest sale con código 1. El archivo temporal se elimina al cerrar la prueba.
El control requiere espacio para 513 MiB y conserva un margen de 1 GiB;
si no hay espacio, reporta SKIP / NOT_DEMONSTRATED.

## Scratch y recuperación

LPAC no atravesó el Temp privado del usuario en esta máquina. El adaptador
crea un directorio único `isycode-lpac-*` en la raíz del volumen del staging,
lo protege y copia allí runtime/workspace. No cambia ACLs de sus antecesores
ni del proyecto original. Si el volumen no permite crearlo, la ejecución falla.

Antes de copiar datos escribe `ownership.json`: SID de usuario y perfil,
nombre del perfil, PID y tiempo de creación del dueño, raíz y fase. Lo protege,
hace fsync y reemplaza con write-through. Tras crear el perfil actualiza la
fase. El archivo no contiene claves ni tokens de proveedores.

El cierre elimina perfil y datos. Si falla la eliminación del perfil, intenta
limpiar los datos y conserva el registro para reintentar. Un fallo de limpieza
después de una promoción produce `NOT_VERIFIABLE`, muestra el estado del ledger
y no se disfraza de fallo anterior a la ejecución.

Para recuperar **un directorio exacto** después de la muerte de su creador:

```powershell
$scratch = Read-Host 'Ruta exacta del scratch pendiente'
& .\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; from isycode.platform_windows_sandbox_recovery import recover_owned_scratch; print(recover_owned_scratch(Path(sys.argv[1])))' $scratch
```

Resultados: `RECOVERED`, `ABSENT`, `ACTIVE` o `ACTIVE_OR_UNVERIFIABLE`. La función
comprueba nombre/ubicación, registro privado, propietario, ACL, SID del perfil
y PID más nacimiento y señal de terminación. Rechaza carpetas ajenas y reparse
points. No barre carpetas por prefijo. La recuperación durante copia y después
de crear el perfil tiene controles de muerte real del proceso.

## Trampas verificadas

- `259` también puede ser un código de salida real: consultar la señal del
  handle distingue un proceso terminado de STILL_ACTIVE.
- Un proceso terminado puede seguir siendo abrible mientras existan handles;
  comparar solo PID/nacimiento no basta para recuperar.
- Una junction no es una symlink según todos los métodos de pathlib. El
  staging compartido usa `winfs.is_link` para impedir copiar su destino exterior.
- Un archivo marcador de solo lectura no basta si su carpeta puede renombrarse;
  también se protege DELETE en sus antecesores.
- Crear suspendido y asignar Job después deja un intervalo ante la muerte del
  dueño. El launcher usa `PROC_THREAD_ATTRIBUTE_JOB_LIST` al crear el proceso.
- El tope de bytes de copia no limita lo que un programa escribe después.
  El control de 513 MiB demuestra esta diferencia y bloquea la activación.

## Pendiente para activar

Un almacenamiento de ejecución realmente acotado, incluyendo workspace, temp
y almacenamiento del perfil; aceptación adversarial de ese mecanismo y del
runtime que se vaya a distribuir. CPython es el único runtime admitido por el
prototipo; Node y Bun se rechazan incluso por ruta absoluta. Aún faltan otros
runtimes y el staging de dependencias de proyectos. La matriz de red/IPC y
dispositivos conserva los límites descritos en la continuación de aceptación al
final de esta guía. El inventario general conserva los demás pendientes de
producto.

Un monitor de tamaño es una detección posterior; no se presenta como cuota del
kernel. Microsoft indica que
[JOBOBJECT_IO_RATE_CONTROL_INFORMATION no se soporta desde Windows 10 1607](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/ns-jobapi2-jobobject_io_rate_control_information),
y un límite de ancho de banda tampoco sería una cuota de almacenamiento.

Un volumen virtual acotado es una opción que necesita diseño y prueba adicional:
[AttachVirtualDisk requiere SeManageVolumePrivilege](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-attachvirtualdisk).
Ese privilegio está ausente en el token actual de esta sesión. No se han
montado volúmenes ni alterado cuotas del sistema.

Otra opción futura es un backend Docker elegido explícitamente: conserva el
owner común y ejecuta comandos Linux dentro de un contenedor. Ese backend
no está implementado aquí y no demostraría ejecución nativa Windows.

## Cierre de almacenamiento del perfil (continuación)

Un control real encontró escritura en la carpeta de AppContainer fuera de
scratch, y otro encontró escritura en su registro propio. Cambiar TEMP y
LOCALAPPDATA no eliminaba esos destinos. Ambas rutas quedan restringidas para
el SID antes de ejecutar el comando: la carpeta completa del perfil se obtiene
por GetAppContainerFolderPath; el registro se descubre con el token del hijo
suspendido y GetAppContainerRegistryLocation. No se adivinan rutas de instalación
ni se cambian perfiles de aplicaciones ajenas.

La consulta del registro impersona temporalmente el token restringido del hijo,
restituye la identidad del hilo y después aplica la DACL. Se rechaza una
impersonación previa y una identidad que no coincide. Una protección fallida
impide ResumeThread y termina el hijo contenido en el Job. Se permite lectura
del registro propio; escritura, creación de subclaves y WRITE_DAC se rechazan.

Se conserva el límite pendiente de disco: estas protecciones cierran destinos
alternativos, pero todavía no limitan lo escrito en workspace/temp. El
[diseño de almacenamiento acotado](WINDOWS-STORAGE-DESIGN.md) propone un volumen
VHD fijo, preparado explícitamente por el operador y consumido sin elevar
ISyCode. Es una propuesta, no un proveedor implementado o una activación.

Referencias: [GetAppContainerRegistryLocation](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-getappcontainerregistrylocation),
[ImpersonateLoggedOnUser](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-impersonateloggedonuser).

## Corrección de arranque y promoción sobre el VHD — 2026-10-14

Los fallos de arranque anteriores se conservan como evidencia histórica.
Se localizaron dos fronteras independientes: CreateProcess LPAC rechaza la ruta
GUID del ejecutable, y el montaje inicial añadía un filtro de dispositivo que
impedía cargar las DLL. El launcher fija el archivo con un handle sin compartir
escritura/borrado, obtiene su alias DOS del handle y verifica la imagen nativa
del hijo suspendido antes de permitir ResumeThread. No se codifica una letra.
El operador adjunta el mismo VHD con la opción SDK de política estándar descrita
en WINDOWS-STORAGE-GUIA.md; las ACL de archivos permanecen privadas.

La promoción también mezclaba el namespace GUID con el alias DOS que devuelve
Windows. VerifiedFS conserva el namespace lexical para recorrer componentes y
compara handles contra una clave canónica que normaliza prefijos DOS/UNC.
Rechaza redirección de la raíz y reparse points en su ascendencia. La prueba
real de aprobación exacta ahora ejecuta con exit 0 y entrega el archivo Unicode
con su recibo y efecto confirmado. Esto no habilita por sí solo la activación
ni certifica runtimes adicionales, Internet/IPv6 o todas las superficies IPC.

## Continuación de IPC y runtimes — 2026-10-15

La repetición completa de `tests/test_windows_sandbox_volume_lifecycle.py`
terminó con 12 aprobadas y 3 omitidas. Los skips son el control AF_UNIX sin
testigo host positivo y dos pruebas de desaparición que requieren coordinación
del operador; estas dos últimas ya pasaron en ejecuciones coordinadas separadas.

El host permite construir un objeto socket Winsock de familia 1, pero el bind
falla con `bad family`, antes de probar listen/connect. La API `socketpair` de
CPython en este Windows solo acepta AF_INET/AF_INET6. LPAC también construyó el
socket de familia 1, pero su bind falló con el mismo error. Como no hay un endpoint
AF_UNIX funcional en el host para el control positivo, el resultado sigue
**NOT_DEMONSTRATED**; no se debe llamarlo una denegación de seguridad.

El proceso LPAC tampoco pudo crear un servidor named pipe: `CreateNamedPipeW`
devolvió `ERROR_ACCESS_DENIED` (5). Esto demuestra la denegación de creación
bajo la política probada. El host no pudo intentar abrir una pipe creada por
LPAC, así que esa dirección permanece **NOT_DEMONSTRATED**. La prueba anterior
de pipe creado por el host sí confirmó que LPAC no puede abrirlo. Los controles
de TCP/UDP IPv4/IPv6 y WinHTTP están registrados en la sección correspondiente
de `REPORT.md`.

El selector de runtime pasó 6/6: acepta los alias de CPython definidos y
rechaza `cmd.exe`, Node, Bun y sus rutas absolutas presentes en el host. Esto
confirma que no hay fallback a programas del PATH; no certifica ejecución de
Node/Bun ni dependencias del proyecto. El runtime y `site-packages` siguen
delimitados como arriba. Los hashes y resultados exactos están en
`evidence/windows-ipc-runtime-extension-20261015.txt` y `hashes.json`.

`NATIVE_ACCEPTED=False` permanece. Siguen pendientes otros IPC/dispositivos,
un testigo ACL de otra identidad, staging de dependencias, recuperación ante
pérdida de energía y aceptación de runtimes adicionales.
