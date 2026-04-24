"""
Формы оформления заказа (Фаза 4).
Временно: PurchaseRequestForm — заявка на покупку (телефон + Telegram).
"""
import json
import re

from django import forms

from .models import Order


class PurchaseRequestForm(forms.Form):
    """Форма заявки на покупку: телефон обязателен, Telegram опционален."""
    product_id = forms.IntegerField(required=True, widget=forms.HiddenInput())
    variant_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    source_path = forms.CharField(required=False, widget=forms.HiddenInput())
    phone = forms.CharField(
        label='Телефон',
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'purchase-request-input js-phone-mask',
            'placeholder': '+7 (999) 999-99-99',
            'inputmode': 'tel',
            'autocomplete': 'tel',
        }),
    )
    telegram = forms.CharField(
        label='Telegram',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'purchase-request-input',
            'placeholder': '@username или ссылка t.me/username',
            'autocomplete': 'off',
        }),
    )
    agree_personal_data = forms.BooleanField(
        label='Согласие на обработку персональных данных',
        required=True,
        error_messages={'required': 'Необходимо согласие на обработку персональных данных.'},
        widget=forms.CheckboxInput(attrs={'class': 'purchase-request-checkbox'}),
    )

    def clean_phone(self):
        value = (self.cleaned_data.get('phone') or '').strip()
        digits = re.sub(r'\D', '', value)
        if len(digits) < 10:
            raise forms.ValidationError('Введите корректный номер телефона.')
        return value

    def clean_product_id(self):
        return int(self.cleaned_data.get('product_id') or 0)

    def clean_variant_id(self):
        value = self.cleaned_data.get('variant_id')
        if value in (None, ''):
            return None
        return int(value)

    def clean_source_path(self):
        value = (self.cleaned_data.get('source_path') or '').strip()
        return value[:500]

    def clean_telegram(self):
        value = (self.cleaned_data.get('telegram') or '').strip()
        if not value:
            return ''
        lower_value = value.lower()
        if lower_value.startswith('https://t.me/'):
            value = value.split('t.me/', 1)[1]
        elif lower_value.startswith('http://t.me/'):
            value = value.split('t.me/', 1)[1]
        elif lower_value.startswith('t.me/'):
            value = value.split('t.me/', 1)[1]
        value = value.strip().lstrip('@')
        if not value:
            return ''
        if ' ' in value:
            return (self.cleaned_data.get('telegram') or '').strip()
        return f'@{value}'


