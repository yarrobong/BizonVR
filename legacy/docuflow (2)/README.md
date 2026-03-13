<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# Run and deploy your AI Studio app

This contains everything you need to run your app locally.

View your app in AI Studio: https://ai.studio/apps/drive/1P6eQ-ZBmwjh8DZqP8YDxvr-8Qtmjm9Nt

## Run Locally

**Prerequisites:**  Node.js


1. Install dependencies:
   `npm install`
2. Install backend dependencies:
   `npm --prefix server install`
3. Set the `GEMINI_API_KEY` in [.env.local](.env.local) to your Gemini API key
4. Run both frontend + backend together:
   `npm run dev`

Alternative manual mode:
1. Start backend API:
   `npm --prefix server start`
2. In a second terminal, run frontend:
   `npm run dev:client`

By default frontend runs on `http://localhost:3000` and backend on `http://localhost:3001`.
If port `3000` is busy, Vite will stop (strict port mode), so free the port and rerun.

## Architecture (Feature-First + API v2)

### Frontend structure

- `src/app` — app providers, router, feature flags store.
- `src/shared` — API clients, common types, config, reusable helpers.
- `src/entities` — domain entities (`contract`, `invoice`, `counterparty`, `template`, `settings`).
- `src/features` — feature-level modules (edit/create/export/theme/profile switching).
- `src/widgets` — composed UI blocks.
- `src/pages` — route-level pages.
- `App.tsx` + `views/*` are currently kept as legacy UI and rendered through the new router as a compatibility layer.

### Backend structure

- `server/src/index.js` — thin bootstrap.
- `server/src/app` — app creation and error middleware.
- `server/src/api/v2` — modular v2 API routes.
- `server/src/api/v1` — v1 compatibility adapter routes.
- `server/src/modules/*` — domain services.
- `server/src/legacy/legacy-app.js` — legacy monolith retained as compatibility core during migration.

### API versioning

- Legacy API remains available under `/api/*` and `/api/v1/*`.
- New modular API lives under `/api/v2/*`.
- v1 responses include `Deprecation` + `Sunset` headers.

### Feature flags

- `VITE_USE_API_V2`
- `VITE_USE_QUERY_DATA_LAYER`
- `VITE_USE_NEW_ROUTER`

Example in `.env.local`:

```bash
VITE_USE_API_V2=true
VITE_USE_QUERY_DATA_LAYER=true
VITE_USE_NEW_ROUTER=true
```

### QA/CI commands

- `npm run typecheck`
- `npm run lint`
- `npm run test`
- `npm run build`
- `npm run test:e2e` (Playwright)
- `npm run generate:api-types`

## Data Storage

- Backend now stores all core entities in SQLite: `contracts`, `invoices`, `counterparties`, `templates`, and `settings` in `server/data.sqlite`.
- On first backend start, existing records are automatically migrated from `server/data.json` if the DB tables are empty.
- `server/data.json` is kept only as a bootstrap source for initial migration.
