# Firefox Context Menu Notes

This folder keeps the reproducibility files for the Firefox context-menu tuning work done on 2026-04-27.

Files:
- `firefox_context_menu_summary_2026-04-27.xlsx`
  - Summary workbook of the extension, CSS, and AutoConfig work.
- `mozilla.cfg`
  - AutoConfig script that places `AV Text Paster` / `サクラエディタを前面に` using the current mode.
- `local-settings.js`
  - Firefox preference bootstrap for loading `mozilla.cfg`.
- `install-firefox-autoconfig.ps1`
  - Helper script used to copy the AutoConfig files into `C:\Program Files\Mozilla Firefox`.
- `userChrome.css.snapshot`
  - Current profile-side separator cleanup only. Ordering is now handled by `mozilla.cfg`.

Runtime setting:
- `%APPDATA%\\sakura\\avtext\\menu_order_mode.json`
  - Current context-menu placement mode.
  - `top` keeps the target at the top.
  - `near_cursor` moves the target to the edge nearest the right-click position.

Apply step:
- Re-copy `mozilla.cfg` and `local-settings.js` into `C:\Program Files\Mozilla Firefox` when the mode-switch feature is updated.
- `install-firefox-autoconfig.ps1` uses `C:\dev\firefox-autoconfig-staging` as its source.
