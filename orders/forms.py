"""
Формы оформления заказа (Фаза 4).
Временно: PurchaseRequestForm — заявка на покупку (телефон + Telegram).
"""
import re
from django import forms

from catalog.models import PickupPoint


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
    first_name = forms.CharField(
        label='Имя',
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    last_name = forms.CharField(
        label='Фамилия',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    email = forms.EmailField(
        label='Email',
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    address = forms.CharField(
        label='Адрес доставки',
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'rows': 3,
            'placeholder': 'Город, улица, дом, квартира',
        }),
    )
    delivery_type = forms.ChoiceField(
        label='Способ доставки',
        choices=[
            ('courier', 'Курьером'),
            ('pickup', 'Самовывоз'),
            ('post', 'Почтой'),
        ],
        required=True,
        widget=forms.Select(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
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
    pickup_point = forms.ModelChoiceField(
        label='Точка выдачи',
        queryset=PickupPoint.objects.none(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
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
        self.fields['pickup_point'].queryset = PickupPoint.objects.order_by('city__order', 'order', 'name')
        self.user = user

    def clean_pickup_point(self):
        delivery = self.cleaned_data.get('delivery_type')
        pickup_point = self.cleaned_data.get('pickup_point')
        if delivery == 'pickup' and not pickup_point:
            raise forms.ValidationError('Выберите точку выдачи.')
        return pickup_point

    def clean_phone(self):
        value = (self.cleaned_data.get('phone') or '').strip()
        digits = re.sub(r'\D', '', value)
        if len(digits) < 10:
            raise forms.ValidationError('Введите корректный номер телефона.')
        return value

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

    def clean(self):
        cleaned_data = super().clean()
        delivery_type = cleaned_data.get('delivery_type')
        address = (cleaned_data.get('address') or '').strip()

        if delivery_type in {'courier', 'post'} and not address:
            self.add_error('address', 'Укажите адрес доставки.')
        if delivery_type == 'pickup':
            cleaned_data['address'] = ''
        return cleaned_data
