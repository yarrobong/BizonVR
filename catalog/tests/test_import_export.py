from ._shared import *  # noqa: F401,F403


@tag('slow')
class SeedStarvrPacksCommandTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _pack_payload(self, slug):
        module = import_module('catalog.management.commands.seed_starvr_packs')
        return next(pack for pack in module.PACKS if pack['game_pack_slug'] == slug)

    def test_command_creates_games_and_packs(self):
        call_command('seed_starvr_packs')

        digital_section = CatalogSection.objects.get(slug='cifrovye-tovary')
        business_section = CatalogSection.objects.get(slug='resheniya-dlya-vr-biznesa')
        games_category = Category.objects.get(slug='mr-vr-games', section=digital_section)
        packs_category = Category.objects.get(slug='vr-zone-packs', section=business_section)

        self.assertEqual(Product.objects.filter(category=games_category, is_active=True).count(), 5)
        self.assertEqual(
            Product.objects.filter(
                category=packs_category,
                product_kind=Product.PRODUCT_KIND_GAME_PACK,
                is_active=True,
            ).count(),
            3,
        )

        base_pack = Product.objects.get(sku='STARVR-PACK-BASE')
        universal_pack = Product.objects.get(sku='STARVR-PACK-UNIVERSAL')
        all_in_pack = Product.objects.get(sku='STARVR-PACK-ALL-IN')

        self.assertEqual(base_pack.price, Decimal('6990.00'))
        self.assertFalse(base_pack.allow_order_on_request)
        self.assertEqual(base_pack.game_pack_items.count(), 5)

        self.assertEqual(universal_pack.price, Decimal('8990.00'))
        self.assertTrue(
            universal_pack.game_pack_items.filter(title='Настройка шлема', platform='Сервис').exists()
        )

        self.assertEqual(all_in_pack.price, Decimal('9990.00'))
        self.assertTrue(
            all_in_pack.game_pack_items.filter(
                title='Игры для VR-Зон (20 штук на выбор, или из каталога)',
                platform='Доп. библиотека',
            ).exists()
        )

        self.assertTrue(
            GamePackItem.objects.filter(
                product=base_pack,
                title='House Defender: Mixed Reality',
                platform='Meta Quest / MR',
            ).exists()
        )

        self.assertEqual(ProductGameMetadata.objects.filter(is_active=True).count(), 5)
        self.assertTrue(
            ProductGameMetadata.objects.filter(
                product__sku='STARVR-GAME-LASERTAG',
                club_format=ProductGameMetadata.FORMAT_CLUB,
                is_multiplayer=True,
            ).exists()
        )

        self.assertTrue(
            Service.objects.filter(
                name='Настройка шлема',
                price=Decimal('2000.00'),
                is_vr_club_service=True,
                is_active=True,
            ).exists()
        )
        self.assertTrue(
            Service.objects.filter(
                name='Игры для VR-Зон (20 штук на выбор, или из каталога)',
                price=Decimal('1000.00'),
                is_vr_club_service=True,
                is_active=True,
            ).exists()
        )

        club_pack = GamePack.objects.get(slug='starvr-universal')
        maximum_pack = GamePack.objects.get(slug='starvr-all-inclusive')
        self.assertEqual(club_pack.vr_club_tariff, GamePack.TARIFF_CLUB)
        self.assertEqual(club_pack.club_format, ProductGameMetadata.FORMAT_CLUB)
        self.assertEqual(maximum_pack.club_format, ProductGameMetadata.FORMAT_CLUB)
        self.assertTrue(club_pack.show_on_vr_club_page)
        self.assertEqual(club_pack.in_stock_price, Decimal('8990.00'))
        self.assertTrue(
            GamePackServiceEntry.objects.filter(
                game_pack=club_pack,
                service__name='Настройка шлема',
            ).exists()
        )
        self.assertTrue(
            GamePackServiceEntry.objects.filter(
                game_pack=maximum_pack,
                service__name='Игры для VR-Зон (20 штук на выбор, или из каталога)',
            ).exists()
        )

    def test_command_is_idempotent(self):
        call_command('seed_starvr_packs')
        call_command('seed_starvr_packs')

        self.assertEqual(Product.objects.filter(sku__startswith='STARVR-GAME-').count(), 5)
        self.assertEqual(Product.objects.filter(sku__startswith='STARVR-PACK-').count(), 3)
        self.assertEqual(
            Service.objects.filter(
                name__in=[
                    'Настройка шлема',
                    'Игры для VR-Зон (20 штук на выбор, или из каталога)',
                ]
            ).count(),
            2,
        )
        self.assertEqual(
            GamePack.objects.filter(show_on_vr_club_page=True, category__slug='vr-zone-packs').count(),
            3,
        )

    def test_rerun_preserves_existing_game_and_pack_changes(self):
        call_command('seed_starvr_packs')

        game = Product.objects.get(sku='STARVR-GAME-LASERTAG')
        game.name = 'Lasertag Custom'
        game.description = 'Кастомное описание игры'
        game.price = Decimal('5555.00')
        game.save(update_fields=['name', 'description', 'price'])

        game_pack = GamePack.objects.get(slug='starvr-base')
        game_pack.name = 'ПАК "Кастом"'
        game_pack.description = 'Кастомное описание пака'
        game_pack.price = Decimal('12345.00')
        game_pack.included_summary = 'Только одна игра'
        game_pack.save(update_fields=['name', 'description', 'price', 'included_summary'])
        GamePackEntry.objects.filter(game_pack=game_pack).delete()
        GamePackEntry.objects.create(
            game_pack=game_pack,
            product=Product.objects.get(sku='STARVR-GAME-SPATIAL-OPS'),
            platform='Custom platform',
            quantity=1,
            sort_order=1,
        )

        call_command('seed_starvr_packs')

        game.refresh_from_db()
        game_pack.refresh_from_db()

        self.assertEqual(game.name, 'Lasertag Custom')
        self.assertEqual(game.description, 'Кастомное описание игры')
        self.assertEqual(game.price, Decimal('5555.00'))

        self.assertEqual(game_pack.name, 'ПАК "Кастом"')
        self.assertEqual(game_pack.description, 'Кастомное описание пака')
        self.assertEqual(game_pack.price, Decimal('12345.00'))
        self.assertEqual(game_pack.included_summary, 'Только одна игра')
        self.assertEqual(game_pack.entries.count(), 1)
        self.assertEqual(game_pack.entries.get().product.sku, 'STARVR-GAME-SPATIAL-OPS')
        self.assertEqual(game_pack.entries.get().platform, 'Custom platform')

    def test_sync_existing_flag_restores_seed_defaults(self):
        call_command('seed_starvr_packs')

        game = Product.objects.get(sku='STARVR-GAME-LASERTAG')
        game.name = 'Lasertag Custom'
        game.price = Decimal('5555.00')
        game.save(update_fields=['name', 'price'])

        game_pack = GamePack.objects.get(slug='starvr-base')
        game_pack.name = 'ПАК "Кастом"'
        game_pack.price = Decimal('12345.00')
        game_pack.save(update_fields=['name', 'price'])
        GamePackEntry.objects.filter(game_pack=game_pack).delete()

        call_command('seed_starvr_packs', '--sync-existing')

        game.refresh_from_db()
        game_pack.refresh_from_db()
        payload = self._pack_payload('starvr-base')

        self.assertEqual(game.name, 'Lasertag')
        self.assertEqual(game.price, Decimal('1398.00'))
        self.assertEqual(game_pack.name, payload['name'])
        self.assertEqual(game_pack.price, payload['price'])
        self.assertEqual(game_pack.entries.count(), len(payload['games']))

    def test_seeded_game_packs_link_to_single_compatibility_mirror(self):
        call_command('seed_starvr_packs')

        seeded_packs = GamePack.objects.filter(slug__in=['starvr-base', 'starvr-universal', 'starvr-all-inclusive'])
        self.assertEqual(seeded_packs.count(), 3)

        for game_pack in seeded_packs.select_related('mirror_product').prefetch_related('entries', 'service_entries'):
            with self.subTest(game_pack=game_pack.slug):
                self.assertIsNotNone(game_pack.mirror_product)
                self.assertEqual(game_pack.mirror_product.product_kind, Product.PRODUCT_KIND_GAME_PACK)
                self.assertEqual(game_pack.mirror_product.mirrored_game_pack_source, game_pack)
                self.assertEqual(GamePack.objects.filter(mirror_product=game_pack.mirror_product).count(), 1)

    def test_mirror_product_items_match_game_pack_composition(self):
        call_command('seed_starvr_packs')

        for slug in ['starvr-base', 'starvr-universal', 'starvr-all-inclusive']:
            payload = self._pack_payload(slug)
            game_pack = GamePack.objects.select_related('mirror_product').get(slug=slug)
            mirror_items = list(
                game_pack.mirror_product.game_pack_items.order_by('sort_order', 'id').values_list('title', 'platform', 'note')
            )
            expected_items = [
                (item['title'], item.get('platform', ''), item.get('note', ''))
                for item in payload['games'] + payload['services']
            ]

            with self.subTest(game_pack=slug):
                self.assertEqual(mirror_items, expected_items)
                self.assertEqual(game_pack.entries.count() + game_pack.service_entries.count(), len(mirror_items))

    def test_command_reuses_existing_starvr_mirror_product(self):
        legacy_section = CatalogSection.objects.create(name='Legacy', slug='legacy-game-packs')
        legacy_category = Category.objects.create(section=legacy_section, name='Legacy packs', slug='legacy-packs')
        existing_product = Product.objects.create(
            category=legacy_category,
            name='Legacy STARVR Base',
            sku='STARVR-PACK-BASE',
            slug='legacy-starvr-pack-base',
            product_kind=Product.PRODUCT_KIND_GAME_PACK,
            price=Decimal('1.00'),
            is_active=False,
            allow_order_on_request=True,
        )

        call_command('seed_starvr_packs')

        game_pack = GamePack.objects.select_related('mirror_product').get(slug='starvr-base')
        existing_product.refresh_from_db()

        self.assertEqual(game_pack.mirror_product_id, existing_product.pk)
        self.assertEqual(existing_product.category.slug, 'vr-zone-packs')
        self.assertEqual(existing_product.name, game_pack.name)
        self.assertEqual(existing_product.price, game_pack.price)
        self.assertEqual(Product.objects.filter(sku='STARVR-PACK-BASE').count(), 1)
        self.assertEqual(existing_product.game_pack_items.count(), 5)

    def test_rerun_does_not_create_extra_mirrors_or_duplicate_items(self):
        call_command('seed_starvr_packs')
        initial_counts = {
            slug: (
                GamePack.objects.get(slug=slug).mirror_product_id,
                Product.objects.get(sku=self._pack_payload(slug)['sku']).game_pack_items.count(),
            )
            for slug in ['starvr-base', 'starvr-universal', 'starvr-all-inclusive']
        }

        call_command('seed_starvr_packs')

        self.assertEqual(Product.objects.filter(sku__startswith='STARVR-PACK-').count(), 3)
        for slug, (mirror_product_id, mirror_item_count) in initial_counts.items():
            game_pack = GamePack.objects.select_related('mirror_product').get(slug=slug)
            with self.subTest(game_pack=slug):
                self.assertEqual(game_pack.mirror_product_id, mirror_product_id)
                self.assertEqual(game_pack.mirror_product.game_pack_items.count(), mirror_item_count)



