from ._shared import *  # noqa: F401,F403

from config.formatting import format_currency_amount

from catalog.admin.game_packs import (
    GamePackAdmin,
    GamePackEntryInline,
    GamePackEntryInlineForm,
    GamePackServiceEntryInline,
    GamePackServiceEntryInlineForm,
)
from catalog.models import ProductVariantCharacteristic

class ProductAdminGamePackMirrorTest(TestCase):
    def setUp(self):
        self.section = CatalogSection.objects.create(name='Catalog', slug='catalog-section')
        self.category = Category.objects.create(section=self.section, name='Game packs', slug='game-packs')
        self.admin_user = User.objects.create_superuser(
            username='mirror-admin',
            email='mirror-admin@example.com',
            password='password',
        )
        self.product_admin = ProductAdmin(Product, admin.site)
        self.mirror_product = Product.objects.create(
            category=self.category,
            name='Mirror Product',
            sku='STARVR-PACK-MIRROR',
            slug='mirror-product',
            product_kind=Product.PRODUCT_KIND_GAME_PACK,
            price=Decimal('4900.00'),
            is_active=True,
        )
        self.game_pack = GamePack.objects.create(
            category=self.category,
            mirror_product=self.mirror_product,
            name='Mirror Game Pack',
            slug='mirror-game-pack',
            price=Decimal('4900.00'),
            is_active=True,
        )
        self.legacy_product = Product.objects.create(
            category=self.category,
            name='Legacy Product Pack',
            sku='LEGACY-PACK-1',
            slug='legacy-product-pack',
            product_kind=Product.PRODUCT_KIND_GAME_PACK,
            price=Decimal('3900.00'),
            is_active=True,
        )

    def _request(self):
        request = RequestFactory().get('/admin/catalog/product/')
        request.user = self.admin_user
        return request

    def test_mirrored_product_admin_is_read_only_and_points_to_game_pack(self):
        request = self._request()

        readonly_fields = self.product_admin.get_readonly_fields(request, obj=self.mirror_product)
        notice = str(self.product_admin.mirror_source_notice(self.mirror_product))

        self.assertTrue(set(ProductAdmin.MIRRORED_PRODUCT_READONLY_FIELDS).issubset(set(readonly_fields)))
        self.assertIn('mirror_source_notice', readonly_fields)
        self.assertIn(reverse('admin:catalog_gamepack_change', args=[self.game_pack.pk]), notice)
        self.assertIn('generated compatibility mirror', notice)

    def test_mirrored_product_admin_hides_editing_affordances(self):
        request = self._request()

        fieldsets = self.product_admin.get_fieldsets(request, obj=self.mirror_product)
        duplicate_link = str(self.product_admin.duplicate_game_pack_link(self.mirror_product))

        self.assertEqual(fieldsets[0][0], 'Compatibility mirror')
        self.assertEqual(self.product_admin.get_inline_instances(request, obj=self.mirror_product), [])
        self.assertNotIn('href=', duplicate_link)

    def test_non_mirrored_legacy_pack_remains_editable(self):
        request = self._request()

        readonly_fields = self.product_admin.get_readonly_fields(request, obj=self.legacy_product)
        duplicate_link = str(self.product_admin.duplicate_game_pack_link(self.legacy_product))

        self.assertNotIn('name', readonly_fields)
        self.assertNotIn('mirror_source_notice', readonly_fields)
        self.assertIn('href=', duplicate_link)


