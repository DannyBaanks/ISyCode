# ISyCode — Plan de mejoras UI/UX por milestones

> **Para trabajadores agénticos:** la implementación se hace inline; marcar el progreso en este documento.
> Aprobado en plan mode el 2026-10-05. Versión de trabajo: `~/.commandcode/plans/isycode-ux-improvements.md`.

**Goal:** reducir fricción y mejorar accesibilidad de la TUI de ISyCode **sin debilitar** el modelo de seguridad (Workspace Authority + ISySentinel + approvals request-bound de un solo uso, ROADMAP M15).

**Architecture:** Python 3.12 + Textual + Rich. Cambios acotados a la capa de presentación (`tui_theme.py`, `tui_app_rail.py`, `tui_composer.py`) y a los owners/approvals existentes (`workspace_authority.py`, `approvals.py`, `tui_screens_approval.py`). No se toca IsyMotron ni OpenISy.

---

## Verificación de la auditoría previa (correcciones importantes)

El plan del agente de planificación anterior mezcla gaps reales con afirmaciones falsas o desactualizadas. Verificado contra el código:

| Afirmación previa | Realidad (verificado) |
|---|---|
| P11 "Clipboard deshabilitado / implementar ClipboardOwner" | **FALSO.** `ClipboardOwner` existe (`clipboard_owner.py:91`) y está cableado a `file-copy-path` (`tui.py:1013`). El botón solo se desactiva sin selección. ROADMAP M1 está desactualizado aquí. |
| P4/T-UX1.2 "MUTED probablemente falla WCAG" | **FALSO.** Contrastes sobre BG `#1a1a2e`: TEXT 12.9:1, MUTED 6.67:1, GREEN 9.8:1, RED 6.2:1, YELLOW 10.2:1 — todos pasan AA. ACCENT `#e94560` = 4.46:1, pero solo se usa en el bullet decorativo "◇" y el wordmark en negrita (≥3:1 basta) → **no es un fallo real**. |
| P8 "Búsqueda limitada a sesión actual" | **PARCIAL.** `/sessions search TEXT` ya existe (`tui_app_sessions.py:928`). `Ctrl+F` es de sesión. Una pantalla dedicada es mejora, no falta. |
| P12/T-UX3.3 "Modelo no visible en composer" | **PARCIAL.** Ya se ve en el idle board (`tui.py:2124`) y el título de la idea box. Inline en el prompt es mejora. |
| P15 "Dependencia excesiva en color" | **REAL (acotado).** `switch_row()` (`tui_theme.py:75`) usa `●` idéntico para ON (verde) y OFF (rojo). `test_side_panel.py:22` exige que NO haya texto "ON"/"OFF", así que el fix debe ser de **glifo**, no de texto. |
| P6 "Fatiga de aprobaciones / batch" | **REAL.** No hay batch; `ApprovalScreen` es y/n por acción. Debe respetar M15 (digest de un solo uso). |
| T-UX2.2 "Session trust" | **REAL.** Solo hay grant persistente (`set_grant`) u overlay "user-approved-once" (`workspace_authority.py:33-49`). No hay trust que expire por sesión. |

**Gaps reales y de valor:** (1) glifos distinguibles sin color en `switch_row`, (2) batch approvals + session trust **dentro** del modelo de seguridad, (3) feedback de progreso, (4) onboarding progresivo, (5) high-contrast opcional.

---

## Global Constraints (no negociables)

- **M15:** approvals request-bound, atómicas, ligadas a digest, de un solo uso. Un "batch" = N digests de un solo uso aprobados en un gesto, **nunca** un grant persistente implícito.
- Deny-by-default intacto; ninguna UX eleva permisos por omisión.
- Secretos fuera de repo/transcript/UI.
- Conservar Enter-send / Shift+Enter-newline y el layout 20/60/20 del composer.
- No modificar IsyMotron ni OpenISy.

---

## M-UX1 — Accesibilidad de estados (CRÍTICO, acotado, bajo riesgo)

### T-UX1.1 Glifos distintos para ON/OFF en `switch_row`  ✅ HECHO
**Files:** `src/isycode/tui_theme.py` (`switch_row`); consumidores en `tui_app_rail.py`.
- [x] ON `●`→`✓`, OFF `●`→`✗`; `○` (inactive) y `···` (None) sin colisión.
- [x] Compatible con `test_side_panel.py` (sigue sin texto "ON"/"OFF", colores intactos).
- [x] Test nuevo: ON y OFF distinguibles en monocromo (glifos distintos).

### T-UX1.2 Test de contraste WCAG (regression guard)  ✅ HECHO
**Files:** `src/isycode/tui_theme.py`, `tests/`.
- [x] Test que fija los ratios reales: body text (TEXT/MUTED) ≥4.5, UI/acentos ≥3.0.
- [ ] (Opcional, no necesario hoy) subir ACCENT a ≥4.5 si algún día se usa para texto normal.

### T-UX1.3 Modo alto contraste opcional  ✅ HECHO
**Files:** `src/isycode/user_defaults.py` (`UserDefaultsStore`), `tui_theme.py`, `tui.py`, `tui_app_menu.py`, `tui_app_providers.py`, `tests/test_high_contrast.py`.
- [x] `high_contrast: bool` + overrides CSS (BG `#000`, TEXT `#fff`; la paleta semántica ya cumplía AA sobre negro, solo se reestilizan superficies y bordes).
- [x] Entrada en Settings ("High contrast display · on/off") con conmutación en vivo vía `stylesheet.add_source` + tests de conmutación, validación y contraste.

