from django.conf import settings
from django.test import SimpleTestCase

from manager_portal.single_db_contract import collect_single_db_contract_violations


class SingleDatabaseContractTests(SimpleTestCase):
    def test_only_default_postgresql_database_is_configured(self):
        self.assertEqual(sorted(settings.DATABASES.keys()), ['default'])
        self.assertIn('postgresql', settings.DATABASES['default']['ENGINE'].lower())
        self.assertFalse(getattr(settings, 'DATABASE_ROUTERS', []))

    def test_repo_single_db_contract_has_no_violations(self):
        self.assertEqual(collect_single_db_contract_violations(), [])
