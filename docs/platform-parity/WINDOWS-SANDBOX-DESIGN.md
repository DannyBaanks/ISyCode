# Sandbox nativo de Windows — propuesta para revisión

Fecha: 2026-10-14. Estado: **propuesto; ejecución aislada NOT_DEMONSTRATED**.

## Propósito y frontera

Ejecutar pruebas, builds y linters con una sola implementación de la política
de ISyCode y dos adaptadores de aislamiento. Linux conserva Bubblewrap y
seccomp. Windows necesita aislamiento de archivos, red y procesos antes de
habilitar `workspace.command.run`. Un Job Object por sí solo no cumple ese
contrato.

Authority, IsySentinel, aprobación de la petición exacta, staging independiente,
medición del diff, promoción mediante effect ledger y recibos siguen siendo
responsabilidad del código común. El adaptador no concede permisos.

## Selección propuesta

Windows: **Less-Privileged AppContainer (LPAC) + Job Object**. LPAC evita
heredar el acceso general concedido a ALL APPLICATION PACKAGES. No se conceden
capacidades de red ni excepciones de loopback. La disponibilidad real exige
una prueba ejecutada, no solamente encontrar símbolos en una DLL.

Se descartan como implementación de este contrato: ejecutar con el usuario
actual más un Job Object, y usar una ruta alternativa sin aislamiento cuando
falla la preparación. Docker/WSL pueden ser entornos explícitos futuros; no
constituyen evidencia de ejecución nativa Windows.

## Contrato del adaptador

Composición elige el adaptador una vez. El owner común obtiene un descriptor
inmutable de backend y programa; prepara una ejecución con argv, cwd lógico,
staging, timeout, límite de salida y lista de entradas sensibles. El adaptador
devuelve un proceso con lectura asíncrona de salida, espera, cancelación de
todo el árbol y cierre verificable. La identidad del backend y del runtime
forma parte de la petición aprobada y se revalida antes de ejecutar.

El programa lógico no exige rutas POSIX en Windows. La traducción entre rutas
del workspace y staging pertenece al adaptador. Los argumentos se conservan
como lista; al construir la línea Win32 se aplica el quoting de CreateProcess,
sin cmd.exe ni PowerShell intermediarios. Ejecutar un intérprete como programa
aprobado sigue permitido dentro del aislamiento.

## Preparación Windows

1. Crear un perfil LPAC único para la ejecución. No reutilizar perfiles ajenos.
2. Crear staging privado y copiar bytes, sin hardlinks al original. Quitar
   entradas sensibles y aliases de sus inodos antes de conceder acceso.
   Rechazar junctions/reparse points y enlaces que permitan salir del scope.
   `.isyroot` se mantiene protegido contra escritura.
3. Usar un runtime explícito autocontenido, copiado a un directorio privado
   separado y de solo lectura para LPAC. No ampliar ACLs de Python instalado,
   Program Files, el repo original ni directorios personales. La selección y
   verificación de runtime tienen que quedar en la petición revisada.
4. Conceder al SID de esta ejecución exclusivamente los permisos necesarios
   sobre staging y runtime. Aplicar también los niveles de integridad
   necesarios; una DACL permisiva no basta. Incluir el almacenamiento propio
   del perfil en el presupuesto de scratch y en la limpieza.
5. Construir un entorno mínimo sin credenciales, PATH heredado ni handles del
   host. Heredar únicamente los handles de E/S explícitos y revisados.
6. Crear el proceso suspendido con SECURITY_CAPABILITIES y la exclusión de
   ALL APPLICATION PACKAGES. Asignarlo al Job antes de reanudarlo. Job con
   KILL_ON_JOB_CLOSE, límite de procesos y sin breakaway. Un fallo en cualquier
   paso aborta y limpia; nunca reanuda un proceso aún sin contención.

## Ejecución y finalización

El timeout, la cancelación y la muerte del owner terminan todos los procesos
del Job. Se espera a que no queden hijos ni handles de escritura antes de
medir efectos. Salida acotada incluso si el hijo sigue produciendo datos.
Un estado incierto impide promover. Cancelar conserva el árbol original.

Solo el código común puede promover un diff con preimages válidas y permisos
todavía vigentes. El perfil, los handles y el scratch se eliminan después;
los fallos de limpieza se registran sin ocultarlos. Una recuperación posterior
solo toca recursos identificados como propiedad de esta ejecución.

## Aceptación antes de habilitar

| Control real | Resultado exigido |
| --- | --- |
| Programa benigno, Unicode y rutas con espacios | stdout, exit y diff correctos |
| Lectura de secretos sembrados en original y perfil del usuario | Denegada; originales y secretos intactos |
| Escritura fuera de staging y en runtime | Denegada |
| `.env`, `.git`, claves y aliases hardlink | No disponibles al comando |
| Junction/reparse, escapes `..`, UNC y dispositivos | Rechazados o acceso denegado |
| TCP/UDP, Internet, loopback y sockets Windows | Acceso de red denegado; testigos externos verifican ausencia de tráfico |
| Hijo, nieto y tentativa de breakaway | Todos contenidos y terminados al cancelar |
| Muerte abrupta del owner y timeout | Sin procesos supervivientes; recuperación de scratch verificable |
| Cambio humano concurrente o revocación | Diff no sobrescribe trabajo ni evade grants |
| Preparación, asignación al Job o token fallidos | No ejecución y no promoción |
| Evidencia Linux del mismo contrato | Sin regresión del sandbox existente |

Cada control necesita comando exacto, salida cruda, exit status, entorno y
SHA-256. Pruebas simuladas complementan estos controles; no los sustituyen.
La red, confinamiento LPAC, runtime compatible y cierre de hijos están todavía
**NOT_DEMONSTRATED**. No se modifica ninguna puerta de release.

## Evidencia disponible y límites

La inspección de DLLs de este host encontró CreateAppContainerProfile,
DeleteAppContainerProfile, DeriveAppContainerSidFromAppContainerName,
CreateJobObjectW, AssignProcessToJobObject, TerminateJobObject e
InitializeProcThreadAttributeList. No creó perfiles, no lanzó un LPAC y no
modificó ACLs. El log adjunto contiene exactamente ese alcance.

Queda por verificar que LPAC pueda cargar el runtime escogido con permisos
mínimos. Si exige ampliar la superficie del host o habilitar capacidades de
red, la implementación debe permanecer indisponible y revisar esta propuesta.

## Fuentes primarias

- [Microsoft: Launch an AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)
- [Microsoft: AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)
- [Microsoft: Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

Estas fuentes describen mecanismos del sistema; no demuestran que ISyCode los
haya implementado ni que este host pase los controles.