---

## M-UX2 — Reducir fatiga de aprobaciones (CRÍTICO, sensible a seguridad)  ⬜ PENDIENTE

### T-UX2.1 Batch approval (N digests de un solo uso, un gesto)
**Files:** `approvals.py`, `tui_screens_approval.py`, `workspace_write.py`.
- [ ] Agrupar requests relacionados (mismo archivo/tarea) en una pantalla que lista cada diff.
- [ ] "Approve group" emite N approvals de un solo uso (cada una ligada a su digest); sin grant persistente.
- [ ] "Review each" → flujo y/n actual. "Reject all" → deniega.
- [ ] Tests: cada digest se consume una vez; replay falla; journal registra cada aprobación.

### T-UX2.2 Session trust (grant que expira por sesión)
**Files:** `workspace_authority.py`.
- [ ] Scope "session" que expira al cerrar la TUI (no persiste a `policy_path`).
- [ ] Botón "Trust for session" en aprobación de writes; journal lo marca.
- [ ] Tests: no sobrevive reinicio; no se escribe en disco; respeta el límite de Authority.

### T-UX2.3 Feedback de progreso en operaciones multi-paso
**Files:** `tui_composer.py` / `tui_widgets.py`.
- [ ] Indicador (n/total + barra) durante batch writes; reutilizar elapsed timer; no bloquear render.

---

## M-UX3 — Visibilidad y feedback (mejoras)  ⬜ PENDIENTE

### T-UX3.1 Modelo actual inline en el composer  ✅ HECHO
- [x] `#model-button` con el modelo actual en la command bar (`GPT 5.6 Sol ▾`); click abre el selector de providers existente; refresco en `on_mount` y tras `_select_provider`. Tests en `tests/test_model_button.py`.

### T-UX3.2 Pantalla dedicada de búsqueda cross-session  ✅ HECHO
- [x] `SessionSearchScreen` (título + transcript, filtro en vivo, Enter/Esc) alimentada por el owner con autoridad; `Ctrl+Shift+F` registrado en `APP_SHORTCUTS` sin colisiones (solo `ctrl+shift+p`/`ctrl+shift+enter` existían, en el composer). Tests en `tests/test_session_search_screen.py` (6).

### T-UX3.3 Selector de modelos agrupado por familia  ⬜ PENDIENTE (idea de Danny, 2026-10-06)
**Problema:** el selector muestra una lista plana de ~100 modelos por provider.
**Diseño:** dos niveles jerárquicos — el provider expone **familias** como padres (GLM, GPT, Qwen, DeepSeek…); cada familia se abre como subcarpeta/pestaña y dentro aparecen sus variantes (5.2, 5.3, 5.3-Flash, 5.2-Flash…). Semánticamente: provider → familia (hijo) → variante (nieto).
- [ ] Derivar la familia desde el id del modelo (`model_presentation.model_display_name` ya normaliza marcas: glm→GLM, gpt→GPT, llama→Llama, qwen→Qwen, deepseek→DeepSeek, kimi→Kimi, nemotron→Nemotron); familia = primer token de marca reconocido, resto = "Otros".
- [ ] Selector rápido de dos pasos: familia → variante, reutilizando `_menu`/PreviewOptionList (mismo patrón que providers → models, sin pantalla nueva).
- [ ] Tests: agrupación correcta con ids reales (glm-5.3-flash → GLM; gpt-6-luna → GPT), fallback "Otros", y que elegir variante llega a `_select_provider` con el id intacto.

---

## M-UX4 — Onboarding progresivo (retención)  ⬜ PENDIENTE
**Files:** `workspace_setup.py`, `workspace_trust.py`, `tui.py`.
- [ ] Quick Start: provider en env → recurrente + Classic → "Turn on all coding tools" → chat (<2 min).
- [ ] Custom Setup: wizard 4 pasos. Tour opcional (`/help tour`).
- [ ] Tests: quick start no concede nada fuera de Classic; trust screen sigue en Security.

---

## M-UX5 — Polish y accesibilidad completa (bajo)  ⬜ PENDIENTE
- [ ] Fallback ASCII-only (sin `✓✗●○`) para terminales sin Unicode.
- [ ] Pruebas con lector de pantalla (Orca).
- [ ] Documentar estados/atajos en `GUIA.md` (§10b del contrato raíz).

---

## Orden de ejecución
1. **M-UX1** — bajo riesgo, valor inmediato. (T-UX1.1 y T-UX1.2 hechos; T-UX1.3 pendiente.)
2. **M-UX2** — mayor valor; cuidado con M15.
3. **M-UX3** → 4. **M-UX4** → 5. **M-UX5**.

## Verification
- Suite completa tras cada milestone: `env -u ISYCODE_STATE_HOME python3 -m pytest -q` (baseline: **1414 passed, 6 skipped, 0 failed**).
- `python3 scripts/validate_gates.py` en verde (evidencia M15 intacta).
- Tests nuevos por milestone. Capturas en 80×24 / 100×30 / 140×40, normal y high-contrast, con y sin color.
- M-UX2: test de replay de digest y de no-persistencia de grants.

## Riesgos
- **M-UX2.1 batch:** no debilitar el un solo uso. Mitigación: N digests independientes + tests de replay.
- **M-UX2.2 session trust:** no escribir en `policy_path` ni sobrevivir reinicios.
- **Atajos nuevos (Ctrl+Shift+F):** verificar colisiones.
