from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from config.views.static_pages import not_found_view


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)
class CompactVRRegressionTests(TestCase):
    def test_legacy_compact_vr_asset_path_returns_404(self):
        # Guards against bringing back stale PNG asset routes after the static image move.
        response = self.client.get('/compact-vr/img/katvrplayer.png')

        self.assertEqual(response.status_code, 404)

    def test_home_page_compact_vr_slide_uses_static_asset_url(self):
        # Guards against homepage slides linking to removed landing-local media paths.
        response = self.client.get(reverse('home'))
        html = response.content.decode('utf-8')

        self.assertNotIn('/static/images/compact-vr-v3/katvrplayer.png', html)
        self.assertNotIn('/compact-vr/img/katvrplayer.png', html)

    def test_compact_vr_script_reacts_to_threshold_events_instead_of_global_scroll_listener(self):
        # Guards against reintroducing the expensive global scroll listener in the landing script.
        script = (settings.BASE_DIR / 'static/js/compact-vr-v3.js').read_text(encoding='utf-8')

        self.assertIn('layout-scroll-threshold', script)
        self.assertNotIn('window.addEventListener("scroll"', script)


class PublicSiteTrackerRegressionTests(TestCase):
    def test_home_layout_uses_shared_threshold_observer_for_sticky_header(self):
        # Guards against Alpine scroll handlers returning after the shared observer refactor.
        response = self.client.get(reverse('home'))
        html = response.content.decode('utf-8')

        self.assertIn('observeElementViewportState(mainHeader, syncLayoutHeaderVisibility)', html)
        self.assertIn("window.dispatchEvent(new CustomEvent('layout-scroll-threshold'", html)
        self.assertNotIn('@scroll.window.passive.throttle.50ms=', html)

    def test_home_mobile_header_uses_threshold_observer_for_fixed_search(self):
        # Guards against mobile search regressions that depended on throttled window scroll hooks.
        response = self.client.get(reverse('home'))
        html = response.content.decode('utf-8')

        self.assertIn('observePageThreshold(100, syncFixedSearch)', html)
        self.assertNotIn("window.addEventListener('scroll', throttled", html)

    def test_error_page_disables_webvisor_outside_public_funnel(self):
        # Guards against enabling Webvisor for error pages outside the intended public funnel prefixes.
        request = RequestFactory().get('/missing-page/')
        request.user = AnonymousUser()
        request.session = {}
        response = not_found_view(request, unmatched_path='missing-page/')
        html = response.content.decode('utf-8')

        self.assertIn('webvisorAllowedPrefixes', html)
        self.assertIn('webvisor: shouldEnableWebvisor(w.location && w.location.pathname)', html)
        self.assertNotIn('webvisor: true', html)
