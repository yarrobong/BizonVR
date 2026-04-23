from django.urls import reverse

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import override_settings

from config.views.static_pages import not_found_view
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

    def test_landing_contains_working_contact_form_redirect(self):
        response = self.client.get(reverse('conference_attractions'))
        html = self._streaming_content(response).decode('utf-8')

        self.assertIn('<form method="get" action="/contacts/">', html)
        self.assertIn('name="name"', html)
        self.assertIn('name="phone"', html)
        self.assertIn('name="site_context"', html)
        self.assertIn('name="site_comment"', html)

    def test_landing_contact_links_are_not_placeholders(self):
        response = self.client.get(reverse('conference_attractions'))
        html = self._streaming_content(response).decode('utf-8')

        self.assertIn('https://wa.me/79931033610', html)
        self.assertIn('https://t.me/bizon_order_manager', html)
        self.assertIn('tel:+79931033610', html)
        self.assertIn('+7 (993) 103-36-10', html)
        self.assertNotIn('href="#">WhatsApp</a>', html)
        self.assertNotIn('href="#">Telegram</a>', html)
        self.assertNotIn('tel:+70000000000', html)


class InvestLandingTests(SimpleTestCase):
    databases = {'default'}

    def _streaming_content(self, response):
        return b''.join(response.streaming_content)

    def test_landing_root_returns_html(self):
        response = self.client.get(reverse('invest'))
        html = self._streaming_content(response).decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/html')
        self.assertIn('Компактная VR-арена Bizon', html)
        self.assertIn('https://bizonvr.ru', html)
        self.assertIn('noindex, nofollow', html)
        self.assertNotIn('../img/', html)
        self.assertNotIn('../invest/index.html', html)

    def test_landing_css_asset_is_served(self):
        response = self.client.get('/invest/styles.css')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/css')

    def test_landing_script_asset_is_served(self):
        response = self.client.get('/invest/script.js')

        self.assertEqual(response.status_code, 200)
        self.assertIn('javascript', response['Content-Type'])

    def test_landing_image_asset_is_served(self):
        response = self.client.get('/invest/1.jpg')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')

    def test_landing_rejects_path_traversal(self):
        response = self.client.get('/invest/%2E%2E/README.md')

        self.assertEqual(response.status_code, 404)


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)
class CompactVRLandingTests(TestCase):
    def test_compact_vr_page_returns_200(self):
        response = self.client.get(reverse('compact_vr'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Компактная VR-арена')

    def test_legacy_compact_vr_asset_path_returns_404(self):
        response = self.client.get('/compact-vr/img/katvrplayer.png')

        self.assertEqual(response.status_code, 404)

    def test_home_page_compact_vr_slide_uses_static_asset_url(self):
        response = self.client.get(reverse('home'))
        html = response.content.decode('utf-8')

        self.assertIn('/static/images/compact-vr-v3/katvrplayer.png', html)
        self.assertNotIn('/compact-vr/img/katvrplayer.png', html)


class PublicSiteMetrikaTemplateTests(TestCase):
    def test_home_page_includes_yandex_metrika_counter(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'https://mc.yandex.ru/metrika/tag.js?id=108292006', html=False)
        self.assertContains(response, 'https://mc.yandex.ru/watch/108292006', html=False)

    def test_custom_404_page_includes_yandex_metrika_counter(self):
        request = RequestFactory().get('/missing-page/')
        request.user = AnonymousUser()
        request.session = {}
        response = not_found_view(request, unmatched_path='missing-page/')

        self.assertEqual(response.status_code, 404)
        self.assertIn('https://mc.yandex.ru/metrika/tag.js?id=108292006', response.content.decode('utf-8'))