@tag('slow')
class NormalizeGameSectionsMigrationTest(TestCase):
    def setUp(self):
        self.migration = import_module('catalog.migrations.0063_normalize_game_sections')
        self.factory = RequestFactory()
        Category.objects.filter(slug__in=['mr-vr-games', 'vr-zone-packs', 'vr-games', 'game-packs']).delete()
        CatalogSection.objects.filter(
            slug__in=['vr-games-and-packs', 'cifrovye-tovary', 'resheniya-dlya-vr-biznesa']
        ).delete()

    def test_renames_legacy_section_and_moves_pack_category_to_business(self):
        legacy_section = CatalogSection.objects.create(name='Legacy games', slug='vr-games-and-packs', order=50)
        business_section = CatalogSection.objects.create(
            name='Business',
            slug='resheniya-dlya-vr-biznesa',
            order=10,
        )
        games_category = Category.objects.create(section=legacy_section, name='Games', slug='mr-vr-games')
        packs_category = Category.objects.create(section=legacy_section, name='Packs', slug='vr-zone-packs')

        self.migration.normalize_game_sections(django_apps, None)

        digital_section = CatalogSection.objects.get(slug='cifrovye-tovary')
        games_category.refresh_from_db()
        packs_category.refresh_from_db()

        self.assertEqual(digital_section.name, 'Цифровые товары')
        self.assertEqual(games_category.section_id, digital_section.id)
        self.assertEqual(games_category.name, 'MR / VR Игры')
        self.assertEqual(packs_category.section_id, business_section.id)
        self.assertEqual(packs_category.name, 'Паки для VR-зон')
        self.assertFalse(CatalogSection.objects.filter(slug='vr-games-and-packs').exists())

    def test_uses_existing_digital_section_and_deletes_empty_legacy_duplicate(self):
        legacy_section = CatalogSection.objects.create(name='Legacy games', slug='vr-games-and-packs', order=50)
        digital_section = CatalogSection.objects.create(name='Old digital', slug='cifrovye-tovary', order=3)
        business_section = CatalogSection.objects.create(
            name='Business',
            slug='resheniya-dlya-vr-biznesa',
            order=10,
        )
        games_category = Category.objects.create(section=legacy_section, name='Games', slug='mr-vr-games')
        packs_category = Category.objects.create(section=legacy_section, name='Packs', slug='vr-zone-packs')

        self.migration.normalize_game_sections(django_apps, None)

        digital_section.refresh_from_db()
        games_category.refresh_from_db()
        packs_category.refresh_from_db()

        self.assertEqual(digital_section.name, 'Цифровые товары')
        self.assertEqual(games_category.section_id, digital_section.id)
        self.assertEqual(packs_category.section_id, business_section.id)
        self.assertFalse(CatalogSection.objects.filter(slug='vr-games-and-packs').exists())

    def test_raises_when_business_section_is_missing(self):
        legacy_section = CatalogSection.objects.create(name='Legacy games', slug='vr-games-and-packs', order=50)
        Category.objects.create(section=legacy_section, name='Packs', slug='vr-zone-packs')

        with self.assertRaisesMessage(RuntimeError, "resheniya-dlya-vr-biznesa"):
            self.migration.normalize_game_sections(django_apps, None)

    def test_missing_form_started_at_does_not_block(self):
        request = self.factory.post('/contacts/', {'message': 'Нужна консультация'})
        self.assertFalse(is_spam_request(request))

    def test_invalid_form_started_at_does_not_block(self):
        request = self.factory.post('/contacts/', {
            'message': 'Нужна консультация',
            'form_started_at': 'not-a-timestamp',
        })
        self.assertFalse(is_spam_request(request))

    def test_two_links_block(self):
        request = self.factory.post('/contacts/', {'message': 'https://spam.example и www.bad.example'})
        result = check_spam_submission(request)
        self.assertTrue(result.is_spam)
        self.assertIn('message_contains_multiple_links', result.reasons)

    def test_spam_word_blocks(self):
        request = self.factory.post('/contacts/', {'message': 'Нужен seo traffic прямо сейчас'})
        result = check_spam_submission(request)
        self.assertFalse(result.is_spam)
        self.assertIn('seo_word:seo', result.reasons)

    def test_normal_payload_passes(self):
        request = self.factory.post('/contacts/', {
            'message': 'Нужна консультация по VR-арене',
            'form_started_at': str(int(time.time()) - 3),
        })
        self.assertFalse(is_spam_request(request))

    def test_telegram_text_does_not_block(self):
        request = self.factory.post('/contacts/', {
            'message': 'Telegram @username',
            'form_started_at': str(int(time.time()) - 3),
        })
        self.assertFalse(is_spam_request(request))

    def test_whatsapp_text_does_not_block(self):
        request = self.factory.post('/contacts/', {
            'message': 'WhatsApp +79991234567',
            'form_started_at': str(int(time.time()) - 3),
        })
        self.assertFalse(is_spam_request(request))



