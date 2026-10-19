# Reparación del Hive y del gato — 2026-10-18

Esta corrección parte de `594050e29b2bbd57022efee5ad56eced275cfca7`.

## Cómo usar la reparación de harnesses

Abre Multi Harness, revisa el compose y elige **Launch repair conversation**.
Se abre una conversación normal de ISyCode con el modelo seleccionado en la
sesión. El compose completo se publica como mensaje; los permisos y las
aprobaciones siguen pasando por los owners habituales, Authority e ISySentinel.

**External Hive · unavailable** está deshabilitado. El lanzamiento anterior
arrancaba un CLI separado sin owner de ejecución y descartaba el compose.
No basta con corregir su selector: los hooks de coordinación no controlan los
comandos ni las acciones de ese proceso. La API de lanzamiento también rechaza
la operación sin crear agentes, arrancar sockets ni ejecutar procesos.

El buzón Hive sigue siendo experimental. Sus correcciones incluyen validación
de identificadores y sobres, remitente ligado al outbox, rechazo de enlaces,
lectura limitada a archivos regulares, entrega sin sobrescribir y acuse en
`.done`. El router ya no relee `.sent` y consulta el registro vigente.
Los archivos rechazados se conservan; no se eliminan ni se mueven al intentar
validar una ruta insegura.

El generador experimental de configuración Claude invoca el módulo Python
existente, con rutas entrecomilladas. No genera hooks ni flags de bypass para
otros CLIs. La prueba ejecuta ese shim localmente con un evento controlado;
no demuestra una sesión real de Claude ni autoriza lanzar un proceso externo.

## Gato

El gato ahora es naranja, de contorno ligero, cuerpo compacto y cola levantada
al caminar. Dormido conserva la silueta y una cola más visible. Si caben, muestra
tres `z` en escalera; en columnas estrechas conserva la presentación compacta.
Los puntos siguen usando Braille Unicode de 2×4 subceldas. El tamaño físico de
cada punto depende de la fuente del terminal, que este cambio no modifica.
La animación y el modo de movimiento reducido conservan su lógica existente.

## Verificación local

Usa el entorno de desarrollo descrito en `CONTRIBUTING.md`. Si ejecutas desde
un checkout que no está instalado en el intérprete actual, propaga su fuente a
los procesos hijos para evitar que importen otra instalación:

```bash
PYTHONPATH=src python -m pytest -q tests/test_hive.py tests/test_hive_regressions.py tests/test_cat_activity.py
PYTHONPATH=src python -m pytest -q -m 'not integration' --tb=short
```

El snapshot M15 se regenera desde `authority_coverage_snapshot()`; no se
modifican sus clasificaciones a mano. Su coincidencia con el catálogo no
certifica por sí sola un nuevo subsistema ni una integración externa.

El test de cancelación de compactación espera `wait_for_ready()` antes de
persistir la sesión: una pausa de render no garantiza que el owner exista.
Esto elimina esa dependencia temporal del test. No se atribuye retroactivamente
una causa demostrada al fallo histórico intermitente de CI.

## Protecciones de GitHub

Se verificó y actualizó la protección de `main`: exige la base actualizada,
Linux, Linux con Textual 8, Windows y Gate evidence. También se aplica a
administradores. No se reescribió el historial ni se fusionó ningún PR.

## Límites pendientes

- Owner de ejecución acotado para CLIs externos Hive: pendiente; lanzamiento bloqueado.
- Revisión de protocolos de hooks para otros CLIs: pendiente, no se anuncia soporte.
- Pruebas nativas Windows de estos cambios y CI remoto: no demostradas por una ejecución Linux local.
- Resistencia completa a carreras de filesystem en Windows: no demostrada; el
  helper POSIX fija descriptores de directorio, Windows rechaza enlaces y junctions
  observables pero no proporciona una garantía equivalente frente a procesos hostiles.
- Fuente y apariencia en tu terminal físico: la comparación raster y las
  capturas Textual son vistas previas; no cambian ni certifican tu fuente.
