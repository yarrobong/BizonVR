from ._shared import *  # noqa: F401,F403
from .factories import create_category, create_product

class SpamProtectionHelperTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_honeypot_website_blocks(self):
        request = self.factory.post('/contacts/', {'website': 'spam.example'})
        self.assertTrue(is_spam_request(request))

    def test_honeypot_company_site_blocks(self):
        request = self.factory.post('/contacts/', {'company_site': 'spam.example'})
        self.assertTrue(is_spam_request(request))

    def test_fast_submit_blocks(self):
        request = self.factory.post('/contacts/', {'form_started_at': str(int(time.time() * 1000))})
        result = check_spam_submission(request)
        self.assertFalse(result.is_spam)
        self.assertIn('submitted_too_fast', result.reasons)
        self.assertGreaterEqual(result.score, 25)

    def test_searchregister_phrase_blocks_with_reason(self):
        request = self.factory.post('/contacts/', {
            'email': 'domains@search-bizonvr.ru',
            'message': 'Greetings feature bizonvr.ru now: https://searchregister.info',
        })
        result = check_spam_submission(request)
        self.assertTrue(result.is_spam)
        self.assertGreaterEqual(result.score, 100)
        self.assertIn('keyword:searchregister', result.reasons)

    def test_missing_form_started_at_only_increases_score(self):
        request = self.factory.post('/contacts/', {'message': 'Нужна консультация по VR-арене'})
        result = check_spam_submission(request)
        self.assertFalse(result.is_spam)
        self.assertIn('form_started_at_missing', result.reasons)



class RequestScopedCartServicesCacheTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='+79990000000')
        self.category = Category.objects.create(name='Тест', slug='request-cache')
        self.product = Product.objects.create(
            category=self.category,
            name='Quest 3',
            slug='quest-3-request-cache',
            price=100,
            is_active=True,
        )
        CartItem.objects.create(user=self.user, product=self.product, quantity=2)
        Favorite.objects.create(user=self.user, product=self.product)

    def _build_request(self):
        request = self.factory.get('/catalog/')
        request.user = self.user
        request.session = {}
        return request

    def test_get_cart_items_and_count_query_db_once_per_request(self):
        request = self._build_request()

        with self.assertNumQueries(1):
            self.assertEqual(len(get_cart_items(request)), 1)
            self.assertEqual(get_cart_count(request), 2)
            self.assertEqual(get_cart_count(request), 2)

    def test_get_favorite_product_ids_query_db_once_per_request(self):
        request = self._build_request()

        with self.assertNumQueries(1):
            self.assertEqual(get_favorite_product_ids(request), {self.product.pk})
            self.assertEqual(get_favorite_product_ids(request), {self.product.pk})


class CatalogSortLinksEscapingRegressionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.section = CatalogSection.objects.create(name='VR оборудование', slug='sort-escape-vr-oborudovanie')
        cls.category = create_category(
            name='Шлемы',
            slug='sort-escape-vr-headsets',
            section=cls.section,
        )
        cls.tag = ProductTag.objects.create(name='Хит', slug='sort-escape-bestseller')
        cls.product = create_product(
            category=cls.category,
            name='Quest 3',
            slug='sort-escape-quest-3',
            description='VR headset',
            price=100,
            is_active=True,
        )
        cls.product.tags.add(cls.tag)

    def test_mobile_sort_links_escape_query_ampersands(self):
        # Guards against broken sort links when multiple query params are preserved on mobile.
        response = self.client.get(
            reverse('catalog:product_list'),
            {
                'sort': 'newest',
                'section': self.section.slug,
                'category': self.category.slug,
                'tag': self.tag.slug,
                'q': 'Quest',
                'price_min': '50',
                'price_max': '150',
            },
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn(
            'href="?sort=name&amp;section=sort-escape-vr-oborudovanie&amp;category=sort-escape-vr-headsets'
            '&amp;tag=sort-escape-bestseller&amp;q=Quest&amp;price_min=50&amp;price_max=150"',
            html,
        )
        self.assertNotIn(
            'href="?sort=name&category=sort-escape-vr-headsets&section=sort-escape-vr-oborudovanie'
            '&tag=sort-escape-bestseller&q=Quest&price_min=50&price_max=150"',
            html,
        )


class PublicLocationCleanupRegressionTest(TestCase):
    def test_set_city_route_is_removed(self):
        # Guards against resurrecting the removed public city switcher endpoint.
        with self.assertRaises(NoReverseMatch):
            reverse('catalog:set_city')

    def test_public_pages_do_not_render_city_selector(self):
        # Guards against stale city-selector UI appearing on the public shell after cleanup.
        category = Category.objects.create(name='Тест', slug='cleanup-test')
        Product.objects.create(
            category=category,
            name='Товар',
            slug='cleanup-product',
            price=100,
            is_active=True,
        )

        for url in (reverse('home'), reverse('catalog:product_list')):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertNotContains(resp, '/catalog/set-city/')
            self.assertNotContains(resp, 'Все регионы')


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)

class LegalPagesAndLinksTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_legal_pages_return_200_and_oferta_is_not_privacy(self):
        urls = [
            ('privacy', 'Политика конфиденциальности'),
            ('oferta', 'Публичная оферта'),
            ('user_agreement', 'Пользовательское соглашение'),
            ('pd_consent', 'Согласие на обработку персональных данных'),
            ('cookies_policy', 'Политика использования файлов cookies'),
            ('sales_terms', 'Условия оплаты, доставки, возврата и гарантии'),
            ('service_request_terms', 'Условия обработки заявок'),
        ]
        for name, marker in urls:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, msg=name)
            self.assertContains(resp, marker)
            self.assertNotContains(resp, '[УКАЖИТЕ')
            self.assertNotContains(resp, '[ТЕЛЕФОН]')
            self.assertNotContains(resp, 'Заполните placeholders')
        oferta_resp = self.client.get(reverse('oferta'))
        self.assertNotContains(oferta_resp, 'Настоящая политика конфиденциальности определяет')

    def test_cookie_and_privacy_pages_disclose_tracking_services(self):
        for name in ('privacy', 'cookies_policy'):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, msg=name)
            self.assertContains(resp, 'Яндекс.Метрик')
            self.assertContains(resp, 'Calltouch')
            self.assertContains(resp, 'Alfa-Track')

    def test_home_footer_and_cookie_banner_have_legal_links(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('privacy'))
        self.assertContains(resp, reverse('cookies_policy'))
        self.assertContains(resp, reverse('oferta'))



class LegalConsentFormsAndViewsTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_contact_form_is_valid_without_email(self):
        form = ContactForm(data={
            'name': 'Иван',
            'phone': '+7 999 111 22 33',
            'message': 'Тест',
            'agree_personal_data': 'on',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_contact_form_requires_personal_data_consent(self):
        form = ContactForm(data={
            'name': 'Иван',
            'email': 'ivan@example.com',
            'phone': '+7 999 111 22 33',
            'message': 'Тест',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('agree_personal_data', form.errors)

    def test_callback_form_requires_personal_data_consent(self):
        form = CallbackForm(data={
            'name': 'Иван',
            'phone': '+7 999 111 22 33',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('agree_personal_data', form.errors)

    def test_contacts_view_saves_legal_acceptance(self):
        resp = self.client.post(
            reverse('contacts'),
            {
                'name': 'Иван',
                'email': 'ivan@example.com',
                'phone': '+7 (999) 111-22-33',
                'message': 'Нужна консультация',
                'agree_personal_data': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('contacts'))
        req = ContactRequest.objects.first()
        self.assertIsNotNone(req)
        self.assertIsNotNone(req.legal_accepted_at)
        self.assertEqual(req.legal_docs_version, LEGAL_BUNDLE_VERSION)

    @override_settings(CRM_LEADS_EMAIL='crm@example.com')
    def test_contacts_view_sends_crm_email_after_saving_request(self):
        resp = self.client.post(
            reverse('contacts'),
            {
                'name': 'Иван',
                'email': 'ivan@example.com',
                'phone': '+7 999 000-00-00',
                'message': 'Хочу узнать цену на 10 шлемов',
                'agree_personal_data': 'on',
            },
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ContactRequest.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['crm@example.com'])
        self.assertEqual(message.reply_to, ['ivan@example.com'])
        self.assertEqual(message.subject, 'Заявка с сайта BizonVR: +7 999 000-00-00 — Иван')
        self.assertIn('Тип формы: Контакты', message.body)
        self.assertIn('Имя: Иван', message.body)
        self.assertIn('Телефон: +7 999 000-00-00', message.body)
        self.assertIn('Email: ivan@example.com', message.body)
        self.assertIn('Страница: http://testserver/contacts/', message.body)
        self.assertIn('Комментарий:\nХочу узнать цену на 10 шлемов', message.body)

    @override_settings(CRM_LEADS_EMAIL='crm@example.com')
    def test_contacts_view_spam_does_not_send_crm_email(self):
        resp = self.client.post(
            reverse('contacts'),
            {
                'name': 'Иван',
                'email': 'ivan@example.com',
                'phone': '+7 999 000-00-00',
                'message': 'Нужна консультация',
                'agree_personal_data': 'on',
                'website': 'spam.example',
            },
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ContactRequest.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(CRM_LEADS_EMAIL='crm@example.com')
    def test_contacts_crm_email_failure_keeps_success_flow_and_logs(self):
        with (
            patch('config.crm_leads.EmailMessage.send', side_effect=RuntimeError('smtp down')),
            patch('config.crm_leads.logger.exception') as logger_exception,
        ):
            resp = self.client.post(
                reverse('contacts'),
                {
                    'name': 'Иван',
                    'email': 'ivan@example.com',
                    'phone': '+7 999 000-00-00',
                    'message': 'Нужна консультация',
                    'agree_personal_data': 'on',
                },
            )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ContactRequest.objects.count(), 1)
        logger_exception.assert_called_once_with('Failed to send CRM lead email.')

    def test_contacts_view_prefills_message_from_landing_query(self):
        resp = self.client.get(
            reverse('contacts'),
            {
                'name': 'Иван',
                'phone': '+7 (999) 111-22-33',
                'site_context': 'Екатеринбург, ТРЦ',
                'site_comment': 'Нужна консультация по бюджету',
            },
        )
        self.assertEqual(resp.status_code, 200)
        form = resp.context['form']
        self.assertEqual(form['name'].value(), 'Иван')
        self.assertEqual(form['phone'].value(), '+7 (999) 111-22-33')
        self.assertEqual(
            form['message'].value(),
            'Город и тип площадки: Екатеринбург, ТРЦ\n\nКомментарий: Нужна консультация по бюджету',
        )

    def test_contacts_view_prefers_direct_message_query(self):
        resp = self.client.get(
            reverse('contacts'),
            {
                'message': 'Готовое сообщение',
                'site_context': 'Екатеринбург, ТРЦ',
                'site_comment': 'Нужна консультация по бюджету',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['form']['message'].value(), 'Готовое сообщение')

    def test_contacts_view_saves_request_without_email(self):
        resp = self.client.post(
            reverse('contacts'),
            {
                'name': 'Иван',
                'phone': '+7 (999) 111-22-33',
                'message': 'Нужна консультация',
                'agree_personal_data': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('contacts'))
        req = ContactRequest.objects.first()
        self.assertIsNotNone(req)
        self.assertEqual(req.email, '')
        self.assertIsNotNone(req.legal_accepted_at)

    def test_contacts_view_spam_redirects_like_success_without_saving(self):
        resp = self.client.post(
            reverse('contacts'),
            {
                'name': 'Иван',
                'email': 'ivan@example.com',
                'phone': '+7 (999) 111-22-33',
                'message': 'Нужна консультация',
                'agree_personal_data': 'on',
                'website': 'spam.example',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('contacts'))
        self.assertEqual(ContactRequest.objects.count(), 0)

    @override_settings(CRM_LEADS_EMAIL='crm@example.com')
    def test_contacts_view_blocks_searchregister_spam_before_db_and_email(self):
        resp = self.client.post(
            reverse('contacts'),
            {
                'name': 'Craig Gonsalves',
                'email': 'domains@search-bizonvr.ru',
                'phone': '7724029977',
                'message': 'Greetings Feature bizonvr.ru in GoogleSearchIndex: https://searchregister.info',
                'agree_personal_data': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('contacts'))
        self.assertEqual(ContactRequest.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_contacts_view_blocks_searchregister_net_spam(self):
        resp = self.client.post(
            reverse('contacts'),
            {
                'name': 'Nannette Cadman',
                'email': 'domains@search-bizonvr.ru',
                'phone': '7954273189',
                'message': 'Dear Sir/Madam Enlist bizonvr.ru in GoogleSearchIndex: https://searchregister.net',
                'agree_personal_data': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ContactRequest.objects.count(), 0)

    def test_contacts_view_blocks_google_search_index_phrase(self):
        resp = self.client.post(
            reverse('contacts'),
            {
                'name': 'Spam Bot',
                'email': 'bot@example.com',
                'phone': '+7 999 111-22-33',
                'message': 'Please add feature bizonvr.ru to Google Search Index for better online search results',
                'agree_personal_data': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ContactRequest.objects.count(), 0)



class PublicLeadFormsSpamProtectionTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_arenda_callback_spam_redirects_without_creating_request(self):
        resp = self.client.post(
            reverse('arenda'),
            {
                'form_type': 'callback',
                'name': 'Иван',
                'phone': '+7 (999) 111-22-33',
                'agree_personal_data': 'on',
                'website': 'spam.example',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].endswith(reverse('arenda') + '#contacts'))
        self.assertEqual(CallbackRequest.objects.count(), 0)

    @override_settings(CRM_LEADS_EMAIL='crm@example.com')
    def test_arenda_callback_sends_crm_email(self):
        resp = self.client.post(
            reverse('arenda'),
            {
                'form_type': 'callback',
                'name': 'Иван',
                'phone': '+7 (999) 111-22-33',
                'agree_personal_data': 'on',
            },
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(CallbackRequest.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Тип формы: Аренда', mail.outbox[0].body)
        self.assertIn('Товар/услуга: Аренда VR-шлемов', mail.outbox[0].body)

    def test_compact_vr_spam_redirects_without_creating_request(self):
        resp = self.client.post(
            reverse('compact_vr'),
            {
                'form_type': 'compact_vr',
                'name': 'Иван',
                'contact': '+7 (999) 111-22-33',
                'city': 'Екатеринбург',
                'format': 'Core',
                'email': 'ivan@example.com',
                'premises': '',
                'comment': 'Хочу обсудить запуск',
                'agree_personal_data': 'on',
                'website': 'spam.example',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].endswith(reverse('compact_vr') + '#contact'))
        self.assertEqual(ContactRequest.objects.count(), 0)

    @override_settings(CRM_LEADS_EMAIL='crm@example.com')
    def test_compact_vr_sends_crm_email(self):
        resp = self.client.post(
            reverse('compact_vr'),
            {
                'form_type': 'compact_vr',
                'name': 'Иван',
                'contact': '+7 (999) 111-22-33',
                'city': 'Екатеринбург',
                'format': 'Core',
                'email': 'ivan@example.com',
                'premises': '80 м2',
                'comment': 'Хочу обсудить запуск',
                'agree_personal_data': 'on',
            },
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ContactRequest.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, ['ivan@example.com'])
        self.assertIn('Тип формы: Compact VR', mail.outbox[0].body)
        self.assertIn('Город: Екатеринбург', mail.outbox[0].body)
        self.assertIn('Товар/услуга: Компактная VR-арена (Core)', mail.outbox[0].body)