@tag('slow')
class AdminProductExportTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

        self.admin_user = User.objects.create_superuser(
            username='catalog-export-admin',
            email='catalog-export-admin@example.com',
            password='secret123',
        )
        self.client.force_login(self.admin_user)

        self.section_vr = CatalogSection.objects.create(name='VR решения', slug='vr-solutions-admin')
        self.section_attr = CatalogSection.objects.create(name='VR аттракционы', slug='vr-attractions-admin')
        self.category_vr = Category.objects.create(
            name='Шлемы',
            slug='helmets-admin',
            section=self.section_vr,
        )
        self.category_attr = Category.objects.create(
            name='Аттракционы',
            slug='attractions-admin',
            section=self.section_attr,
        )

    def _png_file(self, name='image.png'):
        return SimpleUploadedFile(
            name,
            (
                b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
                b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?'
                b'\x00\x05\xfe\x02\xfeA\xd9\x89\xc9\x00\x00\x00\x00IEND\xaeB`\x82'
            ),
            content_type='image/png',
        )

    def _post_export_action(self, *products):
        return self.client.post(
            reverse('admin:catalog_product_changelist'),
            {
                'action': 'export_catalog_with_images',
                '_selected_action': [str(product.pk) for product in products],
                'index': 0,
                'select_across': 0,
            },
        )

    def test_product_admin_changelist_filters_by_catalog_section(self):
        vr_product = Product.objects.create(
            category=self.category_vr,
            name='Quest 3',
            slug='quest-3-admin-filter',
            price=Decimal('100.00'),
            is_active=True,
        )
        attr_product = Product.objects.create(
            category=self.category_attr,
            name='VR Арена',
            slug='vr-arena-admin-filter',
            price=Decimal('200.00'),
            is_active=True,
        )

        response = self.client.get(
            reverse('admin:catalog_product_changelist'),
            {'category__section__id__exact': str(self.section_vr.pk)},
        )

        self.assertEqual(response.status_code, 200)
        result_slugs = list(response.context['cl'].queryset.values_list('slug', flat=True))
        self.assertEqual(result_slugs, [vr_product.slug])
        self.assertNotIn(attr_product.slug, result_slugs)

    def test_export_catalog_with_images_groups_images_inside_product_folder(self):
        product = Product.objects.create(
            category=self.category_vr,
            name='Quest 3 Комплект',
            slug='quest-3-export',
            price=Decimal('123.00'),
            is_active=True,
            image=self._png_file('main.png'),
        )
        ProductVariant.objects.create(
            product=product,
            name='128 GB / White',
            sku='VAR-128',
            image=self._png_file('variant.png'),
            order=10,
        )
        ProductImage.objects.create(
            product=product,
            image=self._png_file('gallery.png'),
            order=5,
        )

        response = self._post_export_action(product)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')

        with zipfile.ZipFile(BytesIO(response.content), 'r') as archive:
            names = set(archive.namelist())

        self.assertIn('catalog_export.csv', names)
        self.assertIn('images/Quest 3 Комплект/main.png', names)
        self.assertIn('images/Quest 3 Комплект/variant_128 GB _ White.png', names)
        self.assertIn('images/Quest 3 Комплект/extra_5.png', names)

    def test_export_catalog_with_images_keeps_separate_product_folders_for_shared_source_file(self):
        first_product = Product.objects.create(
            category=self.category_vr,
            name='Shared Image One',
            slug='shared-image-one',
            price=Decimal('100.00'),
            is_active=True,
            image=self._png_file('shared-source.png'),
        )
        second_product = Product.objects.create(
            category=self.category_vr,
            name='Shared Image Two',
            slug='shared-image-two',
            price=Decimal('100.00'),
            is_active=True,
        )
        second_product.image = first_product.image.name
        second_product.save(update_fields=['image'])

        response = self._post_export_action(first_product, second_product)

        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(BytesIO(response.content), 'r') as archive:
            names = set(archive.namelist())

        self.assertIn('images/Shared Image One/main.png', names)
        self.assertIn('images/Shared Image Two/main.png', names)

    def test_export_catalog_with_images_adds_slug_suffix_for_duplicate_product_names(self):
        first_product = Product.objects.create(
            category=self.category_vr,
            name='Одинаковое имя',
            slug='duplicate-name-one',
            price=Decimal('100.00'),
            is_active=True,
            image=self._png_file('duplicate-one.png'),
        )
        second_product = Product.objects.create(
            category=self.category_vr,
            name='Одинаковое имя',
            slug='duplicate-name-two',
            price=Decimal('100.00'),
            is_active=True,
            image=self._png_file('duplicate-two.png'),
        )

        response = self._post_export_action(first_product, second_product)

        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(BytesIO(response.content), 'r') as archive:
            names = set(archive.namelist())

        self.assertIn('images/Одинаковое имя/main.png', names)
        self.assertIn('images/Одинаковое имя (duplicate-name-two)/main.png', names)



