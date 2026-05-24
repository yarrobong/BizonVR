from ._shared import *  # noqa: F401,F403

class CatalogSectionFilterTest(TestCase):
    """Фильтры каталога должны быть ограничены выбранным разделом."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.section_vr = CatalogSection.objects.create(name='VR', slug='vr-filter')
        self.section_pc = CatalogSection.objects.create(name='PC', slug='pc-filter')
        self.section_attractions = CatalogSection.objects.create(
            name='VR аттракционы',
            slug='vr-attrakciony-ad-filter',
        )
        self.cat_vr = Category.objects.create(name='VR Шлемы', slug='vr-headsets-filter', section=self.section_vr)
        self.cat_pc = Category.objects.create(name='Ноутбуки', slug='laptops-filter', section=self.section_pc)
        self.cat_attractions = Category.objects.create(
            name='Стационарные аттракционы',
            slug='stationary-attractions-filter',
            section=self.section_attractions,
        )
        self.bundle_category = Category.objects.create(
            name='Комплекты для VR АРЕН',
            slug='komplekty-dlya-vr-aren',
            section=self.section_attractions,
            is_bundles_category=True,
        )
        self.bundle_category_secondary = Category.objects.create(
            name='Комплекты для VR клубов',
            slug='komplekty-dlya-vr-clubs',
            section=self.section_attractions,
            is_bundles_category=True,
        )
        self.tag_vr = ProductTag.objects.create(name='VR тег', slug='vr-tag', order=1)
        self.tag_pc = ProductTag.objects.create(name='PC тег', slug='pc-tag', order=2)

        self.vr_product = Product.objects.create(
            category=self.cat_vr,
            name='Quest 3',
            slug='quest-3',
            price=100,
            is_active=True,
        )
        self.pc_product = Product.objects.create(
            category=self.cat_pc,
            name='Laptop',
            slug='laptop',
            price=200,
            is_active=True,
        )
        self.attractions_product = Product.objects.create(
            category=self.cat_attractions,
            name='VR Arena',
            slug='vr-arena',
            price=300,
            is_active=True,
        )
        self.bundle_helper_product = Product.objects.create(
            category=self.cat_attractions,
            name='Arena Sensors',
            slug='arena-sensors',
            price=600,
            is_active=True,
        )
        self.bundle = ProductBundle.objects.create(
            category=self.bundle_category,
            name='Arena комплект',
            slug='arena-bundle',
        )
        ProductBundleItem.objects.create(bundle=self.bundle, product=self.attractions_product, quantity=1)
        ProductBundleItem.objects.create(bundle=self.bundle, product=self.vr_product, quantity=1)
        self.secondary_bundle = ProductBundle.objects.create(
            category=self.bundle_category_secondary,
            name='Club комплект',
            slug='club-bundle',
        )
        ProductBundleItem.objects.create(bundle=self.secondary_bundle, product=self.bundle_helper_product, quantity=1)
        ProductBundleItem.objects.create(bundle=self.secondary_bundle, product=self.pc_product, quantity=1)

        ProductCharacteristic.objects.create(product=self.vr_product, name='Память', value='128 GB')
        ProductCharacteristic.objects.create(product=self.vr_product, name='Совместимость', value='Quest 3')
        ProductCharacteristic.objects.create(product=self.attractions_product, name='Тип', value='Арена')
        ProductCharacteristic.objects.create(product=self.bundle_helper_product, name='Память', value='256 ГБ')
        ProductCharacteristic.objects.create(product=self.bundle_helper_product, name='Совместимость', value='Pico 4')

        self.vr_product.tags.add(self.tag_vr)
        self.pc_product.tags.add(self.tag_pc)

    def test_tags_in_filters_are_limited_by_selected_section(self):
        resp = self.client.get(reverse('catalog:product_list'), {'section': self.section_vr.slug})
        self.assertEqual(resp.status_code, 200)
        tag_slugs = {tag.slug for tag in resp.context['product_tags']}
        self.assertIn(self.tag_vr.slug, tag_slugs)
        self.assertNotIn(self.tag_pc.slug, tag_slugs)

    def test_malformed_section_slug_recovers_valid_prefix_and_sanitizes_links(self):
        malformed_section = f'{self.section_attractions.slug}/?calltouch_tm=yd_c:42'
        response = self.client.get(
            reverse('catalog:product_list'),
            {
                'section': malformed_section,
                'utm_source': 'yandex',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['current_section'], self.section_attractions.slug)
        self.assertEqual(response.context['current_section_effective'], self.section_attractions.slug)
        self.assertEqual(
            {product.slug for product in response.context['products']},
            {self.attractions_product.slug, self.bundle_helper_product.slug},
        )

        request = RequestFactory().get(
            reverse('catalog:product_list'),
            {'section': malformed_section, 'utm_source': 'yandex'},
        )
        built_url = CatalogFilterService(request).build_query_string(tag='vr-tag')
        pagination_url = Template('{% load catalog_tags %}{% filter_url_pagination 2 %}').render(
            Context({'request': request})
        )
        self.assertIn(f'section={self.section_attractions.slug}', built_url)
        self.assertIn('utm_source=yandex', built_url)
        self.assertNotIn(urlencode({'section': malformed_section}), built_url)
        self.assertIn(f'section={self.section_attractions.slug}', pagination_url)
        self.assertNotIn(urlencode({'section': malformed_section}), pagination_url)

    def test_unknown_section_slug_falls_back_to_unfiltered_catalog(self):
        response = self.client.get(
            reverse('catalog:product_list'),
            {'section': 'missing-section', 'utm_source': 'yandex'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['current_section'], '')
        self.assertEqual(response.context['current_section_effective'], '')
        self.assertEqual(
            {product.slug for product in response.context['products']},
            {self.attractions_product.slug, self.bundle_helper_product.slug, 'quest-3', 'laptop'},
        )

    def test_malformed_category_slug_recovers_valid_prefix_and_sanitizes_links(self):
        malformed_category = f'{self.cat_attractions.slug}/?calltouch_tm=yd_c:42'
        response = self.client.get(
            reverse('catalog:product_list'),
            {
                'category': malformed_category,
                'utm_source': 'yandex',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['current_category'], self.cat_attractions.slug)
        self.assertEqual(response.context['current_section_effective'], self.section_attractions.slug)
        self.assertEqual(
            {product.slug for product in response.context['products']},
            {self.attractions_product.slug, self.bundle_helper_product.slug},
        )

        request = RequestFactory().get(
            reverse('catalog:product_list'),
            {'category': malformed_category, 'utm_source': 'yandex'},
        )
        built_url = CatalogFilterService(request).build_query_string(tag='vr-tag')
        pagination_url = Template('{% load catalog_tags %}{% filter_url_pagination 2 %}').render(
            Context({'request': request})
        )
        self.assertIn(f'category={self.cat_attractions.slug}', built_url)
        self.assertIn('utm_source=yandex', built_url)
        self.assertNotIn(urlencode({'category': malformed_category}), built_url)
        self.assertIn(f'category={self.cat_attractions.slug}', pagination_url)
        self.assertNotIn(urlencode({'category': malformed_category}), pagination_url)

    def test_bundles_category_page_renders_without_catalog_price_annotation_errors(self):
        response = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.bundle_category.slug},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_bundles_category'])
        self.assertEqual(response.context['results_count'], 1)
        self.assertEqual(list(response.context['products']), [])
        self.assertEqual([bundle.slug for bundle in response.context['bundles']], [self.bundle.slug])
        self.assertEqual(response.context['category_result_counts'][self.bundle_category.pk], 1)
        self.assertEqual(response.context['category_result_counts'][self.bundle_category_secondary.pk], 1)

    def test_bundle_only_section_links_resolve_to_bundle_category(self):
        bundle_only_section = CatalogSection.objects.create(name='Bundle only', slug='bundle-only')
        bundle_only_category = Category.objects.create(
            name='Bundle only category',
            slug='bundle-only-category',
            section=bundle_only_section,
            is_bundles_category=True,
        )
        bundle_only = ProductBundle.objects.create(
            category=bundle_only_category,
            name='Bundle only set',
            slug='bundle-only-set',
        )
        ProductBundleItem.objects.create(bundle=bundle_only, product=self.vr_product, quantity=1)
        ProductBundleItem.objects.create(bundle=bundle_only, product=self.attractions_product, quantity=1)
        request = RequestFactory().get(
            reverse('catalog:product_list'),
            {'section': bundle_only_section.slug},
        )
        request.user = AnonymousUser()
        request.session = {}
        context = catalog_menu(request)
        built_url = Template('{% load catalog_tags %}{% url "catalog:product_list" %}{% filter_url_section section %}').render(
            Context({'request': request, 'section': bundle_only_section, **context})
        )

        self.assertIn(f'section={bundle_only_section.slug}', built_url)
        self.assertIn(f'category={bundle_only_category.slug}', built_url)

    def test_bundles_category_card_uses_bundle_image_before_first_product_image(self):
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
            self.attractions_product.image = SimpleUploadedFile('product-card.png', png_bytes, content_type='image/png')
            self.attractions_product.save(update_fields=['image'])
            self.bundle.image = SimpleUploadedFile('bundle-card.png', png_bytes, content_type='image/png')
            self.bundle.save(update_fields=['image'])

            response = self.client.get(
                reverse('catalog:product_list'),
                {'category': self.bundle_category.slug},
            )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        card_start = html.index(f'id="bundle-{self.bundle.pk}"')
        card_html = html[card_start:html.index('</article>', card_start)]
        self.assertIn('/media/bundles/bundle-card', card_html)
        self.assertNotIn('/media/products/product-card', card_html)

    def test_tags_in_filters_are_limited_by_selected_category(self):
        """При выбранной категории показываются только теги, у которых есть товары в этой категории (чтобы не вести в пустой каталог)."""
        # Только в VR-категории есть товар с tag_vr; в PC-категории — с tag_pc
        resp = self.client.get(reverse('catalog:product_list'), {'category': self.cat_vr.slug})
        self.assertEqual(resp.status_code, 200)
        tag_slugs = {tag.slug for tag in resp.context['product_tags']}
        self.assertIn(self.tag_vr.slug, tag_slugs)
        self.assertNotIn(self.tag_pc.slug, tag_slugs)

    def test_bundle_category_page_shows_only_bundles_from_selected_category(self):
        response = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.bundle_category.slug},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([bundle.slug for bundle in response.context['bundles']], [self.bundle.slug])
        self.assertNotContains(response, '−5%')

    def test_bundle_price_bounds_and_price_filter_use_bundle_totals(self):
        bundle_same_category = ProductBundle.objects.create(
            category=self.bundle_category,
            name='Arena комплект Plus',
            slug='arena-bundle-plus',
        )
        ProductBundleItem.objects.create(bundle=bundle_same_category, product=self.bundle_helper_product, quantity=1)
        ProductBundleItem.objects.create(bundle=bundle_same_category, product=self.attractions_product, quantity=1)

        response = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.bundle_category.slug, 'price_min': '700', 'price_max': '900'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['filter_price_min'], 400)
        self.assertEqual(response.context['filter_price_max'], 900)
        self.assertEqual([bundle.slug for bundle in response.context['bundles']], [bundle_same_category.slug])

    def test_bundle_price_bounds_use_discounted_product_prices(self):
        self.bundle_helper_product.discount_percent = Decimal('50.00')
        self.bundle_helper_product.save(update_fields=['discount_percent'])

        response = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.bundle_category_secondary.slug, 'price_min': '450', 'price_max': '550'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['filter_price_min'], 500)
        self.assertEqual(response.context['filter_price_max'], 500)
        self.assertEqual([bundle.slug for bundle in response.context['bundles']], [self.secondary_bundle.slug])

    def test_bundle_card_shows_old_total_when_item_has_product_discount(self):
        self.attractions_product.discount_percent = Decimal('10.00')
        self.attractions_product.save(update_fields=['discount_percent'])

        response = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.bundle_category.slug},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '370 ₽')
        self.assertContains(response, '400 ₽')
        self.assertNotContains(response, '−5%')

    def test_bundle_tag_filter_matches_any_bundle_item(self):
        response = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.bundle_category.slug, 'tag': self.tag_vr.slug},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([bundle.slug for bundle in response.context['bundles']], [self.bundle.slug])
        tag_slugs = {tag.slug for tag in response.context['product_tags']}
        self.assertIn(self.tag_vr.slug, tag_slugs)
        self.assertNotIn(self.tag_pc.slug, tag_slugs)

    def test_bundle_search_matches_included_product_name(self):
        response = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.bundle_category.slug, 'q': 'Quest 3'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([bundle.slug for bundle in response.context['bundles']], [self.bundle.slug])

    def test_bundle_legacy_characteristic_counts_are_distinct_by_bundle(self):
        bundle_same_category = ProductBundle.objects.create(
            category=self.bundle_category,
            name='Arena комплект Memory',
            slug='arena-bundle-memory',
        )
        ProductBundleItem.objects.create(bundle=bundle_same_category, product=self.vr_product, quantity=1)
        ProductBundleItem.objects.create(bundle=bundle_same_category, product=self.bundle_helper_product, quantity=1)

        response = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.bundle_category.slug},
        )

        self.assertEqual(response.status_code, 200)
        memory_group = next(
            group for group in response.context['characteristic_filters']
            if group['label'] == 'Память'
        )
        option_counts = {option['label']: option['count'] for option in memory_group['options']}
        self.assertEqual(option_counts['128 GB'], 2)
        self.assertEqual(option_counts['256 ГБ'], 1)

    def test_bundle_popularity_sort_uses_bundle_views(self):
        bundle_same_category = ProductBundle.objects.create(
            category=self.bundle_category,
            name='Arena комплект Popular',
            slug='arena-bundle-popular',
        )
        ProductBundleItem.objects.create(bundle=bundle_same_category, product=self.bundle_helper_product, quantity=1)
        ProductBundleItem.objects.create(bundle=bundle_same_category, product=self.attractions_product, quantity=1)

        self.client.get(reverse('catalog:bundle_detail', kwargs={'slug': bundle_same_category.slug}))
        response = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.bundle_category.slug, 'sort': 'popularity'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [bundle.slug for bundle in response.context['bundles']],
            [bundle_same_category.slug, self.bundle.slug],
        )



class CatalogPriceBoundsTest(TestCase):
    """Границы ценового фильтра не должны схлопываться до текущего price-фильтра."""

    def setUp(self):
        self.client = Client()
        self.section = CatalogSection.objects.create(name='VR', slug='vr-price')
        self.category = Category.objects.create(name='Шлемы', slug='price-headsets', section=self.section)
        self.city = City.objects.create(name='Тестоград', slug='price-test-city')
        self.pickup_point = PickupPoint.objects.create(city=self.city, name='Склад цен')
        self.low_product = Product.objects.create(
            category=self.category,
            name='Базовый шлем',
            slug='price-low',
            price=100,
            is_active=True,
        )
        self.mid_product = Product.objects.create(
            category=self.category,
            name='Средний шлем',
            slug='price-mid',
            price=500,
            is_active=True,
        )
        self.high_product = Product.objects.create(
            category=self.category,
            name='Топовый шлем',
            slug='price-high',
            price=900,
            is_active=True,
        )
        self.on_request_product = Product.objects.create(
            category=self.category,
            name='Под заказ',
            slug='price-on-request',
            price=650,
            price_on_request=700,
            is_active=True,
            allow_order_on_request=True,
        )
        self.unpriced_product = Product.objects.create(
            category=self.category,
            name='Без цены',
            slug='price-unpriced',
            price=None,
            price_on_request=None,
            is_active=True,
        )
        ProductStock.objects.create(product=self.low_product, pickup_point=self.pickup_point, quantity=5)
        ProductStock.objects.create(product=self.mid_product, pickup_point=self.pickup_point, quantity=5)
        ProductStock.objects.create(product=self.high_product, pickup_point=self.pickup_point, quantity=5)

    def test_price_filter_keeps_full_category_bounds(self):
        resp = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.category.slug, 'price_min': '500', 'price_max': '700'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['filter_price_min'], 100)
        self.assertEqual(resp.context['filter_price_max'], 900)
        self.assertEqual(resp.context['price_min_filter'], '500')
        self.assertEqual(resp.context['price_max_filter'], '700')

    def test_price_filter_uses_effective_catalog_price_for_on_request_products(self):
        resp = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.category.slug, 'price_min': '650', 'price_max': '750'},
        )

        self.assertEqual(resp.status_code, 200)
        slugs = [product.slug for product in resp.context['products']]
        self.assertIn(self.on_request_product.slug, slugs)
        self.assertNotIn(self.unpriced_product.slug, slugs)

    def test_price_filter_uses_discounted_in_stock_product_price(self):
        self.high_product.discount_percent = Decimal('50.00')
        self.high_product.save(update_fields=['discount_percent'])

        resp = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.category.slug, 'price_min': '440', 'price_max': '460'},
        )

        self.assertEqual(resp.status_code, 200)
        slugs = [product.slug for product in resp.context['products']]
        self.assertIn(self.high_product.slug, slugs)
        self.assertEqual(resp.context['filter_price_max'], 700)

    def test_price_sort_puts_unpriced_products_last(self):
        resp = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.category.slug, 'sort': 'price_asc'},
        )

        self.assertEqual(resp.status_code, 200)
        slugs = [product.slug for product in resp.context['products']]
        self.assertEqual(
            slugs,
            [
                self.low_product.slug,
                self.mid_product.slug,
                self.on_request_product.slug,
                self.high_product.slug,
                self.unpriced_product.slug,
            ],
        )


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)

class CatalogManagedFiltersTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.section = CatalogSection.objects.create(name='VR фильтры', slug='vr-managed')
        self.category = Category.objects.create(name='Шлемы', slug='managed-headsets', section=self.section)
        self.accessories = Category.objects.create(name='Аксессуары', slug='managed-accessories', section=self.section)
        self.other_section = CatalogSection.objects.create(name='Другая секция', slug='other-managed')
        self.other_category = Category.objects.create(
            name='Другая категория',
            slug='other-managed-category',
            section=self.other_section,
        )
        self.featured_tag = ProductTag.objects.create(name='Хит', slug='managed-hit', order=1)
        self.sale_tag = ProductTag.objects.create(name='Распродажа', slug='managed-sale', order=2)

        self.white_128 = Product.objects.create(
            category=self.category,
            name='Quest 3 128 White',
            slug='quest-3-128-white',
            price=100,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.white_128, name='Память', value='128 GB')
        ProductCharacteristic.objects.create(product=self.white_128, name='Цвет', value='Белый')
        ProductCharacteristic.objects.create(product=self.white_128, name='Гарантия', value='1 год')
        self.white_128.tags.add(self.featured_tag)

        self.black_128 = Product.objects.create(
            category=self.category,
            name='Quest 3 128 Black',
            slug='quest-3-128-black',
            price=120,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.black_128, name='Память', value='128Gb')
        ProductCharacteristic.objects.create(product=self.black_128, name='Цвет', value='Черный')
        ProductCharacteristic.objects.create(product=self.black_128, name='Гарантия', value='1 год')
        self.black_128.tags.add(self.featured_tag)
        self.black_128.tags.add(self.sale_tag)

        self.black_256 = Product.objects.create(
            category=self.category,
            name='Quest 3 256 Black',
            slug='quest-3-256-black',
            price=150,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.black_256, name='Память', value='256 ГБ')
        ProductCharacteristic.objects.create(product=self.black_256, name='Цвет', value='Черный')
        ProductCharacteristic.objects.create(product=self.black_256, name='Гарантия', value='1 год')

        self.accessory = Product.objects.create(
            category=self.accessories,
            name='Quest 3 Strap',
            slug='quest-3-strap',
            price=80,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.accessory, name='Цвет', value='Красный')
        ProductCharacteristic.objects.create(product=self.accessory, name='Тип', value='Ремешок')
        self.accessory.tags.add(self.featured_tag)

    def _create_managed_definitions(self):
        memory = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
            sort_order=20,
            is_filterable=True,
            is_active=True,
        )
        color = CharacteristicDefinition.objects.create(
            code='color',
            name='Цвет',
            source_name='Цвет',
            sort_order=10,
            is_filterable=True,
            is_active=True,
        )
        warranty = CharacteristicDefinition.objects.create(
            code='warranty',
            name='Гарантия',
            source_name='Гарантия',
            sort_order=30,
            is_filterable=True,
            is_active=True,
        )
        for raw_value in ('128 GB', '128Gb', '128 ГБ', '128гб'):
            CharacteristicValueAlias.objects.create(
                characteristic_definition=memory,
                raw_value=raw_value,
                normalized_value='128-memory',
                display_value='128 ГБ',
                sort_order=1,
            )
        CharacteristicValueAlias.objects.create(
            characteristic_definition=memory,
            raw_value='256 ГБ',
            normalized_value='256-memory',
            display_value='256 ГБ',
            sort_order=2,
        )
        return memory, color, warranty

    def test_managed_filters_use_source_aliases_and_legacy_raw_source_params_still_work(self):
        memory, _, _ = self._create_managed_definitions()
        CharacteristicSourceAlias.objects.create(
            characteristic_definition=memory,
            raw_source_name='Объем памяти',
        )
        ProductCharacteristic.objects.filter(product=self.black_128, name='Память').delete()
        ProductCharacteristic.objects.create(product=self.black_128, name='Объем памяти', value='128Gb')
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=memory,
            is_visible=True,
            is_quick_filter=True,
            sort_order=10,
            hide_single_value=False,
        )

        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(resp.status_code, 200)
        memory_group = resp.context['characteristic_filters'][0]
        option_counts = {option['label']: option['count'] for option in memory_group['options']}
        self.assertEqual(option_counts['128 ГБ'], 2)

        legacy_resp = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.category.slug, 'char_Объем памяти': '128Gb'},
        )
        self.assertEqual(legacy_resp.status_code, 200)
        legacy_slugs = {product.slug for product in legacy_resp.context['products']}
        self.assertEqual(legacy_slugs, {self.white_128.slug, self.black_128.slug})

    def test_managed_bundle_filters_normalize_values_and_count_distinct_bundles(self):
        memory, _, _ = self._create_managed_definitions()
        bundle_category = Category.objects.create(
            name='Комплекты VR',
            slug='managed-vr-bundles',
            section=self.section,
            is_bundles_category=True,
        )
        FilterConfig.objects.create(
            category=bundle_category,
            characteristic_definition=memory,
            is_visible=True,
            is_quick_filter=True,
            sort_order=10,
            hide_single_value=False,
        )

        bundle_one = ProductBundle.objects.create(
            category=bundle_category,
            name='Bundle One',
            slug='bundle-one',
        )
        ProductBundleItem.objects.create(bundle=bundle_one, product=self.white_128, quantity=1)
        ProductBundleItem.objects.create(bundle=bundle_one, product=self.accessory, quantity=1)

        bundle_two = ProductBundle.objects.create(
            category=bundle_category,
            name='Bundle Two',
            slug='bundle-two',
        )
        ProductBundleItem.objects.create(bundle=bundle_two, product=self.black_128, quantity=1)
        ProductBundleItem.objects.create(bundle=bundle_two, product=self.black_256, quantity=1)

        resp = self.client.get(reverse('catalog:product_list'), {'category': bundle_category.slug})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['is_bundles_category'])
        memory_group = resp.context['characteristic_filters'][0]
        option_counts = {option['label']: option['count'] for option in memory_group['options']}
        self.assertEqual(option_counts['128 ГБ'], 2)
        self.assertEqual(option_counts['256 ГБ'], 1)

        filtered_resp = self.client.get(
            reverse('catalog:product_list'),
            {'category': bundle_category.slug, 'char_memory': '128-memory'},
        )
        self.assertEqual(filtered_resp.status_code, 200)
        self.assertEqual(
            {bundle.slug for bundle in filtered_resp.context['bundles']},
            {bundle_one.slug, bundle_two.slug},
        )

    def test_legacy_fallback_keeps_auto_filters_and_raw_char_filter(self):
        resp = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.category.slug, 'char_Память': '128 GB'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['filter_mode'], 'legacy')
        labels = [item['label'] for item in resp.context['characteristic_filters']]
        self.assertEqual(labels, ['Память'])
        product_slugs = {product.slug for product in resp.context['products']}
        self.assertEqual(product_slugs, {self.white_128.slug})

    def test_managed_category_filters_use_config_order_and_quick_flags(self):
        memory, color, warranty = self._create_managed_definitions()
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=memory,
            is_visible=True,
            is_quick_filter=True,
            sort_order=20,
        )
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=color,
            is_visible=True,
            is_quick_filter=False,
            sort_order=10,
        )
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=warranty,
            is_visible=True,
            is_quick_filter=False,
            sort_order=30,
        )

        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['filter_mode'], 'category')
        labels = [item['label'] for item in resp.context['characteristic_filters']]
        self.assertEqual(labels, ['Цвет', 'Память'])
        quick_labels = [item['label'] for item in resp.context['quick_characteristic_filters']]
        self.assertEqual(quick_labels, ['Память'])
        self.assertNotIn('Гарантия', labels)

    def test_managed_filters_normalize_values_and_merge_counts(self):
        memory, _, _ = self._create_managed_definitions()
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=memory,
            is_visible=True,
            is_quick_filter=True,
            sort_order=10,
            hide_single_value=False,
        )

        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(resp.status_code, 200)
        memory_group = resp.context['characteristic_filters'][0]
        option_counts = {option['label']: option['count'] for option in memory_group['options']}
        self.assertEqual(option_counts['128 ГБ'], 2)
        self.assertEqual(option_counts['256 ГБ'], 1)

    def test_managed_filters_hide_single_value_only_when_flag_enabled(self):
        memory, _, warranty = self._create_managed_definitions()
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=memory,
            is_visible=True,
            sort_order=5,
            hide_single_value=False,
        )
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=warranty,
            is_visible=True,
            sort_order=10,
            hide_single_value=True,
        )
        hidden_resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(hidden_resp.status_code, 200)
        self.assertEqual(hidden_resp.context['filter_mode'], 'category')
        self.assertEqual([item['label'] for item in hidden_resp.context['characteristic_filters']], ['Память'])

        FilterConfig.objects.filter(category=self.category).delete()
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=warranty,
            is_visible=True,
            sort_order=10,
            hide_single_value=False,
        )
        visible_resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(visible_resp.status_code, 200)
        self.assertEqual([item['label'] for item in visible_resp.context['characteristic_filters']], ['Гарантия'])
        self.assertEqual(visible_resp.context['characteristic_filters'][0]['options'][0]['label'], '1 год')

    def test_section_config_used_for_section_page_and_category_config_overrides_it(self):
        memory, color, _ = self._create_managed_definitions()
        FilterConfig.objects.create(
            section=self.section,
            characteristic_definition=color,
            is_visible=True,
            is_quick_filter=True,
            sort_order=10,
        )
        section_resp = self.client.get(reverse('catalog:product_list'), {'section': self.section.slug})
        self.assertEqual(section_resp.status_code, 200)
        self.assertEqual(section_resp.context['filter_mode'], 'section')
        self.assertEqual([item['label'] for item in section_resp.context['characteristic_filters']], ['Цвет'])

        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=memory,
            is_visible=True,
            is_quick_filter=True,
            sort_order=5,
            hide_single_value=False,
        )
        category_resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(category_resp.status_code, 200)
        self.assertEqual(category_resp.context['filter_mode'], 'category')
        self.assertEqual([item['label'] for item in category_resp.context['characteristic_filters']], ['Память'])

    def test_existing_raw_param_and_canonical_param_both_work_and_code_wins(self):
        memory, _, _ = self._create_managed_definitions()
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=memory,
            is_visible=True,
            is_quick_filter=True,
            sort_order=10,
            hide_single_value=False,
        )

        legacy_resp = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.category.slug, 'char_Память': '128Gb'},
        )
        self.assertEqual(legacy_resp.status_code, 200)
        legacy_slugs = {product.slug for product in legacy_resp.context['products']}
        self.assertEqual(legacy_slugs, {self.white_128.slug, self.black_128.slug})

        canonical_resp = self.client.get(
            reverse('catalog:product_list'),
            {
                'category': self.category.slug,
                'char_memory': '256-memory',
                'char_Память': '128 GB',
            },
        )
        self.assertEqual(canonical_resp.status_code, 200)
        self.assertEqual(list(canonical_resp.context['char_filters'].keys()), ['memory'])
        self.assertEqual(canonical_resp.context['active_characteristic_filters'][0]['selected_value'], '256-memory')
        self.assertEqual(canonical_resp.context['active_characteristic_filters'][0]['value'], '256 ГБ')
        canonical_slugs = {product.slug for product in canonical_resp.context['products']}
        self.assertEqual(canonical_slugs, {self.black_256.slug})

    def test_tag_links_preserve_active_characteristic_params(self):
        memory, _, _ = self._create_managed_definitions()
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=memory,
            is_visible=True,
            is_quick_filter=True,
            sort_order=10,
            hide_single_value=False,
        )

        resp = self.client.get(
            reverse('catalog:product_list'),
            {'category': self.category.slug, 'char_memory': '128-memory'},
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('/catalog/?category=managed-headsets&amp;char_memory=128-memory&amp;tag=managed-hit', html)
        self.assertIn('/catalog/?category=managed-headsets&amp;char_memory=128-memory&amp;sort=newest', html)

    def test_config_without_visible_groups_falls_back_to_legacy(self):
        ghost = CharacteristicDefinition.objects.create(
            code='ghost',
            name='Призрак',
            source_name='Несуществующая характеристика',
            sort_order=1,
            is_filterable=True,
            is_active=True,
        )
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=ghost,
            is_visible=True,
            sort_order=10,
        )

        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['filter_mode'], 'legacy')
        self.assertEqual([item['label'] for item in resp.context['characteristic_filters']], ['Память', 'Цвет'])

    def test_managed_filters_sort_numeric_values_by_preset_and_global_fallback(self):
        memory = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
            sorting_mode='numeric_unit',
            sort_order=10,
            is_filterable=True,
            is_active=True,
        )
        series = CharacteristicDefinition.objects.create(
            code='series',
            name='Поколение',
            source_name='Поколение',
            sorting_mode='numeric_unit',
            sort_order=20,
            is_filterable=True,
            is_active=True,
        )
        product_64 = Product.objects.create(
            category=self.category,
            name='Quest 3 64 White',
            slug='quest-3-64-white',
            price=95,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=product_64, name='Память', value='64 GB')
        ProductCharacteristic.objects.create(product=self.white_128, name='Поколение', value='2')
        ProductCharacteristic.objects.create(product=self.black_128, name='Поколение', value='10')
        ProductCharacteristic.objects.create(product=self.black_256, name='Поколение', value='3')
        for raw_value, normalized_value, display_value in (
            ('64 GB', '64 gb', '64 ГБ'),
            ('128 GB', '128 gb', '128 ГБ'),
            ('128Gb', '128 gb', '128 ГБ'),
            ('256 ГБ', '256 gb', '256 ГБ'),
        ):
            CharacteristicValueAlias.objects.create(
                characteristic_definition=memory,
                raw_value=raw_value,
                normalized_value=normalized_value,
                display_value=display_value,
            )
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=memory,
            is_visible=True,
            sort_order=10,
            hide_single_value=False,
        )
        FilterConfig.objects.create(
            category=self.category,
            characteristic_definition=series,
            is_visible=True,
            sort_order=20,
            hide_single_value=False,
        )

        response = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(response.status_code, 200)
        groups = {group['label']: group for group in response.context['characteristic_filters']}
        self.assertEqual(
            [option['label'] for option in groups['Память']['options']],
            ['64 ГБ', '128 ГБ', '256 ГБ'],
        )
        self.assertEqual(
            [option['label'] for option in groups['Поколение']['options']],
            ['2', '3', '10'],
        )


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)

class CatalogFilterAuditTest(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.old = self.now - timedelta(days=10)

        self.managed_section = CatalogSection.objects.create(name='Managed', slug='audit-managed')
        self.legacy_section = CatalogSection.objects.create(name='Legacy', slug='audit-legacy')
        self.weak_section = CatalogSection.objects.create(name='Weak', slug='audit-weak')

        self.managed_category = Category.objects.create(
            name='Managed category',
            slug='audit-managed-category',
            section=self.managed_section,
        )
        self.legacy_category = Category.objects.create(
            name='Legacy category',
            slug='audit-legacy-category',
            section=self.legacy_section,
        )
        self.weak_category = Category.objects.create(
            name='Weak category',
            slug='audit-weak-category',
            section=self.weak_section,
        )

        self.memory = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
            is_filterable=True,
            is_active=True,
        )
        self.color = CharacteristicDefinition.objects.create(
            code='color',
            name='Цвет',
            source_name='Цвет',
            is_filterable=True,
            is_active=False,
        )
        self.ghost = CharacteristicDefinition.objects.create(
            code='ghost',
            name='Призрак',
            source_name='Несуществующая характеристика',
            is_filterable=True,
            is_active=True,
        )
        CharacteristicValueAlias.objects.create(
            characteristic_definition=self.memory,
            raw_value='128 GB',
            normalized_value='128 gb',
            display_value='128 ГБ',
            is_active=True,
        )

        self.managed_recent = Product.objects.create(
            category=self.managed_category,
            name='Managed recent',
            slug='audit-managed-recent',
            price=100,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.managed_recent, name='Память', value='256 GB')
        ProductCharacteristic.objects.create(product=self.managed_recent, name='Цвет', value='Черный')

        self.managed_old_covered = Product.objects.create(
            category=self.managed_category,
            name='Managed old covered',
            slug='audit-managed-old-covered',
            price=110,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.managed_old_covered, name='Память', value='128 GB')

        self.managed_old_uncovered = Product.objects.create(
            category=self.managed_category,
            name='Managed old uncovered',
            slug='audit-managed-old-uncovered',
            price=120,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.managed_old_uncovered, name='Память', value='512 GB')

        self.legacy_recent = Product.objects.create(
            category=self.legacy_category,
            name='Legacy recent',
            slug='audit-legacy-recent',
            price=130,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.legacy_recent, name='Материал', value='Пластик')

        self.legacy_old = Product.objects.create(
            category=self.legacy_category,
            name='Legacy old',
            slug='audit-legacy-old',
            price=140,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.legacy_old, name='Форм-фактор', value='Standalone')

        self.weak_product = Product.objects.create(
            category=self.weak_category,
            name='Weak product',
            slug='audit-weak-product',
            price=150,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.weak_product, name='Цвет', value='Белый')

        Product.objects.filter(pk=self.managed_recent.pk).update(updated_at=self.now, created_at=self.now)
        Product.objects.filter(pk=self.legacy_recent.pk).update(updated_at=self.now, created_at=self.now)
        Product.objects.filter(pk=self.weak_product.pk).update(updated_at=self.now, created_at=self.now)
        Product.objects.filter(pk=self.managed_old_covered.pk).update(updated_at=self.old, created_at=self.old)
        Product.objects.filter(pk=self.managed_old_uncovered.pk).update(updated_at=self.old, created_at=self.old)
        Product.objects.filter(pk=self.legacy_old.pk).update(updated_at=self.old, created_at=self.old)

        FilterConfig.objects.create(
            category=self.managed_category,
            characteristic_definition=self.memory,
            is_visible=True,
            is_quick_filter=False,
            hide_single_value=False,
        )
        FilterConfig.objects.create(
            section=self.weak_section,
            characteristic_definition=self.ghost,
            is_visible=True,
            is_quick_filter=False,
            hide_single_value=False,
        )

    def test_build_filter_audit_dashboard_context_uses_live_queries(self):
        context = build_filter_audit_dashboard_context(days=7)

        self.assertTrue(context['is_live_audit'])
        self.assertFalse(context['supports_historical_snapshots'])

        uncovered_sources = {row['name']: row['product_count'] for row in context['uncovered_source_names']}
        self.assertEqual(uncovered_sources, {'Материал': 1, 'Форм-фактор': 1})

        uncovered_values = {
            (row['definition'].code, row['raw_value']): row['product_count']
            for row in context['uncovered_raw_values']
        }
        self.assertEqual(uncovered_values, {('memory', '256 GB'): 1, ('memory', '512 GB'): 1})

        self.assertEqual(
            [item.slug for item in context['legacy_categories']],
            [self.legacy_category.slug, self.weak_category.slug],
        )
        self.assertEqual([item.slug for item in context['legacy_sections']], [self.legacy_section.slug])
        self.assertEqual(
            [item.slug for item in context['managed_categories_without_quick_filters']],
            [self.managed_category.slug],
        )
        self.assertEqual(
            [item.slug for item in context['weak_managed_sections']],
            [self.weak_section.slug],
        )
        self.assertEqual(context['weak_managed_categories'], [])

        disabled = {
            item['definition'].code: item['product_count']
            for item in context['disabled_definitions_with_raw_data']
        }
        self.assertEqual(disabled, {'color': 2})

    def test_recent_live_audit_helpers_filter_by_recently_updated_products(self):
        recent_sources = {
            item['raw_source_name']: item['recent_product_count']
            for item in get_new_uncovered_sources(days=7)
        }
        self.assertEqual(recent_sources, {'Материал': 1})

        recent_values, uncovered_pairs = get_new_uncovered_values(days=7)
        self.assertEqual(uncovered_pairs, {('Память', '256 GB'), ('Память', '512 GB')})
        self.assertEqual(
            {(item['raw_source_name'], item['raw_value']): item['recent_product_count'] for item in recent_values},
            {('Память', '256 GB'): 1},
        )

    def test_sync_catalog_filter_audit_snapshots_returns_live_stats(self):
        stats = sync_catalog_filter_audit_snapshots()
        self.assertEqual(stats['mode'], 'live')
        self.assertEqual(stats['uncovered_source_count'], 2)
        self.assertEqual(stats['uncovered_value_count'], 2)


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)

class CatalogFilterAutomationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.section = CatalogSection.objects.create(name='Автоматизация', slug='automation')
        self.category = Category.objects.create(name='VR Шлемы', slug='automation-headsets', section=self.section)
        self.product_a = Product.objects.create(
            category=self.category,
            name='Quest 3 128 White',
            slug='automation-quest-128-white',
            price=100,
            is_active=True,
        )
        self.product_b = Product.objects.create(
            category=self.category,
            name='Quest 3 128 Black',
            slug='automation-quest-128-black',
            price=110,
            is_active=True,
        )
        self.product_c = Product.objects.create(
            category=self.category,
            name='Quest 3 256 Black',
            slug='automation-quest-256-black',
            price=120,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.product_a, name='Память', value='128 GB')
        ProductCharacteristic.objects.create(product=self.product_a, name='Цвет', value='Белый')
        ProductCharacteristic.objects.create(product=self.product_b, name='Память', value='128Gb')
        ProductCharacteristic.objects.create(product=self.product_b, name='Цвет', value='Черный')
        ProductCharacteristic.objects.create(product=self.product_c, name='Память', value='256 ГБ')
        ProductCharacteristic.objects.create(product=self.product_c, name='Цвет', value='Черный')

        self.admin_user = User.objects.create_superuser(
            username='admin-automation',
            email='admin@example.com',
            password='secret123',
        )

    def test_definition_code_autogenerated_and_collision_gets_suffix(self):
        first = CharacteristicDefinition.objects.create(
            code='',
            name='Память',
            source_name='Память',
        )
        second = CharacteristicDefinition.objects.create(
            code='',
            name='Pamyat',
            source_name='Pamyat',
        )
        self.assertEqual(first.code, 'pamyat')
        self.assertEqual(second.code, 'pamyat-2')

    def test_characteristic_definition_bootstrap_command_is_idempotent(self):
        CharacteristicDefinition.objects.create(code='memory', name='Память', source_name='Память')

        dry_run_output = StringIO()
        call_command('bootstrap_characteristic_definitions', stdout=dry_run_output)
        self.assertIn('would_create: Цвет -> tsvet', dry_run_output.getvalue())

        call_command('bootstrap_characteristic_definitions', '--apply')
        self.assertEqual(CharacteristicDefinition.objects.count(), 2)
        call_command('bootstrap_characteristic_definitions', '--apply')
        self.assertEqual(CharacteristicDefinition.objects.count(), 2)

    def test_bootstrap_definitions_skips_source_name_already_covered_by_source_alias(self):
        definition = CharacteristicDefinition.objects.create(code='memory', name='Память', source_name='Память')
        CharacteristicSourceAlias.objects.create(
            characteristic_definition=definition,
            raw_source_name='Встроенная память',
        )
        ProductCharacteristic.objects.create(product=self.product_a, name='Встроенная память', value='128 GB')

        call_command('bootstrap_characteristic_definitions', '--apply')
        self.assertEqual(CharacteristicDefinition.objects.filter(source_name='Встроенная память').count(), 0)

    def test_source_name_admin_form_uses_distinct_choices_and_allows_current_value(self):
        blank_form = CharacteristicDefinitionAdminForm()
        blank_choices = {value for value, _ in blank_form.fields['source_name'].choices}
        self.assertIn('Память', blank_choices)
        self.assertIn('Цвет', blank_choices)
        self.assertNotIn('Неизвестная', blank_choices)

        invalid_form = CharacteristicDefinitionAdminForm(
            data={
                'code': '',
                'name': 'Тест',
                'source_name': 'Неизвестная',
                'is_filterable': True,
                'sort_order': 0,
                'is_active': True,
            }
        )
        self.assertFalse(invalid_form.is_valid())

        definition = CharacteristicDefinition.objects.create(
            code='legacy-hidden',
            name='Скрытая',
            source_name='Скрытая характеристика',
        )
        instance_form = CharacteristicDefinitionAdminForm(instance=definition)
        instance_choices = {value for value, _ in instance_form.fields['source_name'].choices}
        self.assertIn('Скрытая характеристика', instance_choices)

    def test_normalization_and_alias_suggestions_group_values(self):
        definition = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
        )
        suggestion_keys = {
            normalize_characteristic_value(raw).normalized_key
            for raw in (' 128 GB ', '128Gb', '128 гб')
        }
        self.assertEqual(suggestion_keys, {'128 gb'})

        suggestions = build_alias_suggestions(definition)
        grouped = {item['normalized_key']: item for item in suggestions}
        self.assertEqual(grouped['128 gb']['product_count'], 2)
        self.assertEqual(grouped['128 gb']['suggested_display'], '128 ГБ')
        self.assertEqual(grouped['128 gb']['status'], SAFE_AUTO_APPLICABLE)

    def test_alias_helper_page_creates_missing_aliases_without_duplicates(self):
        definition = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
        )
        self.client.force_login(self.admin_user)
        url = reverse('admin:catalog_characteristicdefinition_alias_suggestions', args=[definition.pk])

        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, '128 GB')

        suggestion = next(item for item in build_alias_suggestions(definition) if item['normalized_key'] == '128 gb')
        post_response = self.client.post(
            url,
            data={
                'selected_groups': [suggestion['normalized_key']],
                'display__0': '128 ГБ',
                'display__1': '256 ГБ',
            },
            follow=True,
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertEqual(CharacteristicValueAlias.objects.filter(characteristic_definition=definition).count(), 2)

        self.client.post(
            url,
            data={
                'selected_groups': [suggestion['normalized_key']],
                'display__0': '128 ГБ',
                'display__1': '256 ГБ',
            },
        )
        self.assertEqual(CharacteristicValueAlias.objects.filter(characteristic_definition=definition).count(), 2)

    def test_safe_auto_apply_command_creates_only_safe_groups(self):
        definition = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
        )
        CharacteristicValueAlias.objects.create(
            characteristic_definition=definition,
            raw_value='256 ГБ',
            normalized_value='manual-256',
            display_value='256 ГБ',
        )
        stdout = StringIO()
        call_command(
            'suggest_characteristic_aliases',
            '--definition',
            definition.code,
            '--auto-apply-safe',
            stdout=stdout,
        )
        self.assertEqual(
            CharacteristicValueAlias.objects.filter(characteristic_definition=definition, raw_value__in=['128 GB', '128Gb']).count(),
            2,
        )
        self.assertEqual(
            CharacteristicValueAlias.objects.filter(characteristic_definition=definition, raw_value='256 ГБ').count(),
            1,
        )
        self.assertIn('Safe auto-apply', stdout.getvalue())

    def test_source_alias_helper_page_creates_source_aliases(self):
        definition = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
        )
        ProductCharacteristic.objects.create(product=self.product_a, name='Объем памяти', value='128 GB')
        self.client.force_login(self.admin_user)
        url = reverse('admin:catalog_characteristicdefinition_source_alias_suggestions', args=[definition.pk])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Объем памяти')

        self.client.post(url, data={'selected_source_names': ['Объем памяти']}, follow=True)
        self.assertTrue(
            CharacteristicSourceAlias.objects.filter(
                characteristic_definition=definition,
                raw_source_name='Объем памяти',
            ).exists()
        )

    def test_definition_admin_action_redirects_to_alias_helper_for_single_selection(self):
        definition = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
        )
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('admin:catalog_characteristicdefinition_changelist'),
            {
                'action': 'open_alias_suggestions',
                '_selected_action': [definition.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse('admin:catalog_characteristicdefinition_alias_suggestions', args=[definition.pk]),
            response['Location'],
        )

    def test_bootstrap_catalog_filter_configs_command_creates_missing_configs_with_defaults(self):
        memory = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
            sort_order=20,
            is_filterable=True,
            is_active=True,
        )
        color = CharacteristicDefinition.objects.create(
            code='color',
            name='Цвет',
            source_name='Цвет',
            sort_order=10,
            is_filterable=True,
            is_active=False,
        )
        CharacteristicDefinition.objects.create(
            code='ghost',
            name='Призрак',
            source_name='Несуществующая',
            sort_order=5,
            is_filterable=True,
            is_active=True,
        )

        preview_output = StringIO()
        call_command(
            'bootstrap_catalog_filter_configs',
            '--category',
            self.category.slug,
            stdout=preview_output,
        )
        self.assertIn('would_create: memory / Память', preview_output.getvalue())
        self.assertIn('would_create: color / Цвет', preview_output.getvalue())

        call_command('bootstrap_catalog_filter_configs', '--category', self.category.slug, '--apply')
        self.assertEqual(FilterConfig.objects.filter(category=self.category).count(), 2)
        memory_config = FilterConfig.objects.get(category=self.category, characteristic_definition=memory)
        color_config = FilterConfig.objects.get(category=self.category, characteristic_definition=color)
        self.assertEqual(memory_config.sort_order, 20)
        self.assertTrue(memory_config.hide_single_value)
        self.assertTrue(memory_config.is_visible)
        self.assertEqual(color_config.sort_order, 10)
        self.assertFalse(color_config.is_visible)

        call_command('bootstrap_catalog_filter_configs', '--category', self.category.slug, '--apply')
        self.assertEqual(FilterConfig.objects.filter(category=self.category).count(), 2)

    def test_bootstrap_catalog_filter_configs_command_creates_section_configs(self):
        CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
            sort_order=20,
            is_filterable=True,
            is_active=True,
        )
        CharacteristicDefinition.objects.create(
            code='color',
            name='Цвет',
            source_name='Цвет',
            sort_order=10,
            is_filterable=True,
            is_active=True,
        )

        preview_output = StringIO()
        call_command(
            'bootstrap_catalog_filter_configs',
            '--section',
            self.section.slug,
            stdout=preview_output,
        )
        self.assertIn('would_create: memory / Память', preview_output.getvalue())
        call_command('bootstrap_catalog_filter_configs', '--section', self.section.slug, '--apply')
        self.assertEqual(FilterConfig.objects.filter(section=self.section).count(), 2)

    def test_category_and_section_admin_actions_create_configs(self):
        CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
            sort_order=10,
            is_filterable=True,
            is_active=True,
        )
        CharacteristicDefinition.objects.create(
            code='color',
            name='Цвет',
            source_name='Цвет',
            sort_order=20,
            is_filterable=True,
            is_active=True,
        )
        self.client.force_login(self.admin_user)

        category_response = self.client.post(
            reverse('admin:catalog_category_changelist'),
            {
                'action': 'bootstrap_filter_configs_action',
                '_selected_action': [self.category.pk],
            },
            follow=True,
        )
        self.assertEqual(category_response.status_code, 200)
        self.assertEqual(FilterConfig.objects.filter(category=self.category).count(), 2)

        section_response = self.client.post(
            reverse('admin:catalog_catalogsection_changelist'),
            {
                'action': 'bootstrap_filter_configs_action',
                '_selected_action': [self.section.pk],
            },
            follow=True,
        )
        self.assertEqual(section_response.status_code, 200)
        self.assertEqual(FilterConfig.objects.filter(section=self.section).count(), 2)

    def test_filter_setup_wizard_preview_splits_missing_definitions_aliases_and_quick_filters(self):
        memory = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
            is_filterable=True,
            is_active=True,
        )
        CharacteristicDefinition.objects.create(
            code='color',
            name='Цвет',
            source_name='Цвет',
            is_filterable=True,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.product_c, name='Объем памяти', value='256 ГБ')
        ProductCharacteristic.objects.create(product=self.product_a, name='Частота обновления', value='90 Гц')
        ProductCharacteristic.objects.create(product=self.product_b, name='Частота обновления', value='120 Гц')
        ProductCharacteristic.objects.create(product=self.product_c, name='Частота обновления', value='120 Гц')

        wizard = CatalogFilterSetupWizard('category', self.category)
        preview = wizard.build_preview()

        self.assertEqual([item['source_name'] for item in preview['missing_definitions']], ['Частота обновления'])
        self.assertEqual(len(preview['source_alias_suggestions']), 1)
        self.assertEqual(preview['source_alias_suggestions'][0]['definition'], memory)
        self.assertEqual(
            [item['raw_source_name'] for item in preview['source_alias_suggestions'][0]['items']],
            ['Объем памяти'],
        )
        self.assertEqual(
            sorted(item['definition'].code for item in preview['safe_value_alias_suggestions']),
            ['color', 'memory'],
        )
        safe_value_items = {
            item['definition'].code: [entry['normalized_key'] for entry in item['items']]
            for item in preview['safe_value_alias_suggestions']
        }
        self.assertEqual(safe_value_items['memory'], ['128 gb', '256 gb'])
        self.assertEqual(safe_value_items['color'], ['черный', 'белый'])
        self.assertEqual(
            sorted(item['definition'].code for item in preview['missing_configs']),
            ['color', 'memory'],
        )
        self.assertEqual(
            sorted(item['definition'].code for item in preview['quick_filter_recommendations']),
            ['color', 'memory'],
        )

    def test_category_filter_setup_wizard_admin_page_applies_selected_steps(self):
        memory = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
            is_filterable=True,
            is_active=True,
        )
        CharacteristicDefinition.objects.create(
            code='color',
            name='Цвет',
            source_name='Цвет',
            is_filterable=True,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.product_c, name='Объем памяти', value='256 ГБ')
        ProductCharacteristic.objects.create(product=self.product_a, name='Частота обновления', value='90 Гц')
        ProductCharacteristic.objects.create(product=self.product_b, name='Частота обновления', value='120 Гц')
        ProductCharacteristic.objects.create(product=self.product_c, name='Частота обновления', value='120 Гц')

        self.client.force_login(self.admin_user)
        url = reverse('admin:catalog_category_filter_setup_wizard', args=[self.category.pk])

        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, 'Объем памяти')
        self.assertContains(get_response, 'Частота обновления')

        post_response = self.client.post(
            url,
            data={
                'missing_definitions': ['Частота обновления'],
                'source_aliases': [f'{memory.pk}::Объем памяти'],
                'value_aliases': [f'{memory.pk}::128 gb', f'{memory.pk}::256 gb'],
                'apply_missing_configs': '1',
                'quick_filters': [str(memory.pk)],
            },
            follow=True,
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertTrue(
            CharacteristicDefinition.objects.filter(source_name='Частота обновления').exists()
        )
        self.assertTrue(
            CharacteristicSourceAlias.objects.filter(
                characteristic_definition=memory,
                raw_source_name='Объем памяти',
            ).exists()
        )
        self.assertEqual(
            CharacteristicValueAlias.objects.filter(
                characteristic_definition=memory,
                raw_value__in=['128 GB', '128Gb', '256 ГБ'],
            ).count(),
            3,
        )
        self.assertEqual(FilterConfig.objects.filter(category=self.category).count(), 3)
        self.assertTrue(
            FilterConfig.objects.get(category=self.category, characteristic_definition=memory).is_quick_filter
        )

    def test_category_change_form_contains_filter_setup_wizard_link(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('admin:catalog_category_change', args=[self.category.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse('admin:catalog_category_filter_setup_wizard', args=[self.category.pk]),
        )

    def test_suggest_characteristic_aliases_command_outputs_json(self):
        definition = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
        )
        stdout = StringIO()
        call_command(
            'suggest_characteristic_aliases',
            '--definition',
            definition.code,
            '--format',
            'json',
            stdout=stdout,
        )
        self.assertIn('"normalized_key": "128 gb"', stdout.getvalue())

    def test_typed_sort_key_supports_screen_size_and_boolean(self):
        screen_values = sorted(
            ['15.6"', '13"', '14"'],
            key=lambda value: get_typed_value_sort_key(value, sorting_mode='screen_size'),
        )
        boolean_values = sorted(
            ['Нет', 'Да'],
            key=lambda value: get_typed_value_sort_key(value, sorting_mode='boolean'),
        )

        self.assertEqual(screen_values, ['13"', '14"', '15.6"'])
        self.assertEqual(boolean_values, ['Да', 'Нет'])
