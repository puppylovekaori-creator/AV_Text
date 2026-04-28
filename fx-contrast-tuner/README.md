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
  - Reads `storage.local` and reacts to settings changes.
- `content.css`
  - Visual tuning.
  - Uses `--fx-contrast-*` variables for background and link colors.
- `defaults.js`
  - Shared default values for detection thresholds and colors.
- `popup/`
  - Toolbar popup.
  - Enable toggle and shortcut to detailed settings.
- `options/`
  - Detailed settings screen.
  - Thresholds and colors are editable here.
- `icons/`
  - Toolbar / addon icons.

Current default behavior:
- Adds `data-fx-contrast-mode="light-page"` to the root when at least one large light surface is found.
- Marks matched light surfaces with `data-fx-contrast-surface="true"`.
- Only those marked surfaces get the darker background and stronger link/hover colors.

Current status:
- Has toolbar popup and detailed settings page.
- Not installed or enabled automatically.
