# Review only the affected behavior

| Change | Evidence that matters |
| --- | --- |
| Layout / menus | A useful normal-size view and 80×24 view; all actions reachable, modal height bounded, status/name wrapping or truncation intentional. Also check 100×30 and 140×40 when the change spans responsive layouts. |
| Focus / navigation | Open, navigate, activate, Escape/back and return focus. New conversation returns focus to the editor. Disabled options do not execute. |
| Selection / copy | Exact partial line and two-line payload; spaces, tabs, Unicode, wrap, scroll and reversed drag. Zero selection never becomes whole-box copy. Real clipboard check where supported; label a fixture separately. |
| Icons / state | Unicode and ASCII labels, actual cell widths, error/unknown/loading distinct, no color-only meaning. Configuration does not become an unverified success. |
| Motion | Starts/stops with actual lifecycle, no idle animation, cancellation/unmount stops timers, reduced-motion/static behavior, no changing label width. |
| Permissions / approval | Existing owner and grant path retained; clear scope, actual result and journal. Do not advance the roadmap through a visual-only change. |
| Spanish | Critical labels and hints translate and remain translated after repaint; translation expansion does not hide actions. |

Choose checks proportional to the change. Reuse the smallest existing relevant tests; do not rerun a full suite for a documentation-only skill update or write tests that merely repeat the implementation. Screenshot inspection and native clipboard/terminal checks should be reported separately from headless fixtures. A browser preview or passing style parser is not evidence of terminal behavior.
