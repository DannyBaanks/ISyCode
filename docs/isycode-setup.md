# ISyCode Setup (`isycode setup`)

Asistente de configuración inicial y mantenimiento para ISyCode, inspirado en el flujo por secciones de *Hermes Setup* y adaptado a la arquitectura de autoridad, credenciales e integraciones propias de ISyCode.

## Uso rápido

```bash
# Asistente interactivo completo (primera vez o reconfiguración)
isycode setup

# Configuración rápida (idioma + proveedor/modelo/credencial + workspace)
isycode setup --quick

# Ver el estado de todas las integraciones sin modificar nada ni hacer llamadas de red
isycode setup --status
isycode setup --status --json
```

## Secciones independientes

Puedes ejecutar o reconfigurar una sola sección cuando quieras:

```bash
isycode setup language   # Idioma de la interfaz (es / en / zh)
isycode setup provider   # Proveedor, modelo, API key (Keyring o keys.env) y slots (small / gus)
isycode setup workspace  # Marcador .isyroot, modo de Workspace Authority y defaults de carpetas nuevas
isycode setup mcp        # Servidores MCP locales (~/.config/isycode/mcp.json): ISyMCP Hub, playwright, context7
isycode setup gateway    # ISyCo Gateway (URL, detección de isyco-gateway-mcp y clave en keyring)
isycode setup telegram   # Estado del frontend personal de Telegram y guía de emparejamiento
isycode setup defaults   # Pasos del agente, longitud de respuesta, presupuesto de tokens y accesibilidad
```

## Modo no interactivo (scripts / CI / SSH sin TTY)

```bash
# Ejemplo con NVIDIA NIM leyendo la clave desde variable de entorno
export NVIDIA_API_KEY="nvapi-..."
isycode setup --non-interactive \
  --locale es \
  --provider nvidia \
  --model nvidia/nemotron-3-ultra-550b-a55b \
  --api-key-env NVIDIA_API_KEY \
  --workspace ~/mi-proyecto \
  --init-workspace \
  --mode flow \
  --mcp-preset isymcp-hub \
  --json
```

### Flags principales

| Flag | Descripción |
|---|---|
| `--non-interactive` | Ejecuta sin prompts interactivos |
| `--status` | Muestra el estado actual de integraciones sin modificar nada |
| `--json` | Salida JSON estructurada (para `--status` o `--non-interactive`) |
| `--locale es\|en\|zh` | Idioma de la interfaz |
| `--provider NAME` | Proveedor de `providers.PRESETS` (`nvidia`, `chatgpt`, `antigravity`, `openai`, `anthropic`, `ollama`, etc.) |
| `--model ID` | Modelo principal para el proveedor |
| `--small-model PROV:MODEL` | Slot auxiliar `small` |
| `--gus-model PROV:MODEL` | Slot auxiliar `gus` |
| `--api-key-env VAR` | Lee la API key desde la variable de entorno indicada (preferible sobre `--api-key`) |
| `--key-storage auto\|vault\|file` | Destino de guardado (`auto` usa OS keyring y hace fallback a `keys.env` `0600`) |
| `--workspace PATH` | Ruta del workspace (por defecto el directorio actual) |
| `--init-workspace` | Crea `.isyroot` respetando la protección de directorios amplios (`$HOME`, `/`, `/tmp`) |
| `--mode classic\|flow\|security` | Modo de Workspace Authority del workspace |
| `--default-mode ask\|classic\|security` | Modo por defecto para workspaces nuevos |
| `--new-workspace ask\|temporary\|recurring` | Recurrencia por defecto para carpetas nuevas |
| `--mcp-preset NAME` | Registra un preset MCP (`playwright`, `context7`, `isymcp-hub`); repetible |

## Garantías de seguridad

- **Sin red:** `isycode setup` y `--status` no realizan peticiones de red; para verificar conectividad usa `/check` dentro de la TUI.
- **Sin fuga de secretos:** Las claves se guardan en el OS Keyring (`CredentialVault`) o en `keys.env` con permisos `0600` y nunca se imprimen en salida estándar ni JSON.
- **Protección de raíz amplia:** Nunca crea `.isyroot` en `$HOME`, `/`, `/tmp` ni puntos de montaje.
