from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import Category, City, PickupPoint, Product, ProductBundle, ProductBundleItem, ProductStock, Service


@override_settings(CATALOG_API_TOKEN='test-catalog-token', CATALOG_API_DEFAULT_LIMIT=20, CATALOG_API_MAX_LIMIT=2)
class CatalogApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.items_url = reverse('catalog_api:items')
        cls.category = Category.objects.create(name='Шлемы', slug='headsets')
        cls.bundle_category = Category.objects.create(
            name='Комплекты',
            slug='kits',
            is_bundles_category=True,
        )
        cls.city = City.objects.create(name='Екатеринбург', slug='ekb')
        cls.pickup_point = PickupPoint.objects.create(city=cls.city, name='Основной склад')

        cls.product = Product.objects.create(
            category=cls.category,
            name='Meta Quest 3',
            slug='meta-quest-3',
            sku='MQ3-128',
            description='Флагманский VR-шлем',
            price=Decimal('39990.00'),
            is_active=True,
        )
        ProductStock.objects.create(
            product=cls.product,
            pickup_point=cls.pickup_point,
            quantity=5,
        )

        cls.second_product = Product.objects.create(
            category=cls.category,
            name='Pico 4 Ultra',
            slug='pico-4-ultra',
            sku='PICO-4-U',
            description='Шлем для клуба',
            price=Decimal('45990.00'),
            is_active=True,
        )
        ProductStock.objects.create(
            product=cls.second_product,
            pickup_point=cls.pickup_point,
            quantity=3,
        )

        cls.inactive_product = Product.objects.create(
            category=cls.category,
            name='Hidden Quest',
            slug='hidden-quest',
            sku='HIDDEN-1',
            description='Скрытая позиция',
            price=Decimal('9999.00'),
            is_active=False,
        )

        cls.service = Service.objects.create(
            name='Настройка оборудования',
            description='Подключение и базовая настройка VR-оборудования.',
            price=Decimal('15000.00'),
            is_active=True,
        )

        cls.bundle = ProductBundle.objects.create(
            category=cls.bundle_category,
            name='Комплект для VR-клуба',
            slug='vr-club-bundle',
            description='Готовый комплект оборудования.',
        )
        ProductBundleItem.objects.create(bundle=cls.bundle, product=cls.product, quantity=2)

    def _auth_headers(self, token='test-catalog-token'):
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def test_items_requires_token(self):
        response = self.client.get(self.items_url)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'unauthorized')

    def test_items_rejects_invalid_token(self):
        response = self.client.get(self.items_url, **self._auth_headers('wrong-token'))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'unauthorized')

    def test_items_returns_list_for_valid_token(self):
        response = self.client.get(self.items_url, {'type': 'product'}, **self._auth_headers())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('items', payload)
        self.assertIn('pagination', payload)
        self.assertGreaterEqual(payload['pagination']['total'], 2)
        self.assertTrue(any(item['id'] == f'product:{self.product.pk}' for item in payload['items']))

    def test_search_filters_items(self):
        response = self.client.get(
            self.items_url,
            {'q': 'MQ3-128', 'type': 'product'},
            **self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['pagination']['total'], 1)
        self.assertEqual(payload['items'][0]['name'], 'Meta Quest 3')

    def test_limit_is_applied(self):
        response = self.client.get(
            self.items_url,
            {'limit': 1},
            **self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['pagination']['limit'], 1)
        self.assertEqual(len(payload['items']), 1)
        self.assertTrue(payload['pagination']['hasMore'])

    def test_limit_above_maximum_is_clamped(self):
        response = self.client.get(
            self.items_url,
            {'limit': 500},
            **self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['pagination']['limit'], 2)

    def test_inactive_items_are_hidden_by_default(self):
        response = self.client.get(
            self.items_url,
            {'type': 'product'},
            **self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        returned_ids = {item['id'] for item in response.json()['items']}
        self.assertNotIn(f'product:{self.inactive_product.pk}', returned_ids)

    def test_response_does_not_expose_internal_fields(self):
        response = self.client.get(
            self.items_url,
            {'type': 'product', 'q': 'Meta Quest 3'},
            **self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()['items'][0]
        self.assertNotIn('purchase_price', item)
        self.assertNotIn('margin', item)
        self.assertNotIn('supplier', item)
        self.assertEqual(
            set(item.keys()),
            {
                'id',
                'externalId',
                'type',
                'name',
                'description',
                'unit',
                'price',
                'currency',
                'vatRate',
                'sku',
                'category',
                'imageUrl',
                'isActive',
                'updatedAt',
            },
        )

    def test_item_detail_returns_catalog_item(self):
        response = self.client.get(
            reverse('catalog_api:item_detail', args=[f'product:{self.product.pk}']),
            **self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['id'], f'product:{self.product.pk}')
        self.assertEqual(payload['name'], self.product.name)

    def test_unknown_item_detail_returns_404(self):
        response = self.client.get(
            reverse('catalog_api:item_detail', args=['product:999999']),
            **self._auth_headers(),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'not_found')

    def test_bundle_detail_returns_bundle_composition(self):
        response = self.client.get(
            reverse('catalog_api:bundle_detail', args=[f'bundle:{self.bundle.pk}']),
            **self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['type'], 'bundle')
        self.assertEqual(payload['id'], f'bundle:{self.bundle.pk}')
        self.assertEqual(len(payload['items']), 1)
        self.assertEqual(payload['items'][0]['itemId'], f'product:{self.product.pk}')
