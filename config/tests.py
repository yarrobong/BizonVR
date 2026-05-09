from pathlib import Path
from tempfile import TemporaryDirectory

from django.urls import reverse

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import override_settings

from config.views.static_pages import not_found_view, serve_media
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
        self.assertIn('Компактная VR-арена', html)
        self.assertIn('Получить модель', html)
        self.assertIn('href="#investment"', html)
        self.assertNotIn('/invest-2/', html)
        self.assertNotIn('../img/', html)

    def test_new_landing_alias_returns_same_html(self):
        canonical_response = self.client.get(reverse('invest'))
        alias_response = self.client.get(reverse('invest_2'))
        canonical_html = self._streaming_content(canonical_response).decode('utf-8')
        alias_html = self._streaming_content(alias_response).decode('utf-8')

        self.assertEqual(alias_response.status_code, 200)
        self.assertEqual(alias_response['Content-Type'], 'text/html')
        self.assertEqual(alias_html, canonical_html)

    def test_landing_css_asset_is_served(self):
        response = self.client.get('/invest/styles.css')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/css')

    def test_new_landing_alias_serves_assets(self):
        response = self.client.get('/invest-2/styles.css')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/css')

    def test_new_landing_alias_video_asset_is_served(self):
        response = self.client.get('/invest-2/HOW%20TO%20WALK%20ON%20KAT%20Walk%20C2%20%5Bget.gt%5D.mp4')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'video/mp4')

    def test_new_landing_route_returns_invest_2_html(self):
        response = self.client.get(reverse('invest_2_new'))
        html = self._streaming_content(response).decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/html')
        self.assertIn('Инвестиции в компактную VR-арену BIZON', html)
        self.assertIn('class="topbar-menu-toggle"', html)
        self.assertIn('aria-controls="topbarMenuPanel"', html)
        self.assertIn('data-mobile-cards="growth-plan"', html)
        self.assertIn('href="#risks"', html)
        self.assertIn('Риски и защита инвестора', html)

    def test_new_landing_route_serves_css_asset(self):
        response = self.client.get('/invest-2-new/styles.css')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/css')

    def test_new_landing_route_serves_script_asset(self):
        response = self.client.get('/invest-2-new/script.js')

        self.assertEqual(response.status_code, 200)
        self.assertIn('javascript', response['Content-Type'])

    def test_new_landing_route_serves_image_asset(self):
        response = self.client.get('/invest-2-new/1.jpg')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')

    def test_landing_script_asset_is_served(self):
        response = self.client.get('/invest/script.js')

        self.assertEqual(response.status_code, 200)
        self.assertIn('javascript', response['Content-Type'])

    def test_landing_video_asset_is_served(self):
        response = self.client.get('/invest/HOW%20TO%20WALK%20ON%20KAT%20Walk%20C2%20%5Bget.gt%5D.mp4')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'video/mp4')

    def test_landing_rejects_path_traversal(self):
        response = self.client.get('/invest/%2E%2E/README.md')

        self.assertEqual(response.status_code, 404)

    def test_new_landing_route_rejects_path_traversal(self):
        response = self.client.get('/invest-2-new/%2E%2E/README.md')

        self.assertEqual(response.status_code, 404)


