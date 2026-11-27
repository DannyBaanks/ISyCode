# Revisión final independiente

Baseline: `71d25cfdd5c90d9201e08f68ac54df9342697cbd..9728919`.
Reviewer independiente de solo lectura: `/root/final_review`, GPT-6 Astra.
Evaluación inicial: **Ready with fixes**, 2026-10-11 UTC.
Una revisión y una pasada de correcciones; no se solicita una segunda revisión.

| Hallazgo | Corrección y evidencia |
|---|---|
| Critical P1: Git sobrescribía archivos ignorados | Comprobar colisiones de adiciones antes del preview y otra vez antes de aplicar, incluidos directorios y enlaces; `merge --no-overwrite-ignore` como guarda final. Git real conserva bytes y HEAD en ambas pruebas. |
| Critical P1: Anthropic reenviaba x-api-key a otro origen | Transporte oficial SDK con `follow_redirects=False`. Dos servidores locales verifican ausencia de petición/clave en el segundo origen para stream y create. |
| Important P1: SDK instalado rechazaba temperature | Enviar esa opción solo cuando la firma explícita del SDK la admite; stream usa el mismo parser estructurado. SDK real 1.13.0 con HTTP fixture comprueba complete, stream_completion y stream. |
| Important P2: reabrir enviaba historial a otro provider | Restaurar provider/modelo/protocolo guardados en Qt y TUI; cuando falta la conexión, selección vacía y bloqueo hasta elegir un reemplazo explícito. También conservar modelo personalizado al refrescar la lista. |
| Minor: mensajes nuevos en inglés | Mensajes de inicio, finalización y cancelación en español. |

Las once regresiones fallaron antes de corregir y pasaron después:
`review-red-0410.log/.json`, `review-green-0420.log/.json`, con SHA-256.
Se añadió una comprobación de freshness al cambiar upstream al mismo commit;
los contadores antiguos no se presentan como comprobados en la rama nueva.
Una primera suite final detectó un typo del test (`checked_at` por `checked`):
202 passed y 1 failed. Se conserva el raw log privado, sin modificarlo.
La nueva suite completa tiene su propio log y manifest público.

## Rulings pendientes de evidencia externa

- OAuth, entitlement/inferencia y catálogo GitHub con cuentas reales:
  **NOT_DEMONSTRATED**. Preparar el CLI y comprobar protocolo no demuestra login.
- Una mutación hostil entre comprobación de ruta y reemplazo: fuera de la
  garantía del lock cooperativo; no se promete CAS contra otros procesos.
- Merge/rebase avanzados, MCP externo, browser y marketplace: fuera de v1.
- Las pruebas adicionales de cancelación, instalación y HiDPI del padre no
  estaban en el baseline de la revisión; sus resultados se registran aparte.

No hay hallazgos Critical/Important declinados. El reviewer no modificó fuente,
index, HEAD ni ramas, y sus reproducciones usaron datos y credenciales ficticios.
