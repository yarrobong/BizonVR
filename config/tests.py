from django.urls import reverse

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


class ConferenceAttractionsLandingTests(SimpleTestCase):
    databases = {'default'}

    def _streaming_content(self, response):
        return b''.join(response.streaming_content)

    def test_landing_root_returns_html(self):
        response = self.client.get(reverse('conference_attractions'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/html')
        self.assertIn('VR Аттракционы под ключ', self._streaming_content(response).decode('utf-8'))

    def test_landing_image_asset_is_served(self):
        response = self.client.get('/conference-attractions/%D0%9A%D0%BE%D0%BD%D1%82%D0%B5%D0%BD%D1%82/VARTOneMotion360.png')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')

    def test_landing_video_asset_is_served(self):
        response = self.client.get('/conference-attractions/%D0%9A%D0%BE%D0%BD%D1%82%D0%B5%D0%BD%D1%82/%D0%92%D0%B8%D0%B4%D0%B5%D0%BE/VR%20Bike.mp4')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'video/mp4')

    def test_landing_rejects_path_traversal(self):
        response = self.client.get('/conference-attractions/%2E%2E/README.md')

        self.assertEqual(response.status_code, 404)

    def test_landing_missing_asset_returns_404(self):
        response = self.client.get('/conference-attractions/%D0%9A%D0%BE%D0%BD%D1%82%D0%B5%D0%BD%D1%82/missing.png')

        self.assertEqual(response.status_code, 404)
