"""
Формы входа по телефону (Фаза 2).
"""
from django import forms
from django.contrib.auth import get_user_model

from catalog.models import PickupPoint

from .services import normalize_phone

User = get_user_model()


class PhoneRequestForm(forms.Form):
    """Форма запроса кода: ввод телефона и согласие с политикой конфиденциальности."""
    phone = forms.CharField(
        label='Номер телефона',
        max_length=20,
        widget=forms.TextInput(attrs={
            'placeholder': '+7 (999) 123-45-67',
            'autocomplete': 'tel',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    agree_privacy = forms.BooleanField(
        label='Согласен с политикой конфиденциальности',
        required=True,
        error_messages={'required': 'Необходимо согласие с политикой конфиденциальности.'},
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


class CompleteRegistrationForm(forms.Form):
    """Форма завершения регистрации: ФИО и согласие на обработку ПД."""
    contact_name = forms.CharField(
        label='Контактное лицо (ФИО)',
        max_length=255,
        widget=forms.TextInput(attrs={
            'placeholder': 'Иванов Иван Иванович',
            'autocomplete': 'name',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    agree_privacy = forms.BooleanField(
        label='',
        required=True,
        error_messages={'required': 'Необходимо согласие на обработку персональных данных.'},
    )


class ProfileUpdateForm(forms.Form):
    """Редактирование данных профиля в личном кабинете."""

    contact_name = forms.CharField(
        label='Получатель заказа',
        max_length=255,
        widget=forms.TextInput(attrs={
            'placeholder': 'Иванов Иван Иванович',
            'autocomplete': 'name',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )

    def clean_contact_name(self):
        value = (self.cleaned_data.get('contact_name') or '').strip()
        if not value:
            raise forms.ValidationError('Укажите ФИО.')
        return value


class SavedAddressForm(forms.Form):
    """CRUD-форма сохранённого адреса пользователя."""

    label = forms.CharField(
        label='Название адреса',
        max_length=120,
        widget=forms.TextInput(attrs={
            'placeholder': 'Например: Дом, Офис, Склад',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    recipient_name = forms.CharField(
        label='Получатель',
        max_length=255,
        widget=forms.TextInput(attrs={
            'placeholder': 'Иванов Иван Иванович',
            'autocomplete': 'name',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    phone = forms.CharField(
        label='Телефон',
        max_length=40,
        widget=forms.TextInput(attrs={
            'placeholder': '+7 (999) 123-45-67',
            'autocomplete': 'tel',
            'inputmode': 'tel',
            'class': 'js-phone-mask w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    email = forms.EmailField(
        label='Email',
        required=False,
        widget=forms.EmailInput(attrs={
            'placeholder': 'email@example.com',
            'autocomplete': 'email',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    delivery_type = forms.ChoiceField(
        label='Способ доставки',
        choices=[
            ('courier', 'Курьером'),
            ('pickup', 'Самовывоз'),
            ('post', 'Почтой'),
        ],
        widget=forms.Select(attrs={
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
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
    address = forms.CharField(
        label='Адрес',
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Город, улица, дом, квартира',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    comment = forms.CharField(
        label='Комментарий',
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'placeholder': 'Код домофона, подъезд, этаж',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    is_default = forms.BooleanField(
        label='Использовать по умолчанию',
        required=False,
        widget=forms.CheckboxInput(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pickup_point'].queryset = PickupPoint.objects.order_by('city__order', 'order', 'name')

    def clean_label(self):
        value = (self.cleaned_data.get('label') or '').strip()
        if not value:
            raise forms.ValidationError('Укажите название адреса.')
        return value

    def clean_recipient_name(self):
        value = (self.cleaned_data.get('recipient_name') or '').strip()
        if not value:
            raise forms.ValidationError('Укажите получателя.')
        return value

    def clean_phone(self):
        value = (self.cleaned_data.get('phone') or '').strip()
        phone = normalize_phone(value)
        if len(phone) < 10:
            raise forms.ValidationError('Введите корректный номер телефона (минимум 10 цифр).')
        return phone

    def clean_email(self):
        return (self.cleaned_data.get('email') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        delivery_type = cleaned_data.get('delivery_type')
        pickup_point = cleaned_data.get('pickup_point')
        address = (cleaned_data.get('address') or '').strip()

        if delivery_type == 'pickup':
            if not pickup_point:
                self.add_error('pickup_point', 'Выберите точку выдачи.')
            cleaned_data['address'] = ''
        elif delivery_type in {'courier', 'post'}:
            if not address:
                self.add_error('address', 'Укажите адрес доставки.')
            cleaned_data['pickup_point'] = None

        cleaned_data['comment'] = (cleaned_data.get('comment') or '').strip()
        return cleaned_data


class _BasePhoneChangeForm(forms.Form):
    """Общая валидация нового номера телефона для смены логина."""

    new_phone = forms.CharField(
        label='Новый номер телефона',
        max_length=20,
        widget=forms.TextInput(attrs={
            'placeholder': '+7 (999) 123-45-67',
            'autocomplete': 'tel',
            'inputmode': 'tel',
            'class': 'js-phone-mask w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user

    def clean_new_phone(self):
        raw = (self.cleaned_data.get('new_phone') or '').strip()
        phone = normalize_phone(raw)
        if len(phone) < 10:
            raise forms.ValidationError('Введите корректный номер телефона (минимум 10 цифр).')
        if self.current_user and phone == normalize_phone(self.current_user.username):
            raise forms.ValidationError('Этот номер уже используется в текущем аккаунте.')
        if self.current_user and User.objects.filter(username=phone).exclude(pk=self.current_user.pk).exists():
            raise forms.ValidationError('Этот номер уже используется другим аккаунтом.')
        return phone


class PhoneChangeRequestForm(_BasePhoneChangeForm):
    """Форма запроса SMS-кода на новый номер."""


class PhoneChangeConfirmForm(_BasePhoneChangeForm):
    """Форма подтверждения смены номера по SMS-коду."""

    code = forms.CharField(
        label='Код из SMS',
        max_length=10,
        widget=forms.TextInput(attrs={
            'placeholder': '123456',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent text-center tracking-widest',
        }),
    )

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip()
        if not code or not code.isdigit():
            raise forms.ValidationError('Введите цифровой код из SMS.')
        return code
