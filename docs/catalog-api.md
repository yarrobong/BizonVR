# Catalog API for DocuFlow

`BizonVR` now exposes a protected read-only catalog API for server-to-server access from DocuFlow. The site database remains private: DocuFlow must call this backend API and must not connect to the site database directly.

## Purpose

- Source of truth for public catalog positions.
- Safe synchronization of products, services and bundles into DocuFlow.
- Read-only integration without changes to the current site admin or public catalog models.

## Authorization

All requests must include a bearer token in the `Authorization` header:

```http
Authorization: Bearer <CATALOG_API_TOKEN>
```

Required environment variables:

- `CATALOG_API_TOKEN` — shared server-to-server token.
- `CATALOG_API_ALLOWED_ORIGINS` — optional comma-separated browser origin allowlist for CORS. Leave empty for backend-to-backend use.
- `CATALOG_API_DEFAULT_LIMIT` — optional default page size, default `20`.
- `CATALOG_API_MAX_LIMIT` — optional maximum page size, default `100`.

Important:

- Do not embed the token in frontend code, templates, or browser JavaScript.
- Preferred usage is backend DocuFlow -> BizonVR API.
- If `CATALOG_API_TOKEN` is not configured, the API returns `503`.

## Endpoints

### `GET /api/v1/catalog/items`

Returns a paginated list of catalog positions.

Query params:

- `q` — text search by name, SKU, and description where available.
- `type` — `product`, `service`, or `bundle`.
- `categoryId` — internal category ID filter for products and bundles.
- `limit` — page size, clamped to `CATALOG_API_MAX_LIMIT`.
- `offset` — pagination offset.
- `updatedAfter` — ISO-8601 datetime filter, for example `2026-05-24T10:00:00Z`.
- `includeInactive` — `true` to include inactive products/services/game packs. Default is `false`.

Example:

```bash
curl -H "Authorization: Bearer $CATALOG_API_TOKEN" \
  "https://bizonvr.example/api/v1/catalog/items?q=quest&type=product&limit=20&offset=0"
```

Response:

```json
{
  "items": [
    {
      "id": "product:1",
      "externalId": "1",
      "type": "product",
      "name": "Meta Quest 3",
      "description": "Флагманский VR-шлем",
      "unit": "шт.",
      "price": 39990.0,
      "currency": "RUB",
      "vatRate": 0,
      "sku": "MQ3-128",
      "category": {
        "id": "5",
        "name": "Шлемы"
      },
      "imageUrl": null,
      "isActive": true,
      "updatedAt": "2026-05-24T12:00:00Z"
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total": 1,
    "hasMore": false
  }
}
```

### `GET /api/v1/catalog/items/<id>`

Returns one catalog position by public API ID.

Supported ID formats:

- `product:<id>`
- `service:<id>`
- `bundle:<id>`
- `game-pack:<id>`

For bundle-like items, the response also includes `bundleItems`.

Example:

```bash
curl -H "Authorization: Bearer $CATALOG_API_TOKEN" \
  "https://bizonvr.example/api/v1/catalog/items/product:1"
```

### `GET /api/v1/catalog/bundles/<id>`

Returns bundle composition for:

- `bundle:<id>` — `ProductBundle`
- `game-pack:<id>` — `GamePack`

Example:

```bash
curl -H "Authorization: Bearer $CATALOG_API_TOKEN" \
  "https://bizonvr.example/api/v1/catalog/bundles/bundle:10"
```

Response:

```json
{
  "id": "bundle:10",
  "externalId": "10",
  "type": "bundle",
  "name": "Комплект VR-клуба",
  "description": "Готовый комплект оборудования.",
  "unit": "комплект",
  "price": 79980.0,
  "currency": "RUB",
  "vatRate": 0,
  "sku": null,
  "category": {
    "id": "8",
    "name": "Комплекты"
  },
  "imageUrl": null,
  "isActive": true,
  "updatedAt": "2026-05-24T12:00:00Z",
  "items": [
    {
      "itemId": "product:1",
      "type": "product",
      "name": "Meta Quest 3",
      "quantity": 2,
      "unit": "шт.",
      "price": 39990.0,
      "priceOverride": 39990.0,
      "vatRate": 0
    }
  ]
}
```

## DTO contract

Returned item fields are intentionally whitelisted and detached from internal model structure:

- `id`
- `externalId`
- `type`
- `name`
- `description`
- `unit`
- `price`
- `currency`
- `vatRate`
- `sku`
- `category`
- `imageUrl`
- `isActive`
- `updatedAt`

The API does not expose:

- purchase prices
- margin fields
- supplier data
- internal notes
- customer/order personal data
- internal user IDs

## Errors

- `401 unauthorized` — missing or invalid bearer token.
- `404 not_found` — item or bundle is absent or unavailable through the API.
- `429 rate_limited` — too many requests.
- `500 catalog_api_error` — unexpected backend error.
- `503 catalog_api_unavailable` — `CATALOG_API_TOKEN` is not configured.

## Logging

The API logs:

- successful catalog requests
- invalid token attempts
- rate limit hits
- unexpected API errors

The raw token value is never written to logs.

## DocuFlow integration notes

- Store `CATALOG_API_TOKEN` only on the DocuFlow backend.
- Save and use API IDs like `product:1` or `bundle:10` for stable detail lookups.
- Use `updatedAfter` plus pagination for incremental synchronization.
- If DocuFlow later needs create/update operations, add a separate write API with stronger auth and auditing instead of extending this read-only surface directly.
