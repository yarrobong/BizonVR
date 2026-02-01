"""
Формы оформления заказа (Фаза 4).
"""
import re
from django import forms

from catalog.models import PickupPoint


class CheckoutForm(forms.Form):
    """Форма контактов и доставки при оформлении заказа."""
    phone = forms.CharField(
        label='Телефон',
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '+7 (999) 123-45-67',
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

    def __init__(self, *args, selected_city=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.selected_city = selected_city
        if selected_city:
            self.fields['pickup_point'].queryset = PickupPoint.objects.filter(city=selected_city).order_by('order', 'name')

    def clean_pickup_point(self):
        delivery = self.cleaned_data.get('delivery_type')
        pickup_point = self.cleaned_data.get('pickup_point')
        if delivery == 'pickup' and self.selected_city:
            if PickupPoint.objects.filter(city=self.selected_city).exists() and not pickup_point:
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
