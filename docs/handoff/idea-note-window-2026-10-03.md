# Idea note window — 2026-10-03

The existing Idea box retains its layout rules. Its top border now shows Enter / Space expand. Focus it with Tab and press Enter or Space to open the full note. Alternatively type /idea in the composer. The floating window has scrollable text, updates as the agent updates the note, and closes with Esc or its Close button. Opening the view does not run a provider request or grant actions.

Related visual work completed in this session: walking pixel cat that curls up when ready (69ccf6f; 27 tests passed), compact collapsible tool activity cards (5f5cb97; 34 tests passed). Tool request, outcome, diagnostics and duration text remain in the expanded card. Command output retains its separate compact command card.

Window verification: 15 passed across note expansion, original idea tools, composer geometry, animation status and live authority snapshot. The new tests cover keyboard expansion, /idea, live updates, Esc/Close, and returning to the original box geometry at 80x24 and 120x40. git diff --check passed. No full-suite claim is made for these visual changes.
