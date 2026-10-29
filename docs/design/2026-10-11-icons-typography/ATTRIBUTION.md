# Third-party material and changes

Its Hover: Copyright 2026 itshover, Apache License 2.0. Repository https://github.com/itshover/itshover, pinned revision `e5fc90512d9bcd8e6cba407ebf88cb9458989ca3`. Original source files are preserved unmodified under `sources/itshover/`; the complete license is `licenses/itshover-Apache-2.0.txt`.

Modified on 2026-10-11: the six SVGs in `icons/itshover/` and inline SVGs in `preview.html` extract original path geometry from JSX. `build-hover-assets.py` performs the extraction. `hover-motion.js` translates motion ideas from React/Motion to the browser Web Animations API, adds finite character-frame examples, keyboard activation and reduced-motion handling. The demo returns to its initial state and is not a drop-in implementation of the original components. `itshover-svg.json` stores the extracted markup used by the builder. These adapted files are provided under Apache-2.0; their notices identify the changes. No upstream NOTICE file was present in the pinned tree.

Tabler Icons: original SVG files and MIT license preserved; provenance in `asset-sources.json` and `licenses/tabler-MIT.txt`.

Nerd Fonts: downloaded patched font files, aggregate license and collection notices preserved. This demo's mapped PUA glyphs use Octicons and Seti/original, both listed as MIT in the pinned collection notices. This does not classify every glyph in the downloaded patched fonts as MIT.

JetBrains Mono, Cascadia Code and Iosevka Term: original OFL notices preserved for the underlying font designs. Ubuntu Sans Mono: installed, unmodified font copy with the package's original copyright/licensing notice. DejaVu Sans Mono: installed, unmodified fallback copy; Bitstream Vera and public-domain DejaVu changes, with package notices preserved. Browser-only scaling changes rendering size, not font data or names.
