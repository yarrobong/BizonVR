from ._shared import *  # noqa: F401,F403
from accounts.tests.factories import create_user
from catalog.cart_services import build_cart_item_share_key
from .factories import create_category, create_product
from integrations.models import SiteLeadRequest

class CatalogSearchTest(TestCase):
    """Поиск по товарам (параметр q=)."""

    @classmethod
    def setUpTestData(cls):
        category = create_category(name='Тест', slug='test')
        create_product(
            category=category,
            name='VR Шлем Meta',
            slug='vr-meta',
            description='Шлем виртуальной реальности',
            price=100,
            is_active=True,
        )
        create_product(
            category=category,
            name='Клавиатура',
            slug='keyboard',
            description='Игровая клавиатура',
            price=50,
            is_active=True,
        )

    def test_search_by_name(self):
        resp = self.client.get(reverse('catalog:product_list'), {'q': 'VR'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('search_query', resp.context)
        self.assertEqual(resp.context['search_query'], 'VR')
        self.assertEqual(len(resp.context['products']), 1)
        self.assertEqual(resp.context['products'][0].name, 'VR Шлем Meta')

    def test_search_by_description(self):
        resp = self.client.get(reverse('catalog:product_list'), {'q': 'виртуальной'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['products']), 1)

    def test_search_empty_returns_all(self):
        resp = self.client.get(reverse('catalog:product_list'), {'q': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['products']), 2)

    def test_product_list_uses_shared_catalog_runtime_without_extra_page_script(self):
        resp = self.client.get(reverse('catalog:product_list'))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'x-data="catalogProductList()"', html=False)
        self.assertNotContains(resp, "js/catalog/product_list.js", html=False)

    def test_product_list_htmx_response_omits_global_layout_shell(self):
        resp = self.client.get(
            reverse('catalog:product_list'),
            HTTP_HX_REQUEST='true',
            HTTP_HX_BOOSTED='true',
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '<title>Каталог — BizonVR</title>', html=False)
        self.assertContains(resp, 'id="htmx-active-section"', html=False)
        self.assertContains(resp, 'id="mobile-header-slot"', html=False)
        self.assertContains(resp, 'id="main-content"', html=False)
        self.assertNotContains(resp, '<html', html=False)
        self.assertNotContains(resp, 'id="main-body"', html=False)
        self.assertNotContains(resp, 'id="sticky-header"', html=False)
        self.assertNotContains(resp, 'id="catalog-overlay"', html=False)
        self.assertNotContains(resp, 'class="vr-footer"', html=False)
        self.assertNotContains(resp, 'id="cookie-consent-banner"', html=False)
        self.assertNotContains(resp, 'class="mobile-dock"', html=False)
        self.assertNotContains(resp, 'id="footer-products-feed"', html=False)



class CatalogSearchSuggestTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.suggest_url = reverse('catalog:search_suggest')
        cls.category = create_category(name='Шлемы', slug='headsets')
        cls.bundle_category = create_category(
            name='Комплекты',
            slug='bundles',
            is_bundles_category=True,
        )
        cls.city = City.objects.create(name='Екатеринбург', slug='ekaterinburg')
        cls.pickup_point = PickupPoint.objects.create(city=cls.city, name='Основной склад')

        cls.product_by_name = create_product(
            category=cls.category,
            name='Quest 3 Pro',
            slug='quest-3-pro',
            description='Флагманский VR шлем',
            price=100,
            is_active=True,
        )
        ProductStock.objects.create(
            product=cls.product_by_name,
            pickup_point=cls.pickup_point,
            quantity=4,
        )

        cls.product_by_description = create_product(
            category=cls.category,
            name='Pico Ultra',
            slug='pico-ultra',
            description='Квестовый VR шлем для аркад',
            price=90,
            is_active=True,
        )
        ProductStock.objects.create(
            product=cls.product_by_description,
            pickup_point=cls.pickup_point,
            quantity=2,
        )

        cls.variant_product = create_product(
            category=cls.category,
            name='Meta Quest Carry',
            slug='meta-quest-carry',
            description='Товар с вариантами',
            price=120,
            is_active=True,
        )
        cls.variant = ProductVariant.objects.create(
            product=cls.variant_product,
            name='256 GB',
            sku='Q3-256',
        )
        ProductStock.objects.create(
            product=cls.variant_product,
            pickup_point=cls.pickup_point,
            variant=cls.variant,
            quantity=1,
        )

        cls.bundle_helper_product = create_product(
            category=cls.category,
            name='Titan Stand',
            slug='titan-stand',
            description='Стойка для VR',
            price=55,
            is_active=True,
        )
        ProductStock.objects.create(
            product=cls.bundle_helper_product,
            pickup_point=cls.pickup_point,
            quantity=3,
        )

        cls.bundle = ProductBundle.objects.create(
            category=cls.bundle_category,
            name='Аркадный комплект',
            slug='arcade-bundle',
        )
        ProductBundleItem.objects.create(bundle=cls.bundle, product=cls.product_by_name, quantity=1)
        ProductBundleItem.objects.create(bundle=cls.bundle, product=cls.bundle_helper_product, quantity=1)

        cls.inactive_product = create_product(
            category=cls.category,
            name='Ghost Quest',
            slug='ghost-quest',
            description='Скрытый товар',
            price=70,
            is_active=False,
        )

        for index in range(4):
            product = create_product(
                category=cls.category,
                name=f'Neo Limit {index}',
                slug=f'neo-limit-{index}',
                description='Тест лимита',
                price=80 + index,
                is_active=True,
            )
            ProductStock.objects.create(
                product=product,
                pickup_point=cls.pickup_point,
                quantity=1,
            )

    def setUp(self):
        self.suggest_url = reverse('catalog:search_suggest')

    def test_short_query_returns_empty_groups(self):
        response = self.client.get(self.suggest_url, {'q': 'Q'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'query': 'Q',
                'groups': {
                    'products': [],
                    'bundles': [],
                    'variants': [],
                },
                'has_results': False,
            },
        )

    def test_finds_product_by_name(self):
        response = self.client.get(self.suggest_url, {'q': 'Quest 3'})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['has_results'])
        self.assertEqual(payload['groups']['products'][0]['title'], self.product_by_name.name)
        self.assertEqual(
            set(payload['groups']['products'][0].keys()),
            {'type', 'title', 'subtitle', 'url', 'image_url', 'price_label', 'status_label', 'badge'},
        )

    def test_finds_product_by_description(self):
        response = self.client.get(self.suggest_url, {'q': 'аркад'})

        self.assertEqual(response.status_code, 200)
        product_titles = [item['title'] for item in response.json()['groups']['products']]
        self.assertIn(self.product_by_description.name, product_titles)

    def test_finds_bundle_by_included_product_name(self):
        response = self.client.get(self.suggest_url, {'q': 'Titan Stand'})

        self.assertEqual(response.status_code, 200)
        bundle_titles = [item['title'] for item in response.json()['groups']['bundles']]
        self.assertIn(self.bundle.name, bundle_titles)

    def test_returns_variant_row_when_matching_variant_name(self):
        response = self.client.get(self.suggest_url, {'q': '256 GB'})

        self.assertEqual(response.status_code, 200)
        variants = response.json()['groups']['variants']
        self.assertEqual(variants[0]['title'], f'{self.variant_product.name} · {self.variant.name}')
        self.assertEqual(variants[0]['badge'], 'Вариант')

    def test_returns_variant_row_when_matching_variant_sku(self):
        response = self.client.get(self.suggest_url, {'q': 'Q3-256'})

        self.assertEqual(response.status_code, 200)
        variants = response.json()['groups']['variants']
        self.assertEqual(variants[0]['title'], f'{self.variant_product.name} · {self.variant.name}')

    def test_inactive_products_do_not_appear(self):
        response = self.client.get(self.suggest_url, {'q': 'Ghost Quest'})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload['has_results'])
        self.assertEqual(payload['groups']['products'], [])

    def test_limits_group_size_to_three_items(self):
        response = self.client.get(self.suggest_url, {'q': 'Neo Limit'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['groups']['products']), 3)

