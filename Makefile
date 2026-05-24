# BizonVR — локальная разработка и обслуживание
# Однократно: createdb bizon && cp .env.example .env
# Затем: make install-local && make migrate-local && make run-local

PY = .venv/bin/python
PIP = .venv/bin/pip
TEST_SETTINGS_MODULE = config.settings_test
TEST_MANAGE = DJANGO_SETTINGS_MODULE=$(TEST_SETTINGS_MODULE) $(PY) manage.py
TEST_FLAGS = --keepdb --noinput
TEST_PARALLEL_FLAGS = --parallel auto
TEST_PUBLIC_APPS = config catalog orders accounts payments
TEST_ALL_APPS = $(TEST_PUBLIC_APPS) manager_portal

.PHONY: install install-local migrate migrate-local run run-local load-data load-data-local
.PHONY: load-data-clear load-data-clear-local shell superuser superuser-local collectstatic clear-cache check-single-db
.PHONY: test test-fast test-shop test-catalog test-orders test-accounts test-config test-payments test-manager test-slow test-manager-smoke
.PHONY: clear-manager-data seed-manager-test-deal
.DEFAULT_GOAL := run-local

install: install-local

install-local:
	python3 -m venv .venv
	$(PIP) install -r requirements.txt
	npm install

migrate: migrate-local

migrate-local:
	$(PY) manage.py migrate

run: run-local

run-local:
	@[ -f static/css/tailwind.css ] || (npm run build:css || true)
	$(PY) manage.py runserver

load-data: load-data-local

load-data-local:
	$(PY) manage.py load_catalog_data

load-data-clear: load-data-clear-local

load-data-clear-local:
	$(PY) manage.py load_catalog_data --clear

superuser: superuser-local

superuser-local:
	$(PY) manage.py createsuperuser

shell:
	$(PY) manage.py shell

collectstatic:
	$(PY) manage.py collectstatic --noinput

clear-cache:
	$(PY) manage.py clear_catalog_cache

check-single-db:
	$(PY) scripts/check_single_db_contract.py

test:
	$(TEST_MANAGE) test $(TEST_ALL_APPS) $(TEST_FLAGS)

test-fast:
	$(TEST_MANAGE) test $(TEST_PUBLIC_APPS) $(TEST_FLAGS) $(TEST_PARALLEL_FLAGS) --exclude-tag=slow

test-shop:
	$(TEST_MANAGE) test $(TEST_PUBLIC_APPS) $(TEST_FLAGS)

test-catalog:
	$(TEST_MANAGE) test catalog $(TEST_FLAGS) $(TEST_PARALLEL_FLAGS)

test-orders:
	$(TEST_MANAGE) test orders $(TEST_FLAGS) $(TEST_PARALLEL_FLAGS)

test-accounts:
	$(TEST_MANAGE) test accounts $(TEST_FLAGS) $(TEST_PARALLEL_FLAGS)

test-config:
	$(TEST_MANAGE) test config $(TEST_FLAGS) $(TEST_PARALLEL_FLAGS)

test-payments:
	$(TEST_MANAGE) test payments $(TEST_FLAGS) $(TEST_PARALLEL_FLAGS)

test-manager:
	$(TEST_MANAGE) test manager_portal $(TEST_FLAGS) $(TEST_PARALLEL_FLAGS)

test-slow:
	$(TEST_MANAGE) test $(TEST_ALL_APPS) $(TEST_FLAGS) --tag=slow

test-manager-smoke:
	$(TEST_MANAGE) test \
		manager_portal.tests.ManagerPortalAccessTests.test_staff_entry_shows_internal_modules \
		manager_portal.tests.ManagerPortalServiceTests.test_website_workflow_creates_client_deal_and_variant_aware_reservation \
		manager_portal.tests.ManagerPortalViewTests.test_deal_list_overview_separates_kpis_queues_and_signals \
		manager_portal.test_legacy_imports.LegacyImportCommandTests.test_single_db_contract_helper_passes_for_archived_layout \
		$(TEST_FLAGS)

# Менеджерский портал: очистка и тестовые данные
clear-manager-data:
	$(PY) manage.py clear_manager_data --confirm

seed-manager-test-deal:
	$(PY) manage.py seed_manager_test_deal
