"""Формы для страниц config (контакты и т.д.)."""
import re

from django import forms


class ContactForm(forms.Form):
    """Форма обратной связи на странице контактов."""
    name = forms.CharField(
        label='Имя',
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': 'Ваше имя',
        }),
    )
    email = forms.EmailField(
        label='Email',
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': 'email@example.com',
        }),
    )
    phone = forms.CharField(
        label='Телефон',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'js-phone-mask w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
            'placeholder': '+7 (999) 999-99-99',
            'inputmode': 'tel',
        }),
    )
    message = forms.CharField(
        label='Сообщение',
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent min-h-[120px]',
            'placeholder': 'Ваше сообщение...',
            'rows': 4,
        }),
    )

    def clean_phone(self):
        value = (self.cleaned_data.get('phone') or '').strip()
        if value:
            digits = re.sub(r'\D', '', value)
            if len(digits) < 10:
                raise forms.ValidationError('Введите корректный номер телефона.')
        return value
