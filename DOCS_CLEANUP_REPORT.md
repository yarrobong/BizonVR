# BizonVR Documentation Cleanup Report

Date: 2026-05-09

Scope: documentation inventory and cleanup recommendations only. No files were deleted. Manager portal code, templates, routes, JavaScript, CSS, and API endpoints were not modified.

## Current Source Of Truth

Keep these files as active documentation:

- `README.md` - project overview, runtime assumptions, quick links.
- `docs/LOCAL_DEVELOPMENT.md` - local setup and run instructions.
- `docs/ADMIN_GUIDE.md` - public-site Django admin workflow.
- `docs/VR_CLUB_GAMES_ADMIN.md` - game and game-pack admin workflow.
- `docs/SITE_CHECKLIST.md` - public-site smoke and validation checklist.
- `DEPLOY.md` - first production deploy.
- `DEPLOY_UPDATE.md` - repeat production deploy.
- `docs/CITIES_AND_PRODUCTS.md` - city, pickup point, and public stock behavior.
- `docs/ORDER_PLACEMENT_AND_ACCOUNT_FLOW.md` - checkout/account target behavior.
- `docs/SOLUTIONS_LANDING_AUTHORING.md` - manually authored `/solutions/` pages.
- `legacy/README.md` - legacy archive rules.
- `.env.example` - environment variable reference.

## Needs Update Or Review

- `docs/DEV_CHEATSHEET.md` - contains sensitive-looking database values and mixes local, production, and manager commands. Recommendation: replace with links to `docs/LOCAL_DEVELOPMENT.md`, `DEPLOY.md`, and `DEPLOY_UPDATE.md`, then remove secrets from the file after approval.
- `docs/ORDER_PLACEMENT_AND_ACCOUNT_FLOW.md` - useful, but some sections describe older target auth behavior. Recommendation: review against current `accounts` and checkout implementation.
- `docs/CHECKOUT_USER_REPORT.md` - likely overlaps with `docs/ORDER_PLACEMENT_AND_ACCOUNT_FLOW.md`. Recommendation: merge the still-current findings into the order-flow doc.
- `docs/CATALOG_FILTERS_AUDIT.md` and `docs/CATALOG_FILTER_PERFORMANCE_PLAN.md` - both useful, but should eventually become one current filter operations document plus one archived implementation plan.
- `docs/FRONTEND_PERFORMANCE_PLAN.md` - keep as a plan only if it is actively tracked; otherwise archive as historical.
- `docs/SEO_PRESENTATION_LANDING_PLAN.md` - keep if SEO landing work is planned; otherwise archive as a proposal.
- `AUDIT_REPORT.md` - useful as a point-in-time audit, not a source of truth. Recommendation: move to `docs/archive/` after confirmation.
- `DEVELOPMENT_LOG.md` - useful as a short change log if the team wants one. Recommendation: keep only if future changes will append to it.

## Duplicates Or Overlap

- `README.md`, `docs/DEV_CHEATSHEET.md`, `DEPLOY.md`, and `DEPLOY_UPDATE.md` all contain setup/deploy instructions. Recommendation: keep README short, use `docs/LOCAL_DEVELOPMENT.md` for local setup, and keep deploy details in `DEPLOY*.md`.
- `docs/CHECKOUT_USER_REPORT.md`, `chechoutupdate.md`, and `docs/ORDER_PLACEMENT_AND_ACCOUNT_FLOW.md` all relate to checkout/order flow. Recommendation: keep `docs/ORDER_PLACEMENT_AND_ACCOUNT_FLOW.md` as source of truth and archive/delete the others after extracting unique facts.
- `tech.md`, `docs/project_work_description.md`, and `docs/prodile.md` are large specification/report-style documents. Recommendation: classify as historical project reports unless the team confirms they are still maintained.
- `docs/SOLUTIONS_LANDING_AUTHORING.md` and `docs/SEO_PRESENTATION_LANDING_PLAN.md` overlap on landing pages. Recommendation: keep authoring workflow active, keep SEO plan as proposal/archive.

## Likely Obsolete Or Temporary

Do not delete without explicit confirmation:

- `chechoutupdate.md` - typo in filename and appears to be a temporary checkout update report.
- `create-discriptions-tz.md` - typo in filename and appears to be an old description-generation task/spec.
- `tech.md` - original technical assignment; likely historical, not current implementation source.
- `docs/prodile.md` - typo in filename and very large; likely historical profile/account report.
- `docs/project_work_description.md` - very large academic/project report; keep only if required for reporting.
- The two `.txt` planning files under the conference/attractions static folder - standalone old planning notes for a separate static section.
- The two `.txt` planning files under `invest (sponsor) 2/` - standalone planning notes for an old/static investment section.

## Dangerous To Delete

- `README.md`
- `AGENTS.md`
- `.env.example`
- `requirements.txt`
- `DEPLOY.md`
- `DEPLOY_UPDATE.md`
- `docs/MANAGER_PORTAL.md` and `docs/MANAGER_SIMPLIFICATION.md` - manager portal documentation; do not edit or delete in this cleanup task.
- `legacy/README.md`
- `static/robots.txt`
- `templates/emails/order_event.txt`
- `static/images/ICONS_README.md`
- `static/images/hero/README.md`
- Any migration files, even if they contain explanatory comments.

## References Found

- `deploy/cloud-init.yml` points operators to `DEPLOY.md`.
- `README.md` links to `docs/CITIES_AND_PRODUCTS.md`, `docs/MANAGER_PORTAL.md`, `docs/ORDER_PLACEMENT_AND_ACCOUNT_FLOW.md`, `legacy/README.md`, and `DEPLOY.md`.
- `DEPLOY.md` links to `DEPLOY_UPDATE.md`.
- `DEPLOY_UPDATE.md` links back to `DEPLOY.md`.
- `docs/CATALOG_FILTER_PERFORMANCE_PLAN.md` links to `docs/CATALOG_FILTERS_AUDIT.md`.
- `config/tests.py` intentionally tests that static/standalone routes cannot expose `README.md` through path traversal.
- Several docs contain old absolute links like `/Users/Yaroslav/Documents/dev/BizonVR/...`; these should be converted to relative links during future doc cleanup.

## Recommended Next Cleanup Batch

1. Confirm whether historical report files must be kept for legal, academic, or business reasons.
2. Move historical files to `docs/archive/` instead of deleting immediately.
3. Rename typo files only after checking external references.
4. Merge checkout docs into `docs/ORDER_PLACEMENT_AND_ACCOUNT_FLOW.md`.
5. Replace `docs/DEV_CHEATSHEET.md` with a secret-free index or remove it after confirmation.
6. Convert absolute local links in docs to relative repository links.

## Candidate Delete List After Confirmation

- `chechoutupdate.md`
- `create-discriptions-tz.md`
- `docs/prodile.md`
- `AUDIT_REPORT.md`
- The `.txt` planning file named `Plan` under the conference/attractions static folder.
- `SITE_PLAN.txt` under the conference/attractions static folder.
- The `.txt` structure file under `invest (sponsor) 2/`.
- `invest (sponsor) 2/site_structure_full.txt`

Prefer archiving before deletion for the first cleanup pass.
