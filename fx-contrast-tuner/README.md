# FX Contrast Tuner

Purpose:
- Detect white or near-white page surfaces.
- Apply a slightly darker surface color and stronger link colors only on those surfaces.
- Keep the tuning logic easy to tweak later.

Files:
- `manifest.json`
  - Firefox MV3 addon manifest.
- `content.js`
  - Detection logic.
  - Tweak `CONFIG.selectors`, `perChannelThreshold`, `luminanceThreshold`, `minArea`, and `debounceMs`.
- `content.css`
  - Visual tuning.
  - Tweak `--fx-contrast-*` variables for background and link colors.

Current default behavior:
- Adds `data-fx-contrast-mode="light-page"` to the root when at least one large light surface is found.
- Marks matched light surfaces with `data-fx-contrast-surface="true"`.
- Only those marked surfaces get the darker background and stronger link/hover colors.

Current status:
- Created only.
- Not installed or enabled automatically.
- Intended for later tuning.
