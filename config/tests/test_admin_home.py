from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AdminHomePageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='testpass123',
        )
        self.client.force_login(self.user)

    def test_admin_home_uses_task_based_layout_and_hides_technical_models(self):
        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Глобальный поиск')
        self.assertContains(response, 'Сегодня требует внимания')
        self.assertContains(response, 'Быстрые действия')
        self.assertContains(response, 'Task center')
        self.assertContains(response, 'Служебное')
        self.assertNotContains(response, 'class="addlink"', html=False)
        self.assertNotContains(response, 'class="changelink"', html=False)

        admin_home = response.context['admin_home']
        self.assertEqual(
            [item['label'] for item in admin_home['navigation']],
            ['Главная', 'Продажи', 'Каталог', 'Склад', 'CRM', 'Документы', 'Финансы', 'Настройки', 'Служебное'],
        )

        section_models = {
            section['name']: {model['object_name'] for model in section['models']}
            for section in admin_home['sections']
        }
        self.assertNotIn('OrderItem', section_models['Продажи'])
        self.assertNotIn('GamePackEntry', section_models['Каталог'])
        self.assertNotIn('CharacteristicSourceAlias', section_models['Настройки'])

        service_models = {
            model['object_name']
            for service_section in admin_home['service_sections']
            for model in service_section['models']
        }
        self.assertIn('OrderItem', service_models)
        self.assertIn('GamePackEntry', service_models)
        self.assertIn('CharacteristicSourceAlias', service_models)

        self.assertEqual(
            [action['label'] for action in admin_home['quick_actions']],
            ['Новый заказ', 'Новый товар', 'Приход на склад', 'Создать договор', 'Добавить клиента'],
        )
