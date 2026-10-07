# Cat composer visual pass — 2026-10-03

Requested behavior: place activity and usage beside the Idea box, remove cost/request counts and the commands hint, animate working status, replace the blue chat scrollbar with three directional strokes, add original ASCII art.

Activity occupies the left 20%, Idea box the center 60%, tokens and estimated context the right 20%. Chat working dots update every 300ms; completion stops the timer and restores Chat ready. Errors/interruption retain explicit wording. The chat scrollbar uses three gray strokes while moving and one center stroke after 450ms of rest. Native scrolling and mouse action metadata remain in place. Other scrollbars retain their original appearance; this prototype is scoped to the chat.

The existing checked-in landscape asset is preserved; the renderer adds an original two-line ASCII cat between its trees. Header remains :3_ ISYCODE. No dependencies, external artwork, authorization or execution behavior changed.

Verification: visual/startup/layout/chat/snapshot set 33 passed; new composer matrix plus daily chat, modal usage and command cards 26 passed; final composer/chat-sequence/snapshot set 12 passed. Matrix covers 80x24, 100x30, 120x40, 140x40. git diff --check passes. Full suite was not rerun for this visual-only pass. The earlier runtime suite remains historical evidence (1245 passed).