class GamePackAdminConfigurationTest(TestCase):
    def setUp(self):
        self.section = CatalogSection.objects.create(name='Catalog', slug='catalog-section')
        self.category = Category.objects.create(section=self.section, name='Game packs', slug='game-packs')
        self.admin_user = User.objects.create_superuser(
            username='game-pack-admin',
            email='game-pack-admin@example.com',
            password='password',
        )
        self.game_pack_admin = GamePackAdmin(GamePack, admin.site)
        self.entry_inline = GamePackEntryInline(GamePack, admin.site)
        self.service_inline = GamePackServiceEntryInline(GamePack, admin.site)
        self.product = Product.objects.create(
            category=self.category,
            name='Arena Heroes',
            slug='arena-heroes',
            price=Decimal('1500.00'),
            is_active=True,
        )
        self.game_pack = GamePack.objects.create(
            category=self.category,
            name='Club Pack',
            slug='club-pack',
            price=Decimal('4900.00'),
            is_active=True,
        )
        self.entry = GamePackEntry.objects.create(
            game_pack=self.game_pack,
            product=self.product,
            quantity=2,
            sort_order=1,
        )

    def _request(self):
        request = RequestFactory().get('/admin/catalog/gamepack/')
        request.user = self.admin_user
        return request

    def test_game_pack_admin_uses_bundle_like_inline_fields(self):
        self.assertEqual(
            self.entry_inline.fields,
            ('product', 'quantity', 'price_preview', 'unresolved_title', 'platform', 'note', 'sort_order'),
        )
        self.assertEqual(self.entry_inline.readonly_fields, ('price_preview',))
        self.assertEqual(self.entry_inline.extra, 1)
        self.assertEqual(
            self.service_inline.fields,
            ('service', 'quantity', 'price', 'title', 'platform', 'note', 'sort_order'),
        )
        self.assertEqual(self.service_inline.extra, 1)

    def test_game_pack_entry_price_preview_uses_catalog_price(self):
        preview = self.entry_inline.price_preview(self.entry)

        self.assertEqual(preview, format_currency_amount(self.product.price))

    def test_game_pack_admin_exposes_image_preview_and_items_count(self):
        fieldsets = self.game_pack_admin.get_fieldsets(self._request(), obj=self.game_pack)
        main_fields = fieldsets[0][1]['fields']

        self.assertIn('image_preview', self.game_pack_admin.readonly_fields)
        self.assertLess(main_fields.index('image_preview'), main_fields.index('image'))
        self.assertEqual(self.game_pack_admin.items_count(self.game_pack), 1)

    def test_legacy_unresolved_title_remains_supported_in_inline_form(self):
        form = GamePackEntryInlineForm(data={
            'game_pack': self.game_pack.pk,
            'product': '',
            'unresolved_title': 'Legacy Shooter',
            'platform': 'Quest',
            'quantity': 1,
            'note': '',
            'sort_order': 0,
        })
        legacy_entry = GamePackEntry(
            game_pack=self.game_pack,
            unresolved_title='Legacy Shooter',
            quantity=1,
        )

        self.assertIn('legacy', form.fields['unresolved_title'].help_text.lower())
        self.assertTrue(form.is_valid(), form.errors)
        legacy_entry.full_clean()
        self.assertEqual(self.entry_inline.price_preview(legacy_entry), '—')

    def test_service_inline_form_marks_manual_title_as_legacy_fallback(self):
        form = GamePackServiceEntryInlineForm()

        self.assertIn('Основной сценарий', form.fields['service'].help_text)
        self.assertIn('legacy', form.fields['title'].help_text.lower())
        self.assertEqual(form.fields['title'].label, 'Временное название')



class AdminCatalogExcelExportTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username='excel-manager',
            password='testpass',
            is_staff=True,
        )
        self.view_permission = Permission.objects.get(codename='view_product')
        self.section = CatalogSection.objects.create(name='VR', slug='vr-section')
        self.category = Category.objects.create(section=self.section, name='Шлемы', slug='vr-headsets')

    def _login_staff(self, *, with_view_permission=False):
        if with_view_permission:
            self.staff_user.user_permissions.add(self.view_permission)
        self.client.force_login(self.staff_user)

    def _image_upload(self, filename, color):
        buffer = BytesIO()
        PilImage.new('RGB', (24, 24), color=color).save(buffer, format='PNG')
        buffer.seek(0)
        return SimpleUploadedFile(filename, buffer.getvalue(), content_type='image/png')

    def test_export_excel_endpoint_requires_view_permission(self):
        self._login_staff()

        response = self.client.get(reverse('admin:catalog_product_export_excel'))

        self.assertEqual(response.status_code, 403)

    def test_export_excel_button_visible_with_view_permission(self):
        self._login_staff(with_view_permission=True)

        response = self.client.get(reverse('admin:catalog_product_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('admin:catalog_product_export_excel'))
        self.assertContains(response, 'Экспорт Excel')

    def test_export_excel_contains_product_data_links_and_embedded_images(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                product = Product.objects.create(
                    category=self.category,
                    name='Meta Quest 3',
                    sku='QUEST3-128',
                    slug='meta-quest-3',
                    description='Автономный VR-шлем для дома и бизнеса.',
                    price=Decimal('54990.00'),
                    discount_percent=Decimal('5.00'),
                    price_on_request=Decimal('49990.00'),
                    image=self._image_upload('quest3.png', '#0ea5e9'),
                    is_active=True,
                    allow_order_on_request=True,
                    avito_url='https://www.avito.ru/item-1',
                    ozon_url='https://www.ozon.ru/product-1',
                    wildberries_url='https://www.wildberries.ru/catalog/1/detail.aspx',
                )
                product.tags.add(ProductTag.objects.create(name='Хит', slug='hit'))
                ProductCharacteristic.objects.create(product=product, name='Память', value='128 ГБ')
                variant = ProductVariant.objects.create(
                    product=product,
                    name='Quest 3 512GB',
                    sku='QUEST3-512',
                    image=self._image_upload('quest3-512.png', '#22c55e'),
                    price_override=Decimal('64990.00'),
                    price_on_request_override=Decimal('61990.00'),
                )
                ProductVariantCharacteristic.objects.create(
                    variant=variant,
                    name='Память',
                    value='512 ГБ',
                )
                ProductImage.objects.create(
                    product=product,
                    image=self._image_upload('quest3-side.png', '#f97316'),
                    order=1,
                )

                self._login_staff(with_view_permission=True)
                response = self.client.get(reverse('admin:catalog_product_export_excel'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertIn('attachment; filename="catalog_export_', response['Content-Disposition'])

        from openpyxl import load_workbook

        workbook = load_workbook(BytesIO(response.content))
        worksheet = workbook['Каталог']
        expected_product_url = f'http://testserver{product.get_absolute_url()}'

        self.assertEqual(worksheet['B2'].value, product.name)
        self.assertEqual(worksheet['C2'].value, self.section.name)
        self.assertEqual(worksheet['D2'].value, self.category.name)
        self.assertEqual(worksheet['F2'].value, expected_product_url)
        self.assertEqual(worksheet['F2'].hyperlink.target, expected_product_url)
        self.assertEqual(worksheet['G2'].value, product.sku)
        self.assertEqual(worksheet['H2'].value, product.slug)
        self.assertEqual(worksheet['I2'].value, 'Да')
        self.assertEqual(worksheet['J2'].value, 'Да')
        self.assertEqual(worksheet['K2'].value, '54990.00')
        self.assertEqual(worksheet['L2'].value, '5.00')
        self.assertEqual(worksheet['M2'].value, '49990.00')
        self.assertIn('Хит', worksheet['N2'].value)
        self.assertEqual(worksheet['O2'].value, product.description)
        self.assertIn('Память: 128 ГБ', worksheet['P2'].value)
        self.assertIn('Quest 3 512GB', worksheet['Q2'].value)
        self.assertIn('SKU: QUEST3-512', worksheet['Q2'].value)
        self.assertIn('Память: 512 ГБ', worksheet['Q2'].value)
        self.assertEqual(worksheet['R2'].hyperlink.target, worksheet['R2'].value)
        self.assertIn('Основное:', worksheet['S2'].value)
        self.assertIn('quest3-side.png', worksheet['S2'].value)
        self.assertIn('Вариант 1: Quest 3 512GB', worksheet['S2'].value)
        self.assertEqual(worksheet['T2'].hyperlink.target, product.avito_url)
        self.assertEqual(worksheet['U2'].hyperlink.target, product.ozon_url)
        self.assertEqual(worksheet['V2'].hyperlink.target, product.wildberries_url)

        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            media_entries = [name for name in archive.namelist() if name.startswith('xl/media/')]
        self.assertTrue(media_entries)


class AdminRestoreSecurityTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username='manager',
            password='testpass',
            is_staff=True,
        )
        self.restore_permission = Permission.objects.get(codename='can_restore_backup')
        self.view_permission = Permission.objects.get(codename='view_product')

    def _login_staff(self, *, with_restore_permission=False, with_view_permission=False):
        if with_restore_permission:
            self.staff_user.user_permissions.add(self.restore_permission)
        if with_view_permission:
            self.staff_user.user_permissions.add(self.view_permission)
        self.client.force_login(self.staff_user)

    def _build_restore_zip(self, *, image_filename=None, image_bytes=None):
        backup_data = {
            'version': '1.0',
            'models': {
                'catalog_sections': [],
                'categories': [
                    {'id': 1, 'name': 'Тест', 'slug': 'restore-test', 'section_id': None},
                ],
                'product_tags': [],
                'products': [
                    {
                        'id': 1,
                        'name': 'Тестовый товар',
                        'slug': 'restore-product',
                        'description': '',
                        'price': '10.00',
                        'image': image_filename,
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
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('backup.json', json.dumps(backup_data))
            if image_filename and image_bytes is not None:
                archive.writestr('images/products/restore-product_main' + image_filename[image_filename.rfind('.'):], image_bytes)
        return zip_buffer.getvalue()

    def _png_bytes(self):
        return (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?'
            b'\x00\x05\xfe\x02\xfeA\xd9\x89\xc9\x00\x00\x00\x00IEND\xaeB`\x82'
        )

    def test_restore_endpoint_requires_custom_permission(self):
        self._login_staff()
        response = self.client.get(reverse('admin:catalog_product_restore_backup'))
        self.assertEqual(response.status_code, 403)

    def test_restore_button_hidden_without_custom_permission(self):
        self._login_staff(with_view_permission=True)
        response = self.client.get(reverse('admin:catalog_product_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('admin:catalog_product_restore_backup'))

    def test_restore_button_visible_with_custom_permission(self):
        self._login_staff(with_restore_permission=True, with_view_permission=True)
        response = self.client.get(reverse('admin:catalog_product_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('admin:catalog_product_restore_backup'))

    def test_restore_rejects_html_file(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                with self.assertRaisesMessage(CommandError, 'Недопустимый тип файла'):
                    call_command(
                        'restore_catalog',
                        self._write_temp_backup(
                            image_filename='products/payload.html',
                            image_bytes=b'<html>bad</html>',
                        ),
                    )

    def test_restore_rejects_svg_file(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                with self.assertRaisesMessage(CommandError, 'Недопустимый тип файла'):
                    call_command(
                        'restore_catalog',
                        self._write_temp_backup(
                            image_filename='products/payload.svg',
                            image_bytes=b'<svg></svg>',
                        ),
                    )

    def test_restore_generates_new_server_side_filename(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                call_command(
                    'restore_catalog',
                    self._write_temp_backup(
                        image_filename='products/original-name.png',
                        image_bytes=self._png_bytes(),
                    ),
                )

                product = Product.objects.get(slug='restore-product')
                self.assertTrue(product.image.name.startswith('products/'))
                self.assertNotEqual(product.image.name, 'products/original-name.png')
                self.assertTrue(os.path.exists(os.path.join(media_root, product.image.name)))

    def _write_temp_backup(self, *, image_filename, image_bytes):
        temp_file = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
        temp_file.write(self._build_restore_zip(image_filename=image_filename, image_bytes=image_bytes))
        temp_file.flush()
        temp_file.close()
        self.addCleanup(lambda: os.path.exists(temp_file.name) and os.remove(temp_file.name))
        return temp_file.name


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)

class AdminImportJsonSecurityTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username='json-manager',
            password='testpass',
            is_staff=True,
        )
        self.import_permission = Permission.objects.get(codename='can_import_catalog_json')
        self.view_permission = Permission.objects.get(codename='view_product')

    def _login_staff(self, *, with_import_permission=False, with_view_permission=False):
        if with_import_permission:
            self.staff_user.user_permissions.add(self.import_permission)
        if with_view_permission:
            self.staff_user.user_permissions.add(self.view_permission)
        self.client.force_login(self.staff_user)

    def _payload_upload(self):
        payload = {
            'version': '1.0',
            'models': {
                'catalog_sections': [],
                'categories': [
                    {'id': 1, 'name': 'Шлемы', 'slug': 'admin-category', 'section_id': None},
                ],
                'product_tags': [],
                'products': [
                    {
                        'id': 1,
                        'name': 'Admin JSON товар',
                        'slug': 'admin-json-product',
                        'description': '',
                        'price': '42.00',
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
        return SimpleUploadedFile(
            'catalog.json',
            json.dumps(payload).encode('utf-8'),
            content_type='application/json',
        )

    def _conflicting_payload_upload(self):
        category = Category.objects.create(name='Существующая', slug='existing-admin-category')
        Product.objects.create(
            category=category,
            name='Старый admin товар',
            slug='admin-json-product',
            description='Старое описание',
            price=Decimal('12.00'),
            is_active=True,
            allow_order_on_request=True,
        )
        payload = {
            'version': '1.0',
            'models': {
                'catalog_sections': [],
                'categories': [],
                'product_tags': [],
                'products': [
                    {
                        'id': 1,
                        'name': 'Admin JSON товар',
                        'slug': 'admin-json-product',
                        'description': 'Новое описание',
                        'price': '42.00',
                        'is_active': True,
                        'allow_order_on_request': True,
                        'option_label': '',
                        'category_id': make_direct_target_reference(category.pk),
                        'tag_ids': [],
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
        return SimpleUploadedFile(
            'catalog-conflict.json',
            json.dumps(payload).encode('utf-8'),
            content_type='application/json',
        )

    def test_import_endpoint_requires_custom_permission(self):
        self._login_staff()
        response = self.client.get(reverse('admin:catalog_product_import_json'))
        self.assertEqual(response.status_code, 403)

    def test_import_button_hidden_without_custom_permission(self):
        self._login_staff(with_view_permission=True)
        response = self.client.get(reverse('admin:catalog_product_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('admin:catalog_product_import_json'))

    def test_import_button_visible_with_custom_permission(self):
        self._login_staff(with_import_permission=True, with_view_permission=True)
        response = self.client.get(reverse('admin:catalog_product_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('admin:catalog_product_import_json'))

    def test_import_json_dry_run_does_not_persist_changes(self):
        self._login_staff(with_import_permission=True)
        response = self.client.post(
            reverse('admin:catalog_product_import_json'),
            {'json_file': self._payload_upload(), 'dry_run': 'on'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Проверка пакета')
        self.assertEqual(CatalogImportBatch.objects.count(), 1)
        self.assertFalse(Product.objects.filter(slug='admin-json-product').exists())

    def test_import_json_redirects_to_review_and_apply_clean_persists(self):
        self._login_staff(with_import_permission=True)
        response = self.client.post(
            reverse('admin:catalog_product_import_json'),
            {'json_file': self._payload_upload()},
        )

        self.assertEqual(response.status_code, 302)
        batch = CatalogImportBatch.objects.get()
        self.assertEqual(
            response.url,
            reverse('admin:catalog_product_import_json_review', args=[batch.pk]),
        )
        self.assertFalse(Product.objects.filter(slug='admin-json-product').exists())

        apply_response = self.client.post(
            reverse('admin:catalog_product_import_json_apply_clean', args=[batch.pk]),
            follow=True,
        )

        self.assertEqual(apply_response.status_code, 200)
        self.assertContains(apply_response, 'Проверка пакета')
        self.assertTrue(Product.objects.filter(slug='admin-json-product').exists())

    def test_review_page_renders_conflict_and_save_resolution(self):
        self._login_staff(with_import_permission=True)
        response = self.client.post(
            reverse('admin:catalog_product_import_json'),
            {'json_file': self._conflicting_payload_upload()},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Конфликты, требующие решения')
        self.assertContains(response, 'Открыть текущую запись')

        batch = CatalogImportBatch.objects.get()
        conflict = batch.conflicts.get(collection_name='products')
        resolution_response = self.client.post(
            reverse('admin:catalog_product_import_json_conflict', args=[batch.pk, conflict.pk]),
            {
                'mode__name': 'take_incoming',
                'mode__description': 'take_incoming',
                'mode__price': 'take_incoming',
                'mode__slug': 'manual',
                'manual__slug': 'admin-json-product-new',
            },
            follow=True,
        )

        self.assertEqual(resolution_response.status_code, 200)
        self.assertContains(resolution_response, 'Разрешённые конфликты')
