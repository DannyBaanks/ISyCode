# Probar esta etapa en Windows

Desde el checkout de ISyCode:

```powershell
& .\scripts\install-windows.ps1 -TestDependencies
```

Regla de oro: no quitar Authority, Sentinel, aprobaciones ni aislamiento para hacer pasar Windows. Esta etapa habilita almacenamiento y Git; el sandbox de comandos sigue pendiente.

## Instalación verificada

Últimas líneas reales de `windows-install-r2.log`:

```text
Successfully installed isycode-1.0.0rc1
ISyCode 1.0.0rc1
Start ISyCode with: & "C:\Development\ISyCo Git\ISyCode\.venv\Scripts\isycode.exe"
```

## Pruebas nativas

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_platform_storage.py tests/test_platform_windows_git.py
```

Salida real de la verificación final de contratos:

```text
................                                                         [100%]
16 passed in 1.43s
```

Se probaron locks entre procesos, muerte del escritor, exclusión entre threads, Unicode, rechazo de ACL abiertas y junctions, eliminación y preservación de cambios concurrentes. Las pruebas de Git incluyen rechazo de dependencias/directorios no confiables.

## Diagnóstico con estado aislado

Estos comandos se ejecutaron desde el checkout:

```powershell
$env:ISYCODE_STATE_HOME=Join-Path $PWD '.isycode\parity-guide-state'
$env:XDG_CONFIG_HOME=Join-Path $PWD '.isycode\parity-guide-config'
$env:XDG_STATE_HOME=Join-Path $PWD '.isycode\parity-guide-xdg'
& .\.venv\Scripts\isycode.exe doctor --json
```

Campos reales de la salida (archivo completo en `evidence/windows-doctor-final.json`):

```json
{
  "command_sandbox": "unavailable; needs Linux bubblewrap, libseccomp and /usr/bin/python3",
  "defaults": "valid",
  "enabled_actions": [],
  "network_tested": false
}
```

Esta es una selección literal de campos, no el JSON completo. El comando crea/consulta estado de diagnóstico; no comprueba una conexión de modelo.

## Leer los resultados

| Resultado | Significado | Acción |
| --- | --- | --- |
| Prueba PASS | Ese contrato o flujo pasó en la plataforma indicada | Revisar su alcance y controles |
| Private state is unsafe | Ownership/permisos/ACL no cumplen el contrato | Conservar el estado y revisarlo; no aceptar sus grants a ciegas |
| Git unavailable | No hay instalación administrativa cuya cadena de ACL pase la validación | Revisar instalación y permisos; no reemplazarla por un git del proyecto |
| Sandbox unavailable | No existe todavía un backend Windows aceptado | Mantener comandos aislados deshabilitados |
| NOT_DEMONSTRATED | Falta evidencia para esa capacidad | No llamarlo paridad completa |

## Trampas

- El test de proveedor simulado verifica owners reales, pero no demuestra inferencia remota.
- En Windows las fixtures deben usar `ISYCODE_STATE_HOME`; solo `XDG_STATE_HOME` puede terminar usando el estado real del usuario.
- El instalador usa `py` para crear el entorno y el Python de `.venv\Scripts` para instalar.
- PowerShell 5 puede tratar los avisos de stderr como errores terminantes; el instalador evita el aviso de actualización de pip y comprueba los códigos reales.
- Un launcher de Python de venv en Windows puede crear otro proceso: matar solo el launcher no prueba que murió el escritor. La prueba de muerte usa el intérprete real.
- No mezclar evidencia ejecutada como root con controles de permisos de un usuario normal en Linux.
- Usar `Get-Content -Encoding UTF8` para leer documentos en PowerShell 5.
- Los recursos fijados por hash deben conservar sus bytes: `.gitattributes` evita que Git los convierta a CRLF. No cambiar el hash esperado para aceptar una conversión accidental.

El sandbox Windows, el empaquetado EXE y las integraciones pendientes están en INVENTORY.md. Los resultados negativos y sus correcciones se conservan en el reporte.

## Regresión multiplataforma actual

Windows, desde la raíz del checkout:

```powershell
& .\.venv\Scripts\python.exe -m pytest -v --tb=short --durations=30 -m 'not integration'
```

La salida íntegra se conserva en
`evidence/windows-full-suite-final-closure-r2-20261015.txt`. El flujo de UI,
sesiones, modelos y carpetas puede repetirse en 39 pruebas:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q --tb=short tests/test_session_messages.py tests/test_model_reasoning_ui.py tests/test_workspace_folders_tui.py tests/test_design_interactions.py tests/test_tui_startup.py
```

Linux actual se verifica en un contenedor desechable con usuario sin
privilegios y montaje de solo lectura del checkout:

```powershell
$repoPath = (Get-Location).Path
docker run --rm --mount "type=bind,source=$repoPath,target=/repo,readonly" python:3.11 bash /repo/docs/platform-parity/evidence/linux-native-adapters-final.sh
```

El contenedor instala sus dependencias dentro de la capa desechable, copia el
código a `/tmp/current` y ejecuta el conjunto de adaptadores. No configura el
host ni prueba una terminal Linux física. Las salidas exactas de Windows y
Linux están en `REPORT.md` y tienen SHA-256 en el manifiesto de cierre.
