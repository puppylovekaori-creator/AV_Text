# Firefox Context Menu Notes

This folder keeps the reproducibility files for the Firefox context-menu tuning work done on 2026-04-27.

Files:
- `firefox_context_menu_summary_2026-04-27.xlsx`
  - Summary workbook of the extension, CSS, and AutoConfig work.
- `mozilla.cfg`
  - AutoConfig script that keeps `AV Text Paster` at the top of the page context menu.
- `local-settings.js`
  - Firefox preference bootstrap for loading `mozilla.cfg`.
- `install-firefox-autoconfig.ps1`
  - Helper script used to copy the AutoConfig files into `C:\Program Files\Mozilla Firefox`.
