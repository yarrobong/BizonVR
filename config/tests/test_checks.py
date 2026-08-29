from django.test import SimpleTestCase, override_settings

from config.checks import production_launch_settings_check


PRODUCTION_SETTINGS = {
    'DEBUG': False,
    'USE_HTTPS': True,
    'SITE_URL': 'https://bizonvr.ru',
    'SECRET_KEY': 'prod-secret-key',
    'ALLOWED_HOSTS': ['bizonvr.ru', 'www.bizonvr.ru'],
    'ALLOWED_HOSTS_WAS_SET': True,
    'EMAIL_HOST': 'smtp.bizonvr.ru',
    'EMAIL_PORT': 587,
    'EMAIL_PORT_WAS_SET': True,
    'EMAIL_PORT_CONFIG_ERROR': '',
    'EMAIL_HOST_USER': 'orders@bizonvr.ru',
    'EMAIL_HOST_PASSWORD': 'smtp-password',
    'EMAIL_USE_TLS': True,
    'EMAIL_USE_SSL': False,
    'DEFAULT_FROM_EMAIL': 'BizonVR <orders@bizonvr.ru>',
    'LEGAL_OPERATOR_FULL_NAME': 'Индивидуальный предприниматель Едигарьев Ярослав Алексеевич',
    'LEGAL_OPERATOR_INN': '667907832209',
    'LEGAL_OPERATOR_OGRN': '325665800130159',
    'LEGAL_OPERATOR_PD_EMAIL': 'orders@bizonvr.ru',
}


class ProductionLaunchSettingsCheckTests(SimpleTestCase):
    @override_settings(**PRODUCTION_SETTINGS)
    def test_valid_production_settings_pass_custom_check(self):
        messages = production_launch_settings_check(None)

        self.assertEqual(messages, [])

    @override_settings(**(PRODUCTION_SETTINGS | {'SITE_URL': 'http://bizonvr.ru'}))
    def test_http_site_url_fails_in_production(self):
        messages = production_launch_settings_check(None)

        self.assertIn('config.E002', {message.id for message in messages})

    @override_settings(**(PRODUCTION_SETTINGS | {
        'EMAIL_HOST': '',
        'EMAIL_HOST_USER': '',
        'EMAIL_HOST_PASSWORD': '',
        'DEFAULT_FROM_EMAIL': '',
        'EMAIL_PORT_WAS_SET': False,
    }))
    def test_missing_email_settings_fail_in_production(self):
        messages = production_launch_settings_check(None)

        error = next(message for message in messages if message.id == 'config.E001')
        self.assertIn('DEFAULT_FROM_EMAIL', error.hint)
        self.assertIn('EMAIL_HOST', error.hint)
        self.assertIn('EMAIL_HOST_PASSWORD', error.hint)
        self.assertIn('EMAIL_HOST_USER', error.hint)
        self.assertIn('EMAIL_PORT', error.hint)

    @override_settings(**(PRODUCTION_SETTINGS | {'SECRET_KEY': 'django-insecure-change-me'}))
    def test_insecure_secret_key_fails_in_production(self):
        messages = production_launch_settings_check(None)

        error = next(message for message in messages if message.id == 'config.E001')
        self.assertIn('SECRET_KEY', error.hint)

    @override_settings(**(PRODUCTION_SETTINGS | {'USE_HTTPS': False}))
    def test_https_must_be_enabled_in_production(self):
        messages = production_launch_settings_check(None)

        error = next(message for message in messages if message.id == 'config.E006')
        self.assertIn('USE_HTTPS', error.hint)

    @override_settings(**(PRODUCTION_SETTINGS | {
        'EMAIL_PORT': 587,
        'EMAIL_PORT_WAS_SET': True,
        'EMAIL_PORT_CONFIG_ERROR': 'smtp-port',
    }))
    def test_invalid_email_port_fails_custom_check(self):
        messages = production_launch_settings_check(None)

        self.assertIn('config.E004', {message.id for message in messages})
