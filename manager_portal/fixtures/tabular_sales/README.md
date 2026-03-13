Normalized files for `import_manager_tabular_sales`.

Required files:
- `avito_deals.csv`
- `supply_deals.csv`
- `supply_allocations.csv`
- `product_aliases.json`
- `people_aliases.json`

Notes:
- All dates from the provided Avito dataset are normalized to year `2026`.
- `supply_deals.csv` is committed with headers only. The pasted source for client supply blocks did not contain explicit `order_date` for each deal block, and the importer intentionally rejects supply rows without that field.
- Fill `supply_deals.csv` and `supply_allocations.csv` only after each client block has an explicit normalized date.
