# Colores efectivos del tema por defecto y límites del terminal (G8-03)

Medido 2026-10-06 contra `src/isycode/tui_theme.py`. Ratios calculados con la
fórmula WCAG 2.x de luminancia relativa (la misma que usa
`tests/test_side_panel.py::test_palette_meets_wcag_aa_for_its_actual_uses`).

## Sobre el fondo base `#1a1a2e`

| Uso | Color | Ratio | Regla | Pasa |
|---|---|---|---|---|
| Texto normal (TEXT) | `#e0e0e0` | 12.9:1 | ≥4.5:1 | sí |
| Texto secundario (MUTED) | `#9aa3ad` | 6.67:1 | ≥4.5:1 | sí |
| Éxito / granted (GREEN) | `#4ade80` | 9.8:1 | ≥3:1 (indicador) | sí |
| Error / denied (RED) | `#f87171` | 6.2:1 | ≥3:1 (indicador) | sí |
| Aviso / plan (YELLOW) | `#fbbf24` | 10.2:1 | ≥3:1 (indicador) | sí |
| Info (CYAN) | `#22d3ee` | ≥3:1 | ≥3:1 (indicador) | sí |
| Acento de marca (ACCENT) | `#e94560` | 4.46:1 | solo bullet decorativo y wordmark en negrita (≥3:1 basta) | sí |

## Sobre negro puro (modo High contrast, M-UX1.3)

La paleta semántica no cambia: TEXT 13.7:1, MUTED 8.5:1, GREEN 10.8:1,
YELLOW 11.6:1, RED 5.9:1 — todo ≥4.5:1 para texto y ≥3:1 para indicadores.
El modo solo reestiliza superficies y bordes de controles.

## Estados sin depender solo del color

ON/OFF se distinguen por glifo (✓/✗, M-UX1.1) o por marca ASCII
(`[x]`/`[ ]`, M-UX5), no solo por verde/rojo. Error, bloqueado, incierto y
éxito llevan además texto de estado (DENY/UNCERTAIN/ALLOW, "Failed",
"Rejected") en tarjetas y recibos.

## Límites del terminal

- Terminales sin Unicode: activar Settings → `ASCII-only display` (banner y
  glifos pasan a texto plano).
- Terminales con fondo claro propio: los ratios anteriores están medidos
  contra el fondo del tema (`Screen { background }`); si el terminal fuerza
  su propio fondo, usar `High contrast display` para fondos negros
  garantizados.
- `NO_COLOR`/monocromo: los estados siguen siendo legibles por glifo y
  texto; el color nunca es el único canal.
- Lector de pantalla (Orca): NOT_DEMONSTRATED en este host (sin Orca);
  los estados viajan como texto literal, que es lo que un lector vocaliza.
