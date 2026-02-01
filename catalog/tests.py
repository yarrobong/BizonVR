"""Базовые тесты каталога: поиск, избранное (Фаза 6)."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Category, Favorite, Product

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

    def test_toggle_favorite_requires_login(self):
        url = reverse('catalog:toggle_favorite', kwargs={'product_id': self.product.pk})
        resp = self.client.post(url, {})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(reverse('accounts:login')))

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
        import json
        trigger = json.loads(resp['HX-Trigger'])
        self.assertEqual(trigger['cart-updated']['count'], 1)