@tag('slow')
class CatalogJsonImportServiceTest(TestCase):
    def _payload(self, *, product_name='Импортируемый товар', price='199.00', stock_qty=4, include_media=False):
        product_item = {
            'id': 1,
            'name': product_name,
            'slug': 'json-product',
            'sku': 'SKU-001',
            'description': 'Описание JSON товара',
            'price': price,
            'discount_percent': '7.50',
            'price_on_request': '149.00',
            'is_active': True,
            'allow_order_on_request': True,
            'avito_url': 'https://example.com/avito',
            'ozon_url': 'https://example.com/ozon',
            'wildberries_url': 'https://example.com/wb',
            'option_label': 'Комплектация',
            'category_id': 1,
            'tag_ids': [1],
        }
        variant_item = {
            'id': 1,
            'product_id': 1,
            'name': '64 GB',
            'sku': 'VAR-64',
            'price_override': '209.00',
            'price_on_request_override': '159.00',
            'order': 10,
        }
        payload = {
            'version': '1.1',
            'models': {
                'catalog_sections': [
                    {'id': 1, 'name': 'VR', 'slug': 'vr', 'order': 1},
                ],
                'categories': [
                    {'id': 1, 'name': 'Шлемы', 'slug': 'headsets', 'section_id': 1},
                    {
                        'id': 2,
                        'name': 'Комплекты',
                        'slug': 'bundle-headsets',
                        'section_id': 1,
                        'is_bundles_category': True,
                    },
                ],
                'product_tags': [
                    {'id': 1, 'name': 'Новинка', 'slug': 'new', 'order': 1},
                ],
                'products': [product_item],
                'product_variants': [variant_item],
                'product_characteristics': [
                    {'id': 1, 'product_id': 1, 'name': 'Память', 'value': '64 ГБ'},
                ],
                'product_variant_characteristics': [
                    {'id': 1, 'variant_id': 1, 'name': 'Цвет', 'value': 'Черный'},
                ],
                'product_images': [],
                'product_videos': [
                    {
                        'id': 1,
                        'product_id': 1,
                        'rutube_url': 'https://rutube.ru/video/1234567890abcdef1234567890abcdef/',
                        'title': 'Обзор',
                        'thumbnail_url': 'https://cdn.example.com/thumb.jpg',
                        'order': 1,
                    },
                ],
                'product_content_blocks': [
                    {
                        'id': 1,
                        'product_id': 1,
                        'block_type': ProductContentBlock.BlockType.TEXT,
                        'title': 'Почему стоит купить',
                        'text': 'Подробный текст для карточки.',
                        'sort_order': 1,
                        'is_active': True,
                    },
                ],
                'product_bundles': [
                    {
                        'id': 1,
                        'category_id': 2,
                        'name': 'Комплект VR',
                        'slug': 'vr-kit',
                        'description': 'Комплект',
                    },
                ],
                'product_bundle_items': [
                    {'id': 1, 'bundle_id': 1, 'product_id': 1, 'quantity': 2},
                ],
                'cities': [
                    {'id': 1, 'name': 'Екатеринбург', 'slug': 'ekb', 'order': 1},
                ],
                'pickup_points': [
                    {'id': 1, 'city_id': 1, 'name': 'Склад', 'address': 'ул. Тестовая, 1', 'order': 1},
                ],
                'product_stocks': [
                    {'id': 1, 'product_id': 1, 'pickup_point_id': 1, 'variant_id': 1, 'quantity': stock_qty},
                ],
            },
        }
        if include_media:
            payload['models']['products'][0]['image'] = 'products/main.png'
            payload['models']['product_variants'][0]['image'] = 'products/variant.png'
            payload['models']['product_images'].append(
                {'id': 1, 'product_id': 1, 'image': 'products/extra.png', 'order': 1}
            )
        return payload

    def test_import_upserts_without_duplicates_and_preserves_omitted_data(self):
        unrelated_category = Category.objects.create(name='Другое', slug='other')
        unrelated_product = Product.objects.create(category=unrelated_category, name='Лишний', slug='extra')

        report_first = CatalogDataImporter(self._payload()).import_data()
        self.assertEqual(report_first.created['products'], 1)
        self.assertEqual(Product.objects.filter(slug='json-product').count(), 1)

        product = Product.objects.get(slug='json-product')
        extra_variant = ProductVariant.objects.create(product=product, name='128 GB', sku='VAR-128', order=20)
        city = City.objects.get(slug='ekb')
        pickup_point = PickupPoint.objects.get(city=city, name='Склад')
        ProductStock.objects.create(product=product, pickup_point=pickup_point, variant=extra_variant, quantity=9)

        report_second = CatalogDataImporter(
            self._payload(product_name='Обновлённый товар', price='299.00', stock_qty=7)
        ).import_data()

        product.refresh_from_db()
        variant = ProductVariant.objects.get(product=product, sku='VAR-64')
        stock = ProductStock.objects.get(product=product, pickup_point=pickup_point, variant=variant)

        self.assertEqual(report_second.updated['products'], 1)
        self.assertEqual(Product.objects.filter(slug='json-product').count(), 1)
        self.assertEqual(ProductVariant.objects.filter(product=product, sku='VAR-64').count(), 1)
        self.assertEqual(product.name, 'Обновлённый товар')
        self.assertEqual(product.price, Decimal('299.00'))
        self.assertEqual(product.discount_percent, Decimal('7.50'))
        self.assertEqual(stock.quantity, 7)
        self.assertTrue(ProductVariant.objects.filter(product=product, sku='VAR-128').exists())
        self.assertTrue(ProductStock.objects.filter(product=product, variant=extra_variant, quantity=9).exists())
        self.assertTrue(Product.objects.filter(pk=unrelated_product.pk).exists())
        self.assertEqual(ProductVideo.objects.filter(product=product).count(), 1)
        self.assertEqual(ProductContentBlock.objects.filter(product=product).count(), 1)

    def test_import_supports_old_backup_schema_without_new_fields(self):
        payload = {
            'version': '1.0',
            'models': {
                'catalog_sections': [],
                'categories': [
                    {'id': 1, 'name': 'Тест', 'slug': 'legacy-category', 'section_id': None},
                ],
                'product_tags': [],
                'products': [
                    {
                        'id': 1,
                        'name': 'Legacy товар',
                        'slug': 'legacy-product',
                        'description': '',
                        'price': '10.00',
                        'is_active': True,
                        'allow_order_on_request': True,
                        'option_label': '',
                        'category_id': 1,
                        'tag_ids': [],
                    },
                ],
                'product_variants': [],
                'product_characteristics': [],
                'product_variant_characteristics': [],
                'product_images': [],
                'product_bundles': [],
                'product_bundle_items': [],
                'cities': [],
                'pickup_points': [],
                'product_stocks': [],
            },
        }

        CatalogDataImporter(payload).import_data()

        product = Product.objects.get(slug='legacy-product')
        self.assertEqual(product.name, 'Legacy товар')
        self.assertEqual(product.price, Decimal('10.00'))
        self.assertEqual(product.discount_percent, Decimal('0.00'))
        self.assertEqual(product.sku, '')

    def test_import_ignores_media_fields_and_reports_warnings(self):
        report = CatalogDataImporter(self._payload(include_media=True)).import_data()

        product = Product.objects.get(slug='json-product')
        variant = ProductVariant.objects.get(product=product, sku='VAR-64')

        self.assertFalse(product.image)
        self.assertFalse(variant.image)
        self.assertEqual(ProductImage.objects.count(), 0)
        self.assertTrue(report.warnings)
        self.assertTrue(any('products.image' in warning for warning in report.warnings))

    def test_import_dry_run_rolls_back_changes(self):
        report = CatalogDataImporter(self._payload()).import_data(dry_run=True)

        self.assertEqual(report.created['products'], 1)
        self.assertFalse(Product.objects.filter(slug='json-product').exists())

    def test_backup_catalog_includes_extended_schema_fields(self):
        category = Category.objects.create(name='Экспорт', slug='export-category')
        product = Product.objects.create(
            category=category,
            name='Экспортируемый товар',
            slug='export-product',
            sku='SKU-EXP',
            price=Decimal('300.00'),
            discount_percent=Decimal('15.00'),
            price_on_request=Decimal('250.00'),
            avito_url='https://example.com/avito',
            ozon_url='https://example.com/ozon',
            wildberries_url='https://example.com/wb',
            option_label='Модификация',
        )
        ProductVariant.objects.create(
            product=product,
            name='128 GB',
            sku='VAR-128',
            price_override=Decimal('320.00'),
            price_on_request_override=Decimal('270.00'),
        )
        with patch('catalog.models._fetch_rutube_video_metadata', return_value={}):
            ProductVideo.objects.create(
                product=product,
                rutube_url='https://rutube.ru/video/1234567890abcdef1234567890abcdef/',
                order=1,
            )
        ProductContentBlock.objects.create(
            product=product,
            block_type=ProductContentBlock.BlockType.TEXT,
            title='Детали',
            text='Подробности',
            sort_order=1,
        )

        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
            output_path = temp_file.name
        self.addCleanup(lambda: os.path.exists(output_path) and os.remove(output_path))

        call_command('backup_catalog', output=output_path)

        with zipfile.ZipFile(output_path, 'r') as archive:
            backup_data = json.loads(archive.read('backup.json').decode('utf-8'))

        product_item = backup_data['models']['products'][0]
        variant_item = backup_data['models']['product_variants'][0]

        self.assertIn('product_videos', backup_data['models'])
        self.assertIn('product_content_blocks', backup_data['models'])
        self.assertEqual(product_item['sku'], 'SKU-EXP')
        self.assertEqual(product_item['discount_percent'], '15.00')
        self.assertEqual(product_item['price_on_request'], '250.00')
        self.assertEqual(product_item['avito_url'], 'https://example.com/avito')
        self.assertEqual(variant_item['sku'], 'VAR-128')
        self.assertEqual(variant_item['price_on_request_override'], '270.00')



