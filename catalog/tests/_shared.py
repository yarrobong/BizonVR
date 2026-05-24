"""Базовые тесты каталога: поиск, избранное (Фаза 6)."""
import html as html_lib
from importlib import import_module
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
from django.apps import apps as django_apps
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
from django.test import Client, TestCase, override_settings, tag
from django.test.client import RequestFactory
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from PIL import Image as PilImage

from accounts.models import Profile
from config.forms import CallbackForm, ContactForm
from config.legal_docs import LEGAL_BUNDLE_VERSION
from config.utils.spam_protection import check_spam_submission, is_spam_request
from orders.models import Order, OrderItem

from catalog.cart_services import get_cart_count, get_cart_items, get_favorite_product_ids, group_cart_items
from catalog.characteristic_normalization import normalize_characteristic_value
from catalog.club_formats import normalize_club_format
from catalog.context_processors import catalog_menu
from catalog.filter_audit import (
    build_filter_audit_dashboard_context,
    get_new_uncovered_sources,
    get_new_uncovered_values,
    sync_catalog_filter_audit_snapshots,
)
from catalog.filtering import CatalogFilterService
from catalog.filter_bootstrap import build_alias_suggestions
from catalog.filter_bootstrap import SAFE_AUTO_APPLICABLE
from catalog.filter_presets import get_typed_value_sort_key
from catalog.filter_setup_wizard import CatalogFilterSetupWizard
from catalog.import_workflow import CatalogImportWorkflowService, make_direct_target_reference
from catalog.importers import CatalogDataImporter
from catalog.image_utils import build_responsive_image_data
from catalog.product_descriptions import build_admin_constructor_state, migrate_legacy_blocks
from catalog.pricing import PURCHASE_MODE_STOCK, resolve_in_stock_price, resolve_public_purchase_mode
from catalog.stock import public_product_stock_status
from catalog.templatetags.catalog_tags import build_product_card_gallery_images
from catalog.models import (
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
from catalog.views import feeds as feed_views
from catalog.views.feeds import vr_attractions_yml_feed_view
from catalog.admin.filters import CharacteristicDefinitionAdminForm
from catalog.admin.products import ProductAdmin, ProductAdminForm, ProductContentBlockAdmin, ProductContentBlockInline, ProductImageInline

User = get_user_model()
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ClubFormatNormalizationTest(TestCase):
    def test_normalize_club_format_accepts_known_values_and_aliases(self):
        expected_values = {
            '': '',
            '  ': '',
            'club': ProductGameMetadata.FORMAT_CLUB,
            'arena': ProductGameMetadata.FORMAT_ARENA,
            'VR-клуб': ProductGameMetadata.FORMAT_CLUB,
            'Арена': ProductGameMetadata.FORMAT_ARENA,
            'VR-зона': ProductGameMetadata.FORMAT_CLUB,
            'Выездной формат': ProductGameMetadata.FORMAT_MOBILE,
        }

        for raw_value, expected_value in expected_values.items():
            with self.subTest(raw_value=raw_value):
                self.assertEqual(normalize_club_format(raw_value), expected_value)

    def test_normalize_club_format_raises_for_unknown_values(self):
        with self.assertRaisesMessage(ValueError, 'Unknown club format: experimental'):
            normalize_club_format('experimental')


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
        resp = self.client.get(reverse('catalog:vr_club_games'), {
            'device': 'Quest',
            'players': '4',
            'headset_count': '6',
        })

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Готовые паки')
        self.assertContains(resp, 'Конструктор игр')
        self.assertContains(resp, 'Получить подбор')
        self.assertContains(resp, self.game.name)
        self.assertContains(resp, self.service.name)
        self.assertContains(
            resp,
            'name="headset_count" type="number" min="1" value="6"',
            html=False,
        )
        self.assertContains(resp, 'name="devices" value="Quest"', html=False)

    def test_vr_club_games_page_uses_localized_placeholder_copy(self):
        response = self.client.get(reverse('catalog:vr_club_games'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Библиотека VR-игр')
        self.assertNotContains(response, 'VR game library')

    def test_vr_club_games_empty_states_use_buyer_facing_copy(self):
        self.pack.is_active = False
        self.pack.save(update_fields=['is_active'])
        self.game.game_metadata.is_active = False
        self.game.game_metadata.save(update_fields=['is_active'])
        self.service.is_active = False
        self.service.save(update_fields=['is_active'])

        resp = self.client.get(reverse('catalog:vr_club_games'))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Подборка паков обновляется')
        self.assertContains(resp, 'Игры по вашим фильтрам не найдены')
        self.assertContains(resp, 'Услуги запуска подбираем под задачу')
        self.assertContains(resp, 'Оставить заявку')
        self.assertContains(resp, 'Обсудить запуск')
        self.assertContains(resp, 'id="quiz"', html=False)
        self.assertNotContains(resp, 'GamePack')
        self.assertNotContains(resp, 'ProductGameMetadata')
        self.assertNotContains(resp, 'админка')
        self.assertNotContains(resp, 'админ-панел')

    def test_vr_club_games_page_does_not_show_unpublished_packs(self):
        self.pack.show_on_vr_club_page = False
        self.pack.save(update_fields=['show_on_vr_club_page'])
        hidden_pack = GamePack.objects.create(
            category=self.category,
            name='Hidden Club Pack',
            slug='hidden-club-pack',
            price=Decimal('4500.00'),
            is_active=True,
            show_on_vr_club_page=False,
        )

        resp = self.client.get(reverse('catalog:vr_club_games'))

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['has_vr_club_packs'])
        self.assertContains(resp, 'Подборка паков обновляется')
        self.assertContains(resp, 'id="quiz"', html=False)
        self.assertNotContains(resp, self.pack.name)
        self.assertNotContains(resp, hidden_pack.name)

    def test_vr_club_games_page_shows_filtered_empty_state_without_hidden_fallback(self):
        self.pack.devices = 'Pico'
        self.pack.save(update_fields=['devices'])
        hidden_pack = GamePack.objects.create(
            category=self.category,
            name='Hidden Quest Pack',
            slug='hidden-quest-pack',
            price=Decimal('4900.00'),
            is_active=True,
            show_on_vr_club_page=False,
            devices='Quest',
        )

        resp = self.client.get(reverse('catalog:vr_club_games'), {'device': 'Quest'})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['has_vr_club_packs'])
        self.assertContains(resp, 'По текущим фильтрам паки не найдены')
        self.assertNotContains(resp, self.pack.name)
        self.assertNotContains(resp, hidden_pack.name)

    def test_vr_club_games_device_filter_matches_whole_tokens(self):
        similar_game = Product.objects.create(
            category=self.category,
            name='Similar Device Game',
            slug='similar-device-game',
            price=Decimal('1000.00'),
            is_active=True,
        )
        ProductGameMetadata.objects.create(
            product=similar_game,
            devices='SuperQuest',
            genres='PvP',
            min_players=1,
            max_players=4,
            age_rating='12+',
            club_format=ProductGameMetadata.FORMAT_CLUB,
            b2b_note='Похоже по названию устройства, но это другой токен.',
        )
        similar_pack = GamePack.objects.create(
            category=self.category,
            name='SuperQuest Pack',
            slug='superquest-pack',
            price=Decimal('4500.00'),
            is_active=True,
            show_on_vr_club_page=True,
            devices='SuperQuest',
        )

        resp = self.client.get(reverse('catalog:vr_club_games'), {'device': 'Quest'})

        self.assertContains(resp, self.game.name)
        self.assertNotContains(resp, similar_game.name)
        self.assertNotContains(resp, similar_pack.name)

    def test_vr_club_games_page_keeps_normalized_legacy_pack_visible_for_club_filter(self):
        self.pack.club_format = normalize_club_format('VR-зона')
        self.pack.save(update_fields=['club_format'])
        other_pack = GamePack.objects.create(
            category=self.category,
            name='Home Pack',
            slug='home-pack',
            price=Decimal('5500.00'),
            is_active=True,
            show_on_vr_club_page=True,
            club_format=ProductGameMetadata.FORMAT_HOME,
        )

        resp = self.client.get(reverse('catalog:vr_club_games'), {'club_format': ProductGameMetadata.FORMAT_CLUB})

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.pack.name)
        self.assertContains(resp, self.game.name)
        self.assertNotContains(resp, other_pack.name)

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

    def test_custom_game_pack_cart_explains_services_are_separate_lines(self):
        resp = self.client.post(reverse('catalog:add_vr_club_custom_pack'), {
            'game_ids': [str(self.game.pk)],
            'service_ids': [str(self.service.pk)],
            'headset_count': '4',
            'devices': 'Quest',
            'club_format': ProductGameMetadata.FORMAT_CLUB,
        })
        cart_resp = self.client.get(reverse('catalog:cart'))

        self.assertRedirects(resp, reverse('catalog:cart'))
        self.assertContains(cart_resp, 'Выбранные услуги добавлены ниже отдельными строками.')

    def test_active_game_metadata_requires_public_card_quality(self):
        self.game.image = None
        self.game.save(update_fields=['image'])
        metadata = self.game.game_metadata
        metadata.devices = ''
        metadata.genres = ''
        metadata.b2b_note = ''
        metadata.min_players = 4
        metadata.max_players = 2

        with self.assertRaises(ValidationError) as ctx:
            metadata.full_clean()

        self.assertIn('devices', ctx.exception.message_dict)
        self.assertIn('genres', ctx.exception.message_dict)
        self.assertIn('b2b_note', ctx.exception.message_dict)
        self.assertIn('max_players', ctx.exception.message_dict)
        self.assertIn('product', ctx.exception.message_dict)

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


__all__ = [name for name in globals() if not name.startswith('__')]
__all__.append('_build_test_uploaded_image')
