# Accepted ISyCode visual standard — v1

Accepted by Danny on 2026-10-11. Scope: the Python/Textual ISyCode TUI in this repository. This standard is not the Qt ISyCode-IDE standard and does not grant authority to runtime tools.

## Visual direction

- **Contraste esencial**, proposal 1: flat black surfaces, white main text, muted secondary text, cyan focus/selection, thin consistent frames and separators.
- Preserve the landscape, cat and chat identity when changing menu chrome.
- Group Settings into Conversation, Preferences, Permissions and Connections. Do not repeat category names at the beginning of every setting row.
- Keep Overview/Files sidebar sections flat. Use progressive detail and reserve space for status text rather than nesting framed containers.
- Use one search/list/detail pattern, one field/help/error pattern and one decision/diff pattern across menu families. A new menu should fit a pattern before it adds a new surface style.
- Regular body weight; emphasis for titles, selection and explicit actions. Do not make an entire list bold.
- Symbols identify functions; text identifies state. Neutral availability is not a green success result. State must remain understandable in ASCII and without color.

The palette and profile are in [tokens.json](../assets/tokens.json). Common scoped TCSS is in [tokens.tcss](../assets/tokens.tcss). These are reusable authoring assets; they have not been wired into production.

## Translation glossary

Added 2026-10-23 at Danny's request. Spanish and Chinese translate the explanation, not developer jargon a programmer already reads in English. Keep these in English in every locale: commit, push, merge, diff, branch, stream, steer, snapshot, lane, batch, token, prompt, endpoint, hook, lease, owner, API key, sandbox, and product or protocol names (Workspace Authority, IsySentinel, Gateway, MCP, LSP, Bridge, Classic, Flow, Security). Spanish uses "workspace" (not "espacio de trabajo"); "Espacio" names only the Space key. Chinese keeps 工作区 for workspace, its standard term. Every message passed to `tr()` needs an en/es/zh catalog entry (`test_every_literal_ui_message_has_a_catalog_entry`).

## Role colors

Added 2026-10-23 at Danny's request (opencode-style agent switch). Each ISyCode role has one identifying color in `role_colors` of [tokens.json](../assets/tokens.json); `catalog.py` is the runtime source. With a role selected, the composer frame takes that color and names the role in its title (`● coder`, `* coder` in ASCII mode), and each answer gets a thin left rule in the color of the role it was asked under, with the role name after its time. The name always accompanies the color, so the role reads without color. No role keeps the neutral/cyan frame. Shift+Tab anywhere in the main chat (not in dialogs or the command menu) walks Build, Plan and the ISyCo motors, then back to no role; specialists stay in the Role menu. A role color is identity, not a state: it never means success, warning or a grant. GUS, the ISyCode maintainer (ADR 0011), uses the `maintainer` role color for its window title and its lines; its own transcript never enters the chat.

## Workspace chrome

Added 2026-10-23 at Danny's request. There is no header row above the chat: the landscape starts at the top. The `:3_ ISYCODE` wordmark and the launch folder head the workspace rail, keeping the path's end when it is clipped (full path in the tooltip and the identity dialog). The workspace mode is a chip in the bottom bar just left of ⚙ (`◇ Classic`, `[C] Classic` in ASCII mode; cyan for Classic, muted otherwise). Clicking it opens the mode dialog with Classic, Flow and Security, the current one marked; Esc or Cancel keeps the mode, and a choice goes through the same confirmed switch as Settings → Authority → Workflow (pending approvals and session permissions are invalidated). The bar is measured: when it cannot fit every button, the model yields first (the idea box title names it), then the mode chip (the rail identity line names the mode).

## Typography and compatibility

The accepted comparator profile is **Ubuntu Sans Mono / Unicode / 14 CSS px / 1.3 line-height**. Textual does not set a terminal's font family or point size. Preserve the user's terminal settings unless their request specifically changes them. Calibrate terminal cell metrics separately; 14 CSS px is not a tested GNOME Terminal point size.

