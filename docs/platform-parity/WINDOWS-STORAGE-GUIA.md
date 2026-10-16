# Operación del scratch Windows acotado

Estado: proveedor implementado; VHD real preparado y registrado el 2026-10-14.
La primera aceptación falló en el arranque LPAC y se corrigió. El 2026-10-15,
la aceptación real pasó 13/13 y la recuperación schema2 sobre el VHD pasó en
tres puntos de muerte abrupta. Ese día también se reinició Windows: el mismo
VHD se volvió a adjuntar e inspeccionar y la aceptación pasó 13/13 después del
remount, bajo la sesión ordinaria.
ISyCode no monta ni formatea discos, no instala servicios y sigue sin activar
comandos nativos del producto. El VHD acota la capacidad agregada; no es una
cuota por archivo sobre rutas NTFS arbitrarias.

El usuario autorizó explícitamente «K ENTONCES PREPARALA». La preparación se
ejecutó mediante un helper separado del producto, con elevación de Windows:
`scripts/prepare-windows-sandbox-volume.ps1`. Solo admite una imagen nueva;
vincula su dispositivo con el inspector antes de inicializar/formatear. Su uso
no habilita el producto ni debe invocarse desde la aplicación o los tests.
El resultado y los logs reales están en REPORT.md y evidence/. No repetir
el helper sobre la imagen preparada: rechaza archivos existentes.

## Preparar un volumen nuevo (operador)

1. Elegir una ubicación local para una **imagen nueva** `.vhd`, con más de
   512 MiB + 1 GiB libre. No reutilizar imágenes o volúmenes con datos.
2. En una sesión administrativa, abrir Administración de discos y crear
   VHD clásico, tamaño 512 MiB, **tamaño fijo**, en esa ruta. No seleccionar
   VHDX, dinámico o diferencial en esta versión.
3. Adjuntar esa imagen. Desde la instalación fuente ejecutar el inspector:

   ```powershell
   $imagen = Read-Host 'Ruta absoluta de la imagen NUEVA .vhd'
   & .\.venv\Scripts\python.exe -m isycode.windows_sandbox_storage_cli inspect-image --image $imagen
   ```

   Salida esperada (no verificada todavía en este host): `fixed: true`,
   `device_id: 2`, `virtual_bytes: 536870912`, `physical_device` medido.
   Si es null o falla, detener preparación; no adivinar un número de disco.
4. Comparar ese dispositivo con el disco nuevo mostrado por Administración
   de discos. Inicializar **solo ese disco de la imagen nueva** y crear una
   partición NTFS. No ejecutar operaciones sobre C:, D: ni otro disco existente.
5. En las propiedades avanzadas de seguridad de la imagen y del nuevo volumen,
   establecer como propietario al usuario que ejecutará ISyCode normalmente.
   Deshabilitar herencia y conservar únicamente ese usuario y SYSTEM con control
   total. No ampliar permisos de Python instalado ni del perfil personal.
6. Obtener el GUID del volumen recién creado (por ejemplo con `mountvol` sin
   argumentos, que solo lista montajes); comparar su montaje con ese disco.
   La letra puede cambiar: la configuración conserva GUID e identidad medida.

## Inspeccionar y registrar como usuario normal

Cerrar la sesión administrativa para estas comprobaciones. Elegir el GUID y
una ruta de configuración propia; el directorio nuevo se crea privado, un
directorio existente con permisos amplios se rechaza sin repararlo.

```powershell
$volumen = Read-Host 'GUID completo: \\?\Volume{...}\'
$configuracion = Read-Host 'Ruta absoluta para la configuración privada nueva'
& .\.venv\Scripts\python.exe -m isycode.windows_sandbox_storage_cli inspect-volume --image $imagen --volume-guid $volumen
& .\.venv\Scripts\python.exe -m isycode.windows_sandbox_storage_cli register --image $imagen --volume-guid $volumen --config $configuracion
$env:ISYCODE_WINDOWS_SANDBOX_STORAGE_CONFIG = $configuracion
```

Resultado exigido: NTFS, filesystem <=536870912 bytes, VHD fijo local,
dependencia de imagen correspondiente, propietario/ACL privados y readback
de configuración. Un error deja el proveedor indisponible; no hay fallback.
Registrar no concede grants y no activa `NATIVE_ACCEPTED`.

No se guarda SHA de toda la imagen como identidad: cambia con cada escritura.
Se vinculan GUID/serial de volumen, identificador VHD, file ID y capacidad.
Una configuración distinta existente no se sobreescribe.

## Pruebas y recuperación

El control de cuota real requiere el volumen preparado y se ejecutará como
usuario normal. Los resultados actuales están en REPORT.md y evidence/;
los pasos anteriores no son evidencia de que se hayan ejecutado aquí.

El presupuesto es total: runtime, metadata, workspace y temp comparten menos
de 512 MiB útiles. Proyectos cercanos al límite pueden ser rechazados antes de
copiar, y dos ejecuciones simultáneas comparten capacidad pero tienen SIDs y
directorios distintos. Llenar el volumen debe fallar sin llenar el disco host.

Para remontar después de reiniciar, el operador adjunta la misma imagen y
repite inspección ordinaria. No cambiar configuración solo porque cambió la
letra. No desmontar con ejecuciones activas. Recuperación solo acepta una raíz
exacta y su propiedad; no barre ni borra volúmenes. La imagen no se elimina
automáticamente. Ante preparación incompleta conservar archivo/identidades y
revisar el disco de esa imagen, sin intentar arreglar discos ajenos.

