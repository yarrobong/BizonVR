"""
Формы оформления заказа (Фаза 4).
Временно: PurchaseRequestForm — заявка на покупку (телефон + Telegram).
"""
import re

from django import forms

from .models import Order


class PurchaseRequestForm(forms.Form):
    """Форма заявки на покупку: телефон и Telegram."""
    phone = forms.CharField(
        label='Телефон',
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'js-phone-mask w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '+7 (999) 999-99-99',
            'inputmode': 'tel',
            'autocomplete': 'tel',
        }),
    )
    telegram = forms.CharField(
        label='Telegram',
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '@username или ссылка t.me/username',
        }),
    )
    agree_personal_data = forms.BooleanField(
        label='Согласие на обработку персональных данных',
        required=True,
        error_messages={'required': 'Необходимо согласие на обработку персональных данных.'},
        widget=forms.CheckboxInput(),
    )

    def clean_phone(self):
        value = (self.cleaned_data.get('phone') or '').strip()
        digits = re.sub(r'\D', '', value)
        if len(digits) < 10:
            raise forms.ValidationError('Введите корректный номер телефона.')
        return value

    def clean_telegram(self):
        value = (self.cleaned_data.get('telegram') or '').strip()
        if not value:
            raise forms.ValidationError('Укажите ваш Telegram.')
        return value


