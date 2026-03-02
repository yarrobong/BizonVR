"""Базовые тесты каталога: поиск, избранное (Фаза 6)."""
import json
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from config.forms import CallbackForm, ContactForm
from config.legal_docs import LEGAL_BUNDLE_VERSION
from orders.models import Order, OrderItem

from .models import (
    CartShare,
    CallbackRequest,
    CatalogSection,
    Category,
    City,
    ContactRequest,
    Favorite,
    PickupPoint,
    Product,
    ProductBundle,
    ProductBundleItem,
    ProductCharacteristic,
    ProductStock,
    ProductTag,
    ProductVariant,
    Service,
)

User = get_user_model()


class CatalogSearchTest(TestCase):
    """Поиск по товарам (параметр q=)."""

    def setUp(self):
        self.client = Client()
        cat = Category.objects.create(name='Тест', slug='test')
        Product.objects.create(
            category=cat,
            name='VR Шлем Meta',
            slug='vr-meta',
            description='Шлем виртуальной реальности',
            price=100,
            is_active=True,
        )
        Product.objects.create(
            category=cat,
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


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)
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
        self.city = City.objects.create(name='Екатеринбург', slug='ekb')
        self.pickup_point = PickupPoint.objects.create(city=self.city, name='Точка 1')

    def _extract_product_detail_data(self, response):
        html = response.content.decode()
        match = re.search(
            r'<script id="product-detail-data" type="application/json">(.*?)</script>',
            html,
            re.S,
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

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

    def test_variant_card_uses_variant_price_and_variant_stock_context(self):
        ProductStock.objects.create(
            product=self.product,
            variant=self.variant_one,
            pickup_point=self.pickup_point,
            quantity=3,
        )
        session = self.client.session
        session['selected_city_id'] = self.city.pk
        session.save()

        resp = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['variant_stock_total'].get(self.variant_one.pk), 3)
        self.assertEqual(resp.context['variant_stock_in_city'].get(self.variant_one.pk), 3)
        self.assertContains(resp, '1 200 ₽')
        self.assertContains(resp, 'В наличии: 3 шт.')


class CatalogSectionFilterTest(TestCase):
    """Фильтры каталога должны быть ограничены выбранным разделом."""

    def setUp(self):
        self.client = Client()
        self.section_vr = CatalogSection.objects.create(name='VR', slug='vr')
        self.section_pc = CatalogSection.objects.create(name='PC', slug='pc')
        self.cat_vr = Category.objects.create(name='VR Шлемы', slug='vr-headsets', section=self.section_vr)
        self.cat_pc = Category.objects.create(name='Ноутбуки', slug='laptops', section=self.section_pc)
        self.tag_vr = ProductTag.objects.create(name='VR тег', slug='vr-tag', order=1)
        self.tag_pc = ProductTag.objects.create(name='PC тег', slug='pc-tag', order=2)

        vr_product = Product.objects.create(
            category=self.cat_vr,
            name='Quest 3',
            slug='quest-3',
            price=100,
            is_active=True,
        )
        pc_product = Product.objects.create(
            category=self.cat_pc,
            name='Laptop',
            slug='laptop',
            price=200,
            is_active=True,
        )
        vr_product.tags.add(self.tag_vr)
        pc_product.tags.add(self.tag_pc)

    def test_tags_in_filters_are_limited_by_selected_section(self):
        resp = self.client.get(reverse('catalog:product_list'), {'section': self.section_vr.slug})
        self.assertEqual(resp.status_code, 200)
        tag_slugs = {tag.slug for tag in resp.context['product_tags']}
        self.assertIn(self.tag_vr.slug, tag_slugs)
        self.assertNotIn(self.tag_pc.slug, tag_slugs)

    def test_tags_in_filters_are_limited_by_selected_category(self):
        """При выбранной категории показываются только теги, у которых есть товары в этой категории (чтобы не вести в пустой каталог)."""
        # Только в VR-категории есть товар с tag_vr; в PC-категории — с tag_pc
        resp = self.client.get(reverse('catalog:product_list'), {'category': self.cat_vr.slug})
        self.assertEqual(resp.status_code, 200)
        tag_slugs = {tag.slug for tag in resp.context['product_tags']}
        self.assertIn(self.tag_vr.slug, tag_slugs)
        self.assertNotIn(self.tag_pc.slug, tag_slugs)


