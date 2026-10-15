# Capturas del README

Las imágenes que publica el README están en `complete/`:

- `01-overview.png`: inicio y panel Resumen.
- `02-files.png`: archivo de ejemplo leído por el owner real, con recibo local.
- `03-settings.png`: Configuración y categoría Preferencias.

Son exportaciones del compositor de Textual 8.2.8 a 120 columnas × 40 filas,
convertidas localmente de SVG a PNG con librsvg. El contenido del proyecto es
de demostración. No son una sesión contra un modelo ni una captura del escritorio:
el encabezado de ventana pertenece al exportador. La fuente del SVG tampoco
demuestra qué fuente está configurada en tu terminal.

## Reproducirlas

Desde la raíz del checkout actual, con sus dependencias instaladas, usa una
carpeta nueva para conservar capturas anteriores:

```bash
PYTHONPATH=src .venv/bin/python scripts/capture_readme_screenshots.py --out docs/screenshots/2026-10-12-product/complete
```

Ese comando se ejecutó el 2026-10-12. Si `complete/` ya existe con las imágenes,
cambia el argumento `--out` por otra ruta: el capturador rechaza sobrescribir
los SVG existentes. El script crea estado y un proyecto temporales, usa una
clave ficticia y desactiva los sondeos externos de catálogo y Gateway. La
línea del modelo muestra configuración local, no inferencia validada. El idioma
es español y el modo Classic pertenece exclusivamente al workspace de ejemplo.

En este equipo, `/usr/bin/python3` tiene PyGObject y Rsvg 2.0. La conversión
ejecutada fue:

```bash
/usr/bin/python3 - <<'PY'
from pathlib import Path
import gi

gi.require_version('Rsvg', '2.0')
from gi.repository import Rsvg

for source in sorted(Path('docs/screenshots/2026-10-12-product/complete').glob('*.svg')):
    target = source.with_suffix('.png')
    if target.exists():
        raise SystemExit(f'Preserve existing capture: {target}')
    pixbuf = Rsvg.Handle.new_from_file(str(source)).get_pixbuf()
    pixbuf.savev(str(target), 'png', [], [])
    print(f'{target}: {pixbuf.get_width()}×{pixbuf.get_height()}')
PY
```

Cambia la ruta en ambos comandos al crear otra tanda. El conversor también
conserva PNG anteriores. Si tu Python del sistema no ofrece `gi`/`Rsvg`, el
SVG sigue siendo una captura válida; este documento no certifica otro conversor.

## Evidencia y revisiones

Los [logs de la auditoría](../../audits/2026-10-12-github-product/README.md)
registran el proceso. Se revisaron las tres imágenes finales: texto legible,
panel de Archivos con lectura permitida y botones activos, y Settings agrupado.
`SHA256SUMS.txt` en esta carpeta identifica todos los artefactos guardados.

La primera tanda en la raíz de esta carpeta tiene una vista de Archivos sin
selección completa. `final/` contiene solo Overview de un intento interrumpido
por una selección duplicada en el capturador. Se conservan como evidencia del
proceso; el README usa exclusivamente la tanda exitosa `complete/`.