The comparator uses DejaVu Sans Mono for symbols absent from Ubuntu, with browser-only scaling. Its font data was checked; terminal fallback and widths are still unverified. Reserve a stable symbol column using measured cell width, retain an ASCII mode, and avoid requiring Nerd Fonts for the selected Unicode mode. Do not treat browser SVG rendering as terminal support.

## Behavior targets

Content-box expansion uses **Space only** on a focused, non-editable content box. Space in an editable field inserts a space. Double-click opens the copy menu without expanding or copying immediately. Selection copy uses only the mouse-selected characters; whole-box copy is an explicit separate option. Enter continues to activate real controls and menu choices.

Workspace Authority, IsySentinel, execution owners and the journal retain their contracts. A new icon, animated check or selected row must not imply a grant or successful action. Permissions UX follows the repository's existing Classic/Security roadmap gates.

## Adaptive box and modal sizing (Anti-Void & Anti-Slit)

Added 2026-10-25 at Danny's request. Dialogs, cards, modal windows and expandable content boxes must dynamically adapt to their text length, respecting proportional limits:

- **Anti-Void (No a la ventana gigante para 2 líneas):** No modal screen, approval prompt, confirmation card or simple action menu should set fixed `height: 90%` or `height: 94%`. Small contents (confirmations, rename, single-note views, short question prompts) must use `height: auto` with a sensible minimum (e.g., `min-height: 8-12` rows) and bounded `max-height: 88-90%`, scrolling internally (`overflow-y: auto`) only when text exceeds the bound.
- **Anti-Slit (No a la tira aplastada de 1 línea):** Boxes must not collapse into a single-line horizontal slit when containing brief notes or title bars. They declare a balanced `min-height` (at least 3 visible lines in composer boxes like `#idea-box` and `#shell-box`, at least 8-10 rows in dialogs with title, copy, and buttons) and proportional `min-width: 44-52` cells so the frame feels like a balanced card rather than a ribbon.
- **Content-adaptive expansion:** Expandable output cards (such as `CommandOutputCard`) when expanded must not force a flat 18-row void when the command produced 1 line ("ok"); they use `height: auto; min-height: 6; max-height: 18;` fitting the actual output.
- **Proportional modal width tiers:**
  - Narrow/Confirmation: `min-width: 40; width: 64-68; max-width: 90%;`
  - Standard Dialog: `min-width: 48; width: 80-84; max-width: 94%;`
  - Wide/Form/Diff: `min-width: 60; width: 92-100; max-width: 96%;`

## Provenance and implementation state

Accepted evidence:

- [Proposal catalog and gesture contract](../../../../docs/design/2026-10-11-menu-coherence/PLAN_VISUAL.md)
- [Selected screenshot composition](../../../../docs/design/2026-10-11-menu-overlay/README.md)
- [Selected typography profile](../../../../docs/design/2026-10-11-icons-typography/accepted-profile.json)
- [Icon/motion research and all menu families](../../../../docs/design/2026-10-11-icons-typography/INVESTIGACION.md)
- [Earlier audit findings](../../../../docs/audits/2026-10-11-e2e-1830/AUDITORIA.md)

The design artifacts and comparator are implemented as local design material. The updated comparator's browser review, production styling, Space-only expansion, new double-click copy menu, real-terminal symbol fallback and native motion remain **NOT_DEMONSTRATED** at library creation. Existing content widgets still bind Enter and Space. Inspect current source when implementing; this paragraph is dated provenance, not a permanent claim about runtime state.

Prioritize the audit's stale mode header and inaccessible Settings in 80×24, then new-chat focus, onboarding height, rail preview height and critical translations when those are in the current task's scope. Do not expand a small visual task into unrelated fixes automatically.

When a later user-approved direction changes the standard, update the shared tokens/profile and relevant skill references together. Preserve earlier dated design evidence instead of rewriting it as if the new direction had always been accepted.