class HomeFeaturedProductsTest(TestCase):
    """Главная страница: только товары с промо-тегами."""

    def setUp(self):
        self.client = Client()
        category = Category.objects.create(name='Тест', slug='test-home')
        self.hit_tag = ProductTag.objects.create(name='Хит', slug='hit', order=1)
        self.sale_tag = ProductTag.objects.create(name='Распродажа', slug='sale', order=2)

        self.hit_product = Product.objects.create(
            category=category,
            name='Товар Хит',
            slug='home-hit',
            price=100,
            is_active=True,
        )
        self.sale_product = Product.objects.create(
            category=category,
            name='Товар Распродажа',
            slug='home-sale',
            price=90,
            is_active=True,
        )
        self.regular_product = Product.objects.create(
            category=category,
            name='Обычный товар',
            slug='home-regular',
            price=80,
            is_active=True,
        )
        self.hit_product.tags.add(self.hit_tag)
        self.sale_product.tags.add(self.sale_tag)

    def test_home_shows_only_promo_tagged_products(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        shown_slugs = {p.slug for p in resp.context['featured_products']}
        self.assertIn(self.hit_product.slug, shown_slugs)
        self.assertIn(self.sale_product.slug, shown_slugs)
        self.assertNotIn(self.regular_product.slug, shown_slugs)


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
        oferta_resp = self.client.get(reverse('oferta'))
        self.assertNotContains(oferta_resp, 'Настоящая политика конфиденциальности определяет')

    def test_home_footer_and_cookie_banner_have_legal_links(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('privacy'))
        self.assertContains(resp, reverse('cookies_policy'))
        self.assertContains(resp, reverse('oferta'))


class LegalConsentFormsAndViewsTest(TestCase):
    def setUp(self):
        self.client = Client()

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


class ServicesPageTest(TestCase):
    """Страница услуг: вывод из БД и обработка callback-формы."""

    def setUp(self):
        self.client = Client()
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


class FavoriteTest(TestCase):
    """Избранное: добавление/удаление, доступ только для авторизованных."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='79991234567', password='testpass')
        cat = Category.objects.create(name='Тест', slug='test')
        self.product = Product.objects.create(
            category=cat,
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

    def setUp(self):
        self.client = Client()
        cat = Category.objects.create(name='Тест', slug='test')
        self.product = Product.objects.create(
            category=cat,
            name='Товар',
            slug='product',
            price=100,
            is_active=True,
        )
        self.product_with_variant = Product.objects.create(
            category=cat,
            name='Товар с вариантом',
            slug='product-with-variant',
            price=110,
            is_active=True,
        )
        self.product_variant = ProductVariant.objects.create(
            product=self.product_with_variant,
            name='Черный',
            price_override=120,
        )
        self.product_second = Product.objects.create(
            category=cat,
            name='Товар 2',
            slug='product-2',
            price=200,
            is_active=True,
        )

    def _set_session_cart(self, items):
        session = self.client.session
        session['cart_items'] = items
        session.save()

    def test_add_to_cart_saves_in_session(self):
        url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        resp = self.client.post(url, {})
        self.assertEqual(resp.status_code, 302)
        cart_items = self.client.session.get('cart_items', [])
        self.assertEqual(len(cart_items), 1)
        self.assertEqual(cart_items[0]['product_id'], self.product.pk)
        self.assertEqual(cart_items[0]['quantity'], 1)
        self.assertEqual(cart_items[0]['subtotal'], 100)

    def test_add_to_cart_htmx_returns_cart_count(self):
        url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        resp = self.client.post(url, {}, HTTP_HX_REQUEST='true')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('HX-Trigger', resp)
        trigger = json.loads(resp['HX-Trigger'])
        self.assertEqual(trigger['cart-updated']['count'], 1)

    def test_cart_update_changes_quantity_and_remove_item(self):
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

    def test_cart_page_shows_last_added_first_and_keeps_order_after_update(self):
        add_url_first = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        add_url_second = reverse('catalog:add_to_cart', kwargs={'product_id': self.product_second.pk})
        update_url = reverse('catalog:cart_update')
        cart_url = reverse('catalog:cart')

        self.client.post(add_url_first, {})
        self.client.post(add_url_second, {})

        resp = self.client.get(cart_url)
        self.assertEqual(resp.status_code, 200)
        ids_before = [int(value) for value in re.findall(r'data-product-id="(\d+)"', resp.content.decode())]
        self.assertEqual(ids_before[:2], [self.product_second.pk, self.product.pk])

        self.client.post(update_url, {'product_id': self.product.pk, 'quantity': 3})

        resp = self.client.get(cart_url)
        self.assertEqual(resp.status_code, 200)
        ids_after = [int(value) for value in re.findall(r'data-product-id="(\d+)"', resp.content.decode())]
        self.assertEqual(ids_after[:2], [self.product_second.pk, self.product.pk])

    def test_cart_page_shows_last_added_first_for_authenticated_user(self):
        user = User.objects.create_user(username='79990001122', password='testpass')
        self.client.force_login(user)
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
        self.assertEqual(ids[:2], [self.product_second.pk, self.product.pk])

    def test_cart_clear_clears_session_cart(self):
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
        resp = self.client.post(
            reverse('catalog:cart_share_create'),
            {'selected_item_keys': f'{self.product_with_variant.pk}:{self.product_variant.pk}'},
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

        bundle = ProductBundle.objects.create(name='Bundle')
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

    def test_recommendations_apply_filters_and_sections(self):
        resp = self.client.get(reverse('catalog:product_detail', kwargs={'slug': self.current.slug}))
        self.assertEqual(resp.status_code, 200)

        sections = resp.context['recommendation_sections']
        self.assertTrue(sections)
        self.assertIn('frequently_bought', [s['key'] for s in sections])

        recommended_ids = {p.pk for s in sections for p in s['products']}
        self.assertIn(self.strap.pk, recommended_ids)
        self.assertNotIn(self.current.pk, recommended_ids)
        self.assertNotIn(self.battery.pk, recommended_ids)  # в корзине
        self.assertNotIn(self.incompatible.pk, recommended_ids)  # несовместим
        self.assertNotIn(self.bundle_item.pk, recommended_ids)  # часть комплекта


class FooterProductsFeedTest(TestCase):
    """Ленивая выдача карточек перед футером: порции и лимит."""

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Тест', slug='test')
        for i in range(110):
            Product.objects.create(
                category=self.category,
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
        bundle = ProductBundle.objects.create(name='SEO Bundle')

        resp = self.client.get('/sitemap.xml')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('<urlset', body)
        self.assertIn('<loc>http://testserver/</loc>', body)
        self.assertIn(f'<loc>http://testserver{product.get_absolute_url()}</loc>', body)
        self.assertIn(f'<loc>http://testserver{bundle.get_absolute_url()}</loc>', body)
