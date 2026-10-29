# Probar ISyCode en la Xeon

```powershell
& 'C:\Development\ISyCo Git\ISyCode\.venv\Scripts\isycode.exe'
```

Regla: no quitar las barreras de seguridad para hacer pasar Windows. Los comandos aislados y las escrituras del producto tienen bloqueos pendientes.

Desde `C:\Development\ISyCo Git\ISyCode`, estos comandos sí se ejecutaron:

```powershell
& .\.venv\Scripts\isycode.exe --version
```

Salida real:

```text
ISyCode 1.0.0rc1
```

```powershell
& .\.venv\Scripts\python.exe -m pytest -vv tests/test_tui_startup.py tests/test_workspace_write_tui.py -o faulthandler_timeout=30
```

Última línea real:

```text
============================= 4 passed in 10.27s ==============================
```

La salida completa está en `tui-basic.log`. En la prueba de consola, se usaron directorios de estado/configuración aislados bajo `.isycode/`; tres Esc permitieron llegar al prompt temporal Security y Ctrl+C cerró con código 0.

| Resultado | Qué significa | Qué hacer |
| --- | --- | --- |
| 4 passed | Arranque y diálogo de aprobación básicos pasan | Probar esos flujos |
| No module named fcntl | Iteraciones/sesiones importan una API POSIX | Requiere adaptación de código |
| effect ledger lock is unavailable | El registro de efectos bloquea la operación | Requiere lock nativo y revisión de seguridad |
| command sandbox unavailable | No hay aislamiento compatible con Windows | No habilitar un shell sin aislamiento |
| WinError 1314 | El test necesita privilegios para symlink | Distinguir requisito del test de fallo del producto |

Trampas: usar `py` para crear el entorno; el ejecutable instalado está en `.venv\Scripts`, no `.venv/bin`. Que la TUI abra no significa que sesiones, edición y proveedor funcionen e2e. Los detalles y límites están en REPORT.md.