@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)

class HomeFeaturedProductsTest(TestCase):
    """Главная страница: только товары с промо-тегами."""

    @classmethod
    def setUpTestData(cls):
        category = create_category(name='Тест', slug='test-home')
        cls.hit_tag = ProductTag.objects.create(name='Хит', slug='hit', order=1)
        cls.sale_tag = ProductTag.objects.create(name='Распродажа', slug='sale-home', order=2)

        cls.hit_product = create_product(
            category=category,
            name='Товар Хит',
            slug='home-hit',
            price=100,
            is_active=True,
        )
        cls.sale_product = create_product(
            category=category,
            name='Товар Распродажа',
            slug='home-sale',
            price=90,
            is_active=True,
        )
        cls.regular_product = create_product(
            category=category,
            name='Обычный товар',
            slug='home-regular',
            price=80,
            is_active=True,
        )
        cls.hit_product.tags.add(cls.hit_tag)
        cls.sale_product.tags.add(cls.sale_tag)

    def test_home_shows_only_promo_tagged_products(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        shown_slugs = {p.slug for p in resp.context['featured_products']}
        self.assertIn(self.hit_product.slug, shown_slugs)
        self.assertIn(self.sale_product.slug, shown_slugs)
        self.assertNotIn(self.regular_product.slug, shown_slugs)

    def test_home_marketing_tiles_use_optimized_webp_assets(self):
        resp = self.client.get(reverse('home'))

        self.assertEqual(resp.status_code, 200)
        marketing_tiles = {tile['key']: tile for tile in resp.context['marketing_tiles']}
        self.assertTrue(marketing_tiles['unitree_robot']['bg_url'].endswith('image-Photoroom_20_4RdGPzn.webp'))
        self.assertTrue(marketing_tiles['portable_consoles']['bg_url'].endswith('image-Photoroom_3.webp'))
        self.assertTrue(marketing_tiles['vr_attractions']['bg_url'].endswith('Two-person_360_flight_simulator.webp'))



class CatalogMenuCacheTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.section = CatalogSection.objects.create(name='VR', slug='vr')
        cls.category = create_category(name='Шлемы', slug='headsets', section=cls.section)
        create_product(
            category=cls.category,
            name='Quest 3',
            slug='quest-3-cache',
            price=100,
            is_active=True,
            image='products/quest-3.webp',
        )

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def _build_request(self, path='/'):
        request = self.factory.get(path)
        request.user = AnonymousUser()
        request.session = {}
        return request

    def test_catalog_menu_uses_cached_sections_and_previews(self):
        catalog_menu(self._build_request())

        with self.assertNumQueries(0):
            context = catalog_menu(self._build_request('/catalog/'))

        self.assertIn(self.section.slug, {section.slug for section in context['catalog_sections']})
        self.assertEqual(
            context['catalog_category_previews'][self.category.pk],
            '/media/products/quest-3.webp',
        )

    def test_catalog_menu_prefers_explicit_category_image_over_product_image(self):
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, True)
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?'
            b'\x00\x05\xfe\x02\xfeA\xd9\x89\xc9\x00\x00\x00\x00IEND\xaeB`\x82'
        )

        with override_settings(
            MEDIA_ROOT=media_root,
            STORAGES={
                'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
            },
        ):
            self.category.image = SimpleUploadedFile('category-card.png', png_bytes, content_type='image/png')
            self.category.save(update_fields=['image'])
            context = catalog_menu(self._build_request('/catalog/'))

        self.assertIn(self.category.pk, context['catalog_category_previews'])
        self.assertIn('/media/categories/category-card', context['catalog_category_previews'][self.category.pk])

    @override_settings(
        SITE_AVITO_URL='SITE_AVITO_URL=https://www.avito.ru/user/test/profile',
        SITE_CONTACT_TELEGRAM='export SITE_CONTACT_TELEGRAM=https://t.me/bizonvr_test',
    )
    def test_catalog_menu_normalizes_public_urls_copied_with_env_key_prefix(self):
        context = catalog_menu(self._build_request('/'))

        self.assertEqual(
            context['site_avito_url'],
            'https://www.avito.ru/user/test/profile',
        )
        self.assertEqual(
            context['site_contact_telegram'],
            'https://t.me/bizonvr_test',
        )

    def test_catalog_menu_exposes_bundle_only_section_landing_category(self):
        bundle_section = CatalogSection.objects.create(name='Bundle only', slug='bundle-only')
        bundle_category = Category.objects.create(
            name='Комплекты',
            slug='bundle-only-category',
            section=bundle_section,
            is_bundles_category=True,
        )
        bundle = ProductBundle.objects.create(
            category=bundle_category,
            name='Bundle landing',
            slug='bundle-landing',
        )
        ProductBundleItem.objects.create(bundle=bundle, product=Product.objects.get(slug='quest-3-cache'), quantity=1)
        ProductBundleItem.objects.create(
            bundle=bundle,
            product=Product.objects.create(
                category=self.category,
                name='Quest 3 Extra',
                slug='quest-3-cache-extra',
                price=120,
                is_active=True,
            ),
            quantity=1,
        )

        context = catalog_menu(self._build_request('/catalog/'))
        self.assertEqual(
            context['catalog_section_landing_categories'][bundle_section.slug],
            bundle_category.slug,
        )



