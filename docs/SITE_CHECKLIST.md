# Public Site Check Checklist

Use this checklist after public-site, catalog, checkout, navigation, content, or documentation changes.

## Automated Checks

```bash
python manage.py check
python manage.py test
npm run build:css
```

If frontend lint is later added to `package.json`, run it too. Currently `package.json` defines only `build:css`.

For faster local reruns you can still use `python manage.py test --keepdb --noinput`, but the release-style validation path should use a clean test database to avoid false failures from stale test data.

## Public Smoke Test

1. Open `http://127.0.0.1:8000/`.
2. Open catalog and verify product cards, filters, sort controls, and pagination.
3. Open a product detail page and verify images, price/request state, stock, variants, favorites, and add-to-cart behavior.
4. Open cart and verify quantity changes, deletion, selected totals, and checkout entry.
5. Open checkout and verify contact fields, delivery fields, legal consents, promo code behavior, and successful order creation.
6. Open favorites and verify guest/authenticated behavior if relevant.
7. Open contacts and public lead forms.
8. Check mobile width for header, bottom dock, catalog list, product detail, cart, and checkout.
9. Check desktop width for header, catalog overlay, sticky header, search, footer links, and product grids.
10. Watch the browser console for JavaScript errors.

## Header And Navigation Smoke

1. Desktop: open and close catalog overlay from the normal header.
2. Desktop: scroll until sticky header appears, then open and close catalog overlay from the sticky header.
3. Close overlays by outside click and by Escape.
4. Navigate between public pages with HTMX boost enabled, then click header controls again.
5. Mobile: verify mobile search header and bottom dock stay clickable.
6. Confirm body scroll is restored after overlay close and after navigation.

## Content Checks

- Public copy is readable and not mojibake.
- Images have correct aspect ratio and no broken media.
- Game packs and VR club games have active data and admin-managed copy.
- Footer links point to current legal pages.
- SEO pages have title, meta description, and canonical URL.

## Deployment Readiness

Before production deployment:

- Review `DEPLOY.md` for first deploy.
- Review `DEPLOY_UPDATE.md` for repeat deploys.
- Confirm `.env` changes were approved separately.
- Confirm migrations are committed and not removed.
- Confirm manager portal files were not touched unless explicitly approved in a separate task.
