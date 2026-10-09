# RTK nativo en ISyCode

```text
/rtk
```

En la TUI abre la configuración de RTK. También está en **Settings → RTK compression**.
Revisa la ruta, versión y SHA-256 mostrados y pulsa **Enable this binary**.
Para apagarlo, vuelve a esta pantalla y pulsa **Disable**.

**Regla de oro:** RTK comprime salida; no concede permisos. Authority, Sentinel,
aprobaciones, revocaciones de archivos, sandbox y bloqueo de red siguen aplicándose.

## Qué se probó

La pantalla se abrió con el router real de `/rtk`, se activó con su botón y
se ejecutó el owner real desde la TUI headless, con una aprobación simulada normal.
Se usó RTK 0.51.0 y bubblewrap del equipo, sin proveedor/modelo externo.
La salida comprobada del probe fue:

```json
{"exit_code": 0, "raw_bytes": 7282, "model_bytes": 222, "saved_bytes": 7060, "raw_recall_verified": true, "approval_modals": 1}
```

No necesitas anteponer `rtk` a los comandos del modelo. Cuando está activado,
ISyCode consulta `rtk rewrite`, ejecuta el comando original aprobado **una sola vez**,
archiva su salida capturada y entrega esa salida a `rtk pipe`.
La tarjeta distingue la sugerencia reescrita de la ejecución real del original.
RTK elige y aplica sus filtros; ISyCode no contiene copias de sus implementaciones.
Si el comando no tiene reescritura, se ejecuta normalmente. Si el filtro no ayuda,
falla o no comprende el formato, se conserva la salida original.

Los wrappers de RTK pueden modificar flags y su recall predeterminado no guarda
cada éxito. Usar `pipe` conserva los argumentos aprobados y la evidencia original;
por eso esta integración no ejecuta la sugerencia reescrita como un segundo comando.
La cobertura y el ahorro pueden diferir de los wrappers de Codex, especialmente
para listados o formatos que `pipe` no reconozca.

## Recuperar lo que el filtro omitió

```text
/rtk recall <SHA-256 de raw_sha256>
```

Sustituye el marcador por `rtk.raw_sha256` del resultado de un comando.
El probe abrió esta pantalla y comprobó que incluía la línea original 300,
aunque el modelo había recibido una salida compacta. El hash se verifica al abrirla.
Solo se admite un SHA-256 de 64 caracteres: no una ruta arbitraria.

Los originales y resultados se guardan privados, con permisos 0600, bajo
`<estado de ISyCode>/rtk/outputs/`. El hash del resultado JSON corresponde al
`result_digest` del recibo del journal; ese resultado referencia el hash del original.
Si la captura se truncó o el comando agotó su tiempo, `raw_complete` es falso y
no se comprime: el archivo conserva únicamente los bytes capturados, no una
supuesta salida completa.

## Cómo leer los resultados

| Campo o estado | Significado |
| --- | --- |
| OFF | Predeterminado; RTK no se ejecuta para comprimir comandos. |
| ON | Opt-in explícito ligado a ruta y SHA-256 de un binario. |
| `rtk.applied: true` | RTK redujo la salida entregada al modelo. |
| `rtk.applied: false` | Se conservó la salida original; lee `fallback`. |
| `exit_code != 0` | El comando falló, aunque el filtro haya terminado correctamente. |
| `command_success: false` | Fallo o timeout del comando; no es PASS. |
| `raw_complete: false` | Captura parcial o timeout; no se afirma evidencia completa. |
| `RTK ~… tok saved` | Estimación bytes/4 en este proceso/workspace, no tokens facturados por el proveedor. |
| `binary changed` | Se rechaza el comando; revisa y vuelve a habilitar la nueva identidad, o apaga RTK. |

El recibo confirma una ejecución autorizada y verificable; no convierte un
exit code no cero en pruebas exitosas. Las métricas del proveedor no se modifican.

## Trampas

- Un enlace `/usr/local/bin/rtk` que apunta a `~/.local/bin` puede quedar roto dentro
  del sandbox de comandos. Instala el binario real allí, o habilita la instalación
  personal desde esta integración, que copia y monta solamente el binario fijado.
- RTK solicita revisión (`rewrite` exit 3) en algunos comandos. Esa señal impide
  heredar una aprobación silenciosa de Classic; no se utiliza para saltarse permisos.
- Si actualizas RTK, su hash cambia. Debes revisar y habilitar la nueva identidad.
- La evidencia tiene un límite de 64 MiB o 1024 archivos. No se borra automáticamente.
  Si se llena, apaga RTK para continuar normalmente y conserva/revisa los archivos
  antes de decidir su limpieza. Una falla al guardar el original impide promover
  cambios del comando al proyecto.
- Esta integración no ejecuta `rtk init --codex` ni modifica la configuración de
  Codex o Claude. Es un adaptador propio de ISyCode para el binario externo.

Compresión de salida por [RTK](https://github.com/rtk-ai/rtk), Apache-2.0.