@tag('slow')
class CatalogJsonImportWorkflowTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Workflow', slug='workflow-category')
        self.alt_category = Category.objects.create(name='Alt Workflow', slug='workflow-category-alt')
        self.tag = ProductTag.objects.create(name='Рекомендуем', slug='recommended')
        self.existing_product = Product.objects.create(
            category=self.category,
            name='Старый товар',
            slug='occupied-slug',
            description='Старое описание',
            price=Decimal('100.00'),
            is_active=True,
            allow_order_on_request=True,
        )

    def _payload(self, *, slug='occupied-slug', name='Новый товар', description='Новое описание', price='150.00', category_ref=None, tag_refs=None):
        return {
            'version': '1.1',
            'models': {
                'catalog_sections': [],
                'categories': [],
                'product_tags': [],
                'products': [
                    {
                        'id': 1,
                        'name': name,
                        'slug': slug,
                        'description': description,
                        'price': price,
                        'is_active': True,
                        'allow_order_on_request': True,
                        'option_label': '',
                        'category_id': category_ref if category_ref is not None else make_direct_target_reference(self.category.pk),
                        'tag_ids': tag_refs if tag_refs is not None else [],
                    },
                ],
                'product_variants': [],
                'product_characteristics': [],
                'product_variant_characteristics': [],
                'product_images': [],
                'product_videos': [],
                'product_content_blocks': [],
                'product_bundles': [],
                'product_bundle_items': [],
                'cities': [],
                'pickup_points': [],
                'product_stocks': [],
            },
        }

    def _create_batch(self, payload):
        return CatalogImportWorkflowService.create_batch(payload=payload, source_filename='catalog.json')

    def _resolution_post(self, conflict, overrides=None):
        overrides = overrides or {}
        post_data = QueryDict('', mutable=True)
        for field_name, meta in (conflict.field_conflicts or {}).items():
            if field_name.startswith('__'):
                continue
            config = overrides.get(field_name, {'mode': 'take_incoming'})
            post_data[f'mode__{field_name}'] = config['mode']
            if config['mode'] != 'manual':
                continue
            value = config.get('value')
            if meta.get('field_type') == 'multiselect':
                post_data.setlist(f'manual__{field_name}', [str(item) for item in (value or [])])
            else:
                post_data[f'manual__{field_name}'] = '' if value is None else str(value)
        return post_data

    def test_existing_slug_creates_review_conflict(self):
        batch = self._create_batch(self._payload())

        conflict = batch.conflicts.get(collection_name='products')

        self.assertEqual(conflict.status, CatalogImportConflict.Status.PENDING)
        self.assertIn('name', conflict.field_conflicts)
        self.assertIn('description', conflict.field_conflicts)
        self.assertIn('price', conflict.field_conflicts)
        self.assertIn('slug', conflict.field_conflicts)
        self.assertEqual(Product.objects.filter(slug='occupied-slug').count(), 1)

    def test_manual_slug_change_revalidates_and_creates_new_product(self):
        batch = self._create_batch(self._payload())
        conflict = batch.conflicts.get(collection_name='products')

        CatalogImportWorkflowService(batch).save_conflict_resolution(
            conflict,
            self._resolution_post(
                conflict,
                overrides={'slug': {'mode': 'manual', 'value': 'fresh-slug'}},
            ),
        )

        batch.refresh_from_db()
        conflict.refresh_from_db()

        self.assertEqual(conflict.status, CatalogImportConflict.Status.RESOLVED)
        self.assertEqual(batch.editable_payload['models']['products'][0]['slug'], 'fresh-slug')

        CatalogImportWorkflowService(batch).apply_resolved_rows()

        self.assertTrue(Product.objects.filter(slug='fresh-slug').exists())
        self.assertTrue(Product.objects.filter(pk=self.existing_product.pk, slug='occupied-slug').exists())

    def test_keep_current_take_incoming_and_manual_values_apply_exactly(self):
        batch = self._create_batch(self._payload())
        conflict = batch.conflicts.get(collection_name='products')

        CatalogImportWorkflowService(batch).save_conflict_resolution(
            conflict,
            self._resolution_post(
                conflict,
                overrides={
                    'name': {'mode': 'keep_current'},
                    'description': {'mode': 'take_incoming'},
                    'price': {'mode': 'manual', 'value': '199.00'},
                },
            ),
        )
        CatalogImportWorkflowService(batch).apply_resolved_rows()

        self.existing_product.refresh_from_db()
        self.assertEqual(self.existing_product.name, 'Старый товар')
        self.assertEqual(self.existing_product.description, 'Новое описание')
        self.assertEqual(self.existing_product.price, Decimal('199.00'))

    def test_manual_fk_and_tag_resolution_persist_and_apply(self):
        payload = self._payload(
            slug='new-with-manual-links',
            name='Товар с ручными связями',
            category_ref=999,
            tag_refs=[888],
        )
        batch = self._create_batch(payload)
        conflict = batch.conflicts.get(collection_name='products')

        CatalogImportWorkflowService(batch).save_conflict_resolution(
            conflict,
            self._resolution_post(
                conflict,
                overrides={
                    'category': {'mode': 'manual', 'value': self.alt_category.pk},
                    'tag_ids': {'mode': 'manual', 'value': [self.tag.pk]},
                },
            ),
        )

        batch.refresh_from_db()
        editable_item = batch.editable_payload['models']['products'][0]
        self.assertEqual(editable_item['category_id'], make_direct_target_reference(self.alt_category.pk))
        self.assertEqual(editable_item['tag_ids'], [make_direct_target_reference(self.tag.pk)])

        CatalogImportWorkflowService(batch).apply_resolved_rows()

        product = Product.objects.get(slug='new-with-manual-links')
        self.assertEqual(product.category, self.alt_category)
        self.assertEqual(list(product.tags.values_list('id', flat=True)), [self.tag.pk])

    def test_apply_clean_rows_imports_only_ready_rows_and_is_idempotent(self):
        payload = self._payload(slug='occupied-slug', name='Конфликтный товар')
        payload['models']['products'].append(
            {
                'id': 2,
                'name': 'Чистый товар',
                'slug': 'clean-product',
                'description': '',
                'price': '77.00',
                'is_active': True,
                'allow_order_on_request': True,
                'option_label': '',
                'category_id': make_direct_target_reference(self.category.pk),
                'tag_ids': [],
            }
        )

        batch = self._create_batch(payload)
        workflow = CatalogImportWorkflowService(batch)
        workflow.apply_clean_rows()
        workflow.apply_clean_rows()

        self.assertTrue(Product.objects.filter(slug='clean-product').exists())
        self.assertEqual(Product.objects.filter(slug='clean-product').count(), 1)
        self.assertGreaterEqual(
            batch.conflicts.filter(collection_name='products', status=CatalogImportConflict.Status.PENDING).count(),
            1,
        )
        self.existing_product.refresh_from_db()
        self.assertEqual(self.existing_product.name, 'Старый товар')
