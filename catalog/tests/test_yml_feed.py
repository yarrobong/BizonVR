from ._shared import *  # noqa: F401,F403


@tag('slow')
class VrAttractionsYmlFeedTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.section, _ = CatalogSection.objects.get_or_create(
            slug='vr-attrakciony',
            defaults={'name': 'VR-аттракционы', 'order': 1},
        )
        self.other_section, _ = CatalogSection.objects.get_or_create(
            slug='vr-oborudovanie',
            defaults={'name': 'VR-оборудование', 'order': 2},
        )
        self.category = Category.objects.create(name='Стационарные', slug='stationary-attractions', section=self.section)
        self.variant_category = Category.objects.create(name='Симуляторы', slug='simulators', section=self.section)
        self.other_category = Category.objects.create(name='Шлемы', slug='headsets', section=self.other_section)
        self.city = City.objects.create(name='Москва', slug='moscow-feed')
        self.pickup_point = PickupPoint.objects.create(city=self.city, name='Склад', address='Тестовая улица, 1')

        self.single_product = Product.objects.create(
            category=self.category,
            name='VR-аттракцион Solo',
            slug='vr-attraction-solo',
            description='Одиночный аттракцион для парков.',
            price=Decimal('100000.00'),
            is_active=True,
            allow_order_on_request=False,
        )
        ProductStock.objects.create(
            product=self.single_product,
            pickup_point=self.pickup_point,
            quantity=3,
        )

        self.on_request_with_special_price = Product.objects.create(
            category=self.category,
            name='VR-аттракцион Special Order',
            slug='vr-attraction-special-order',
            description='Под заказ со спецценой.',
            price=Decimal('210000.00'),
            price_on_request=Decimal('199000.00'),
            is_active=True,
            allow_order_on_request=True,
        )

        self.on_request_without_special_price = Product.objects.create(
            category=self.category,
            name='VR-аттракцион Standard Order',
            slug='vr-attraction-standard-order',
            description='Под заказ по обычной цене.',
            price=Decimal('155000.00'),
            is_active=True,
            allow_order_on_request=True,
        )

        self.variant_product = Product.objects.create(
            category=self.variant_category,
            name='VR-симулятор Drift',
            slug='vr-simulator-drift',
            description='Симулятор гонок с вариантами комплектации.',
            price=Decimal('300000.00'),
            is_active=True,
            allow_order_on_request=True,
        )
        self.variant_stock = ProductVariant.objects.create(
            product=self.variant_product,
            name='Стандарт',
            sku='drift-std',
            price_override=Decimal('320000.00'),
            order=0,
        )
        self.variant_on_request = ProductVariant.objects.create(
            product=self.variant_product,
            name='Премиум',
            sku='drift-premium',
            price_override=Decimal('350000.00'),
            price_on_request_override=Decimal('340000.00'),
            order=1,
        )
        ProductStock.objects.create(
            product=self.variant_product,
            variant=self.variant_stock,
            pickup_point=self.pickup_point,
            quantity=2,
        )

        self.other_section_product = Product.objects.create(
            category=self.other_category,
            name='Quest 3',
            slug='quest-3-feed-excluded',
            description='Товар другого раздела.',
            price=Decimal('50000.00'),
            is_active=True,
        )
        ProductStock.objects.create(
            product=self.other_section_product,
            pickup_point=self.pickup_point,
            quantity=5,
        )

        self.unavailable_product = Product.objects.create(
            category=self.category,
            name='Недоступный аттракцион',
            slug='unavailable-attraction',
            description='Без остатка и без заказа под заказ.',
            price=Decimal('88000.00'),
            is_active=True,
            allow_order_on_request=False,
        )

        self.inactive_product = Product.objects.create(
            category=self.category,
            name='Неактивный аттракцион',
            slug='inactive-attraction',
            description='Не должен попасть в фид.',
            price=Decimal('93000.00'),
            is_active=False,
            allow_order_on_request=True,
        )

    def _get_feed_response(self):
        return self.client.get(reverse('vr_attractions_yml_feed'))

    def _parse_feed(self):
        response = self._get_feed_response()
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/xml', response['Content-Type'])
        return response, ET.fromstring(response.content)

    def _offers_by_id(self, xml_root):
        offers = {}
        for offer in xml_root.findall('./shop/offers/offer'):
            offers[offer.attrib['id']] = {
                'available': offer.attrib.get('available'),
                'url': (offer.findtext('url') or '').strip(),
                'price': (offer.findtext('price') or '').strip(),
                'categoryId': (offer.findtext('categoryId') or '').strip(),
                'name': (offer.findtext('name') or '').strip(),
                'description': (offer.findtext('description') or '').strip(),
            }
        return offers

    def test_feed_returns_valid_xml_with_only_vr_attractions_products(self):
        response, xml_root = self._parse_feed()

        self.assertEqual(xml_root.tag, 'yml_catalog')
        self.assertIn('date', xml_root.attrib)
        self.assertEqual(response.status_code, 200)

        offers = self._offers_by_id(xml_root)
        self.assertIn(f'product-{self.single_product.pk}', offers)
        self.assertNotIn(f'product-{self.other_section_product.pk}', offers)
        self.assertNotIn(f'product-{self.unavailable_product.pk}', offers)
        self.assertNotIn(f'product-{self.inactive_product.pk}', offers)

        category_ids = {
            category.attrib['id']
            for category in xml_root.findall('./shop/categories/category')
        }
        self.assertEqual(category_ids, {str(self.category.pk), str(self.variant_category.pk)})

    def test_feed_uses_absolute_product_urls(self):
        _, xml_root = self._parse_feed()

        offers = self._offers_by_id(xml_root)
        offer = offers[f'product-{self.single_product.pk}']
        self.assertEqual(
            offer['url'],
            f'http://testserver{self.single_product.get_absolute_url()}',
        )

    def test_feed_builds_separate_variant_offers_with_correct_names_and_prices(self):
        _, xml_root = self._parse_feed()

        offers = self._offers_by_id(xml_root)
        stock_offer = offers[f'product-{self.variant_product.pk}-variant-{self.variant_stock.pk}']
        on_request_offer = offers[f'product-{self.variant_product.pk}-variant-{self.variant_on_request.pk}']

        self.assertEqual(stock_offer['name'], 'VR-симулятор Drift - Стандарт')
        self.assertEqual(stock_offer['price'], '320000.00')
        self.assertEqual(stock_offer['available'], 'true')

        self.assertEqual(on_request_offer['name'], 'VR-симулятор Drift - Премиум')
        self.assertEqual(on_request_offer['price'], '340000.00')
        self.assertEqual(on_request_offer['available'], 'true')

    def test_feed_keeps_on_request_products_and_uses_checkout_price_rules(self):
        _, xml_root = self._parse_feed()

        offers = self._offers_by_id(xml_root)
        special_price_offer = offers[f'product-{self.on_request_with_special_price.pk}']

        self.assertEqual(special_price_offer['price'], '199000.00')
        self.assertEqual(special_price_offer['available'], 'true')
        self.assertNotIn(f'product-{self.on_request_without_special_price.pk}', offers)

    def test_feed_uses_only_variant_offers_and_skips_empty_categories(self):
        empty_category = Category.objects.create(
            name='Пустые аттракционы',
            slug='empty-attractions',
            section=self.section,
        )
        Product.objects.create(
            category=empty_category,
            name='Пустой аттракцион',
            slug='empty-attraction-product',
            description='Нет ни цены выгрузки, ни доступности.',
            price=Decimal('120000.00'),
            is_active=True,
            allow_order_on_request=False,
        )

        _, xml_root = self._parse_feed()
        offers = self._offers_by_id(xml_root)
        category_ids = {
            category.attrib['id']
            for category in xml_root.findall('./shop/categories/category')
        }

        self.assertNotIn(f'product-{self.variant_product.pk}', offers)
        self.assertNotIn(str(empty_category.pk), category_ids)


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)
@tag('slow')
class VrAttractionsYmlFeedPicturesTest(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)

        self.client = Client()
        self.section, _ = CatalogSection.objects.get_or_create(
            slug='vr-attrakciony',
            defaults={
                'name': 'VR-аттракционы',
                'order': 1,
            },
        )
        self.category = Category.objects.create(
            name='Аттракционы с фото',
            slug='attractions-with-images',
            section=self.section,
        )
        self.city = City.objects.create(name='Екатеринбург', slug='yekaterinburg-feed')
        self.pickup_point = PickupPoint.objects.create(
            city=self.city,
            name='Склад фидов',
            address='Промышленная улица, 7',
        )

    def _png_file(self, name):
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?'
            b'\x00\x05\xfe\x02\xfeA\xd9\x89\xc9\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        return SimpleUploadedFile(name, png_bytes, content_type='image/png')

    def _parse_feed(self):
        response = self.client.get(reverse('vr_attractions_yml_feed'))
        self.assertEqual(response.status_code, 200)
        return ET.fromstring(response.content)

    def _offer_picture_by_id(self, xml_root):
        return {
            offer.attrib['id']: (offer.findtext('picture') or '').strip()
            for offer in xml_root.findall('./shop/offers/offer')
        }

    def test_feed_prefers_variant_picture_over_product_picture(self):
        product = Product.objects.create(
            category=self.category,
            name='VR-симулятор с вариантами',
            slug='vr-simulator-with-variant-picture',
            price=Decimal('450000.00'),
            image=self._png_file('feed-product-main.png'),
            is_active=True,
            allow_order_on_request=True,
        )
        variant = ProductVariant.objects.create(
            product=product,
            name='Максимум',
            image=self._png_file('feed-variant-main.png'),
            order=0,
        )
        ProductStock.objects.create(
            product=product,
            variant=variant,
            pickup_point=self.pickup_point,
            quantity=1,
        )

        pictures = self._offer_picture_by_id(self._parse_feed())

        self.assertEqual(
            pictures[f'product-{product.pk}-variant-{variant.pk}'],
            'http://testserver/media/products/feed-variant-main.png',
        )

    def test_feed_uses_gallery_picture_when_product_has_no_main_image(self):
        product = Product.objects.create(
            category=self.category,
            name='VR-аттракцион с галереей',
            slug='vr-attraction-gallery-picture',
            price=Decimal('180000.00'),
            is_active=True,
            allow_order_on_request=False,
        )
        ProductImage.objects.create(
            product=product,
            image=self._png_file('feed-gallery-image.png'),
            order=0,
        )
        ProductStock.objects.create(
            product=product,
            pickup_point=self.pickup_point,
            quantity=2,
        )

        pictures = self._offer_picture_by_id(self._parse_feed())

        self.assertEqual(
            pictures[f'product-{product.pk}'],
            'http://testserver/media/products/feed-gallery-image.png',
        )