class SolutionLandingTests(SimpleTestCase):
    databases = {'default'}

    def _streaming_content(self, response):
        return b''.join(response.streaming_content)

    def test_solutions_index_returns_only_published_landings(self):
        response = self.client.get(reverse('solutions_index'))
        html = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn('VR для клуба', html)

    def test_vr_club_solution_landing_root_returns_html(self):
        response = self.client.get(reverse('solution_landing', kwargs={'slug': 'vr-dlya-kluba'}))
        html = self._streaming_content(response).decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/html')
        self.assertIn('VR для клуба: оборудование, аксессуары и контент под коммерческую зону', html)
        self.assertIn('action="/contacts/"', html)
        self.assertIn('name="site_context"', html)
        self.assertIn('name="site_comment"', html)
        self.assertIn('info@bizon-business.ru', html)
        self.assertIn('https://bizonvr.ru/solutions/vr-dlya-kluba/', html)
        self.assertIn('img/games/Lasertag/Lasertag for Meta Quest - v2 update trailer [get.gt].mp4', html)
        self.assertIn(
            'data-trailer="img/trailers/Online/Pavlov Shack/Pavlov_Shack_｜_Launch_Trailer_｜_Meta_Quest_Platform_Meta_Quest_1080p.mp4"',
            html,
        )
        self.assertIn(
            'data-trailer="img/trailers/Online/Zero Caliber 2/Zero_Caliber_2_｜_Gameplay_Trailer_｜_Meta_Quest_2_+_Meta_Quest_3.mp4"',
            html,
        )
        self.assertIn(
            'data-trailer="img/trailers/Online/Warhammer 40,000 Battle Sister/Warhammer_40,000：_Battle_Sister_Official_Steam_Release_Trailer_IGN.mp4"',
            html,
        )

    def test_vr_club_solution_landing_css_asset_is_served(self):
        response = self.client.get('/solutions/vr-dlya-kluba/styles.css')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/css')

    def test_vr_club_solution_landing_image_asset_is_served(self):
        response = self.client.get('/solutions/vr-dlya-kluba/img/pico-4-ultra.webp')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/webp')

    def test_vr_club_solution_landing_online_trailer_assets_are_served(self):
        simple_response = self.client.get(
            '/solutions/vr-dlya-kluba/img/trailers/Online/Pavlov%20Shack/'
            'Pavlov_Shack_%EF%BD%9C_Launch_Trailer_%EF%BD%9C_Meta_Quest_Platform_Meta_Quest_1080p.mp4'
        )
        unicode_response = self.client.get(
            '/solutions/vr-dlya-kluba/img/trailers/Online/Warhammer%2040%2C000%20Battle%20Sister/'
            'Warhammer_40%2C000%EF%BC%9A_Battle_Sister_Official_Steam_Release_Trailer_IGN.mp4'
        )
        zero_caliber_response = self.client.get(
            '/solutions/vr-dlya-kluba/img/trailers/Online/Zero%20Caliber%202/'
            'Zero_Caliber_2_%EF%BD%9C_Gameplay_Trailer_%EF%BD%9C_Meta_Quest_2_%2B_Meta_Quest_3.mp4'
        )

        self.assertEqual(simple_response.status_code, 200)
        self.assertEqual(simple_response['Content-Type'], 'video/mp4')
        self.assertEqual(unicode_response.status_code, 200)
        self.assertEqual(unicode_response['Content-Type'], 'video/mp4')
        self.assertEqual(zero_caliber_response.status_code, 200)
        self.assertEqual(zero_caliber_response['Content-Type'], 'video/mp4')

    def test_vr_club_solution_landing_boosted_request_forces_full_redirect(self):
        response = self.client.get(
            reverse('solution_landing', kwargs={'slug': 'vr-dlya-kluba'}),
            HTTP_HX_REQUEST='true',
            HTTP_HX_BOOSTED='true',
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['HX-Redirect'], reverse('solution_landing', kwargs={'slug': 'vr-dlya-kluba'}))

    def test_vr_club_solution_landing_js_asset_is_served(self):
        response = self.client.get('/solutions/vr-dlya-kluba/script.js')

        self.assertEqual(response.status_code, 200)
        self.assertIn('javascript', response['Content-Type'])

    def test_solution_landing_unknown_slug_returns_404(self):
        response = self.client.get('/solutions/missing-solution/')

        self.assertEqual(response.status_code, 404)

    def test_vr_club_solution_landing_rejects_path_traversal(self):
        response = self.client.get('/solutions/vr-dlya-kluba/%2E%2E/README.md')

        self.assertEqual(response.status_code, 404)

    def test_sitemap_contains_solutions_hub_and_published_landing(self):
        response = self.client.get('/sitemap.xml')
        body = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn('/solutions/', body)
        self.assertIn('/solutions/vr-dlya-kluba/', body)
        self.assertNotIn('/solutions/vr-dlya-kluba-draft/', body)


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
        self.assertContains(response, '/static/images/compact-vr-v3/1.webp')
        self.assertContains(response, '/static/images/compact-vr-v3/katvrplayer.webp')
        self.assertContains(response, 'loading="lazy"', html=False)
        self.assertContains(response, 'decoding="async"', html=False)
        self.assertContains(response, 'width="1536" height="1024"', html=False)
        self.assertNotContains(response, '/static/images/compact-vr-v3/1.png')
        self.assertNotContains(response, '/static/images/compact-vr-v3/katvrplayer.png')

    def test_compact_vr_boosted_request_forces_full_redirect(self):
        response = self.client.get(
            reverse('compact_vr'),
            HTTP_HX_REQUEST='true',
            HTTP_HX_BOOSTED='true',
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['HX-Redirect'], reverse('compact_vr'))

    def test_legacy_compact_vr_asset_path_returns_404(self):
        response = self.client.get('/compact-vr/img/katvrplayer.png')

        self.assertEqual(response.status_code, 404)

    def test_home_page_compact_vr_slide_uses_static_asset_url(self):
        response = self.client.get(reverse('home'))
        html = response.content.decode('utf-8')

        self.assertNotIn('/static/images/compact-vr-v3/katvrplayer.png', html)
        self.assertNotIn('/compact-vr/img/katvrplayer.png', html)

    def test_compact_vr_script_reacts_to_threshold_events_instead_of_global_scroll_listener(self):
        script_path = settings.BASE_DIR / 'static/js/compact-vr-v3.js'
        script = script_path.read_text(encoding='utf-8')

        self.assertIn('layout-scroll-threshold', script)
        self.assertNotIn('window.addEventListener("scroll"', script)


