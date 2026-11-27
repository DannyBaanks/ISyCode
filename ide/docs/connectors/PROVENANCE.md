# Connector provenance

Codex app-server adapter adapted from Danny's ISyCode TUI,
`src/isycode/codex_connector.py`, source checkout commit `c9bb088533694959dc2d5924612fc4a217c610bd`.
Original source SHA-256: `83f0bf4db07c0b4f30b61468d1f88d6c775e3b16bc41ddac1b526c55fab64d8c`.

IDE changes: independent package imports, own identity/home, bounded frames and
text, process group termination, and no writes to the TUI catalog caches.
Official CLI owns authentication; native tools are disabled and dynamic tool
requests return to the IDE host after closing the peer connection.

Claude uses official CLI restricted/safe modes with built-in tools disabled,
empty strict MCP configuration and schema-constrained proposals. Grok uses the
CLI session HTTP endpoint identified in the TUI adapter; it is not presented as
an API-key or an officially stable public subscription API. Accounts and real
service compatibility require explicit verification.