@tag('slow')
class VrAttractionsYmlFeedHelpersTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.section, _ = CatalogSection.objects.get_or_create(
            slug='vr-attrakciony',
            defaults={
                'name': 'VR-аттракционы',
                'order': 1,
            },
        )
        self.category = Category.objects.create(
            name='Хелперы фида',
            slug='feed-helpers',
            section=self.section,
        )
        self.product = Product.objects.create(
            category=self.category,
            name='VR-аттракцион helper',
            slug='vr-attraction-helper',
            price=Decimal('99000.00'),
            is_active=True,
            allow_order_on_request=True,
        )

    @override_settings(SITE_URL='https://bizonvr.example')
    def test_build_absolute_url_falls_back_to_site_url_when_request_builder_fails(self):
        request = self.factory.get('/feeds/vr-attractions.yml')
        request.build_absolute_uri = Mock(side_effect=RuntimeError('boom'))

        absolute_url = feed_views._build_absolute_url(request, '/media/products/test.png')

        self.assertEqual(absolute_url, 'https://bizonvr.example/media/products/test.png')

    def test_build_offer_payload_returns_none_when_price_is_unresolved(self):
        request = self.factory.get('/feeds/vr-attractions.yml')

        with patch('catalog.views.feeds._get_stock_total', return_value=0):
            offer = feed_views._build_offer_payload(request, self.product)

        self.assertIsNone(offer)

    def test_build_offer_payload_uses_on_request_price_when_stock_exists_but_in_stock_price_missing(self):
        request = self.factory.get('/feeds/vr-attractions.yml')
        self.product.price = None
        self.product.price_on_request = Decimal('88000.00')
        self.product.save(update_fields=['price', 'price_on_request'])

        with patch('catalog.views.feeds._get_stock_total', return_value=2):
            offer = feed_views._build_offer_payload(request, self.product)

        self.assertIsNotNone(offer)
        self.assertEqual(offer['price'], '88000.00')



@tag('slow')
class VrAttractionsYmlFeedMissingSectionTest(TestCase):
    def test_feed_returns_404_when_vr_attractions_section_is_missing(self):
        CatalogSection.objects.filter(slug='vr-attrakciony').delete()
        request = RequestFactory().get(reverse('vr_attractions_yml_feed'))
        with self.assertRaisesMessage(Http404, 'VR attractions section is not configured.'):
            vr_attractions_yml_feed_view(request)
