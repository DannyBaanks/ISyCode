# Contribuir a ISyCode

Gracias por ayudar a mejorar ISyCode. Los cambios deben mantener claro qué
puede hacer el agente, quién autoriza cada acción y qué evidencia respalda una
afirmación.

## Preparar el entorno

Se requiere Python 3.10 o posterior. Desde la raíz del repositorio:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e . pytest
```

La suite hermética se ejecuta con:

```bash
python -m pytest -q -m "not integration"
```

Las pruebas marcadas `integration` pueden hablar con servicios reales. Revisa
el test y su documentación antes de habilitar una integración externa.

## Enviar un cambio

1. Describe el problema y el resultado observable esperado.
2. Mantén el cambio enfocado y conserva los datos y permisos del workspace.
3. Actualiza la documentación cuando cambien comandos, configuración o
   comportamiento visible.
4. Ejecuta las comprobaciones pertinentes y anota exactamente cuáles corriste
   y sus resultados. No presentes pruebas simuladas como evidencia de una
   integración real.
5. Abre un pull request con resumen, motivo, validación y limitaciones
   pendientes. Incluye capturas si el cambio modifica la TUI.

## Reglas de seguridad

- IsySentinel decide si una acción puede continuar; los owners ejecutan solo
  después de una decisión permitida y registran el resultado.
- `.isyroot` define el límite lógico máximo del workspace; no concede permisos.
- Workspace Authority mantiene grants explícitos por workspace. Preferencias,
  roles, contexto inyectado, credenciales y coordinación no los sustituyen.
- No añadas caminos que permitan saltarse IsySentinel, aprobaciones por acción
  o el journal.
- No incluyas claves, tokens, datos privados ni salidas con secretos en commits,
  issues, capturas o logs.
- Las integraciones con Gateway, MCP, Tailscale y Bridge son independientes y
  deben conservar sus propias comprobaciones y límites.

Consulta [la guía de fronteras de IsySentinel](docs/design/isysentinel-security-boundaries.md)
y el contrato del proyecto en [AGENTS.md](AGENTS.md) antes de modificar estas
superficies.
