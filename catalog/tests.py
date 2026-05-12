"""Базовые тесты каталога: поиск, избранное (Фаза 6)."""
import html as html_lib
import json
import os
import re
import shutil
import time
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from datetime import timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import Http404
from django.http import QueryDict
from django.template import Context, Template
from django.test import Client, TestCase, override_settings
from django.test.client import RequestFactory
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from PIL import Image as PilImage

from accounts.models import Profile
from config.forms import CallbackForm, ContactForm
from config.legal_docs import LEGAL_BUNDLE_VERSION
from config.utils.spam_protection import is_spam_request
from orders.models import Order, OrderItem

from .cart_services import get_cart_count, get_cart_items, get_favorite_product_ids, group_cart_items
from .characteristic_normalization import normalize_characteristic_value
from .context_processors import catalog_menu
from .filter_audit import (
    build_filter_audit_dashboard_context,
    get_new_uncovered_sources,
    get_new_uncovered_values,
    sync_catalog_filter_audit_snapshots,
)
from .filtering import CatalogFilterService
from .filter_bootstrap import build_alias_suggestions
from .filter_bootstrap import SAFE_AUTO_APPLICABLE
from .filter_presets import get_typed_value_sort_key
from .filter_setup_wizard import CatalogFilterSetupWizard
from .import_workflow import CatalogImportWorkflowService, make_direct_target_reference
from .importers import CatalogDataImporter
from .image_utils import build_responsive_image_data
from .product_descriptions import build_admin_constructor_state, migrate_legacy_blocks
from .pricing import PURCHASE_MODE_STOCK, resolve_in_stock_price, resolve_public_purchase_mode
from .stock import public_product_stock_status
from .templatetags.catalog_tags import build_product_card_gallery_images
from .models import (
    CartItem,
    CartShare,
    CallbackRequest,
    CatalogImportBatch,
    CatalogImportConflict,
    CatalogSection,
    Category,
    CharacteristicDefinition,
    CharacteristicSourceAlias,
    CharacteristicValueAlias,
    City,
    ContactRequest,
    DescriptionBlockType,
    DescriptionTemplate,
    DescriptionTemplateSlot,
    Favorite,
    FilterConfig,
    GamePack,
    GamePackEntry,
    GamePackItem,
    GamePackServiceEntry,
    PickupPoint,
    Product,
    ProductBundle,
    ProductBundleItem,
    ProductCharacteristic,
    ProductContentBlock,
    ProductDescription,
    ProductDescriptionBlock,
    ProductGameMetadata,
    ProductImage,
    ProductStock,
    ProductTag,
    ProductVideo,
    ProductVariant,
    Service,
    VRClubQuizRequest,
)
from .views import feeds as feed_views
from .views.feeds import vr_attractions_yml_feed_view
from .admin.filters import CharacteristicDefinitionAdminForm
from .admin.products import ProductAdmin, ProductAdminForm, ProductContentBlockAdmin, ProductContentBlockInline, ProductImageInline

User = get_user_model()


