# Complete the accepted menu design end to end

Accepted reference: the user's proposal 1 menu catalog, plus Ubuntu Sans Mono/
Unicode comparator preferences. This completes existing Textual flows; it does
not introduce a new visual direction or grant model/service capabilities.

Work happens in the primary ISyCode checkout, on local main. Preparation merged
remote main 5a8903b into the approved work at 9ca6df1 without any tracked-file
change; integration base is a425b32e9a2c245d8197dc63a7db6eb7b3363b04.

1. Settings: actual option/value/help rows, separate provider/model navigation,
   coherent heading/scope, grouped categories and cross-category search.
2. Search/list/detail: providers, models, sessions, roles, context, reasoning,
   palette and evidence. Selection and current choice remain distinct.
3. Sidebar: flat Overview/Files, meaningful state and function symbols, useful
   preview, consistent actions. Preserve landscape, cat and input behavior.
4. Decision/form/content dialogs: common frames, regular body text, cyan focus,
   bounded scrolling and explicit controls for approvals, onboarding, keys,
   connections, ideas, queue, command output, file preview and exact copying.
5. Installation: connect the user command to this tested source using the
   existing launcher, retaining its old target and user state. Verify imports
   through the actual command and a clean isolated PTY launch.
6. Verification: meaningful red/green Pilot regressions, owner/approval tests,
   native screen exports at 80x24, 100x30 and 140x40, whole hermetic suite,
   source/gate provenance, independent code review and package contents.

Implementation ownership: parent owns core Settings/provider menus, sidebar,
shared TCSS/presentation, locale catalogs and launcher. Selector agent owns
harness/session screens. Decision agent owns approval/grant/file-preview
screens. Provenance agent investigates the existing G8 historical association
read-only before any metadata correction is reviewed.

Actual values/states replace illustrative mock data. Harness inspection stays
read-only. Auth, approval, execution and clipboard owners retain their contracts.
Terminal font preferences and live service inference are separate from compositor
captures. Evidence records exactly what ran; unresolved checks prevent a claim
that all checks passed. No raw historical witness or user work is overwritten.
