# Legacy Archive

`legacy` stores archived data sources that are kept only for one-way import into BizonVR's active PostgreSQL database.

Current archived sources:

- `BusinessFinance` — former finance runtime, now replaced by `manager_portal` finance models and views.
- `docuflow (2)` — former contracts/documents runtime, now replaced by `manager_portal` contract models and views.
- `db.sqlite3` — former site SQLite snapshot, used only as an import source.

Rules:

- Do not run anything from `legacy` as an active service.
- Do not add Django DB aliases for legacy sources.
- Do not treat legacy data as the source of truth when it conflicts with current PostgreSQL data.
- Import legacy data only through management commands in `manager_portal`:
  - `manage.py import_legacy_docuflow`
  - `manage.py import_legacy_business_finance`
  - `manage.py import_legacy_site_sqlite`
  - `manage.py check_single_db_contract`