class VRClubGamesB2BTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Игры', slug='games')
        self.headset_category = Category.objects.create(name='VR шлемы', slug='vr-headsets')
        self.game = Product.objects.create(
            category=self.category,
            name='Arena Heroes',
            slug='arena-heroes',
            price=Decimal('1000.00'),
            is_active=True,
        )
        ProductGameMetadata.objects.create(
            product=self.game,
            devices='Quest, Pico',
            genres='PvP, Arcade',
            min_players=2,
            max_players=6,
            age_rating='12+',
            club_format=ProductGameMetadata.FORMAT_CLUB,
            is_multiplayer=True,
            b2b_note='Командная игра для коммерческих сессий.',
        )
        self.pack = GamePack.objects.create(
            category=self.category,
            name='Клуб',
            slug='club-pack',
            price=Decimal('5000.00'),
            is_active=True,
            show_on_vr_club_page=True,
            vr_club_tariff=GamePack.TARIFF_CLUB,
        )
        GamePackEntry.objects.create(game_pack=self.pack, product=self.game, quantity=1)
        self.service = Service.objects.create(
            name='Настройка multiplayer',
            short_description='Соберем сетевую игру под клуб.',
            price=Decimal('2500.00'),
            service_kind=Service.KIND_MULTIPLAYER,
            is_vr_club_service=True,
            is_active=True,
        )

    def test_vr_club_games_page_shows_three_scenarios_and_filters_games(self):
        resp = self.client.get(reverse('catalog:vr_club_games'), {'device': 'Quest', 'players': '4'})

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Готовые паки')
        self.assertContains(resp, 'Конструктор игр')
        self.assertContains(resp, 'Получить подбор')
        self.assertContains(resp, self.game.name)
        self.assertContains(resp, self.service.name)

    def test_custom_game_pack_with_service_is_added_to_cart_blocks(self):
        resp = self.client.post(reverse('catalog:add_vr_club_custom_pack'), {
            'game_ids': [str(self.game.pk)],
            'service_ids': [str(self.service.pk)],
            'headset_count': '4',
            'devices': 'Quest',
            'club_format': ProductGameMetadata.FORMAT_CLUB,
        })

        self.assertRedirects(resp, reverse('catalog:cart'))
        items = get_cart_items(resp.wsgi_request)
        self.assertTrue(any(item.get('line_type') == 'custom_game_pack' for item in items))
        self.assertTrue(any(item.get('line_type') == 'service' for item in items))
        groups = group_cart_items(items)
        self.assertEqual([group['title'] for group in groups], ['Игры', 'Услуги'])
        self.assertEqual(sum(group['subtotal'] for group in groups), 3500.0)

    def test_game_product_is_available_without_physical_stock(self):
        self.assertFalse(self.game.tracks_stock)
        self.assertEqual(resolve_public_purchase_mode(self.game, stock_total=0), PURCHASE_MODE_STOCK)
        self.assertEqual(public_product_stock_status(self.game, 0)['label'], 'В наличии')

        resp = self.client.post(reverse('catalog:add_to_cart', args=[self.game.pk]), {'quantity': '1'}, follow=True)

        self.assertEqual(resp.status_code, 200)
        items = get_cart_items(resp.wsgi_request)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['product_id'], self.game.pk)

    def test_quiz_creates_request(self):
        resp = self.client.post(reverse('catalog:vr_club_games'), {
            'name': 'Иван',
            'phone': '+7 999 111-22-33',
            'email': 'club@example.com',
            'club_format': 'VR-клуб',
            'devices': 'Quest',
            'headsets_count': '6',
            'play_places_count': '6',
            'audience': 'семьи',
            'budget': 'до 200 000',
            'comment': 'Нужен запуск под ключ',
            'agree_personal_data': 'on',
        })

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(VRClubQuizRequest.objects.filter(phone='+7 999 111-22-33').exists())


def _build_test_uploaded_image(name='test.jpg', *, size=(1600, 1200), image_format='JPEG', color='#22c55e'):
    image_bytes = BytesIO()
    image = PilImage.new('RGB', size, color=color)
    image.save(image_bytes, format=image_format)
    return SimpleUploadedFile(
        name,
        image_bytes.getvalue(),
        content_type=f'image/{image_format.lower()}',
    )


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
    def setUp(self):
        self.client = Client()
        self.suggest_url = reverse('catalog:search_suggest')
        self.category = Category.objects.create(name='Шлемы', slug='headsets')
        self.bundle_category = Category.objects.create(
            name='Комплекты',
            slug='bundles',
            is_bundles_category=True,
        )
        self.city = City.objects.create(name='Екатеринбург', slug='ekaterinburg')
        self.pickup_point = PickupPoint.objects.create(city=self.city, name='Основной склад')

        self.product_by_name = Product.objects.create(
            category=self.category,
            name='Quest 3 Pro',
            slug='quest-3-pro',
            description='Флагманский VR шлем',
            price=100,
            is_active=True,
        )
        ProductStock.objects.create(
            product=self.product_by_name,
            pickup_point=self.pickup_point,
            quantity=4,
        )

        self.product_by_description = Product.objects.create(
            category=self.category,
            name='Pico Ultra',
            slug='pico-ultra',
            description='Квестовый VR шлем для аркад',
            price=90,
            is_active=True,
        )
        ProductStock.objects.create(
            product=self.product_by_description,
            pickup_point=self.pickup_point,
            quantity=2,
        )

        self.variant_product = Product.objects.create(
            category=self.category,
            name='Meta Quest Carry',
            slug='meta-quest-carry',
            description='Товар с вариантами',
            price=120,
            is_active=True,
        )
        self.variant = ProductVariant.objects.create(
            product=self.variant_product,
            name='256 GB',
            sku='Q3-256',
        )
        ProductStock.objects.create(
            product=self.variant_product,
            pickup_point=self.pickup_point,
            variant=self.variant,
            quantity=1,
        )

        self.bundle_helper_product = Product.objects.create(
            category=self.category,
            name='Titan Stand',
            slug='titan-stand',
            description='Стойка для VR',
            price=55,
            is_active=True,
        )
        ProductStock.objects.create(
            product=self.bundle_helper_product,
            pickup_point=self.pickup_point,
            quantity=3,
        )

        self.bundle = ProductBundle.objects.create(
            category=self.bundle_category,
            name='Аркадный комплект',
            slug='arcade-bundle',
        )
        ProductBundleItem.objects.create(bundle=self.bundle, product=self.product_by_name, quantity=1)
        ProductBundleItem.objects.create(bundle=self.bundle, product=self.bundle_helper_product, quantity=1)

        self.inactive_product = Product.objects.create(
            category=self.category,
            name='Ghost Quest',
            slug='ghost-quest',
            description='Скрытый товар',
            price=70,
            is_active=False,
        )

        for index in range(4):
            product = Product.objects.create(
                category=self.category,
                name=f'Neo Limit {index}',
                slug=f'neo-limit-{index}',
                description='Тест лимита',
                price=80 + index,
                is_active=True,
            )
            ProductStock.objects.create(
                product=product,
                pickup_point=self.pickup_point,
                quantity=1,
            )

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


class CatalogSortLinksEscapingTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.section = CatalogSection.objects.create(name='VR оборудование', slug='sort-escape-vr-oborudovanie')
        self.category = Category.objects.create(
            name='Шлемы',
            slug='sort-escape-vr-headsets',
            section=self.section,
        )
        self.tag = ProductTag.objects.create(name='Хит', slug='sort-escape-bestseller')
        self.product = Product.objects.create(
            category=self.category,
            name='Quest 3',
            slug='sort-escape-quest-3',
            description='VR headset',
            price=100,
            is_active=True,
        )
        self.product.tags.add(self.tag)

    def test_mobile_sort_links_escape_query_ampersands(self):
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
        self.assertNotIn('href="?sort=name&category=sort-escape-vr-headsets&section=sort-escape-vr-oborudovanie&tag=sort-escape-bestseller&q=Quest&price_min=50&price_max=150"', html)


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
        request = self.factory.post('/contacts/', {'form_started_at': str(int(time.time()))})
        self.assertTrue(is_spam_request(request))


class SeedStarvrPacksCommandTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_command_creates_games_and_packs(self):
        call_command('seed_starvr_packs')

        section = CatalogSection.objects.get(slug='vr-games-and-packs')
        games_category = Category.objects.get(slug='mr-vr-games', section=section)
        packs_category = Category.objects.get(slug='vr-zone-packs', section=section)

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
        self.assertTrue(is_spam_request(request))

    def test_spam_word_blocks(self):
        request = self.factory.post('/contacts/', {'message': 'Нужен seo traffic прямо сейчас'})
        self.assertTrue(is_spam_request(request))

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


class GamePackDetailRegressionTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Тест', slug='test-game-pack-detail')

    def test_product_detail_opens_when_pack_contains_non_catalog_items(self):
        product = Product.objects.create(
            category=self.category,
            name='Пак MR Zone',
            slug='mr-zone-pack',
            product_kind=Product.PRODUCT_KIND_GAME_PACK,
            price=Decimal('9990.00'),
            is_active=True,
            allow_order_on_request=False,
        )
        GamePackItem.objects.create(product=product, title='Настройка шлема', platform='Сервис')
        GamePackItem.objects.create(
            product=product,
            title='Игры для VR-зон (20 штук на выбор, или из каталога)',
            platform='Доп. библиотека',
        )

        response = self.client.get(product.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Состав пака')
        self.assertContains(response, 'Настройка шлема')


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
        project_root = os.path.dirname(os.path.dirname(__file__))
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
        self.assertContains(resp, 'Срок поставки: до 35 дней')
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
        self.assertContains(resp, 'Срок поставки: до 35 дней')
        self.assertNotContains(resp, '1 200 ₽')

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
        self.assertContains(resp, 'Срок поставки: до 35 дней')
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
        self.assertContains(resp, 'Срок поставки: до 35 дней')
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
        form = ProductAdminForm(data={
            'name': 'Новый товар с описанием',
            'slug': 'new-product-description',
            'category': self.category.pk,
            'description': 'Краткое описание',
            'price': '1000',
            'price_on_request': '',
            'is_active': 'on',
            'allow_order_on_request': 'on',
            'avito_url': '',
            'ozon_url': '',
            'wildberries_url': '',
            'option_label': '',
            'views_count': 0,
            'tags': [],
            'description_constructor_payload': json.dumps(payload),
        })
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
        form = ProductAdminForm(instance=self.product, data={
            'name': self.product.name,
            'slug': self.product.slug,
            'category': self.category.pk,
            'description': self.product.description,
            'price': str(self.product.price),
            'price_on_request': '',
            'is_active': 'on',
            'allow_order_on_request': 'on',
            'avito_url': '',
            'ozon_url': '',
            'wildberries_url': '',
            'option_label': '',
            'views_count': self.product.views_count,
            'tags': [],
            'description_constructor_payload': json.dumps(payload),
        })
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


class PublicLocationCleanupTest(TestCase):
    def test_set_city_route_is_removed(self):
        with self.assertRaises(NoReverseMatch):
            reverse('catalog:set_city')

    def test_public_pages_do_not_render_city_selector(self):
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
        self.assertEqual(len(preview['safe_value_alias_suggestions']), 1)
        self.assertEqual(
            [item['normalized_key'] for item in preview['safe_value_alias_suggestions'][0]['items']],
            ['128 gb', '256 gb'],
        )
        self.assertEqual(
            [item['definition'].code for item in preview['missing_configs']],
            ['memory'],
        )
        self.assertEqual(
            [item['definition'].code for item in preview['quick_filter_recommendations']],
            ['memory'],
        )

    def test_category_filter_setup_wizard_admin_page_applies_selected_steps(self):
        memory = CharacteristicDefinition.objects.create(
            code='memory',
            name='Память',
            source_name='Память',
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
        self.assertEqual(FilterConfig.objects.filter(category=self.category).count(), 2)
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


class HomeFeaturedProductsTest(TestCase):
    """Главная страница: только товары с промо-тегами."""

    def setUp(self):
        self.client = Client()
        category = Category.objects.create(name='Тест', slug='test-home')
        self.hit_tag = ProductTag.objects.create(name='Хит', slug='hit', order=1)
        self.sale_tag = ProductTag.objects.create(name='Распродажа', slug='sale-home', order=2)

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

    def test_home_marketing_tiles_use_optimized_webp_assets(self):
        resp = self.client.get(reverse('home'))

        self.assertEqual(resp.status_code, 200)
        marketing_tiles = {tile['key']: tile for tile in resp.context['marketing_tiles']}
        self.assertTrue(marketing_tiles['unitree_robot']['bg_url'].endswith('image-Photoroom_20_4RdGPzn.webp'))
        self.assertTrue(marketing_tiles['portable_consoles']['bg_url'].endswith('image-Photoroom_3.webp'))
        self.assertTrue(marketing_tiles['vr_attractions']['bg_url'].endswith('Two-person_360_flight_simulator.webp'))


class CatalogMenuCacheTest(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.section = CatalogSection.objects.create(name='VR', slug='vr')
        self.category = Category.objects.create(name='Шлемы', slug='headsets', section=self.section)
        Product.objects.create(
            category=self.category,
            name='Quest 3',
            slug='quest-3-cache',
            price=100,
            is_active=True,
            image='products/quest-3.webp',
        )

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
        self.city = City.objects.create(name='Екатеринбург', slug='cart-ekb')
        self.pickup_point = PickupPoint.objects.create(city=self.city, name='Склад')
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
        self.bundle = ProductBundle.objects.create(
            category=Category.objects.create(
                name='Тестовые комплекты',
                slug='cart-test-bundles',
                is_bundles_category=True,
            ),
            name='Набор для теста',
            slug='test-bundle',
        )
        ProductBundleItem.objects.create(bundle=self.bundle, product=self.product, quantity=1)
        ProductBundleItem.objects.create(bundle=self.bundle, product=self.product_second, quantity=2)

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

    def test_buy_now_product_redirects_to_checkout_without_touching_regular_cart(self):
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
        ProductStock.objects.create(
            product=self.product,
            pickup_point=self.pickup_point,
            quantity=8,
        )
        session = self.client.session
        session['selected_city_id'] = self.city.pk
        session.save()

        add_url = reverse('catalog:add_to_cart', kwargs={'product_id': self.product.pk})
        self.client.post(add_url, {})

        resp = self.client.get(reverse('catalog:cart'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Мало')
        self.assertNotContains(resp, 'В другом городе')

    def test_cart_update_limits_quantity_by_total_stock(self):
        ProductStock.objects.create(
            product=self.product,
            pickup_point=self.pickup_point,
            quantity=2,
        )
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
        self.assertIn(cross_category_bad.pk, similar_ids)
        self.assertLess(similar_ids.index(same_category_candidate.pk), similar_ids.index(cross_category_good.pk))
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


class FooterProductsFeedTest(TestCase):
    """Ленивая выдача карточек перед футером: порции и лимит."""

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Тест', slug='test')
        for i in range(121):
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


class VrAttractionsYmlFeedMissingSectionTest(TestCase):
    def test_feed_returns_404_when_vr_attractions_section_is_missing(self):
        CatalogSection.objects.filter(slug='vr-attrakciony').delete()
        request = RequestFactory().get(reverse('vr_attractions_yml_feed'))
        with self.assertRaisesMessage(Http404, 'VR attractions section is not configured.'):
            vr_attractions_yml_feed_view(request)


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
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(
            username='9991234567',
            email='compare@example.com',
            password='testpass',
        )
        Profile.objects.create(
            user=self.user,
            phone='9991234567',
            email_verified_at=timezone.now(),
            contact_name='Иван Иванов',
            privacy_agreed_at=timezone.now(),
        )
        self.category = Category.objects.create(name='Тестовая категория', slug='compare-test')
        self.products = [
            Product.objects.create(
                category=self.category,
                name=f'Товар {index}',
                slug=f'compare-product-{index}',
                price=Decimal('1000.00') + index,
                is_active=True,
            )
            for index in range(1, 6)
        ]

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


class StandaloneGamePackCatalogTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.section = CatalogSection.objects.create(name='??????? ??? ???????', slug='biz')
        self.category = Category.objects.create(
            section=self.section,
            name='??????? ????',
            slug='game-packs',
        )
        self.games_category = Category.objects.create(name='????', slug='games')
        self.game = Product.objects.create(
            category=self.games_category,
            name='Beat Saber',
            slug='beat-saber',
            price=Decimal('1990.00'),
            is_active=True,
        )
        self.game_pack = GamePack.objects.create(
            category=self.category,
            name='Quest Arcade Pack',
            slug='quest-arcade-pack',
            price=Decimal('4990.00'),
            is_active=True,
            allow_order_on_request=False,
            description='Большой набор игр для VR-клуба.',
        )
        GamePackEntry.objects.create(game_pack=self.game_pack, product=self.game, quantity=1, sort_order=0)
        self.training_service = Service.objects.create(
            name='Настройка зала',
            price=Decimal('1500.00'),
            is_active=True,
        )
        GamePackServiceEntry.objects.create(
            game_pack=self.game_pack,
            service=self.training_service,
            quantity=2,
            note='С выездом специалиста',
            sort_order=0,
        )

    def test_category_page_renders_game_packs_instead_of_products(self):
        response = self.client.get(reverse('catalog:product_list'), {'category': self.category.slug})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_game_packs_category'])
        self.assertContains(response, self.game_pack.name)

    def test_game_pack_detail_page_renders_entries(self):
        response = self.client.get(reverse('catalog:game_pack_detail', kwargs={'slug': self.game_pack.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.game_pack.name)
        self.assertContains(response, self.game.name)

    def test_game_pack_detail_page_uses_product_detail_sections(self):
        response = self.client.get(reverse('catalog:game_pack_detail', kwargs={'slug': self.game_pack.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Описание')
        self.assertContains(response, 'Доп. услуги')
        self.assertContains(response, 'В комплекте')
        self.assertContains(response, self.training_service.name)
        self.assertContains(response, '2 шт.')
        self.assertContains(response, 'С выездом специалиста')

    def test_game_pack_detail_page_shows_services_empty_state(self):
        self.game_pack.service_entries.all().delete()

        response = self.client.get(reverse('catalog:game_pack_detail', kwargs={'slug': self.game_pack.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Доп. услуги для этого пака пока не указаны.')

    def test_game_pack_detail_page_hides_footer_products_feed(self):
        response = self.client.get(reverse('catalog:game_pack_detail', kwargs={'slug': self.game_pack.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="footer-products-feed"', html=False)