class PublicSiteMetrikaTemplateTests(TestCase):
    def test_home_layout_uses_shared_threshold_observer_for_sticky_header(self):
        response = self.client.get(reverse('home'))
        html = response.content.decode('utf-8')

        self.assertIn('observePageThreshold(180, syncLayoutScrollThreshold)', html)
        self.assertNotIn('@scroll.window.passive.throttle.50ms=', html)

    def test_home_mobile_header_uses_threshold_observer_for_fixed_search(self):
        response = self.client.get(reverse('home'))
        html = response.content.decode('utf-8')

        self.assertIn('observePageThreshold(100, syncFixedSearch)', html)
        self.assertNotIn("window.addEventListener('scroll', throttled", html)

    def test_home_page_includes_yandex_metrika_counter(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'https://mc.yandex.ru/metrika/tag.js?id=', html=False)
        self.assertContains(response, "requestIdleCallback", html=False)
        self.assertContains(response, "BizonVRTrackerLoader", html=False)
        self.assertContains(response, "var isHeavyCatalogPage = false;", html=False)
        self.assertContains(response, "addEventListener('DOMContentLoaded', scheduleMetrika, {once: true})", html=False)
        self.assertContains(response, 'https://mc.yandex.ru/watch/108292006', html=False)
        self.assertContains(response, 'https://mod.calltouch.ru/', html=False)
        self.assertNotContains(response, 'https://cloud.emailtracking.ru/gtm/script.js', html=False)
        self.assertNotContains(response, 'https://cloud.alfa-track.com/gtm/script.js', html=False)
        self.assertNotContains(response, 'tryLoadMirror(0)', html=False)
        self.assertNotContains(response, 'mirrors.forEach(', html=False)

    def test_catalog_page_defers_public_trackers_more_aggressively(self):
        response = self.client.get(reverse('catalog:product_list'))

        self.assertContains(response, "var isHeavyCatalogPage = true;", html=False)
        self.assertContains(response, 'w.setTimeout(run, isHeavyCatalogPage ? 15000 : 8000);', html=False)
        self.assertContains(
            response,
            'idleTimeout: isHeavyCatalogPage ? 9000 : 5000,',
            html=False,
        )
        self.assertContains(
            response,
            'delay: isHeavyCatalogPage ? 3200 : 900',
            html=False,
        )

    @override_settings(ENABLE_ALFATRACK=True)
    def test_home_page_includes_alfatrack_when_enabled(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'https://cloud.emailtracking.ru/gtm/script.js', html=False)
        self.assertContains(response, 'https://cloud.alfa-track.com/gtm/script.js', html=False)
        self.assertContains(response, 'tryLoadMirror(0)', html=False)

    def test_custom_404_page_includes_yandex_metrika_counter(self):
        request = RequestFactory().get('/missing-page/')
        request.user = AnonymousUser()
        request.session = {}
        response = not_found_view(request, unmatched_path='missing-page/')

        self.assertEqual(response.status_code, 404)
        self.assertIn('https://mc.yandex.ru/metrika/tag.js?id=', response.content.decode('utf-8'))
        self.assertIn("requestIdleCallback", response.content.decode('utf-8'))
        self.assertIn("BizonVRTrackerLoader", response.content.decode('utf-8'))

    def test_error_page_disables_webvisor_outside_public_funnel(self):
        request = RequestFactory().get('/missing-page/')
        request.user = AnonymousUser()
        request.session = {}
        response = not_found_view(request, unmatched_path='missing-page/')
        html = response.content.decode('utf-8')

        self.assertIn('webvisorAllowedPrefixes', html)
        self.assertIn('webvisor: shouldEnableWebvisor(w.location && w.location.pathname)', html)
        self.assertNotIn('webvisor: true', html)


class PublicMediaCacheHeadersTests(SimpleTestCase):
    def test_responsive_media_uses_immutable_cache_header(self):
        with TemporaryDirectory() as temp_media_root:
            target = Path(temp_media_root) / 'cache' / 'responsive' / 'hero.webp'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'fake-webp')

            with override_settings(MEDIA_ROOT=temp_media_root):
                response = serve_media(RequestFactory().get('/media/cache/responsive/hero.webp'), 'cache/responsive/hero.webp')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'public, max-age=31536000, immutable')

    def test_regular_media_uses_long_but_mutable_cache_header(self):
        with TemporaryDirectory() as temp_media_root:
            target = Path(temp_media_root) / 'products' / 'hero.png'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'fake-png')

            with override_settings(MEDIA_ROOT=temp_media_root):
                response = serve_media(RequestFactory().get('/media/products/hero.png'), 'products/hero.png')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'public, max-age=2592000')

    def test_non_media_binary_falls_back_to_short_cache_header(self):
        with TemporaryDirectory() as temp_media_root:
            target = Path(temp_media_root) / 'docs' / 'price-list.bin'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'fake-bin')

            with override_settings(MEDIA_ROOT=temp_media_root):
                response = serve_media(RequestFactory().get('/media/docs/price-list.bin'), 'docs/price-list.bin')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'public, max-age=300')
