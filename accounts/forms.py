"""
Формы входа по телефону (Фаза 2).
"""
from django import forms
from .services import normalize_phone


class PhoneRequestForm(forms.Form):
    """Форма запроса кода: ввод телефона."""
    phone = forms.CharField(
        label='Номер телефона',
        max_length=20,
        widget=forms.TextInput(attrs={
            'placeholder': '+7 (999) 123-45-67',
            'autocomplete': 'tel',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )

    def clean_phone(self):
        raw = self.cleaned_data.get('phone', '').strip()
        phone = normalize_phone(raw)
        if len(phone) < 10:
            raise forms.ValidationError('Введите корректный номер телефона (минимум 10 цифр).')
        return phone


class CodeVerifyForm(forms.Form):
    """Форма проверки кода."""
    phone = forms.CharField(widget=forms.HiddenInput())
    code = forms.CharField(
        label='Код из SMS',
        max_length=10,
        widget=forms.TextInput(attrs={
            'placeholder': '123456',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent text-center text-lg tracking-widest',
        }),
    )

    def clean_code(self):
        code = self.cleaned_data.get('code', '').strip()
        if not code or not code.isdigit():
            raise forms.ValidationError('Введите цифровой код из SMS.')
        return code
