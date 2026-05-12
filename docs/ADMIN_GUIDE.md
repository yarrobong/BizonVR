# Django Admin Guide

This guide covers the public-site admin workflow only. It does not document or change manager portal workflows.

## Access

- URL: `/admin/`
- Use a Django superuser or a staff account with explicit model permissions.
- Do not give manager-style operational permissions to public content editors unless they need them.

## Public Catalog Content

Use Django admin for:

- Catalog sections and categories
- Products, product variants, images, tags, characteristics, and content blocks
- Product bundles
- Game packs and game metadata
- Services
- Cities, pickup points, and public stock
- Promo codes
- Callback and lead requests

Keep public content admin-configurable when practical. Avoid hardcoding product copy, game-pack copy, city data, or public navigation content unless the codebase already treats it as code-owned content.

## Product Checklist

For each public product:

1. Name, slug, category, price or request-price mode are set.
2. Product kind matches the intended behavior.
3. Images are present and not broken.
4. Description blocks are filled if the product needs a rich detail page.
5. Variants are configured if the product has colors, storage, or other sellable options.
6. Stock is attached through pickup points when availability should be city-specific.
7. Active status and sort order are correct.

## Cities And Stock

City data is stored in the public catalog models:

- `City`
- `PickupPoint`
- `ProductStock`

The public site reads cities and availability from the same PostgreSQL database as admin. If admin and the public site show different city counts, check that both are using the same `.env` and database.

## Public Lead Forms

Lead and callback content should remain visible in Django admin so operators can process requests. After changes to forms, verify:

- CSRF works.
- Required contacts are validated.
- Legal consent text is shown where required.
- Emails or CRM hooks still fire if configured.

## Do Not Touch

Manager portal templates, routes, views/controllers, JavaScript, CSS, and API endpoints are outside this guide and must not be edited for public-site documentation cleanup.
