# Subagents with a user-selected model

User authorized cross-provider subagents and edits using existing approvals. Each delegation opens a modal showing the assigned task and recent registered provider/model pairs. Explicit Launch selects a pair without changing the main agent. No request happens on cancellation or without a provider network grant.

Initial scheduling is one child at a time while the parent waits. This avoids concurrent diff approvals and file edit collisions. Children receive the assigned task and folder metadata, not the entire parent conversation. They can read/search/create/edit through existing workspace owners, with the same per-root approval mode. They cannot recursively delegate or invoke unregistered tools. Provider calls and usage are owned/accounted, with a bounded 20-turn ceiling, cancellation and truthful completed/blocked/limit/error states. Main chat receives the bounded child result and actual provider/model identity. Expose /models recent entries and /subagent <task>, plus delegate_task for the main model when workspace tools are enabled.

Validation: recent model persistence, cancellation sends nothing, cross-provider routing preserves main selection, denied network never calls transport, native child edit goes through diff approval, unknown/nested tools denied, step limits and cancellation cleanup.