class CheckoutForm(forms.Form):
    """Форма контактов и доставки при оформлении заказа."""

    PUBLIC_DELIVERY_CHOICES = [
        (Order.DELIVERY_CDEK_PVZ, 'CDEK до ПВЗ'),
        (Order.DELIVERY_CDEK_COURIER, 'CDEK курьер'),
        (Order.DELIVERY_PICKUP, 'Самовывоз'),
        (Order.DELIVERY_CITY, 'Доставка по городу'),
        (Order.DELIVERY_OTHER_TRANSPORT, 'Другая ТК'),
    ]
    ADDRESS_REQUIRED_DELIVERY_TYPES = {
        Order.DELIVERY_CDEK_COURIER,
        Order.DELIVERY_CITY,
        Order.DELIVERY_COURIER,
        Order.DELIVERY_POST,
    }

    first_name = forms.CharField(
        label='Имя',
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': 'Иван',
            'autocomplete': 'given-name',
        }),
    )
    last_name = forms.CharField(
        label='Фамилия',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': 'Иванов',
            'autocomplete': 'family-name',
        }),
    )
    phone = forms.CharField(
        label='Телефон',
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'js-phone-mask w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '+7 (999) 999-99-99',
            'inputmode': 'tel',
            'autocomplete': 'tel',
        }),
    )
    email = forms.EmailField(
        label='Email',
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': 'email@example.com',
            'autocomplete': 'email',
        }),
    )
    contact_channel = forms.ChoiceField(
        label='Как с вами связаться',
        required=True,
        initial=Order.CONTACT_CHANNEL_CALL,
        choices=Order.CONTACT_CHANNEL_CHOICES,
        widget=forms.RadioSelect(),
    )
    contact_handle = forms.CharField(
        label='Контакт в мессенджере',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '@username или номер WhatsApp',
        }),
    )
    delivery_type = forms.ChoiceField(
        label='Как получить заказ',
        required=True,
        initial=Order.DELIVERY_CDEK_PVZ,
        choices=PUBLIC_DELIVERY_CHOICES,
        widget=forms.RadioSelect(),
    )
    city_text = forms.CharField(
        label='Город',
        max_length=120,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': 'Екатеринбург',
        }),
    )
    recipient_is_customer = forms.BooleanField(
        label='Получатель совпадает с покупателем',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(),
    )
    recipient_name = forms.CharField(
        label='Имя и фамилия получателя',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': 'Иванов Иван',
            'autocomplete': 'name',
        }),
    )
    recipient_phone = forms.CharField(
        label='Телефон получателя',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'js-phone-mask w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '+7 (999) 999-99-99',
            'inputmode': 'tel',
            'autocomplete': 'tel',
        }),
    )
    address_line = forms.CharField(
        label='Адрес доставки',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'rows': 3,
            'placeholder': 'Город, улица, дом, офис или ориентир для связи',
        }),
    )
    delivery_comment = forms.CharField(
        label='Комментарий для доставки',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'rows': 2,
            'placeholder': 'Ориентир, подъезд, код домофона или пожелания по связи',
        }),
    )
    payment_method = forms.ChoiceField(
        label='Как вам удобнее оплатить после подтверждения',
        required=True,
        initial=Order.PAYMENT_METHOD_SBP,
        choices=Order.PUBLIC_PAYMENT_METHOD_CHOICES,
        widget=forms.RadioSelect(),
    )
    business_company_name = forms.CharField(
        label='Организация',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': 'ООО Виртуальный Мир',
            'autocomplete': 'organization',
        }),
    )
    business_checking_account = forms.CharField(
        label='Номер счёта',
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '40702810900000000001',
            'inputmode': 'numeric',
        }),
    )
    business_inn = forms.CharField(
        label='ИНН',
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '6677001122',
            'inputmode': 'numeric',
        }),
    )
    business_kpp = forms.CharField(
        label='КПП',
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '667701001',
            'inputmode': 'numeric',
        }),
    )
    business_bank_name = forms.CharField(
        label='Банк',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': 'ПАО Сбербанк',
        }),
    )
    business_bik = forms.CharField(
        label='БИК',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '046577674',
            'inputmode': 'numeric',
        }),
    )
    business_correspondent_account = forms.CharField(
        label='Корр. счёт банка',
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '30101810500000000674',
            'inputmode': 'numeric',
        }),
    )
    business_phone = forms.CharField(
        label='Телефон контактного лица',
        max_length=40,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'js-phone-mask w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '+7 (999) 999-99-99',
            'inputmode': 'tel',
            'autocomplete': 'tel',
        }),
    )
    business_telegram = forms.CharField(
        label='Telegram',
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '@username или t.me/username',
        }),
    )
    business_whatsapp = forms.CharField(
        label='WhatsApp',
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '+7 (999) 999-99-99 или wa.me/79991234567',
        }),
    )
    comment = forms.CharField(
        label='Комментарий к заказу',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'rows': 2,
        }),
    )
    promo_code = forms.CharField(
        label='Промокод',
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': 'Необязательно',
        }),
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
            raise forms.ValidationError('Укажите имя.')
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
        address_line = (cleaned_data.get('address_line') or '').strip()
        city_text = (cleaned_data.get('city_text') or '').strip()
        first_name = (cleaned_data.get('first_name') or '').strip()
        last_name = (cleaned_data.get('last_name') or '').strip()
        phone = (cleaned_data.get('phone') or '').strip()
        email = (cleaned_data.get('email') or '').strip()
        contact_channel = (cleaned_data.get('contact_channel') or '').strip()
        contact_handle = (cleaned_data.get('contact_handle') or '').strip()
        delivery_type = (cleaned_data.get('delivery_type') or '').strip()
        recipient_is_customer = bool(cleaned_data.get('recipient_is_customer'))
        recipient_name = (cleaned_data.get('recipient_name') or '').strip()
        recipient_phone = (cleaned_data.get('recipient_phone') or '').strip()

        if not city_text:
            self.add_error('city_text', 'Укажите город доставки.')
        if delivery_type in self.ADDRESS_REQUIRED_DELIVERY_TYPES and not address_line:
            self.add_error('address_line', 'Укажите адрес доставки.')
        if contact_channel == Order.CONTACT_CHANNEL_EMAIL and not email:
            self.add_error('email', 'Укажите email для связи.')
        if contact_channel in {Order.CONTACT_CHANNEL_TELEGRAM, Order.CONTACT_CHANNEL_WHATSAPP} and not contact_handle:
            self.add_error('contact_handle', 'Укажите контакт в выбранном мессенджере.')

        if contact_channel == Order.CONTACT_CHANNEL_TELEGRAM and contact_handle:
            lower_value = contact_handle.lower()
            if lower_value.startswith('https://t.me/'):
                contact_handle = contact_handle.split('t.me/', 1)[1]
            elif lower_value.startswith('http://t.me/'):
                contact_handle = contact_handle.split('t.me/', 1)[1]
            elif lower_value.startswith('t.me/'):
                contact_handle = contact_handle.split('t.me/', 1)[1]
            contact_handle = contact_handle.strip().lstrip('@')
            cleaned_data['contact_handle'] = f'@{contact_handle}' if contact_handle else ''

        if recipient_is_customer:
            cleaned_data['recipient_name'] = ' '.join(part for part in [first_name, last_name] if part).strip()
            cleaned_data['recipient_phone'] = phone
        else:
            if not recipient_name:
                self.add_error('recipient_name', 'Укажите имя и фамилию получателя.')
            if not recipient_phone:
                self.add_error('recipient_phone', 'Укажите телефон получателя.')

        if delivery_type == Order.DELIVERY_PICKUP:
            cleaned_data['address_line'] = ''
        cleaned_data['payment_method'] = (
            cleaned_data.get('payment_method')
            or Order.PAYMENT_METHOD_SBP
        )
        if cleaned_data['payment_method'] == Order.PAYMENT_METHOD_INVOICE and not cleaned_data.get('business_phone'):
            cleaned_data['business_phone'] = phone
        cleaned_data['country'] = 'Россия'
        cleaned_data['postal_code'] = ''
        return cleaned_data
