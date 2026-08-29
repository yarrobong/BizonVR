# Portfolio Screenshot Plan

There are no verified UI screenshots in the repository that can be reused as
portfolio captures. Do not add generated or fabricated screenshots. Capture the
real local application after loading safe demo data, then place only approved
images in this directory and reference them from the root README.

## Capture Rules

- Use a local environment with synthetic data only.
- Do not expose real names, phone numbers, emails, addresses, order IDs, tokens, API URLs, credentials, or customer history.
- Prefer a clean browser profile and a viewport of `1440x1000` for desktop captures.
- Capture mobile states separately at `390x844` only when the responsive behavior is useful.
- Keep the browser chrome out of the image and include the full application viewport.
- Use descriptive filenames such as `storefront-catalog.png` and `manager-inventory.png`.
- Check every image at readable scale before linking it from `README.md`.

## Shot List

### 1. Storefront catalog

- Route: `/catalog/`
- Viewport: `1440x1000`
- Data: seeded catalog with several products, visible category/filter state, and public stock labels.
- Show: header, catalog navigation, product grid, filters, and responsive spacing.
- Hide: real contact details, analytics identifiers, customer-specific data.
- Suggested filename: `storefront-catalog.png`

### 2. Product detail

- Route: `/catalog/product/<seeded-product-slug>/`
- Viewport: `1440x1000`
- Data: a seeded product with an image gallery, variant selector, availability, recommendations, and a visible add-to-cart action.
- Show: product hierarchy, variant-aware purchasing, media, and stock presentation.
- Hide: supplier information, private admin metadata, and real customer data.
- Suggested filename: `product-detail.png`

### 3. Cart and checkout

- Routes: `/catalog/cart/` and `/orders/checkout/`
- Viewport: `1440x1000`
- Data: synthetic guest cart with at least one product variant, delivery selection, and safe placeholder contact values.
- Show: cart line items, checkout sections, legal consent controls, and manager-led payment message.
- Hide: real email, phone, address, delivery account identifiers, access tokens, and order URLs.
- Suggested filename: `checkout.png`

### 4. Manager deal workflow

- Route: `/manager/deals/` or `/manager/deals/<synthetic-deal-id>/`
- Viewport: `1440x1000`
- Data: seeded synthetic deal with a client, order lines, payment state, fulfillment state, and next-step panel.
- Show: operational workflow, status/readiness signals, and the boundary between order and manager deal.
- Hide: real client identity, phone, email, address, Bitrix IDs, and financial amounts if sourced from production.
- Suggested filename: `manager-deal-workflow.png`

### 5. Inventory and reservation workflow

- Routes: `/manager/inventory/` and `/manager/reservations/`
- Viewport: `1440x1000`
- Data: synthetic warehouse with on-hand, reserved, incoming, and at least one public-stock mismatch or low-stock signal.
- Show: stock matrix, warehouse scope, reservation state, and actionable inventory signals.
- Hide: supplier credentials, warehouse addresses, cargo tracking numbers, and real SKU/customer data.
- Suggested filename: `manager-inventory.png`

## After Capture

1. Review each image for personal or production data.
2. Optimize dimensions and file size without making text unreadable.
3. Add approved images to this directory.
4. Add relative image links to the root README under a new `Screenshots` section.
5. Recheck the links from GitHub's rendered README before considering the portfolio presentation complete.
