from ._shared import *  # noqa: F401,F403

class ProductContentBlocksTest(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.storage_override = override_settings(
            MEDIA_ROOT=self.media_root,
            STORAGES={
                'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
            },
        )
        self.storage_override.enable()
        self.addCleanup(self.storage_override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)

        self.client = Client()
        self.category = Category.objects.create(name='Контентные блоки', slug='content-blocks')
        self.product = Product.objects.create(
            category=self.category,
            name='Bizon Helmet',
            slug='bizon-helmet',
            description='Базовое описание товара',
            price=1990,
            is_active=True,
        )

    def _product_admin_form_data(self, **overrides):
        data = {
            'name': self.product.name,
            'slug': self.product.slug,
            'category': self.category.pk,
            'description': self.product.description,
            'product_kind': Product.PRODUCT_KIND_PHYSICAL,
            'price': str(self.product.price),
            'discount_percent': str(self.product.discount_percent),
            'price_on_request': '',
            'is_active': 'on',
            'allow_order_on_request': 'on',
            'avito_url': '',
            'ozon_url': '',
            'wildberries_url': '',
            'option_label': '',
            'views_count': self.product.views_count,
            'tags': [],
            'description_constructor_payload': '',
        }
        data.update(overrides)
        return data

    def _png_file(self, name='block.png'):
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?'
            b'\x00\x05\xfe\x02\xfeA\xd9\x89\xc9\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        return SimpleUploadedFile(name, png_bytes, content_type='image/png')

    def _mock_http_response(self, *, json_data=None, text='', status_code=200):
        response = Mock()
        response.status_code = status_code
        response.text = text
        response.json.return_value = json_data or {}
        response.raise_for_status = Mock()
        return response

    def test_product_content_block_requires_fields_by_type(self):
        text_block = ProductContentBlock(product=self.product, block_type=ProductContentBlock.BlockType.TEXT)
        with self.assertRaises(ValidationError) as text_error:
            text_block.full_clean()
        self.assertIn('title', text_error.exception.message_dict)
        self.assertIn('text', text_error.exception.message_dict)

        image_text_block = ProductContentBlock(
            product=self.product,
            block_type=ProductContentBlock.BlockType.IMAGE_TEXT,
            title='С картинкой',
        )
        with self.assertRaises(ValidationError) as image_text_error:
            image_text_block.full_clean()
        self.assertIn('text', image_text_error.exception.message_dict)
        self.assertIn('image', image_text_error.exception.message_dict)

        full_image_block = ProductContentBlock(
            product=self.product,
            block_type=ProductContentBlock.BlockType.FULL_IMAGE,
        )
        with self.assertRaises(ValidationError) as full_image_error:
            full_image_block.full_clean()
        self.assertIn('image', full_image_error.exception.message_dict)

        video_block = ProductContentBlock(
            product=self.product,
            block_type=ProductContentBlock.BlockType.VIDEO,
        )
        with self.assertRaises(ValidationError) as video_error:
            video_block.full_clean()
        self.assertIn('rutube_url', video_error.exception.message_dict)

    def test_product_detail_renders_active_content_blocks_in_order_with_full_description(self):
        ProductContentBlock.objects.create(
            product=self.product,
            block_type=ProductContentBlock.BlockType.TEXT,
            title='Второй блок',
            text='Текст второго блока',
            sort_order=20,
            is_active=True,
        )
        ProductContentBlock.objects.create(
            product=self.product,
            block_type=ProductContentBlock.BlockType.IMAGE_TEXT,
            title='Первый блок',
            text='Текст первого блока',
            image=self._png_file('image-text.png'),
            image_position=ProductContentBlock.ImagePosition.RIGHT,
            sort_order=10,
            is_active=True,
        )
        ProductContentBlock.objects.create(
            product=self.product,
            block_type=ProductContentBlock.BlockType.FULL_IMAGE,
            title='Третий блок',
            caption='Подпись к изображению',
            image=self._png_file('full-image.png'),
            sort_order=30,
            is_active=False,
        )
        ProductContentBlock.objects.create(
            product=self.product,
            block_type=ProductContentBlock.BlockType.FULL_IMAGE,
            title='Финальный блок',
            caption='Подпись финального блока',
            image=self._png_file('final-image.png'),
            sort_order=40,
            is_active=True,
        )
        with patch('catalog.models.requests.get') as mock_get:
            mock_get.return_value = self._mock_http_response(json_data={
                'title': 'Видео обзор Quest 3',
                'thumbnail_url': 'https://cdn.example/rutube-thumb.jpg',
                'html': '<iframe src="https://rutube.ru/play/embed/7716bd3e665725c3c008ae7ab4ff02e2"></iframe>',
            })
            ProductContentBlock.objects.create(
                product=self.product,
                block_type=ProductContentBlock.BlockType.VIDEO,
                title='Видео обзор',
                caption='Короткий ролик',
                rutube_url='https://www.rutube.ru/video/7716bd3e665725c3c008ae7ab4ff02e2/?utm_source=test',
                sort_order=50,
                is_active=True,
            )

        response = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        self.assertNotContains(response, 'Подробнее')
        self.assertNotIn('detailsExpanded', html)
        self.assertNotIn('class="details-collapsible-fade"', html)
        self.assertNotIn('class="details-toggle-btn details-toggle-btn--corner"', html)
        self.assertNotIn('Третий блок', html)
        self.assertIn('class="content-block content-block--image-text is-image-right"', html)
        self.assertIn('alt="Первый блок"', html)
        self.assertIn('alt="Финальный блок"', html)
        self.assertIn('class="content-block content-block--video"', html)
        self.assertIn('class="content-block__video-poster"', html)
        self.assertIn("x-bind:src=\"videoLoaded ? 'https://rutube.ru/play/embed/7716bd3e665725c3c008ae7ab4ff02e2' : ''\"", html)
        self.assertIn('Видео обзор', html)
        self.assertLess(html.index('Первый блок'), html.index('Второй блок'))
        self.assertLess(html.index('Второй блок'), html.index('Финальный блок'))
        self.assertLess(html.index('Финальный блок'), html.index('Видео обзор'))
        self.assertLess(html.index('details-collapsible-content'), html.index('Характеристики'))

    def test_product_detail_without_description_and_blocks_keeps_empty_state(self):
        self.product.description = ''
        self.product.save(update_fields=['description'])

        response = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Описание пока не добавлено.')
        self.assertNotContains(response, 'Подробнее')

    def test_product_detail_renders_new_description_before_legacy_blocks(self):
        text_type, _ = DescriptionBlockType.objects.get_or_create(slug='text', defaults={'name': 'Текст'})
        feature_type, _ = DescriptionBlockType.objects.get_or_create(slug='feature_grid', defaults={'name': 'Преимущества'})
        ProductContentBlock.objects.create(
            product=self.product,
            block_type=ProductContentBlock.BlockType.TEXT,
            title='Legacy блок',
            text='Legacy текст',
            sort_order=10,
            is_active=True,
        )
        description = ProductDescription.objects.create(
            product=self.product,
            title='Новое подробное описание',
            intro='Вступление нового конструктора',
            status=ProductDescription.Status.PUBLISHED,
            is_active=True,
            source=ProductDescription.Source.CUSTOM,
        )
        ProductDescriptionBlock.objects.create(
            description=description,
            slot_key='second',
            block_type=text_type,
            sort_order=20,
            data={'title': 'Второй новый блок', 'text': 'Текст второго блока'},
        )
        ProductDescriptionBlock.objects.create(
            description=description,
            slot_key='first',
            block_type=feature_type,
            sort_order=10,
            data={
                'title': 'Первый новый блок',
                'items': [{'icon': 'zap', 'title': 'Быстро', 'text': 'Заполняется по шаблону'}],
            },
        )

        response = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        self.assertIn('Новое подробное описание', html)
        self.assertIn('Первый новый блок', html)
        self.assertIn('Второй новый блок', html)
        self.assertNotIn('Legacy блок', html)
        self.assertLess(html.index('Первый новый блок'), html.index('Второй новый блок'))
        self.assertLess(html.index('Второй новый блок'), html.index('Характеристики'))

    def test_product_detail_falls_back_to_legacy_when_new_description_is_inactive(self):
        text_type, _ = DescriptionBlockType.objects.get_or_create(slug='text', defaults={'name': 'Текст'})
        ProductDescription.objects.create(
            product=self.product,
            status=ProductDescription.Status.PUBLISHED,
            is_active=False,
            source=ProductDescription.Source.CUSTOM,
        )
        ProductDescriptionBlock.objects.create(
            description=self.product.product_description,
            slot_key='hidden',
            block_type=text_type,
            data={'title': 'Скрытый новый блок', 'text': 'Не должен отображаться'},
        )
        ProductContentBlock.objects.create(
            product=self.product,
            block_type=ProductContentBlock.BlockType.TEXT,
            title='Legacy работает',
            text='Fallback текст',
            sort_order=10,
            is_active=True,
        )

        response = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Legacy работает')
        self.assertNotContains(response, 'Скрытый новый блок')

    def test_migrate_legacy_blocks_creates_inactive_new_description(self):
        ProductContentBlock.objects.create(
            product=self.product,
            block_type=ProductContentBlock.BlockType.TEXT,
            title='Legacy для миграции',
            text='Текст legacy',
            sort_order=10,
            is_active=True,
        )
        DescriptionBlockType.objects.get_or_create(slug='text', defaults={'name': 'Текст'})

        description, created = migrate_legacy_blocks(self.product)

        self.assertTrue(created)
        self.assertFalse(description.is_active)
        self.assertEqual(description.source, ProductDescription.Source.LEGACY)
        self.assertEqual(description.intro, 'Базовое описание товара')
        self.assertEqual(description.blocks.count(), 1)
        migrated_block = description.blocks.get()
        self.assertEqual(migrated_block.data['title'], 'Legacy для миграции')

    def test_admin_apply_template_endpoint_returns_payload_without_saving_description(self):
        admin_user = User.objects.create_superuser(
            username='description-admin',
            email='description-admin@example.com',
            password='password',
        )
        self.client.force_login(admin_user)
        block_type, _ = DescriptionBlockType.objects.get_or_create(slug='text', defaults={'name': 'Текст'})
        template = DescriptionTemplate.objects.create(
            name='Быстрый шаблон',
            slug='quick-description-template',
            is_active=True,
        )
        DescriptionTemplateSlot.objects.create(
            template=template,
            slot_key='summary',
            block_type=block_type,
            label='Описание',
            sort_order=10,
            default_data={'title': 'Готовый заголовок', 'text': 'Готовый текст'},
        )

        response = self.client.post(
            reverse('admin:catalog_product_description_apply_template', args=[self.product.pk]),
            data=json.dumps({'template_id': template.pk}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['payload']['template_id'], template.pk)
        self.assertEqual(payload['payload']['blocks'][0]['data']['title'], 'Готовый заголовок')
        self.assertFalse(hasattr(self.product, 'product_description'))

    def test_product_admin_description_constructor_uses_visible_template_cards(self):
        html = str(ProductAdmin(Product, admin.site).description_constructor(self.product))

        self.assertIn('data-pdc-template-list', html)
        self.assertIn('data-pdc-template-selection', html)
        self.assertIn('Выбор шаблона', html)
        self.assertIn('Применение только загружает заготовку в редактор ниже', html)
        self.assertIn('1. Общие настройки', html)
        self.assertIn('data-pdc-preview-status', html)
        self.assertNotIn('Предпросмотр текущего', html)
        self.assertNotIn('data-pdc-template-select=', html)

    def test_admin_constructor_state_uses_shared_start_payloads_for_template_and_manual_modes(self):
        block_type, _ = DescriptionBlockType.objects.get_or_create(slug='text', defaults={'name': 'Текст'})
        template = DescriptionTemplate.objects.create(
            name='Общий старт',
            slug='shared-start-template',
            is_active=True,
        )
        DescriptionTemplateSlot.objects.create(
            template=template,
            slot_key='summary',
            block_type=block_type,
            label='Описание',
            sort_order=10,
            default_data={'title': 'Стартовый заголовок', 'text': 'Стартовый текст'},
        )

        state = build_admin_constructor_state(self.product)

        self.assertIn('emptyDescription', state)
        self.assertEqual(state['emptyDescription']['template_id'], None)
        self.assertEqual(state['emptyDescription']['blocks'], [])
        template_state = next(item for item in state['templates'] if item['id'] == template.pk)
        self.assertIn('start_payload', template_state)
        self.assertEqual(template_state['start_payload']['template_id'], template.pk)
        self.assertEqual(template_state['start_payload']['blocks'][0]['block_type'], 'text')
        self.assertEqual(template_state['start_payload']['blocks'][0]['data']['title'], 'Стартовый заголовок')

    def test_description_template_admin_duplicate_view_clones_template_and_slots(self):
        admin_user = User.objects.create_superuser(
            username='template-admin',
            email='template-admin@example.com',
            password='password',
        )
        self.client.force_login(admin_user)
        block_type, _ = DescriptionBlockType.objects.get_or_create(slug='text', defaults={'name': 'Текст'})
        template = DescriptionTemplate.objects.create(
            name='Базовый шаблон',
            slug='base-description-template',
            description='Исходный шаблон',
            category='VR',
            is_active=True,
        )
        DescriptionTemplateSlot.objects.create(
            template=template,
            slot_key='summary',
            block_type=block_type,
            label='Описание',
            sort_order=10,
            default_data={'title': 'Оригинал', 'text': 'Текст'},
        )

        response = self.client.get(reverse('admin:catalog_descriptiontemplate_duplicate', args=[template.pk]))

        self.assertEqual(response.status_code, 302)
        duplicated = DescriptionTemplate.objects.exclude(pk=template.pk).order_by('-pk').first()
        self.assertIsNotNone(duplicated)
        self.assertEqual(duplicated.description, template.description)
        self.assertTrue(duplicated.slug.startswith('base-description-template-copy'))
        self.assertEqual(duplicated.slots.count(), 1)
        self.assertEqual(duplicated.slots.get().label, 'Описание')
        self.assertEqual(duplicated.slots.get().default_data['title'], 'Оригинал')

    def test_editing_template_does_not_change_existing_product_description_blocks(self):
        block_type, _ = DescriptionBlockType.objects.get_or_create(slug='text', defaults={'name': 'Текст'})
        template = DescriptionTemplate.objects.create(
            name='Независимый шаблон',
            slug='independent-description-template',
            is_active=True,
        )
        slot = DescriptionTemplateSlot.objects.create(
            template=template,
            slot_key='summary',
            block_type=block_type,
            label='Описание',
            sort_order=10,
            default_data={'title': 'Старый шаблонный заголовок', 'text': 'Старый текст'},
        )
        description = ProductDescription.objects.create(
            product=self.product,
            template=template,
            title='Описание товара',
            status=ProductDescription.Status.DRAFT,
            is_active=False,
            source=ProductDescription.Source.TEMPLATE,
        )
        ProductDescriptionBlock.objects.create(
            description=description,
            slot_key='summary',
            block_type=block_type,
            sort_order=10,
            is_active=True,
            data={'title': 'Скопированный заголовок', 'text': 'Текст в товаре'},
        )

        slot.default_data = {'title': 'Новый заголовок шаблона', 'text': 'Новый текст шаблона'}
        slot.save(update_fields=['default_data'])

        description_block = description.blocks.get()
        self.assertEqual(description_block.data['title'], 'Скопированный заголовок')
        self.assertEqual(description_block.data['text'], 'Текст в товаре')

    def test_product_admin_hides_legacy_content_blocks_inline_for_non_superuser(self):
        manager_user = User.objects.create_user(
            username='manager-inline-user',
            email='manager-inline@example.com',
            password='password',
            is_staff=True,
        )
        request = RequestFactory().get('/admin/catalog/product/1/change/')
        request.user = manager_user
        product_admin = ProductAdmin(Product, admin.site)
        inline_instances = [
            ProductContentBlockInline(Product, admin.site),
            ProductImageInline(Product, admin.site),
        ]

        with patch('django.contrib.admin.options.ModelAdmin.get_inline_instances', return_value=inline_instances):
            result = product_admin.get_inline_instances(request, obj=self.product)

        self.assertFalse(any(isinstance(item, ProductContentBlockInline) for item in result))
        self.assertTrue(any(isinstance(item, ProductImageInline) for item in result))

    def test_product_content_block_admin_is_superuser_only(self):
        manager_user = User.objects.create_user(
            username='manager-content-block-user',
            email='manager-content-block@example.com',
            password='password',
            is_staff=True,
        )
        superuser = User.objects.create_superuser(
            username='super-content-block-user',
            email='super-content-block@example.com',
            password='password',
        )
        block_admin = ProductContentBlockAdmin(ProductContentBlock, admin.site)
        request_manager = RequestFactory().get('/admin/catalog/productcontentblock/')
        request_manager.user = manager_user
        request_super = RequestFactory().get('/admin/catalog/productcontentblock/')
        request_super.user = superuser

        self.assertFalse(block_admin.has_module_permission(request_manager))
        self.assertEqual(block_admin.get_model_perms(request_manager), {})
        self.assertTrue(block_admin.has_module_permission(request_super))

    def test_product_admin_save_model_creates_description_from_embedded_payload_on_add(self):
        admin_user = User.objects.create_superuser(
            username='product-add-description-admin',
            email='product-add-description-admin@example.com',
            password='password',
        )
        text_type, _ = DescriptionBlockType.objects.get_or_create(slug='text', defaults={'name': 'Текст'})
        payload = {
            'title': 'Подробное из формы товара',
            'intro': 'Вступление',
            'status': ProductDescription.Status.PUBLISHED,
            'is_active': True,
            'source': ProductDescription.Source.CUSTOM,
            'blocks': [
                {
                    'client_id': 'new-1',
                    'slot_key': 'summary',
                    'block_type': text_type.slug,
                    'sort_order': 10,
                    'is_active': True,
                    'data': {'title': 'Блок из add-form', 'text': 'Текст блока'},
                }
            ],
        }
        form = ProductAdminForm(data=self._product_admin_form_data(
            name='Новый товар с описанием',
            slug='new-product-description',
            description='Краткое описание',
            price='1000',
            discount_percent='0',
            views_count=0,
            description_constructor_payload=json.dumps(payload),
        ))
        self.assertTrue(form.is_valid(), form.errors)
        request = RequestFactory().post('/admin/catalog/product/add/', data={
            'description_constructor_payload': json.dumps(payload),
        })
        request.user = admin_user
        product = form.save(commit=False)

        ProductAdmin(Product, admin.site).save_model(request, product, form, change=False)

        description = product.product_description
        self.assertTrue(description.is_active)
        self.assertEqual(description.status, ProductDescription.Status.PUBLISHED)
        self.assertEqual(description.blocks.count(), 1)
        self.assertEqual(description.blocks.get().data['title'], 'Блок из add-form')

    def test_product_admin_save_model_updates_reorders_and_deletes_embedded_blocks(self):
        admin_user = User.objects.create_superuser(
            username='product-change-description-admin',
            email='product-change-description-admin@example.com',
            password='password',
        )
        text_type, _ = DescriptionBlockType.objects.get_or_create(slug='text', defaults={'name': 'Текст'})
        feature_type, _ = DescriptionBlockType.objects.get_or_create(slug='feature_grid', defaults={'name': 'Преимущества'})
        description = ProductDescription.objects.create(
            product=self.product,
            title='Старое подробное',
            status=ProductDescription.Status.PUBLISHED,
            is_active=True,
        )
        kept_block = ProductDescriptionBlock.objects.create(
            description=description,
            slot_key='old',
            block_type=text_type,
            sort_order=10,
            data={'title': 'Старый блок', 'text': 'Старый текст'},
        )
        deleted_block = ProductDescriptionBlock.objects.create(
            description=description,
            slot_key='delete-me',
            block_type=text_type,
            sort_order=20,
            data={'title': 'Удалить'},
        )
        payload = {
            'title': 'Обновлённое подробное',
            'intro': 'Новое вступление',
            'status': ProductDescription.Status.DRAFT,
            'is_active': False,
            'source': ProductDescription.Source.CUSTOM,
            'blocks': [
                {
                    'id': kept_block.pk,
                    'client_id': f'block-{kept_block.pk}',
                    'slot_key': 'second',
                    'block_type': text_type.slug,
                    'sort_order': 20,
                    'is_active': False,
                    'data': {'title': 'Обновлённый блок', 'text': 'Новый текст'},
                },
                {
                    'client_id': 'new-feature',
                    'slot_key': 'first',
                    'block_type': feature_type.slug,
                    'sort_order': 10,
                    'is_active': True,
                    'data': {'title': 'Новый первый', 'items': [{'title': 'Плюс', 'text': 'Описание'}]},
                },
                {
                    'id': deleted_block.pk,
                    'client_id': f'block-{deleted_block.pk}',
                    'slot_key': 'delete-me',
                    'block_type': text_type.slug,
                    'deleted': True,
                    'data': {'title': 'Удалить'},
                },
            ],
        }
        form = ProductAdminForm(
            instance=self.product,
            data=self._product_admin_form_data(
                description_constructor_payload=json.dumps(payload),
            ),
        )
        self.assertTrue(form.is_valid(), form.errors)
        request = RequestFactory().post('/admin/catalog/product/change/', data={
            'description_constructor_payload': json.dumps(payload),
        })
        request.user = admin_user
        product = form.save(commit=False)

        ProductAdmin(Product, admin.site).save_model(request, product, form, change=True)

        description.refresh_from_db()
        self.assertFalse(description.is_active)
        self.assertEqual(description.status, ProductDescription.Status.DRAFT)
        self.assertEqual(description.title, 'Обновлённое подробное')
        self.assertEqual(description.blocks.count(), 2)
        self.assertFalse(ProductDescriptionBlock.objects.filter(pk=deleted_block.pk).exists())
        kept_block.refresh_from_db()
        self.assertFalse(kept_block.is_active)
        self.assertEqual(kept_block.slot_key, 'second')
        self.assertEqual(kept_block.data['title'], 'Обновлённый блок')
        self.assertEqual(
            list(description.blocks.order_by('sort_order').values_list('slot_key', flat=True)),
            ['first', 'second'],
        )