class CheckoutForm(forms.Form):
    """Форма контактов и доставки при оформлении заказа."""

    first_name = forms.CharField(
        label='ФИО',
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-2.5 text-white placeholder:text-gray-500 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30',
            'placeholder': 'Иван Иванов',
            'autocomplete': 'name',
        }),
    )
    last_name = forms.CharField(
        label='Фамилия',
        max_length=150,
        required=False,
        widget=forms.HiddenInput(),
    )
    phone = forms.CharField(
        label='Телефон',
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'js-phone-mask w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-2.5 text-white placeholder:text-gray-500 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30',
            'placeholder': '+7 (999) 999-99-99',
            'inputmode': 'tel',
            'autocomplete': 'tel',
        }),
    )
    email = forms.EmailField(
        label='Email',
        required=False,
        widget=forms.HiddenInput(),
    )
    contact_channel = forms.ChoiceField(
        label='Как с вами связаться',
        required=True,
        initial=Order.CONTACT_CHANNEL_CALL,
        choices=Order.CONTACT_CHANNEL_CHOICES,
        widget=forms.HiddenInput(),
    )
    contact_handle = forms.CharField(
        label='Telegram или WhatsApp',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-2.5 text-white placeholder:text-gray-500 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30',
            'placeholder': '@username или номер WhatsApp',
            'autocomplete': 'off',
        }),
    )
    delivery_type = forms.ChoiceField(
        label='Как получить заказ',
        required=True,
        initial=Order.DELIVERY_CDEK_PVZ,
        choices=[(Order.DELIVERY_CDEK_PVZ, 'CDEK до ПВЗ')],
        widget=forms.HiddenInput(),
    )
    city_text = forms.CharField(
        label='Город',
        max_length=120,
        required=False,
        widget=forms.HiddenInput(),
    )
    recipient_is_customer = forms.BooleanField(
        label='Получатель совпадает с покупателем',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(),
    )
    recipient_name = forms.CharField(
        label='ФИО получателя',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-2.5 text-white placeholder:text-gray-500 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30',
            'placeholder': 'Иванов Иван',
            'autocomplete': 'name',
        }),
    )
    recipient_phone = forms.CharField(
        label='Телефон получателя',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'js-phone-mask w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-2.5 text-white placeholder:text-gray-500 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30',
            'placeholder': '+7 (999) 999-99-99',
            'inputmode': 'tel',
            'autocomplete': 'tel',
        }),
    )
    address_line = forms.CharField(
        label='Код ПВЗ СДЭК',
        required=False,
        widget=forms.HiddenInput(),
    )
    cdek_office_snapshot_raw = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )
    cdek_tariff_snapshot_raw = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )
    delivery_comment = forms.CharField(
        label='Комментарий для доставки',
        required=False,
        widget=forms.HiddenInput(),
    )
    payment_method = forms.ChoiceField(
        label='Как вам удобнее оплатить после подтверждения',
        required=True,
        initial=Order.PAYMENT_METHOD_SBP,
        choices=Order.PUBLIC_PAYMENT_METHOD_CHOICES,
        widget=forms.HiddenInput(),
    )
    business_company_name = forms.CharField(
        label='Организация',
        max_length=255,
        required=False,
        widget=forms.HiddenInput(),
    )
    business_checking_account = forms.CharField(
        label='Номер счёта',
        max_length=64,
        required=False,
        widget=forms.HiddenInput(),
    )
    business_inn = forms.CharField(
        label='ИНН',
        max_length=32,
        required=False,
        widget=forms.HiddenInput(),
    )
    business_kpp = forms.CharField(
        label='КПП',
        max_length=32,
        required=False,
        widget=forms.HiddenInput(),
    )
    business_bank_name = forms.CharField(
        label='Банк',
        max_length=255,
        required=False,
        widget=forms.HiddenInput(),
    )
    business_bik = forms.CharField(
        label='БИК',
        max_length=20,
        required=False,
        widget=forms.HiddenInput(),
    )
    business_correspondent_account = forms.CharField(
        label='Корр. счёт банка',
        max_length=64,
        required=False,
        widget=forms.HiddenInput(),
    )
    business_phone = forms.CharField(
        label='Телефон контактного лица',
        max_length=40,
        required=False,
        widget=forms.HiddenInput(),
    )
    business_telegram = forms.CharField(
        label='Telegram',
        max_length=120,
        required=False,
        widget=forms.HiddenInput(),
    )
    business_whatsapp = forms.CharField(
        label='WhatsApp',
        max_length=120,
        required=False,
        widget=forms.HiddenInput(),
    )
    comment = forms.CharField(
        label='Комментарий к заказу',
        required=False,
        widget=forms.HiddenInput(),
    )
    promo_code = forms.CharField(
        label='Промокод',
        max_length=64,
        required=False,
        widget=forms.HiddenInput(),
    )
    agree_personal_data = forms.BooleanField(
        label='Согласие на обработку персональных данных',
        required=True,
        error_messages={'required': 'Необходимо согласие на обработку персональных данных.'},
        widget=forms.CheckboxInput(),
    )
    agree_offer = forms.BooleanField(
        label='Принятие условий оферты',
        required=True,
        error_messages={'required': 'Необходимо принять условия оферты.'},
        widget=forms.CheckboxInput(),
    )

    def __init__(self, *args, user=None, selected_city=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_phone(self):
        value = (self.cleaned_data.get('phone') or '').strip()
        digits = re.sub(r'\D', '', value)
        if len(digits) < 10:
            raise forms.ValidationError('Введите корректный номер телефона.')
        return value

    def clean_first_name(self):
        value = ' '.join((self.cleaned_data.get('first_name') or '').split())
        if not value:
            raise forms.ValidationError('Укажите имя и фамилию.')
        return value

    def clean_last_name(self):
        return ' '.join((self.cleaned_data.get('last_name') or '').split())

    def clean_promo_code(self):
        value = (self.cleaned_data.get('promo_code') or '').strip()
        if not value:
            return value
        from .models import PromoCode
        promo = PromoCode.objects.filter(code__iexact=value, is_active=True).first()
        if not promo:
            raise forms.ValidationError('Промокод не найден или недействителен.')
        return promo.code  # сохраняем нормализованный код

    def clean_email(self):
        return (self.cleaned_data.get('email') or '').strip()

    def clean_contact_handle(self):
        return (self.cleaned_data.get('contact_handle') or '').strip()

    def clean_delivery_type(self):
        return (self.cleaned_data.get('delivery_type') or '').strip()

    def clean_city_text(self):
        return (self.cleaned_data.get('city_text') or '').strip()

    def clean_recipient_name(self):
        return ' '.join((self.cleaned_data.get('recipient_name') or '').split())

    def clean_recipient_phone(self):
        value = (self.cleaned_data.get('recipient_phone') or '').strip()
        if not value:
            return value
        digits = re.sub(r'\D', '', value)
        if len(digits) < 10:
            raise forms.ValidationError('Введите корректный номер телефона получателя.')
        return value

    def clean_address_line(self):
        return (self.cleaned_data.get('address_line') or '').strip()

    def clean_delivery_comment(self):
        return (self.cleaned_data.get('delivery_comment') or '').strip()

    def clean_cdek_office_snapshot_raw(self):
        return (self.cleaned_data.get('cdek_office_snapshot_raw') or '').strip()

    def clean_cdek_tariff_snapshot_raw(self):
        return (self.cleaned_data.get('cdek_tariff_snapshot_raw') or '').strip()

    def clean_business_company_name(self):
        return ' '.join((self.cleaned_data.get('business_company_name') or '').split())

    def clean_business_checking_account(self):
        return (self.cleaned_data.get('business_checking_account') or '').strip()

    def clean_business_inn(self):
        return (self.cleaned_data.get('business_inn') or '').strip()

    def clean_business_kpp(self):
        return (self.cleaned_data.get('business_kpp') or '').strip()

    def clean_business_bank_name(self):
        return ' '.join((self.cleaned_data.get('business_bank_name') or '').split())

    def clean_business_bik(self):
        return (self.cleaned_data.get('business_bik') or '').strip()

    def clean_business_correspondent_account(self):
        return (self.cleaned_data.get('business_correspondent_account') or '').strip()

    def clean_business_phone(self):
        value = (self.cleaned_data.get('business_phone') or '').strip()
        if not value:
            return value
        digits = re.sub(r'\D', '', value)
        if len(digits) < 10:
            raise forms.ValidationError('Введите корректный номер телефона контактного лица.')
        return value

    def clean_business_telegram(self):
        value = (self.cleaned_data.get('business_telegram') or '').strip()
        if not value:
            return value
        lower_value = value.lower()
        if lower_value.startswith('https://t.me/'):
            value = value.split('t.me/', 1)[1]
        elif lower_value.startswith('http://t.me/'):
            value = value.split('t.me/', 1)[1]
        elif lower_value.startswith('t.me/'):
            value = value.split('t.me/', 1)[1]
        value = value.strip().lstrip('@')
        if not value:
            return ''
        if ' ' in value:
            return (self.cleaned_data.get('business_telegram') or '').strip()
        return f'@{value}'

    def clean_business_whatsapp(self):
        return (self.cleaned_data.get('business_whatsapp') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        first_name = (cleaned_data.get('first_name') or '').strip()
        last_name = (cleaned_data.get('last_name') or '').strip()
        phone = (cleaned_data.get('phone') or '').strip()
        contact_handle = (cleaned_data.get('contact_handle') or '').strip()
        delivery_type = (cleaned_data.get('delivery_type') or '').strip()
        recipient_is_customer = bool(cleaned_data.get('recipient_is_customer'))
        recipient_name = (cleaned_data.get('recipient_name') or '').strip()
        recipient_phone = (cleaned_data.get('recipient_phone') or '').strip()

        office_snapshot = self._parse_cdek_snapshot(
            cleaned_data.get('cdek_office_snapshot_raw'),
            required=True,
            field_name='cdek_office_snapshot_raw',
            missing_message='Выберите ПВЗ СДЭК на карте.',
            invalid_message='Выберите ПВЗ СДЭК на карте.',
        )
        tariff_snapshot = self._parse_cdek_snapshot(
            cleaned_data.get('cdek_tariff_snapshot_raw'),
            required=False,
            field_name='cdek_tariff_snapshot_raw',
            missing_message='',
            invalid_message='Не удалось прочитать данные тарифа CDEK.',
        )

        if office_snapshot:
            office_city = str(office_snapshot.get('city') or '').strip()
            office_postal_code = str(office_snapshot.get('postal_code') or '').strip()
            office_code = str(office_snapshot.get('code') or '').strip()
            office_name = str(office_snapshot.get('name') or '').strip()
            office_address = str(office_snapshot.get('address') or '').strip()
            if not office_city or not office_code or not office_name or not office_address:
                self.add_error('cdek_office_snapshot_raw', 'Выберите ПВЗ СДЭК на карте.')
            else:
                cleaned_data['city_text'] = office_city
                cleaned_data['postal_code'] = office_postal_code
                cleaned_data['address_line'] = f'{office_code} — {office_name}, {office_address}'
                cleaned_data['address'] = cleaned_data['address_line']
                cleaned_data['cdek_office_snapshot'] = office_snapshot
        else:
            cleaned_data['cdek_office_snapshot'] = {}

        cleaned_data['cdek_tariff_snapshot'] = tariff_snapshot or {}
        if delivery_type != Order.DELIVERY_CDEK_PVZ:
            cleaned_data['delivery_type'] = Order.DELIVERY_CDEK_PVZ

        cleaned_data['email'] = ''
        cleaned_data['comment'] = ''
        cleaned_data['delivery_comment'] = ''
        cleaned_data['last_name'] = last_name
        cleaned_data['payment_method'] = Order.PAYMENT_METHOD_SBP

        if contact_handle:
            lower_value = contact_handle.lower()
            if lower_value.startswith(('https://t.me/', 'http://t.me/', 't.me/')):
                contact_handle = contact_handle.split('t.me/', 1)[1]
                contact_handle = contact_handle.strip().lstrip('@')
                cleaned_data['contact_channel'] = Order.CONTACT_CHANNEL_TELEGRAM
                cleaned_data['contact_handle'] = f'@{contact_handle}' if contact_handle else ''
            elif contact_handle.strip().startswith('@'):
                cleaned_data['contact_channel'] = Order.CONTACT_CHANNEL_TELEGRAM
                cleaned_data['contact_handle'] = f"@{contact_handle.strip().lstrip('@')}"
            else:
                cleaned_data['contact_channel'] = Order.CONTACT_CHANNEL_WHATSAPP
                cleaned_data['contact_handle'] = contact_handle.strip()
        else:
            cleaned_data['contact_channel'] = Order.CONTACT_CHANNEL_CALL
            cleaned_data['contact_handle'] = ''

        if recipient_is_customer:
            cleaned_data['recipient_name'] = ' '.join(part for part in [first_name, last_name] if part).strip()
            cleaned_data['recipient_phone'] = phone
        else:
            if not recipient_name:
                self.add_error('recipient_name', 'Укажите ФИО получателя.')
            if not recipient_phone:
                self.add_error('recipient_phone', 'Укажите телефон получателя.')

        cleaned_data['delivery_type'] = Order.DELIVERY_CDEK_PVZ
        if cleaned_data['payment_method'] == Order.PAYMENT_METHOD_INVOICE and not cleaned_data.get('business_phone'):
            cleaned_data['business_phone'] = phone
        cleaned_data['country'] = 'Россия'
        if 'postal_code' not in cleaned_data:
            cleaned_data['postal_code'] = ''
        return cleaned_data

    def _parse_cdek_snapshot(self, raw_value, *, required, field_name, missing_message, invalid_message):
        raw_value = (raw_value or '').strip()
        if not raw_value:
            if required:
                self.add_error(field_name, missing_message)
            return None
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            self.add_error(field_name, invalid_message)
            return None
        if not isinstance(parsed, dict):
            self.add_error(field_name, invalid_message)
            return None
        return parsed
