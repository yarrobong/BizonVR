from ._shared import *  # noqa: F401,F403

class VariantGalleryAndCatalogCardsTest(TestCase):
    """Варианты: предвыбор на PDP и отдельные карточки в каталоге."""

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Варианты', slug='variants')
        self.product = Product.objects.create(
            category=self.category,
            name='Quest 3',
            slug='quest-3-variants',
            price=1000,
            is_active=True,
        )
        self.variant_one = ProductVariant.objects.create(
            product=self.product,
            name='Белый',
            price_override=1200,
            order=0,
        )
        self.variant_two = ProductVariant.objects.create(
            product=self.product,
            name='Черный',
            price_override=1300,
            order=1,
        )
        self.foreign_product = Product.objects.create(
            category=self.category,
            name='Pico 4',
            slug='pico-4-variants',
            price=900,
            is_active=True,
        )
        self.foreign_variant = ProductVariant.objects.create(
            product=self.foreign_product,
            name='Синий',
            price_override=950,
        )
        self.simple_product = Product.objects.create(
            category=self.category,
            name='Meta Quest Pro',
            slug='meta-quest-pro-simple',
            price=800,
            is_active=True,
        )
        self.city = City.objects.create(name='Екатеринбург', slug='ekb')
        self.pickup_point = PickupPoint.objects.create(city=self.city, name='Точка 1')

    def _extract_product_detail_data(self, response):
        html = response.content.decode()
        match = re.search(
            r'<div id="product-detail-data" data-product-detail="([^"]+)" hidden></div>',
            html,
            re.S,
        )
        self.assertIsNotNone(match)
        return json.loads(html_lib.unescape(match.group(1)))

    def _mock_http_response(self, *, json_data=None, text='', status_code=200):
        response = Mock()
        response.status_code = status_code
        response.text = text
        response.json.return_value = json_data or {}
        response.raise_for_status = Mock()
        return response

    def test_product_detail_accepts_variant_query_and_sets_initial_variant_id(self):
        resp = self.client.get(
            reverse('catalog:product_detail', kwargs={'slug': self.product.slug}),
            {'variant': self.variant_two.pk},
        )
        self.assertEqual(resp.status_code, 200)
        data = self._extract_product_detail_data(resp)
        self.assertEqual(data.get('initialVariantId'), self.variant_two.pk)

    def test_product_detail_ignores_foreign_or_invalid_variant_query(self):
        detail_url = reverse('catalog:product_detail', kwargs={'slug': self.product.slug})

        foreign_resp = self.client.get(detail_url, {'variant': self.foreign_variant.pk})
        self.assertEqual(foreign_resp.status_code, 200)
        foreign_data = self._extract_product_detail_data(foreign_resp)
        self.assertIsNone(foreign_data.get('initialVariantId'))

        invalid_resp = self.client.get(detail_url, {'variant': 'abc'})
        self.assertEqual(invalid_resp.status_code, 200)
        invalid_data = self._extract_product_detail_data(invalid_resp)
        self.assertIsNone(invalid_data.get('initialVariantId'))

    def test_product_detail_renders_initial_main_image_without_alpine(self):
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?'
            b'\x00\x05\xfe\x02\xfeA\xd9\x89\xc9\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        self.product.image = SimpleUploadedFile('detail.png', png_bytes, content_type='image/png')
        self.product.save(update_fields=['image'])

        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        self.assertRegex(
            html,
            r'<img\s+src="http://testserver/media/products/[^"]+"[^>]*class="main-image"',
        )
        self.assertIn('x-bind:src="effectiveImage ||', html)

    def test_responsive_image_builder_generates_cached_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(MEDIA_ROOT=temp_dir):
                self.product.image = _build_test_uploaded_image('responsive-source.jpg')
                self.product.save(update_fields=['image'])

                data = build_responsive_image_data(
                    self.product.image,
                    widths=(320, 640, 1600),
                    default_width=640,
                )

                self.assertIn('/media/cache/responsive/', data['src'])
                self.assertIn('320w', data['srcset'])
                self.assertIn('640w', data['srcset'])
                self.assertIn('1600w', data['srcset'])
                self.assertTrue((Path(temp_dir) / 'cache' / 'responsive').exists())

    def test_product_detail_serializes_responsive_media_and_srcset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(MEDIA_ROOT=temp_dir):
                self.product.image = _build_test_uploaded_image('detail-responsive.jpg')
                self.product.save(update_fields=['image'])
                self.variant_one.image = _build_test_uploaded_image(
                    'variant-responsive.jpg',
                    size=(1200, 1200),
                )
                self.variant_one.save(update_fields=['image'])

                resp = self.client.get(
                    reverse('catalog:product_detail', kwargs={'slug': self.product.slug}),
                    {'variant': self.variant_one.pk},
                )

                self.assertEqual(resp.status_code, 200)
                data = self._extract_product_detail_data(resp)
                html = resp.content.decode()
                first_media = data['productMedia'][0]
                variant_payload = next(item for item in data['variants'] if item['id'] == self.variant_one.pk)

                self.assertIn('imageSrcset', first_media)
                self.assertIn('/media/cache/responsive/', first_media['imageSrcset'])
                self.assertIn('thumbnailSrcset', first_media)
                self.assertIn('imageSrcset', variant_payload)
                self.assertIn('thumbnailSrcset', variant_payload)
                self.assertIn('srcset="', html)
                self.assertIn(':srcset="media.thumbnailSrcset || null"', html)

    def test_product_detail_renders_mobile_back_header_in_mobile_slot(self):
        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        self.assertRegex(
            html,
            r'<div id="mobile-header-slot"[^>]*>\s*<div class="pd-mobile-header md:hidden"',
        )
        self.assertIn('class="pd-mobile-icon-btn pd-mobile-back-btn"', html)
        self.assertIn('aria-label="Назад"', html)
        self.assertNotIn('pd-mobile-back-btn__label', html)

    def test_product_detail_hides_footer_products_feed(self):
        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))

        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="footer-products-feed"', html=False)

    def test_product_detail_htmx_response_keeps_selected_content_only(self):
        resp = self.client.get(
            reverse('catalog:product_detail', kwargs={'slug': self.product.slug}),
            HTTP_HX_REQUEST='true',
            HTTP_HX_BOOSTED='true',
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        self.assertIn(f'<title>{self.product.name} — BizonVR</title>', html)
        self.assertIn('id="mobile-header-slot"', html)
        self.assertIn('class="pd-mobile-header md:hidden"', html)
        self.assertIn('id="main-content"', html)
        self.assertIn('id="product-detail-data"', html)
        self.assertIn('id="htmx-active-section"', html)
        self.assertNotIn('<html', html)
        self.assertNotIn('id="main-body"', html)
        self.assertNotIn('id="sticky-header"', html)
        self.assertNotIn('id="catalog-overlay"', html)
        self.assertNotIn('class="vr-footer"', html)
        self.assertNotIn('id="cookie-consent-banner"', html)
        self.assertNotIn('class="mobile-dock"', html)
        self.assertNotIn('id="footer-products-feed"', html)
        self.assertNotIn('<script', html)

    def test_product_detail_mobile_search_uses_full_navigation_and_visible_qty_has_id(self):
        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        self.assertIn('method="get" hx-boost="false" class="pd-mobile-search-form"', html)
        self.assertIn('id="mobile-qty-visible"', html)
        self.assertIn('@pageshow.window="mobileSearchOpen = false; $nextTick(() => updateHeaderFilled())"', html)
        self.assertIn('observeElementViewportState', html)
        self.assertNotIn('@scroll.window.passive="updateHeaderFilled()"', html)
        self.assertNotIn('@resize.window="updateHeaderFilled()"', html)

    def test_product_detail_renders_unified_mobile_hero_layout(self):
        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        self.assertIn('class="mobile-hero-card mobile-only"', html)
        self.assertIn('class="mobile-hero-purchase"', html)
        self.assertNotIn('class="mobile-card mobile-only"', html)
        self.assertNotIn('class="mobile-hero-about"', html)
        self.assertNotIn('class="mobile-hero-subtitle"', html)

    def test_lucide_icon_template_tag_renders_inline_svg_with_alpine_attrs(self):
        html = Template(
            '{% load catalog_tags %}'
            '{% lucide_icon "x" "w-4 h-4" x_show="catalogOverlayOpen" x_cloak=1 aria_hidden="false" %}'
        ).render(Context())

        self.assertIn('<svg', html)
        self.assertIn('class="lucide-icon lucide-icon--x w-4 h-4"', html)
        self.assertIn('x-show="catalogOverlayOpen"', html)
        self.assertIn('x-cloak', html)
        self.assertIn('aria-hidden="false"', html)
        self.assertNotIn('data-lucide=', html)

    def test_catalog_product_card_placeholder_uses_inline_svg(self):
        request = RequestFactory().get(reverse('catalog:product_list'))
        html = Template('{% include "catalog/_product_card.html" %}').render(
            Context(
                {
                    'request': request,
                    'product': self.product,
                    'show_favorite': False,
                    'show_add_button': False,
                    'favorite_product_ids': None,
                    'product_stock_total': {},
                    'variant_stock_total': {},
                    'recommended_variant_ids': {},
                    'from_favorites_page': False,
                }
            )
        )

        self.assertIn('lucide-icon--image-off', html)
        self.assertNotIn('data-lucide="image-off"', html)
        self.assertNotIn('lucide.createIcons()', html)

    def test_product_card_gallery_images_puts_variant_first_and_removes_duplicates(self):
        primary = _build_test_uploaded_image('product-primary.jpg')
        extra = _build_test_uploaded_image('product-extra.jpg')
        variant_image = _build_test_uploaded_image('variant-image.jpg')
        self.product.image = primary
        self.product.save(update_fields=['image'])
        self.product.images.create(image=primary, order=0)
        self.product.images.create(image=extra, order=1)
        variant = ProductVariant.objects.create(product=self.product, name='512 GB', image=variant_image)
        extra_saved_name = self.product.images.order_by('order', 'id')[1].image.name

        gallery_images = build_product_card_gallery_images(self.product, variant)

        self.assertEqual(
            [image.name for image in gallery_images],
            [variant.image.name, self.product.image.name, extra_saved_name],
        )

    def test_catalog_product_card_renders_gallery_segments_for_multiple_images(self):
        request = RequestFactory().get(reverse('catalog:product_list'))
        self.product.image = _build_test_uploaded_image('gallery-primary.jpg')
        self.product.save(update_fields=['image'])
        self.product.images.create(image=_build_test_uploaded_image('gallery-extra-1.jpg'), order=0)
        self.product.images.create(image=_build_test_uploaded_image('gallery-extra-2.jpg'), order=1)

        html = Template('{% include "catalog/_product_card.html" %}').render(
            Context(
                {
                    'request': request,
                    'product': self.product,
                    'show_favorite': False,
                    'show_add_button': False,
                    'favorite_product_ids': None,
                    'product_stock_total': {},
                    'variant_stock_total': {},
                    'recommended_variant_ids': {},
                    'from_favorites_page': False,
                }
            )
        )

        self.assertIn('data-product-card-gallery', html)
        self.assertEqual(html.count('data-product-card-segment') - html.count('data-product-card-segments'), 3)

    def test_product_card_gallery_images_are_limited_to_five(self):
        self.product.image = _build_test_uploaded_image('gallery-limit-primary.jpg')
        self.product.save(update_fields=['image'])
        for index in range(1, 8):
            self.product.images.create(
                image=_build_test_uploaded_image(f'gallery-limit-extra-{index}.jpg'),
                order=index,
            )

        gallery_images = build_product_card_gallery_images(self.product)

        self.assertEqual(len(gallery_images), 5)

    def test_home_page_footer_mobile_dock_uses_inline_home_icon(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        self.assertIn('lucide-icon--home', html)
        self.assertNotIn('<i data-lucide="home"', html)
        self.assertNotIn('class="floating-action__summary"', html)

    def test_product_detail_keeps_variant_picker_inside_mobile_hero(self):
        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        hero_index = html.index('class="mobile-hero-card mobile-only"')
        variants_index = html.index('class="mobile-hero-variants"')
        desktop_info_index = html.index('class="product-info desktop-only"')

        self.assertLess(hero_index, variants_index)
        self.assertLess(variants_index, desktop_info_index)

    def test_product_detail_places_mobile_marketplaces_before_description_block(self):
        self.product.avito_url = 'https://example.com/avito'
        self.product.save(update_fields=['avito_url'])

        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        self.assertIn('data-marketplace-link="avito"', html)
        self.assertIn('class="product-details-block"', html)
        self.assertLess(
            html.index('data-marketplace-link="avito"'),
            html.index('class="product-details-block"'),
        )

    def test_bundle_detail_mobile_search_uses_full_navigation(self):
        bundle_category = Category.objects.create(
            name='Комплекты',
            slug='variant-bundles',
            is_bundles_category=True,
        )
        bundle = ProductBundle.objects.create(
            category=bundle_category,
            name='Quest Pro Pack',
            slug='quest-pro-pack',
        )
        ProductBundleItem.objects.create(bundle=bundle, product=self.product, quantity=1)
        ProductBundleItem.objects.create(bundle=bundle, product=self.foreign_product, quantity=1)

        resp = self.client.get(reverse('catalog:bundle_detail', kwargs={'slug': bundle.slug}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        self.assertIn('method="get" hx-boost="false" class="pd-mobile-search-form"', html)
        self.assertIn('observeElementViewportState', html)
        self.assertNotIn('@scroll.window.passive="updateHeaderFilled()"', html)
        self.assertNotIn('@resize.window="updateHeaderFilled()"', html)

    def test_bundle_detail_no_longer_shows_bundle_discount_copy(self):
        bundle_category = Category.objects.create(
            name='Комплекты без скидки',
            slug='bundle-no-discount',
            is_bundles_category=True,
        )
        bundle = ProductBundle.objects.create(
            category=bundle_category,
            name='Quest Full Pack',
            slug='quest-full-pack',
        )
        ProductBundleItem.objects.create(bundle=bundle, product=self.product, quantity=1)
        ProductBundleItem.objects.create(bundle=bundle, product=self.foreign_product, quantity=1)

        resp = self.client.get(reverse('catalog:bundle_detail', kwargs={'slug': bundle.slug}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Итого:')
        self.assertNotContains(resp, '−5%')
        self.assertNotContains(resp, 'Итого со скидкой')

    def test_bundle_detail_shows_old_total_when_item_has_product_discount(self):
        self.product.discount_percent = Decimal('10.00')
        self.product.save(update_fields=['discount_percent'])
        bundle_category = Category.objects.create(
            name='Комплекты со скидкой товара',
            slug='bundle-product-discount',
            is_bundles_category=True,
        )
        bundle = ProductBundle.objects.create(
            category=bundle_category,
            name='Quest Discount Pack',
            slug='quest-discount-pack',
        )
        ProductBundleItem.objects.create(bundle=bundle, product=self.product, quantity=1)
        ProductBundleItem.objects.create(bundle=bundle, product=self.foreign_product, quantity=1)

        resp = self.client.get(reverse('catalog:bundle_detail', kwargs={'slug': bundle.slug}))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '1 800 ₽')
        self.assertContains(resp, '1 900 ₽')

    def test_product_discount_applies_to_product_and_variant_in_stock_price(self):
        self.product.discount_percent = Decimal('10.00')
        self.product.save(update_fields=['discount_percent'])

        self.assertEqual(resolve_in_stock_price(self.product), Decimal('900.00'))
        self.assertEqual(resolve_in_stock_price(self.product, self.variant_one), Decimal('1080.00'))

    def test_catalog_filters_and_sort_controls_render_identifiers_for_form_fields(self):
        project_root = str(PROJECT_ROOT)
        with open(os.path.join(project_root, 'templates', 'catalog', '_filters_price_tags.html'), encoding='utf-8') as fh:
            price_filters_html = fh.read()
        with open(
            os.path.join(project_root, 'templates', 'catalog', 'product_list', '_filters_summary.html'),
            encoding='utf-8',
        ) as fh:
            filters_summary_html = fh.read()
        with open(
            os.path.join(project_root, 'templates', 'catalog', 'product_list', '_sort_controls.html'),
            encoding='utf-8',
        ) as fh:
            sort_controls_html = fh.read()

        self.assertIn('x-id="[\'price-range-min\', \'price-range-max\']"', price_filters_html)
        self.assertIn(':id="$id(\'price-range-min\')"', price_filters_html)
        self.assertIn(':id="$id(\'price-range-max\')"', price_filters_html)
        self.assertIn('x-id="[\'price-range-min\', \'price-range-max\']"', filters_summary_html)
        self.assertIn(':id="$id(\'price-range-min\')"', filters_summary_html)
        self.assertIn(':id="$id(\'price-range-max\')"', filters_summary_html)
        self.assertIn('id="catalog-sort-select"', sort_controls_html)
        self.assertIn('name="sort"', sort_controls_html)

    def test_product_video_save_normalizes_public_rutube_url_and_fetches_metadata(self):
        with patch('catalog.models.requests.get') as mock_get:
            mock_get.return_value = self._mock_http_response(json_data={
                'title': 'Видео обзор Quest 3',
                'thumbnail_url': 'https://cdn.example/rutube-thumb.jpg',
                'html': '<iframe src="https://rutube.ru/play/embed/7716bd3e665725c3c008ae7ab4ff02e2"></iframe>',
            })
            video = ProductVideo.objects.create(
                product=self.product,
                rutube_url='https://www.rutube.ru/video/7716bd3e665725c3c008ae7ab4ff02e2/?utm_source=test',
                order=3,
            )

        self.assertEqual(video.rutube_url, 'https://rutube.ru/video/7716bd3e665725c3c008ae7ab4ff02e2/')
        self.assertEqual(video.rutube_video_id, '7716bd3e665725c3c008ae7ab4ff02e2')
        self.assertEqual(video.embed_url, 'https://rutube.ru/play/embed/7716bd3e665725c3c008ae7ab4ff02e2')
        self.assertEqual(video.thumbnail_url, 'https://cdn.example/rutube-thumb.jpg')
        self.assertEqual(video.title, 'Видео обзор Quest 3')
        self.assertEqual(mock_get.call_count, 1)

    def test_product_video_rejects_non_rutube_or_private_links(self):
        with self.assertRaises(ValidationError):
            ProductVideo(product=self.product, rutube_url='https://youtube.com/watch?v=abc').clean()

        with self.assertRaises(ValidationError):
            ProductVideo(
                product=self.product,
                rutube_url='https://rutube.ru/video/private/7716bd3e665725c3c008ae7ab4ff02e2/?p=secret',
            ).clean()

    def test_product_detail_includes_rutube_video_after_images_and_renders_lazy_player_markup(self):
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?'
            b'\x00\x05\xfe\x02\xfeA\xd9\x89\xc9\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        self.product.image = SimpleUploadedFile('detail-main.png', png_bytes, content_type='image/png')
        self.product.save(update_fields=['image'])
        self.product.images.create(
            image=SimpleUploadedFile('detail-extra.png', png_bytes, content_type='image/png'),
            order=1,
        )
        ProductVideo.objects.bulk_create([
            ProductVideo(
                product=self.product,
                rutube_url='https://rutube.ru/video/7716bd3e665725c3c008ae7ab4ff02e2/',
                rutube_video_id='7716bd3e665725c3c008ae7ab4ff02e2',
                embed_url='https://rutube.ru/play/embed/7716bd3e665725c3c008ae7ab4ff02e2',
                thumbnail_url='https://cdn.example/rutube-poster.jpg',
                title='Видео обзор Quest 3',
                order=0,
            ),
        ])

        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(resp.status_code, 200)
        data = self._extract_product_detail_data(resp)
        html = resp.content.decode()

        self.assertEqual(data['productMedia'][0]['type'], 'image')
        self.assertEqual(data['productMedia'][-1]['type'], 'video')
        self.assertEqual(
            data['productMedia'][-1]['embedUrl'],
            'https://rutube.ru/play/embed/7716bd3e665725c3c008ae7ab4ff02e2',
        )
        self.assertEqual(data['productMedia'][-1]['thumbnailUrl'], 'https://cdn.example/rutube-poster.jpg')
        self.assertIn('class="main-video-poster"', html)
        self.assertIn('activateCurrentVideo()', html)
        self.assertIn('loading="lazy"', html)
        self.assertIn('thumb-video-play', html)
        self.assertIn("effectiveMedia && effectiveMedia.type === 'video'", html)

    def test_product_detail_keeps_video_without_thumbnail_and_has_fallback_marker(self):
        ProductVideo.objects.bulk_create([
            ProductVideo(
                product=self.product,
                rutube_url='https://rutube.ru/video/7716bd3e665725c3c008ae7ab4ff02e2/',
                rutube_video_id='7716bd3e665725c3c008ae7ab4ff02e2',
                embed_url='https://rutube.ru/play/embed/7716bd3e665725c3c008ae7ab4ff02e2',
                thumbnail_url='',
                title='Видео без постера',
                order=0,
            ),
        ])

        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(resp.status_code, 200)
        data = self._extract_product_detail_data(resp)
        html = resp.content.decode()

        self.assertEqual(data['productMedia'][0]['type'], 'video')
        self.assertEqual(data['productMedia'][0]['thumbnailUrl'], '')
        self.assertIn('thumb-video--fallback', html)
        self.assertIn('thumb-video-label', html)

    def test_catalog_renders_all_variants_as_cards_without_base_product_card(self):
        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        detail_url = reverse('catalog:product_detail', kwargs={'slug': self.product.slug})

        self.assertIn(f'href="{detail_url}?variant={self.variant_one.pk}"', html)
        self.assertIn(f'href="{detail_url}?variant={self.variant_two.pk}"', html)
        self.assertNotIn(f'href="{detail_url}"', html)

    def test_variant_card_links_include_variant_query(self):
        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        detail_url = reverse('catalog:product_detail', kwargs={'slug': self.product.slug})
        links = re.findall(rf'href="{re.escape(detail_url)}\?variant=\d+"', html)
        self.assertGreaterEqual(len(links), 2)

    def test_variant_card_uses_variant_price_and_public_stock_label(self):
        self.variant_one.price_on_request_override = Decimal('1100.00')
        self.variant_one.save(update_fields=['price_on_request_override'])
        ProductStock.objects.create(
            product=self.product,
            variant=self.variant_one,
            pickup_point=self.pickup_point,
            quantity=3,
        )

        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['variant_stock_total'].get(self.variant_one.pk), 3)
        self.assertNotIn('variant_stock_in_city', resp.context)
        self.assertContains(resp, '1 200 ₽')
        self.assertContains(resp, 'В наличии')
        self.assertContains(resp, 'Мало')
        self.assertContains(resp, 'Доставка за 5 дней')
        self.assertContains(resp, 'Под заказ —')
        self.assertContains(resp, '1 100 ₽')
        self.assertContains(resp, 'Срок поставки: 22–28 дней')
        self.assertNotContains(resp, 'В наличии:')
        self.assertNotContains(resp, 'шт. осталось')

    def test_variant_card_shows_high_stock_label(self):
        ProductStock.objects.create(
            product=self.product,
            variant=self.variant_one,
            pickup_point=self.pickup_point,
            quantity=10,
        )

        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'В наличии')
        self.assertContains(resp, 'Много')

    def test_variant_card_shows_on_request_without_stock(self):
        self.variant_one.price_on_request_override = Decimal('1100.00')
        self.variant_one.save(update_fields=['price_on_request_override'])
        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Под заказ')
        self.assertContains(resp, '1 100 ₽')
        self.assertContains(resp, 'Срок поставки: 22–28 дней')
        self.assertNotContains(resp, '1 200 ₽')

    def test_variant_card_shows_in_stock_price_even_when_out_of_stock(self):
        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '1 200 ₽')
        self.assertContains(resp, '1 300 ₽')
        self.assertContains(resp, 'Нет в наличии')
        self.assertNotContains(resp, 'Цена не указана')

    def test_product_card_shows_base_price_even_when_out_of_stock(self):
        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '800 ₽')
        self.assertContains(resp, 'Нет в наличии')
        self.assertNotContains(resp, 'Цена не указана')

    def test_variant_card_prefers_on_request_when_stock_exists_but_in_stock_price_missing(self):
        self.product.price = None
        self.product.save(update_fields=['price'])
        self.variant_one.price_override = None
        self.variant_one.price_on_request_override = Decimal('1100.00')
        self.variant_one.save(update_fields=['price_override', 'price_on_request_override'])
        ProductStock.objects.create(
            product=self.product,
            variant=self.variant_one,
            pickup_point=self.pickup_point,
            quantity=2,
        )

        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Под заказ')
        self.assertContains(resp, '1 100 ₽')
        self.assertNotContains(resp, 'В наличии')

    def test_variant_card_shows_price_not_specified_when_no_public_price(self):
        self.product.price = None
        self.product.save(update_fields=['price'])
        self.variant_one.price_override = None
        self.variant_one.price_on_request_override = None
        self.variant_one.save(update_fields=['price_override', 'price_on_request_override'])
        ProductStock.objects.create(
            product=self.product,
            variant=self.variant_one,
            pickup_point=self.pickup_point,
            quantity=2,
        )

        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Цена не указана')
        self.assertContains(resp, 'Оставить заявку')

    def test_product_detail_shows_in_stock_and_on_request_delivery_terms(self):
        self.variant_one.price_on_request_override = Decimal('1100.00')
        self.variant_one.save(update_fields=['price_on_request_override'])
        ProductStock.objects.create(
            product=self.product,
            variant=self.variant_one,
            pickup_point=self.pickup_point,
            quantity=3,
        )

        resp = self.client.get(
            reverse('catalog:product_detail', kwargs={'slug': self.product.slug}),
            {'variant': self.variant_one.pk},
        )

        self.assertEqual(resp.status_code, 200)
        data = self._extract_product_detail_data(resp)
        self.assertContains(resp, 'В наличии')
        self.assertContains(resp, 'Мало')
        self.assertContains(resp, 'Доставка за 5 дней')
        self.assertContains(resp, 'Под заказ')
        self.assertContains(resp, 'Срок поставки: 22–28 дней')
        variant_payload = next(item for item in data['variants'] if item['id'] == self.variant_one.pk)
        self.assertEqual(variant_payload['onRequestPrice'], 1100.0)

    def test_product_detail_shows_only_on_request_price_when_out_of_stock(self):
        self.variant_one.price_on_request_override = Decimal('1100.00')
        self.variant_one.save(update_fields=['price_on_request_override'])

        resp = self.client.get(
            reverse('catalog:product_detail', kwargs={'slug': self.product.slug}),
            {'variant': self.variant_one.pk},
        )

        self.assertEqual(resp.status_code, 200)
        data = self._extract_product_detail_data(resp)
        self.assertContains(resp, 'Под заказ')
        self.assertContains(resp, 'Срок поставки: 22–28 дней')
        variant_payload = next(item for item in data['variants'] if item['id'] == self.variant_one.pk)
        self.assertEqual(variant_payload['onRequestPrice'], 1100.0)
        self.assertEqual(variant_payload['inStockPrice'], 1200.0)

    def test_product_detail_switches_to_request_only_when_variant_has_no_public_price(self):
        self.product.price = None
        self.product.save(update_fields=['price'])
        self.variant_one.price_override = None
        self.variant_one.price_on_request_override = None
        self.variant_one.save(update_fields=['price_override', 'price_on_request_override'])
        ProductStock.objects.create(
            product=self.product,
            variant=self.variant_one,
            pickup_point=self.pickup_point,
            quantity=1,
        )

        resp = self.client.get(
            reverse('catalog:product_detail', kwargs={'slug': self.product.slug}),
            {'variant': self.variant_one.pk},
        )

        self.assertEqual(resp.status_code, 200)
        data = self._extract_product_detail_data(resp)
        variant_payload = next(item for item in data['variants'] if item['id'] == self.variant_one.pk)
        self.assertEqual(variant_payload['publicPurchaseMode'], 'request_only')
        self.assertIsNone(variant_payload['effectivePrice'])
        self.assertContains(resp, 'Оставить заявку')
        self.assertContains(resp, 'class="purchase-request-panel', html=False)
        self.assertContains(resp, 'id="purchase-request"', html=False)
        self.assertNotContains(resp, 'Цена не указана')

    def test_product_detail_data_uses_total_stock_only(self):
        ProductStock.objects.create(
            product=self.product,
            variant=self.variant_one,
            pickup_point=self.pickup_point,
            quantity=11,
        )

        resp = self.client.get(
            reverse('catalog:product_detail', kwargs={'slug': self.product.slug}),
            {'variant': self.variant_one.pk},
        )
        self.assertEqual(resp.status_code, 200)
        data = self._extract_product_detail_data(resp)
        self.assertIn('stockByVariant', data)
        self.assertIn('stockStatusByVariant', data)
        self.assertIn('stockStatusProduct', data)
        self.assertNotIn('stockInCityByVariant', data)
        self.assertNotIn('stockInCityProduct', data)
        self.assertNotIn('selectedCityName', data)
        self.assertNotContains(resp, 'Укажите город')

    def test_product_accepts_empty_marketplace_urls(self):
        self.product.avito_url = ''
        self.product.ozon_url = ''
        self.product.wildberries_url = ''
        self.product.full_clean()
        self.product.save(update_fields=['avito_url', 'ozon_url', 'wildberries_url'])

        self.product.refresh_from_db()
        self.assertEqual(self.product.avito_url, '')
        self.assertEqual(self.product.ozon_url, '')
        self.assertEqual(self.product.wildberries_url, '')

    def test_product_detail_hides_marketplace_block_without_links(self):
        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Также на маркетплейсах')
        self.assertNotContains(resp, 'data-marketplace-link=')

    def test_product_detail_renders_single_avito_marketplace_link(self):
        self.product.avito_url = 'https://www.avito.ru/test-product'
        self.product.save(update_fields=['avito_url'])

        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        self.assertContains(resp, 'Также на маркетплейсах')
        self.assertEqual(html.count('data-marketplace-link='), 1)
        self.assertIn('data-marketplace-link="avito"', html)
        self.assertIn('href="https://www.avito.ru/test-product"', html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertNotIn('data-marketplace-link="ozon"', html)
        self.assertNotIn('data-marketplace-link="wildberries"', html)

    def test_product_detail_renders_marketplace_links_in_fixed_order(self):
        self.product.avito_url = 'https://www.avito.ru/test-product'
        self.product.ozon_url = 'https://www.ozon.ru/product/test-product/'
        self.product.wildberries_url = 'https://www.wildberries.ru/catalog/123/detail.aspx'
        self.product.save(update_fields=['avito_url', 'ozon_url', 'wildberries_url'])

        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        avito_pos = html.index('data-marketplace-link="avito"')
        ozon_pos = html.index('data-marketplace-link="ozon"')
        wildberries_pos = html.index('data-marketplace-link="wildberries"')

        self.assertLess(avito_pos, ozon_pos)
        self.assertLess(ozon_pos, wildberries_pos)


class ProductRecommendationsTest(TestCase):
    """PDP-рекомендации: фильтры совместимости/исключений + секции."""

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Аксессуары', slug='aksessuary')

        self.current = Product.objects.create(
            category=self.category,
            name='Meta Quest 3 Headset',
            slug='meta-quest-3-headset',
            price=50000,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.current, name='Тип', value='Шлем')
        ProductCharacteristic.objects.create(product=self.current, name='Совместимость', value='Quest 3')

        self.strap = Product.objects.create(
            category=self.category,
            name='Head Strap Quest 3',
            slug='head-strap-quest-3',
            price=7000,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.strap, name='Тип', value='Крепление')
        ProductCharacteristic.objects.create(product=self.strap, name='Совместимость', value='Quest 3')
        self.strap_variant = ProductVariant.objects.create(
            product=self.strap,
            name='Elite',
            price_override=7900,
            order=0,
        )

        self.battery = Product.objects.create(
            category=self.category,
            name='Battery Pack Quest 3',
            slug='battery-pack-quest-3',
            price=6000,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.battery, name='Тип', value='Аккумулятор')
        ProductCharacteristic.objects.create(product=self.battery, name='Совместимость', value='Quest 3')

        self.incompatible = Product.objects.create(
            category=self.category,
            name='Pico 4 Case',
            slug='pico-4-case',
            price=3000,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.incompatible, name='Тип', value='Кейс')
        ProductCharacteristic.objects.create(product=self.incompatible, name='Совместимость', value='Pico 4')

        self.bundle_item = Product.objects.create(
            category=self.category,
            name='Quest 3 Face Cover',
            slug='quest-3-face-cover',
            price=2500,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=self.bundle_item, name='Тип', value='Защита')
        ProductCharacteristic.objects.create(product=self.bundle_item, name='Совместимость', value='Quest 3')

        bundle = ProductBundle.objects.create(
            category=Category.objects.create(
                name='Рекомендованные комплекты',
                slug='recommendation-bundles',
                is_bundles_category=True,
            ),
            name='Bundle',
        )
        ProductBundleItem.objects.create(bundle=bundle, product=self.current, quantity=1)
        ProductBundleItem.objects.create(bundle=bundle, product=self.bundle_item, quantity=1)

        order = Order.objects.create(status=Order.STATUS_DONE, total=57000)
        OrderItem.objects.create(order=order, product=self.current, quantity=1, price=self.current.price)
        OrderItem.objects.create(order=order, product=self.strap, quantity=1, price=self.strap.price)

        # Товар в корзине должен исключаться из рекомендаций.
        session = self.client.session
        session['cart_items'] = [{
            'product_id': self.battery.pk,
            'variant_id': None,
            'name': self.battery.name,
            'price': float(self.battery.price),
            'quantity': 1,
            'subtotal': float(self.battery.price),
        }]
        session.save()

    def _get_product_response(self, product):
        return self.client.get(reverse('catalog:product_detail', kwargs={'slug': product.slug}))

    def _get_recommendation_section(self, response, key):
        return next(section for section in response.context['recommendation_sections'] if section['key'] == key)

    def _get_similar_product_ids(self, product):
        response = self._get_product_response(product)
        section = self._get_recommendation_section(response, 'similar_products')
        return response, [recommended.pk for recommended in section['products']]

    def test_recommendations_apply_filters_and_sections(self):
        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.current.slug}))
        self.assertEqual(resp.status_code, 200)

        sections = resp.context['recommendation_sections']
        self.assertTrue(sections)
        section_keys = [s['key'] for s in sections]
        self.assertIn('frequently_bought', section_keys)
        self.assertIn('similar_products', section_keys)
        self.assertNotIn('compatible_accessories', section_keys)
        self.assertNotIn('alternatives', section_keys)

        recommended_ids = {p.pk for s in sections for p in s['products']}
        self.assertIn(self.strap.pk, recommended_ids)
        self.assertNotIn(self.current.pk, recommended_ids)
        self.assertNotIn(self.battery.pk, recommended_ids)  # в корзине
        self.assertNotIn(self.incompatible.pk, recommended_ids)  # несовместим
        self.assertNotIn(self.bundle_item.pk, recommended_ids)  # часть комплекта
        self.assertContains(resp, 'Похожие')
        self.assertNotContains(resp, 'Рекомендации')
        self.assertNotContains(resp, 'Подборка:')
        self.assertNotContains(resp, 'tracking-wider bg-accent/15 text-accent border border-accent/30">Похожие</span>')
        self.assertNotContains(resp, 'Аксессуары, которые подходят')
        self.assertNotContains(resp, 'Альтернативы')

    def test_recommendation_cards_use_recommended_variant_for_link_and_price(self):
        city = City.objects.create(name='Екатеринбург PDP', slug='pdp-ekb')
        pickup_point = PickupPoint.objects.create(city=city, name='PDP склад')
        ProductStock.objects.create(
            product=self.strap,
            variant=self.strap_variant,
            pickup_point=pickup_point,
            quantity=3,
        )
        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.current.slug}))
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(
            resp.context['recommended_variants'].get(self.strap.pk),
            self.strap_variant,
        )
        self.assertContains(
            resp,
            f'href="{reverse("catalog:product_detail", kwargs={"slug": self.strap.slug})}?variant={self.strap_variant.pk}"',
        )
        self.assertContains(resp, '7 900 ₽')

    def test_similar_products_follow_category_first_cascade(self):
        cases = Category.objects.create(name='Кейсы PDP', slug='pdp-cases')
        covers = Category.objects.create(name='Защита PDP', slug='pdp-covers')
        current = Product.objects.create(
            category=cases,
            name='BOBOVR C3 Quest 3 кейс',
            slug='bobovr-c3-quest-3-case',
            price=7000,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=current, name='Совместимость', value='Quest 3')

        same_category_compat = Product.objects.create(
            category=cases,
            name='Кейс Универсальный для Quest 3',
            slug='quest-3-universal-case',
            price=6500,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=same_category_compat, name='Совместимость', value='Meta Quest 3 и Quest 3S')

        same_category_tokens = Product.objects.create(
            category=cases,
            name='BOBOVR Travel Bag',
            slug='bobovr-travel-bag',
            price=5000,
            is_active=True,
            views_count=500,
        )

        same_category_lexical = Product.objects.create(
            category=cases,
            name='Кейс Народный',
            slug='narodny-case',
            price=3500,
            is_active=True,
            views_count=900,
        )

        cross_category_fallback = Product.objects.create(
            category=covers,
            name='Quest 3 Face Cover',
            slug='quest-3-face-cover-pdp',
            price=2500,
            is_active=True,
            views_count=9999,
        )
        ProductCharacteristic.objects.create(product=cross_category_fallback, name='Совместимость', value='Quest 3')

        _, similar_ids = self._get_similar_product_ids(current)

        self.assertEqual(
            similar_ids[:4],
            [
                same_category_compat.pk,
                same_category_tokens.pk,
                same_category_lexical.pk,
                cross_category_fallback.pk,
            ],
        )

    def test_similar_products_allow_same_category_lexical_fallback_without_compatibility(self):
        cases = Category.objects.create(name='Кейсы без совместимости', slug='cases-no-compat')
        current = Product.objects.create(
            category=cases,
            name='Кейс Народный',
            slug='narodny-base-case',
            price=5000,
            is_active=True,
        )
        lexical_fallback = Product.objects.create(
            category=cases,
            name='Кейс Брат',
            slug='brat-case',
            price=5200,
            is_active=True,
        )
        Product.objects.create(
            category=cases,
            name='Зарядная станция BD3',
            slug='bd3-dock-case-test',
            price=8900,
            is_active=True,
        )

        _, similar_ids = self._get_similar_product_ids(current)

        self.assertEqual(similar_ids, [lexical_fallback.pk])

    def test_similar_products_use_cross_category_only_as_last_resort(self):
        cases = Category.objects.create(name='Кейсы fallback', slug='cases-fallback')
        covers = Category.objects.create(name='Защита fallback', slug='covers-fallback')
        current = Product.objects.create(
            category=cases,
            name='Quest 3 Travel Case',
            slug='quest-3-travel-case-fallback',
            price=6000,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=current, name='Совместимость', value='Quest 3')

        same_category_candidate = Product.objects.create(
            category=cases,
            name='Quest 3 Compact Case',
            slug='quest-3-compact-case',
            price=5500,
            is_active=True,
        )

        cross_category_good = Product.objects.create(
            category=covers,
            name='Quest 3 Face Cover',
            slug='quest-3-face-cover-fallback',
            price=2300,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=cross_category_good, name='Совместимость', value='Meta Quest 3')

        cross_category_bad = Product.objects.create(
            category=covers,
            name='Universal Comfort Pad',
            slug='universal-comfort-pad',
            price=1900,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=cross_category_bad, name='Совместимость', value='Quest 3')

        _, similar_ids = self._get_similar_product_ids(current)

        self.assertIn(same_category_candidate.pk, similar_ids)
        self.assertIn(cross_category_good.pk, similar_ids)
        self.assertLess(similar_ids.index(same_category_candidate.pk), similar_ids.index(cross_category_good.pk))
        if cross_category_bad.pk in similar_ids:
            self.assertLess(similar_ids.index(cross_category_good.pk), similar_ids.index(cross_category_bad.pk))

    def test_similar_products_ignore_price_when_other_signals_equal(self):
        cases = Category.objects.create(name='Кейсы price', slug='cases-price')
        current = Product.objects.create(
            category=cases,
            name='Quest 3 Carry Case',
            slug='quest-3-carry-case-current',
            price=6000,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=current, name='Совместимость', value='Quest 3')

        cheap_first = Product.objects.create(
            category=cases,
            name='Quest 3 Carry Case',
            slug='quest-3-carry-case-cheap',
            price=1000,
            is_active=True,
        )
        expensive_second = Product.objects.create(
            category=cases,
            name='Quest 3 Carry Case',
            slug='quest-3-carry-case-expensive',
            price=9000,
            is_active=True,
        )
        ProductCharacteristic.objects.create(product=cheap_first, name='Совместимость', value='Quest 3')
        ProductCharacteristic.objects.create(product=expensive_second, name='Совместимость', value='Quest 3')

        _, similar_ids = self._get_similar_product_ids(current)

        self.assertEqual(similar_ids[:2], [cheap_first.pk, expensive_second.pk])