Fuentes: [Microsoft: VHD](https://learn.microsoft.com/en-us/windows/win32/vstor/about-vhd),
[dispositivo de una imagen adjunta](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-getvirtualdiskphysicalpath).

## Ejecutar la aceptación después de preparar y registrar

Desde la raíz de ISyCode, en PowerShell ordinario, seleccionar la configuración
privada que acabas de registrar y ejecutar los controles:

```powershell
$env:ISYCODE_WINDOWS_SANDBOX_STORAGE_CONFIG = Read-Host 'Ruta absoluta de storage.json privado'
& .venv\Scripts\python.exe -m pytest tests/test_windows_sandbox_volume_acceptance.py -q -s -rs
```

Sin esa variable, los tests indican `NOT_DEMONSTRATED`, no aceptación. Con la
variable, una inspección inválida debe FALLAR, no convertirse en skip. La imagen
debe tener al menos 1 GiB libre adicional en su volumen host. Los tests solo
escriben sus directorios privados y prueban denegación de rutas externas; no
crean, adjuntan, formatean, desmontan ni eliminan la imagen.

El volumen fijo acota capacidad física. Esto todavía no demuestra el límite de
tamaño lógico de archivos: los controles NTFS sparse/compresión deben rechazar
una evasión de 512 MiB. Cualquier fallo mantiene bloqueada la activación. Estos
tests tampoco certifican Internet, IPC/dispositivos o runtimes adicionales.

Recuperación schema2 requiere la misma configuración y una raíz exacta cuyo
owner ya terminó. Desde una sesión ordinaria con la variable anterior:

```powershell
$scratchRoot = Read-Host 'Raíz exacta isycode-lpac-* del ownership.json retenido'
@'
import sys
from pathlib import Path
from isycode.windows_sandbox_storage_cli import configured_storage
from isycode.platform_windows_sandbox_recovery import recover_owned_scratch
print(recover_owned_scratch(Path(sys.argv[1]), storage_config=configured_storage()))
'@ | & .venv\Scripts\python.exe - $scratchRoot
```

`ACTIVE` o `ACTIVE_OR_UNVERIFIABLE` no autoriza borrar. `RECOVERED` borra solo la
asignación verificada y su perfil; la imagen y el volumen siguen intactos.
La corrida real del 2026-10-15 recuperó schema2 después de muerte durante copia,
después de crear el perfil y mientras un proceso LPAC seguía vivo. La salida
está en `evidence/windows-vhd-lifecycle-continuation-r2-20261015.txt` y su SHA
en `hashes.json`. Esos escenarios ocurrieron con el VHD todavía adjunto; el
reinicio, remount e inspección se verificaron después en la continuación que
sigue.

## Continuación 2026-10-15: reinicio y remount del mismo VHD

Windows se reinició realmente. La inspección posterior encontró el VHD
desmontado, verificó su identidad fija y lo adjuntó con la política normal del
dispositivo; la identidad de volumen y el proveedor acotado pasaron. La
selección real de aceptación pasó **13/13** en 242.69 s bajo el usuario normal,
después del remount. El resultado consolidado está en
`evidence/windows-vhd-reboot-acceptance-final-20261015.txt`; los dos intentos
fallidos de arranque/elevación se conservan por separado para que no se oculte
la depuración. `NATIVE_ACCEPTED=False` permanece: este control no activa el
sandbox del producto ni demuestra paridad completa.

## Continuación 2026-10-14: montaje compatible con LPAC

El VHD debe adjuntarse con `AttachVirtualDisk` y las opciones
`PERMANENT_LIFETIME | NO_SECURITY_DESCRIPTOR` (0x14). El helper de preparación
usa `scripts/attach-windows-sandbox-volume.py`; se entrega junto al `.ps1`.
La seguridad de archivos sigue en NTFS: imagen y raíz privadas de usuario/SYSTEM,
y permisos por SID únicamente en los recursos propios de cada ejecución.

En este host, Mount-DiskImage y un attach ordinario de DiskPart dejaban
FILE_DEVICE_SECURE_OPEN (0x100) y un filtro de seguridad por imagen; Python LPAC
no podía cargar sus DLL aunque sus archivos tuvieran permisos correctos.
No resolverlo concediendo acceso de datos al dispositivo. El montaje SDK dejó
características 0x20020 y conservó GUID, serial, image ID, file ID y DACL privada.

Para remontar esa misma imagen después de reiniciar, ejecutar como operador
administrativo, sin asignaciones `isycode-lpac-*` activas o pendientes:

```powershell
$imagen = Read-Host 'Ruta absoluta de la imagen propia'
$id = Read-Host 'Image ID registrado'
$volumen = Read-Host 'GUID completo registrado'
& .\scripts\remount-windows-sandbox-volume.ps1 -ImagePath $imagen -ExpectedImageId $id -ExpectedVolume $volumen -PythonPath "$PWD\.venv\Scripts\python.exe" -AttachHelper "$PWD\scripts\attach-windows-sandbox-volume.py"
```

El remount verifica la asociación imagen/dispositivo/volumen antes y después;
no formatea, redimensiona ni borra datos. Si falla después de desmontar, conserva
la imagen y diagnostica el error; no inicialices otro disco. Después, volver a
la sesión ordinaria y repetir `inspect-volume` y la aceptación. El programa no
se eleva y `NATIVE_ACCEPTED` sigue deshabilitado hasta cerrar las puertas restantes.

Fuente: [Microsoft: AttachVirtualDisk flags](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/ne-virtdisk-attach_virtual_disk_flag).
