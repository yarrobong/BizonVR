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
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': 'email@example.com',
            'autocomplete': 'email',
        }),
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
        label='Адрес ПВЗ CDEK',
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'rows': 3,
            'placeholder': 'Название или адрес ПВЗ, который удобен для получения',
        }),
    )
    delivery_comment = forms.CharField(
        label='Комментарий для CDEK',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'rows': 2,
            'placeholder': 'Ориентир по ПВЗ, пожелания по выдаче',
        }),
    )
    payment_method = forms.ChoiceField(
        label='Способ оплаты',
        required=False,
        initial=Order.PAYMENT_METHOD_BANK_CARD,
        choices=Order.PUBLIC_PAYMENT_METHOD_CHOICES,
        widget=forms.RadioSelect(),
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

    def clean(self):
        cleaned_data = super().clean()
        address_line = (cleaned_data.get('address_line') or '').strip()
        city_text = (cleaned_data.get('city_text') or '').strip()
        first_name = (cleaned_data.get('first_name') or '').strip()
        last_name = (cleaned_data.get('last_name') or '').strip()
        phone = (cleaned_data.get('phone') or '').strip()
        recipient_is_customer = bool(cleaned_data.get('recipient_is_customer'))
        recipient_name = (cleaned_data.get('recipient_name') or '').strip()
        recipient_phone = (cleaned_data.get('recipient_phone') or '').strip()

        if not city_text:
            self.add_error('city_text', 'Укажите город доставки.')
        if not address_line:
            self.add_error('address_line', 'Укажите адрес ПВЗ CDEK.')

        if recipient_is_customer:
            cleaned_data['recipient_name'] = ' '.join(part for part in [first_name, last_name] if part).strip()
            cleaned_data['recipient_phone'] = phone
        else:
            if not recipient_name:
                self.add_error('recipient_name', 'Укажите имя и фамилию получателя.')
            if not recipient_phone:
                self.add_error('recipient_phone', 'Укажите телефон получателя.')

        cleaned_data['delivery_type'] = Order.DELIVERY_CDEK_PVZ
        cleaned_data['payment_method'] = (
            cleaned_data.get('payment_method')
            or Order.PAYMENT_METHOD_BANK_CARD
        )
        cleaned_data['country'] = 'Россия'
        cleaned_data['postal_code'] = ''
        cleaned_data['pickup_point'] = None
        return cleaned_data