class ServicesPageTest(TestCase):
    """Страница услуг: вывод из БД и обработка callback-формы."""

    @classmethod
    def setUpTestData(cls):
        Service.objects.create(
            name='VR-мероприятия',
            short_description='Выездные активности',
            description='Организация и сопровождение мероприятий.',
            icon='users',
            price_from='от 15 000 ₽',
            order=2,
            is_active=True,
        )
        Service.objects.create(
            name='Скрытая услуга',
            short_description='Не должна отображаться',
            order=1,
            is_active=False,
        )

    def test_services_page_shows_only_active_services(self):
        resp = self.client.get(reverse('uslugi'))
        self.assertEqual(resp.status_code, 200)
        services = list(resp.context['services'])
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0].name, 'VR-мероприятия')
        self.assertContains(resp, 'VR-мероприятия')
        self.assertNotContains(resp, 'Скрытая услуга')
        self.assertContains(resp, 'Помогаем собрать набор услуг под мероприятие, бренд-активацию или запуск VR-зоны.')
        self.assertNotContains(resp, 'админка')

    def test_services_page_empty_state_uses_public_cta(self):
        Service.objects.all().delete()

        resp = self.client.get(reverse('uslugi'))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Расскажите о задаче, и мы предложим услуги под ваш формат мероприятия или площадки.')
        self.assertContains(resp, '<a href="#contacts" class="arenda-btn-services">Обсудить задачу</a>', html=True)
        self.assertNotContains(resp, 'админка')

    def test_services_callback_creates_request_with_source(self):
        resp = self.client.post(
            reverse('uslugi'),
            {
                'form_type': 'callback',
                'name': 'Иван',
                'phone': '+7 (999) 111-22-33',
                'agree_personal_data': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].endswith(reverse('uslugi') + '#contacts'))
        callback = CallbackRequest.objects.first()
        self.assertIsNotNone(callback)
        self.assertEqual(callback.source, 'uslugi')
        self.assertEqual(callback.name, 'Иван')
        self.assertIsNotNone(callback.legal_accepted_at)
        self.assertEqual(callback.legal_docs_version, LEGAL_BUNDLE_VERSION)
        site_request = SiteLeadRequest.objects.get()
        self.assertEqual(site_request.source_type, SiteLeadRequest.SOURCE_CALLBACK_USLUGI)
        self.assertEqual(site_request.phone, '+7 (999) 111-22-33')

    @override_settings(BITRIX_WEBHOOK_URL='https://portal.example/rest/1/webhook', BITRIX_SITE_REQUESTS_ENABLED=True)
    @patch('integrations.bitrix_site_requests.requests.post')
    def test_services_callback_creates_site_request_and_bitrix_deal(self, mock_post):
        def side_effect(url, data=None, timeout=None):
            response = Mock()
            response.raise_for_status.return_value = None
            if url.endswith('/crm.duplicate.findbycomm.json'):
                response.json.return_value = {'result': {'CONTACT': []}}
            elif url.endswith('/crm.contact.add.json'):
                response.json.return_value = {'result': '501'}
            elif url.endswith('/crm.deal.add.json'):
                response.json.return_value = {'result': '601'}
            else:
                raise AssertionError(f'Unexpected Bitrix URL: {url}')
            return response

        mock_post.side_effect = side_effect

        resp = self.client.post(
            reverse('uslugi'),
            {
                'form_type': 'callback',
                'name': 'Иван',
                'phone': '+7 (999) 111-22-33',
                'agree_personal_data': 'on',
            },
        )

        self.assertEqual(resp.status_code, 302)
        site_request = SiteLeadRequest.objects.get()
        self.assertEqual(site_request.sync_status, SiteLeadRequest.SYNC_STATUS_SYNCED)
        self.assertEqual(site_request.bitrix_contact_id, '501')
        self.assertEqual(site_request.bitrix_deal_id, '601')

    @override_settings(CRM_LEADS_EMAIL='crm@example.com')
    def test_services_callback_sends_crm_email(self):
        resp = self.client.post(
            reverse('uslugi'),
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
        self.assertEqual(mail.outbox[0].to, ['crm@example.com'])
        self.assertIn('Тип формы: Услуги', mail.outbox[0].body)
        self.assertIn('Товар/услуга: Услуги BizonVR', mail.outbox[0].body)

    def test_services_callback_spam_redirects_without_creating_request(self):
        resp = self.client.post(
            reverse('uslugi'),
            {
                'form_type': 'callback',
                'name': 'Иван',
                'phone': '+7 (999) 111-22-33',
                'agree_personal_data': 'on',
                'website': 'spam.example',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].endswith(reverse('uslugi') + '#contacts'))
        self.assertEqual(CallbackRequest.objects.count(), 0)
        site_request = SiteLeadRequest.objects.get()
        self.assertEqual(site_request.spam_status, SiteLeadRequest.SPAM_STATUS_SPAM)
        self.assertEqual(site_request.sync_status, SiteLeadRequest.SYNC_STATUS_SKIPPED)



class FavoriteTest(TestCase):
    """Избранное: добавление/удаление, доступ только для авторизованных."""

    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='79991234567', password='testpass')
        category = create_category(name='Тест', slug='test')
        cls.product = create_product(
            category=category,
            name='Товар',
            slug='product',
            price=100,
            is_active=True,
        )

    def test_toggle_favorite_anonymous_stores_in_session(self):
        """Аноним может добавлять в избранное — сохраняется в сессии."""
        url = reverse('catalog:toggle_favorite', kwargs={'product_id': self.product.pk})
        resp = self.client.post(url, {'next': '/'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(self.product.pk, self.client.session.get('favorite_product_ids', []))

    def test_toggle_favorite_add_and_remove(self):
        self.client.force_login(self.user)
        url = reverse('catalog:toggle_favorite', kwargs={'product_id': self.product.pk})
        resp = self.client.post(url, {'next': '/'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Favorite.objects.filter(user=self.user, product=self.product).exists())
        resp = self.client.post(url, {'next': '/'})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Favorite.objects.filter(user=self.user, product=self.product).exists())



class CartTest(TestCase):
    """Добавление в корзину: сессия, счётчик (Фаза 6)."""

    @classmethod
    def setUpTestData(cls):
        category = create_category(name='Тест', slug='test')
        cls.city = City.objects.create(name='Екатеринбург', slug='cart-ekb')
        cls.pickup_point = PickupPoint.objects.create(city=cls.city, name='Склад')
        cls.product = create_product(
            category=category,
            name='Товар',
            slug='product',
            price=100,
            is_active=True,
        )
        cls.product_with_variant = create_product(
            category=category,
            name='Товар с вариантом',
            slug='product-with-variant',
            price=110,
            is_active=True,
        )
        cls.product_variant = ProductVariant.objects.create(
            product=cls.product_with_variant,
            name='Черный',
            price_override=120,
        )
        cls.product_second = create_product(
            category=category,
            name='Товар 2',
            slug='product-2',
            price=200,
            is_active=True,
        )
        cls.bundle = ProductBundle.objects.create(
            category=create_category(
                name='Тестовые комплекты',
                slug='cart-test-bundles',
                is_bundles_category=True,
            ),
            name='Набор для теста',
            slug='test-bundle',
        )
        ProductBundleItem.objects.create(bundle=cls.bundle, product=cls.product, quantity=1)
        ProductBundleItem.objects.create(bundle=cls.bundle, product=cls.product_second, quantity=2)

    def _set_session_cart(self, items):
        session = self.client.session
        session['cart_items'] = items
        session.save()

    def _add_stock(self, product, quantity, *, variant=None):
        ProductStock.objects.create(
            product=product,
            pickup_point=self.pickup_point,
            variant=variant,
            quantity=quantity,
        )

    def test_add_to_cart_saves_in_session(self):
        self._add_stock(self.product, 10)
        url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        resp = self.client.post(url, {})
        self.assertEqual(resp.status_code, 302)
        cart_items = self.client.session.get('cart_items', [])
        self.assertEqual(len(cart_items), 1)
        self.assertEqual(cart_items[0]['product_id'], self.product.pk)
        self.assertEqual(cart_items[0]['quantity'], 1)
        self.assertEqual(cart_items[0]['subtotal'], 100)

    def test_add_to_cart_htmx_returns_cart_count(self):
        self._add_stock(self.product, 10)
        url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        resp = self.client.post(url, {}, HTTP_HX_REQUEST='true')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('HX-Trigger', resp)
        trigger = json.loads(resp['HX-Trigger'])
        self.assertEqual(trigger['cart-updated']['count'], 1)

    def test_buy_now_product_redirects_to_checkout_without_touching_regular_cart(self):
        self._add_stock(self.product, 10)
        url = reverse('catalog:buy_now_product', kwargs={'product_id': self.product.pk})

        resp = self.client.post(url, {'quantity': 1})

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, f"{reverse('orders:checkout')}?mode=buy_now")
        self.assertEqual(self.client.session.get('cart_items', []), [])
        buy_now_checkout = self.client.session.get('buy_now_checkout', {})
        self.assertEqual(len(buy_now_checkout.get('items', [])), 1)
        self.assertEqual(buy_now_checkout['items'][0]['product_id'], self.product.pk)

    def test_buy_now_product_requires_variant_like_add_to_cart(self):
        url = reverse('catalog:buy_now_product', kwargs={'product_id': self.product_with_variant.pk})

        resp = self.client.post(url, {'next': self.product_with_variant.get_absolute_url()})

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(self.product_with_variant.get_absolute_url()))
        self.assertIn('cart_error=1', resp.url)
        self.assertNotIn('buy_now_checkout', self.client.session)

    def test_buy_now_bundle_creates_one_click_draft_without_touching_regular_cart(self):
        url = reverse('catalog:buy_now_bundle')

        resp = self.client.post(url, {'bundle_id': self.bundle.pk, 'next': self.bundle.get_absolute_url()})

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, f"{reverse('orders:checkout')}?mode=buy_now")
        self.assertEqual(self.client.session.get('cart_items', []), [])
        buy_now_checkout = self.client.session.get('buy_now_checkout', {})
        self.assertEqual(len(buy_now_checkout.get('items', [])), 2)
        self.assertEqual(
            {item['product_id'] for item in buy_now_checkout['items']},
            {self.product.pk, self.product_second.pk},
        )
        self.assertEqual(
            {item['price'] for item in buy_now_checkout['items']},
            {float(self.product.price), float(self.product_second.price)},
        )
        self.assertTrue(all(item['price'] == item['original_price'] for item in buy_now_checkout['items']))

    def test_add_bundle_to_cart_uses_full_prices_without_discount_override(self):
        url = reverse('catalog:add_bundle_to_cart')

        resp = self.client.post(url, {'bundle_id': self.bundle.pk, 'next': self.bundle.get_absolute_url()})

        self.assertEqual(resp.status_code, 302)
        cart_items = self.client.session.get('cart_items', [])
        self.assertEqual(len(cart_items), 2)
        self.assertEqual(cart_items[0]['price'], float(self.product.price))
        self.assertEqual(cart_items[0]['original_price'], float(self.product.price))
        self.assertEqual(cart_items[0]['subtotal'], float(self.product.price))
        self.assertEqual(cart_items[1]['price'], float(self.product_second.price))
        self.assertEqual(cart_items[1]['original_price'], float(self.product_second.price))
        self.assertEqual(cart_items[1]['subtotal'], float(self.product_second.price) * 2)

    def test_add_bundle_to_cart_uses_product_discount_when_present(self):
        self.product.discount_percent = Decimal('10.00')
        self.product.save(update_fields=['discount_percent'])

        resp = self.client.post(
            reverse('catalog:add_bundle_to_cart'),
            {'bundle_id': self.bundle.pk, 'next': self.bundle.get_absolute_url()},
        )

        self.assertEqual(resp.status_code, 302)
        cart_items = self.client.session.get('cart_items', [])
        discounted_item = next(item for item in cart_items if item['product_id'] == self.product.pk)
        self.assertEqual(discounted_item['price'], 90.0)
        self.assertEqual(discounted_item['original_price'], 100.0)
        self.assertEqual(discounted_item['subtotal'], 90.0)

    def test_add_bundle_to_cart_htmx_mini_cart_has_no_discount_copy(self):
        url = reverse('catalog:add_bundle_to_cart')

        resp = self.client.post(
            url,
            {'bundle_id': self.bundle.pk, 'next': self.bundle.get_absolute_url()},
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '−5%')

    def test_legacy_bundle_session_prices_are_normalized_on_first_read(self):
        session = self.client.session
        session['cart_items'] = [{
            'product_id': self.product.pk,
            'variant_id': None,
            'variant_name': None,
            'name': self.product.name,
            'price': 95.0,
            'quantity': 2,
            'image_url': '',
            'subtotal': 190.0,
            'bundle_id': self.bundle.pk,
            'bundle_name': self.bundle.name,
            'original_price': 100.0,
            'purchase_mode': 'stock',
        }]
        session.save()

        resp = self.client.get(reverse('catalog:cart'))

        self.assertEqual(resp.status_code, 200)
        normalized_items = self.client.session.get('cart_items', [])
        self.assertEqual(normalized_items[0]['price'], float(self.product.price))
        self.assertEqual(normalized_items[0]['original_price'], float(self.product.price))
        self.assertEqual(normalized_items[0]['subtotal'], float(self.product.price) * 2)
        self.assertNotContains(resp, '−5%')

    def test_cart_page_does_not_show_bundle_discount_copy(self):
        session = self.client.session
        session['cart_items'] = [{
            'product_id': self.product.pk,
            'variant_id': None,
            'variant_name': None,
            'name': self.product.name,
            'price': float(self.product.price),
            'quantity': 1,
            'image_url': '',
            'subtotal': float(self.product.price),
            'bundle_id': self.bundle.pk,
            'bundle_name': self.bundle.name,
            'original_price': float(self.product.price),
            'purchase_mode': 'stock',
        }]
        session.save()

        resp = self.client.get(reverse('catalog:cart'))

        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '−5%')

    def test_cart_update_changes_quantity_and_remove_item(self):
        self._add_stock(self.product, 10)
        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        update_url = reverse('catalog:cart_update')

        self.client.post(add_url, {})
        resp = self.client.post(update_url, {'product_id': self.product.pk, 'quantity': 3})
        self.assertEqual(resp.status_code, 302)
        cart_items = self.client.session.get('cart_items', [])
        self.assertEqual(len(cart_items), 1)
        self.assertEqual(cart_items[0]['quantity'], 3)
        self.assertEqual(cart_items[0]['subtotal'], 300)

        resp = self.client.post(update_url, {'product_id': self.product.pk, 'quantity': 0})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session.get('cart_items', []), [])

    def test_cart_page_uses_total_stock_status_without_city(self):
        self._add_stock(self.product, 8)
        session = self.client.session
        session['selected_city_id'] = self.city.pk
        session.save()

        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        self.client.post(add_url, {})

        resp = self.client.get(reverse('catalog:cart'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Много')
        self.assertNotContains(resp, 'В другом городе')

    def test_cart_update_limits_quantity_by_total_stock(self):
        self._add_stock(self.product, 2)
        session = self.client.session
        session['selected_city_id'] = self.city.pk
        session.save()

        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        update_url = reverse('catalog:cart_update')
        self.client.post(add_url, {})
        self.client.post(update_url, {'product_id': self.product.pk, 'quantity': 5})

        cart_items = self.client.session.get('cart_items', [])
        self.assertEqual(len(cart_items), 1)
        self.assertEqual(cart_items[0]['quantity'], 2)

    def test_cart_page_keeps_add_order_after_update(self):
        self._add_stock(self.product, 10)
        self._add_stock(self.product_second, 10)
        add_url_first = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        add_url_second = reverse('catalog:add_to_cart', kwargs={'product_id': self.product_second.pk})
        update_url = reverse('catalog:cart_update')
        cart_url = reverse('catalog:cart')

        self.client.post(add_url_first, {})
        self.client.post(add_url_second, {})

        resp = self.client.get(cart_url)
        self.assertEqual(resp.status_code, 200)
        ids_before = [int(value) for value in re.findall(r'data-product-id="(\d+)"', resp.content.decode())]
        self.assertEqual(ids_before[:2], [self.product.pk, self.product_second.pk])

        self.client.post(update_url, {'product_id': self.product.pk, 'quantity': 3})

        resp = self.client.get(cart_url)
        self.assertEqual(resp.status_code, 200)
        ids_after = [int(value) for value in re.findall(r'data-product-id="(\d+)"', resp.content.decode())]
        self.assertEqual(ids_after[:2], [self.product.pk, self.product_second.pk])

    def test_cart_page_keeps_add_order_for_authenticated_user(self):
        user = User.objects.create_user(username='79990001122', password='testpass')
        self.client.force_login(user)
        self._add_stock(self.product, 10)
        self._add_stock(self.product_second, 10)
        add_url_first = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        add_url_second = reverse('catalog:add_to_cart', kwargs={'product_id': self.product_second.pk})
        update_url = reverse('catalog:cart_update')
        cart_url = reverse('catalog:cart')

        self.client.post(add_url_first, {})
        self.client.post(add_url_second, {})
        self.client.post(update_url, {'product_id': self.product.pk, 'quantity': 3})

        resp = self.client.get(cart_url)
        self.assertEqual(resp.status_code, 200)
        ids = [int(value) for value in re.findall(r'data-product-id="(\d+)"', resp.content.decode())]
        self.assertEqual(ids[:2], [self.product.pk, self.product_second.pk])

    def test_cart_clear_clears_session_cart(self):
        self._add_stock(self.product, 10)
        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        clear_url = reverse('catalog:cart_clear')

        self.client.post(add_url, {})
        self.client.post(add_url, {})
        self.assertTrue(self.client.session.get('cart_items'))

        resp = self.client.post(clear_url, {'next': reverse('catalog:cart')})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session.get('cart_items', []), [])

    def test_cart_clear_htmx_returns_empty_cart_and_zero_count(self):
        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        clear_url = reverse('catalog:cart_clear')

        self.client.post(add_url, {})
        resp = self.client.post(
            clear_url,
            {'next': reverse('catalog:cart')},
            HTTP_HX_REQUEST='true',
            HTTP_HX_TARGET='main-content',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Корзина пуста', resp.content.decode())
        self.assertIn('HX-Trigger', resp)
        trigger = json.loads(resp['HX-Trigger'])
        self.assertEqual(trigger['cart-updated']['count'], 0)

    def test_cart_share_create_includes_only_selected_items(self):
        self._set_session_cart([
            {
                'product_id': self.product_with_variant.pk,
                'variant_id': self.product_variant.pk,
                'variant_name': self.product_variant.name,
                'name': self.product_with_variant.name,
                'price': 120,
                'quantity': 2,
                'image_url': '',
                'subtotal': 240,
            },
            {
                'product_id': self.product_second.pk,
                'variant_id': None,
                'variant_name': None,
                'name': self.product_second.name,
                'price': 200,
                'quantity': 1,
                'image_url': '',
                'subtotal': 200,
            },
        ])
        selected_item_key = build_cart_item_share_key(self.client.session['cart_items'][0])
        resp = self.client.post(
            reverse('catalog:cart_share_create'),
            {'selected_item_keys': selected_item_key},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Поделиться выбранными товарами вашей корзины')
        self.assertEqual(CartShare.objects.count(), 1)
        share = CartShare.objects.first()
        self.assertEqual(len(share.items), 1)
        self.assertEqual(share.items[0]['product_id'], self.product_with_variant.pk)
        self.assertEqual(share.items[0]['variant_id'], self.product_variant.pk)
        self.assertIn(f'?share={share.code}', resp.content.decode())

    def test_cart_page_with_share_code_opens_modal(self):
        share = CartShare.objects.create(
            code='AbCd123',
            items=[{
                'product_id': self.product_with_variant.pk,
                'variant_id': self.product_variant.pk,
                'quantity': 2,
            }],
            expires_at=timezone.now() + timedelta(days=30),
        )
        resp = self.client.get(reverse('catalog:cart'), {'share': share.code})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['shared_modal_open'])
        self.assertFalse(resp.context['shared_invalid'])
        self.assertEqual(resp.context['shared_cart_code'], share.code)
        self.assertEqual(len(resp.context['shared_cart_items']), 1)
        self.assertContains(resp, 'Список товаров')

    def test_cart_page_with_invalid_share_code_sets_invalid_flag(self):
        resp = self.client.get(reverse('catalog:cart'), {'share': 'invalid1'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['shared_modal_open'])
        self.assertTrue(resp.context['shared_invalid'])
        self.assertEqual(resp.context['shared_cart_items'], [])

    def test_cart_share_add_all_adds_items_and_updates_count(self):
        share = CartShare.objects.create(
            code='EfGh456',
            items=[
                {
                    'product_id': self.product_with_variant.pk,
                    'variant_id': self.product_variant.pk,
                    'quantity': 2,
                },
                {
                    'product_id': self.product_second.pk,
                    'variant_id': None,
                    'quantity': 1,
                },
            ],
            expires_at=timezone.now() + timedelta(days=30),
        )
        resp = self.client.post(
            reverse('catalog:cart_share_add_all'),
            {'share_code': share.code},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('HX-Trigger', resp)
        trigger = json.loads(resp['HX-Trigger'])
        self.assertEqual(trigger['cart-updated']['count'], 3)
        session_items = self.client.session.get('cart_items', [])
        self.assertEqual(len(session_items), 2)

    def test_cart_share_skips_inactive_and_missing_products(self):
        inactive = Product.objects.create(
            category=self.product.category,
            name='Неактивный товар',
            slug='inactive-share-product',
            price=150,
            is_active=False,
        )
        share = CartShare.objects.create(
            code='ZaQw987',
            items=[
                {
                    'product_id': self.product.pk,
                    'variant_id': None,
                    'quantity': 1,
                },
                {
                    'product_id': inactive.pk,
                    'variant_id': None,
                    'quantity': 1,
                },
                {
                    'product_id': 999999,
                    'variant_id': None,
                    'quantity': 1,
                },
            ],
            expires_at=timezone.now() + timedelta(days=30),
        )
        resp = self.client.get(reverse('catalog:cart'), {'share': share.code})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['shared_cart_items']), 1)
        self.assertEqual(resp.context['shared_cart_items'][0]['product_id'], self.product.pk)



class FooterProductsFeedTest(TestCase):
    """Ленивая выдача карточек перед футером: порции и лимит."""

    @classmethod
    def setUpTestData(cls):
        cls.category = create_category(name='Тест', slug='test')
        for i in range(121):
            create_product(
                category=cls.category,
                name=f'Товар {i}',
                slug=f'test-product-{i}',
                price=100 + i,
                is_active=True,
            )

    def test_first_page_contains_next_loader(self):
        resp = self.client.get(reverse('catalog:footer_products_feed'), {'page': 1})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('page=2', html)
        self.assertNotIn('Показать все товары', html)

    def test_last_limited_page_shows_catalog_button(self):
        resp = self.client.get(reverse('catalog:footer_products_feed'), {'page': 8})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('Показать все товары', html)
        self.assertNotIn('page=9', html)



class SeoFilesTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_robots_txt_exists_and_links_sitemap(self):
        resp = self.client.get('/robots.txt')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('User-agent:', body)
        self.assertIn('Sitemap: http://testserver/sitemap.xml', body)

    def test_sitemap_xml_exists_and_contains_urls(self):
        cat = Category.objects.create(name='Тест', slug='seo-test')
        product = Product.objects.create(
            category=cat,
            name='SEO Product',
            slug='seo-product',
            price=100,
            is_active=True,
        )
        bundle = ProductBundle.objects.create(
            category=Category.objects.create(
                name='SEO Комплекты',
                slug='seo-bundles',
                is_bundles_category=True,
            ),
            name='SEO Bundle',
        )

        resp = self.client.get('/sitemap.xml')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('<urlset', body)
        self.assertIn('<loc>http://testserver/</loc>', body)
        self.assertIn(f'<loc>http://testserver{product.get_absolute_url()}</loc>', body)
        self.assertIn(f'<loc>http://testserver{bundle.get_absolute_url()}</loc>', body)



class CompareRemovalTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(
            username='9991234567',
            email='compare@example.com',
            password='testpass',
        )
        Profile.objects.create(
            user=cls.user,
            phone='9991234567',
            email_verified_at=timezone.now(),
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
        )
        cls.category = create_category(name='Тестовая категория', slug='compare-test')
        cls.products = [
            create_product(
                category=cls.category,
                name=f'Товар {index}',
                slug=f'compare-product-{index}',
                price=Decimal('1000.00') + index,
                is_active=True,
            )
            for index in range(1, 6)
        ]

    def setUp(self):
        cache.clear()

    def test_compare_page_returns_404(self):
        resp = self.client.get('/catalog/compare/')
        self.assertEqual(resp.status_code, 404)

    def test_compare_toggle_returns_404(self):
        resp = self.client.post(f'/catalog/compare/{self.products[0].pk}/')
        self.assertEqual(resp.status_code, 404)

    def test_catalog_page_does_not_contain_compare_ui(self):
        resp = self.client.get(reverse('catalog:product_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'x-text="compareCount"', html=False)
        self.assertNotContains(resp, '/catalog/compare/')
        self.assertNotContains(resp, 'Сравнение')

    def test_product_page_does_not_contain_compare_ui(self):
        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.products[0].slug}))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, f'/catalog/compare/{self.products[0].pk}/')
        self.assertNotContains(resp, 'Сравнить')
        self.assertNotContains(resp, 'В сравнении')

    def test_profile_page_does_not_contain_compare_ui(self):
        self.client.force_login(self.user)

        resp = self.client.get(reverse('accounts:profile'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '/catalog/compare/')
        self.assertNotContains(resp, 'Товаров в сравнении')
        self.assertNotContains(resp, 'Список сравнения пока пуст')

    def test_login_still_merges_cart_and_favorites_without_compare(self):
        session = self.client.session
        session['favorite_product_ids'] = [self.products[0].pk]
        session['cart_items'] = [{
            'product_id': self.products[0].pk,
            'variant_id': None,
            'variant_name': None,
            'name': self.products[0].name,
            'price': float(self.products[0].price),
            'quantity': 2,
            'image_url': '',
            'subtotal': float(self.products[0].price) * 2,
            'bundle_id': None,
            'bundle_name': None,
            'original_price': float(self.products[0].price),
        }]
        session.save()

        resp = self.client.post(reverse('accounts:password_login'), {
            'login': self.user.email,
            'password': 'testpass',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Favorite.objects.filter(user=self.user, product=self.products[0]).exists())
        cart_item = CartItem.objects.get(user=self.user, product=self.products[0])
        self.assertEqual(cart_item.quantity, 2)
        self.assertEqual(self.client.session.get('favorite_product_ids', []), [])
        self.assertEqual(self.client.session.get('cart_items', []), [])

    def test_login_clears_legacy_bundle_price_override_when_merging_cart(self):
        bundle_category = Category.objects.create(
            name='Комплекты для входа',
            slug='login-bundles',
            is_bundles_category=True,
        )
        bundle = ProductBundle.objects.create(
            category=bundle_category,
            name='Bundle login',
            slug='bundle-login',
        )
        ProductBundleItem.objects.create(bundle=bundle, product=self.products[0], quantity=1)
        ProductBundleItem.objects.create(bundle=bundle, product=self.products[1], quantity=1)

        session = self.client.session
        session['cart_items'] = [{
            'product_id': self.products[0].pk,
            'variant_id': None,
            'variant_name': None,
            'name': self.products[0].name,
            'price': float(self.products[0].price * Decimal('0.95')),
            'quantity': 1,
            'image_url': '',
            'subtotal': float(self.products[0].price * Decimal('0.95')),
            'bundle_id': bundle.pk,
            'bundle_name': bundle.name,
            'original_price': float(self.products[0].price),
            'purchase_mode': 'stock',
        }]
        session.save()

        resp = self.client.post(reverse('accounts:password_login'), {
            'login': self.user.email,
            'password': 'testpass',
        })

        self.assertEqual(resp.status_code, 302)
        cart_item = CartItem.objects.get(user=self.user, product=self.products[0], bundle=bundle)
        self.assertEqual(cart_item.quantity, 1)
        self.assertIsNone(cart_item.price_override)

@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)

class DigitalCatalogSectionIaTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.digital_section, _ = CatalogSection.objects.update_or_create(
            slug='cifrovye-tovary',
            defaults={'name': 'Цифровые товары'},
        )
        self.business_section, _ = CatalogSection.objects.update_or_create(
            slug='resheniya-dlya-vr-biznesa',
            defaults={'name': 'Решения для VR бизнеса'},
        )
        self.games_category, _ = Category.objects.update_or_create(
            slug='mr-vr-games',
            defaults={'section': self.digital_section, 'name': 'MR / VR Игры'},
        )
        self.packs_category, _ = Category.objects.update_or_create(
            slug='vr-zone-packs',
            defaults={'section': self.business_section, 'name': 'Паки для VR-зон'},
        )
        self.game = Product.objects.create(
            category=self.games_category,
            name='Neon Rhythm Arena',
            slug='neon-rhythm-arena',
            price=Decimal('2490.00'),
            is_active=True,
        )
        self.game_pack = GamePack.objects.create(
            category=self.packs_category,
            name='Quest Arcade Pack',
            slug='quest-arcade-pack',
            price=Decimal('4990.00'),
            is_active=True,
        )
        GamePackEntry.objects.create(game_pack=self.game_pack, product=self.game, quantity=1)

    def test_section_query_for_digital_catalog_shows_games(self):
        response = self.client.get(reverse('catalog:product_list'), {'section': 'cifrovye-tovary'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['is_game_packs_category'])
        self.assertContains(response, self.game.name)
        self.assertNotContains(response, self.game_pack.name)

    def test_business_pack_category_uses_game_pack_mode(self):
        response = self.client.get(reverse('catalog:product_list'), {'category': 'vr-zone-packs'})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_game_packs_category'])
        self.assertEqual(response.context['current_section_effective'], 'resheniya-dlya-vr-biznesa')
        self.assertContains(response, self.game_pack.name)
