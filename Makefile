# BizonVR — локальная разработка и обслуживание
# Однократно: createdb bizon && cp .env.example .env
# Затем: make install-local && make migrate-local && make run-local

PY = .venv/bin/python
PIP = .venv/bin/pip
TEST_SETTINGS_MODULE = config.settings_test
TEST_MANAGE = DJANGO_SETTINGS_MODULE=$(TEST_SETTINGS_MODULE) $(PY) manage.py

.PHONY: install install-local migrate migrate-local run run-local load-data load-data-local
.PHONY: load-data-clear load-data-clear-local shell superuser superuser-local collectstatic clear-cache check-single-db test test-shop test-manager test-manager-smoke
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
	$(TEST_MANAGE) test config catalog orders accounts payments manager_portal --keepdb --noinput

test-shop:
	$(TEST_MANAGE) test config catalog orders accounts payments --keepdb --noinput

test-manager:
	$(TEST_MANAGE) test manager_portal --keepdb --noinput

test-manager-smoke:
	$(TEST_MANAGE) test \
		manager_portal.tests.ManagerPortalAccessTests.test_staff_entry_shows_internal_modules \
		manager_portal.tests.ManagerPortalServiceTests.test_website_workflow_creates_client_deal_and_variant_aware_reservation \
		manager_portal.tests.ManagerPortalViewTests.test_deal_list_overview_separates_kpis_queues_and_signals \
		manager_portal.test_legacy_imports.LegacyImportCommandTests.test_single_db_contract_helper_passes_for_archived_layout \
		--keepdb --noinput

# Менеджерский портал: очистка и тестовые данные
clear-manager-data:
	$(PY) manage.py clear_manager_data --confirm

seed-manager-test-deal:
	$(PY) manage.py seed_manager_test_deal
