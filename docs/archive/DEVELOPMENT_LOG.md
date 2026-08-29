# Development Log

## 2026-05-09 - Public header smoke test

Smoke scenario for the BizonVR public header/navigation:

1. Open the home page on desktop width, click `Каталог`, verify the catalog overlay opens, body scroll is locked, outside click closes it, and Escape closes it.
2. Scroll past the sticky threshold, click `Каталог` in the sticky header, verify the overlay opens and closes the same way.
3. Navigate with HTMX boost from home to catalog and back to a public page, then immediately click `Каталог`; the overlay must open on the first click.
4. Resize to mobile width, verify the mobile search header and bottom dock stay clickable and no desktop catalog overlay blocks the page.
5. Confirm the browser console has no errors during open, close, Escape, outside click, scroll, and HTMX navigation.
