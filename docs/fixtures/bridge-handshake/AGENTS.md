# Bridge handshake acceptance fixture

This fixture is for a one-time console acceptance check of the optional ISyCo Bridge.

1. Register one uniquely named temporary agent with the official `handshake.py hello` operation, declaring the `isycode,acceptance-fixture` capabilities and the current process ID.
2. Keep the returned identity token only in process memory. Never print, persist, or include it in a transcript.
3. Read the mailbox with `peek` and report only the number of records, not their payloads.
4. Finish with `goodbye` using the in-memory token so the temporary agent is marked gone and its leases are released.

The Bridge is an append-only coordination mailbox. It does not grant filesystem, process, network, or tool permission. Do not start a daemon, claim a lease for this check, or modify Bridge storage files directly.
