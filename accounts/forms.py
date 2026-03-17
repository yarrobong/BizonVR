"""
Формы входа по телефону (Фаза 2).
"""
from django import forms
from django.contrib.auth.forms import SetPasswordForm as DjangoSetPasswordForm
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from .services import normalize_email, normalize_phone

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
    """Форма завершения регистрации: ФИО, email и согласие на обработку ПД."""
    contact_name = forms.CharField(
        label='Контактное лицо (ФИО)',
        max_length=255,
        widget=forms.TextInput(attrs={
            'placeholder': 'Иванов Иван Иванович',
            'autocomplete': 'name',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
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
    agree_privacy = forms.BooleanField(
        label='',
        required=True,
        error_messages={'required': 'Необходимо согласие на обработку персональных данных.'},
    )

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user

    def clean_email(self):
        email = normalize_email(self.cleaned_data.get('email', ''))
        if not email:
            return ''
        queryset = User.objects.filter(email__iexact=email)
        if self.current_user is not None:
            queryset = queryset.exclude(pk=self.current_user.pk)
        if queryset.exists():
            raise forms.ValidationError('Этот email уже используется другим аккаунтом.')
        return email


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

    agree_privacy = forms.BooleanField(
        label='',
        required=False,
        error_messages={'required': 'Подтвердите согласие с юридическими документами.'},
        widget=forms.CheckboxInput(attrs={
            'class': 'mt-1 h-4 w-4 rounded border-gray-600 bg-dark-700 text-accent focus:ring-accent focus:ring-offset-0',
        }),
    )

    def __init__(self, *args, require_privacy=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_privacy = require_privacy
        if require_privacy:
            self.fields['agree_privacy'].required = True
        else:
            self.fields.pop('agree_privacy')

    def clean_contact_name(self):
        value = (self.cleaned_data.get('contact_name') or '').strip()
        if not value:
            raise forms.ValidationError('Укажите ФИО.')
        return value


class NotificationPreferencesForm(forms.Form):
    """Настройки пользовательских уведомлений в кабинете."""

    sms_order_updates_enabled = forms.BooleanField(
        label='SMS по важным статусам',
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 rounded border-gray-600 bg-dark-700 text-accent focus:ring-accent focus:ring-offset-0',
        }),
    )
    marketing_email_enabled = forms.BooleanField(
        label='Маркетинговые письма',
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 rounded border-gray-600 bg-dark-700 text-accent focus:ring-accent focus:ring-offset-0',
        }),
    )
    back_in_stock_enabled = forms.BooleanField(
        label='Уведомления о наличии',
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 rounded border-gray-600 bg-dark-700 text-accent focus:ring-accent focus:ring-offset-0',
        }),
    )


class _BaseEmailVerificationForm(forms.Form):
    """Общая форма для запроса и подтверждения email."""

    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={
            'placeholder': 'email@example.com',
            'autocomplete': 'email',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )

    def __init__(self, *args, current_user=None, email_locked=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user
        self.email_locked = email_locked
        if email_locked:
            self.fields['email'].disabled = True

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            raise forms.ValidationError('Введите корректный email.')
        if self.email_locked:
            return email
        if self.current_user and User.objects.filter(email__iexact=email).exclude(pk=self.current_user.pk).exists():
            raise forms.ValidationError('Этот email уже используется другим аккаунтом.')
        return email


class EmailVerificationRequestForm(_BaseEmailVerificationForm):
    """Форма запроса письма с кодом подтверждения."""


class EmailVerificationConfirmForm(_BaseEmailVerificationForm):
    """Форма ввода кода подтверждения email."""

    code = forms.CharField(
        label='Код на email',
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
            raise forms.ValidationError('Введите цифровой код из email.')
        return code


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
    city = forms.CharField(
        label='Город',
        max_length=120,
        widget=forms.TextInput(attrs={
            'placeholder': 'Екатеринбург',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )
    delivery_type = forms.ChoiceField(
        label='Способ доставки',
        choices=[('cdek_pvz', 'CDEK до ПВЗ')],
        initial='cdek_pvz',
        widget=forms.HiddenInput(),
    )
    address = forms.CharField(
        label='Адрес ПВЗ CDEK',
        required=True,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Название или адрес удобного ПВЗ CDEK',
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

    def clean_city(self):
        value = (self.cleaned_data.get('city') or '').strip()
        if not value:
            raise forms.ValidationError('Укажите город.')
        return value

    def clean(self):
        cleaned_data = super().clean()
        address = (cleaned_data.get('address') or '').strip()
        city = (cleaned_data.get('city') or '').strip()

        if not city:
            self.add_error('city', 'Укажите город.')
        if not address:
            self.add_error('address', 'Укажите адрес ПВЗ CDEK.')

        cleaned_data['delivery_type'] = 'cdek_pvz'
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


class PasswordLoginForm(forms.Form):
    login = forms.CharField(
        label='Email',
        max_length=255,
        widget=forms.TextInput(attrs={
            'placeholder': 'email@example.com',
            'autocomplete': 'email',
            'class': 'w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-3 text-white placeholder:text-gray-500 transition focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20',
        }),
    )
    password = forms.CharField(
        label='Пароль',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Введите пароль',
            'autocomplete': 'current-password',
            'x-ref': 'loginPassword',
            'class': 'w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-3 pr-12 text-white placeholder:text-gray-500 transition focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20',
        }),
    )

    def clean_login(self):
        raw = (self.cleaned_data.get('login') or '').strip()
        if not raw:
            raise forms.ValidationError('Укажите email.')
        email = normalize_email(raw)
        if not email or '@' not in email:
            raise forms.ValidationError('Введите корректный email.')
        return email


class RegistrationForm(forms.Form):
    contact_name = forms.CharField(
        label='Имя и фамилия',
        max_length=255,
        widget=forms.TextInput(attrs={
            'placeholder': 'Иван Иванов',
            'autocomplete': 'name',
            'class': 'w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-3 text-white placeholder:text-gray-500 transition focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20',
        }),
    )
    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={
            'placeholder': 'email@example.com',
            'autocomplete': 'email',
            'class': 'w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-3 text-white placeholder:text-gray-500 transition focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20',
        }),
    )
    password1 = forms.CharField(
        label='Пароль',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Не менее 8 символов',
            'autocomplete': 'new-password',
            'class': 'w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-3 text-white placeholder:text-gray-500 transition focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20',
        }),
    )
    password2 = forms.CharField(
        label='Повторите пароль',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Введите пароль ещё раз',
            'autocomplete': 'new-password',
            'class': 'w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-3 text-white placeholder:text-gray-500 transition focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20',
        }),
    )
    agree_privacy = forms.BooleanField(
        label='',
        required=True,
        error_messages={'required': 'Нужно согласие с обработкой персональных данных.'},
        widget=forms.CheckboxInput(attrs={
            'class': 'mt-0.5 h-4 w-4 rounded border-gray-600 bg-dark-700 text-accent focus:ring-accent focus:ring-offset-0',
        }),
    )

    def clean_contact_name(self):
        value = (self.cleaned_data.get('contact_name') or '').strip()
        if not value:
            raise forms.ValidationError('Укажите имя и фамилию.')
        return value

    def clean_email(self):
        email = normalize_email(self.cleaned_data.get('email') or '')
        if not email:
            raise forms.ValidationError('Введите корректный email.')
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Аккаунт с таким email уже существует.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1') or ''
        password2 = cleaned_data.get('password2') or ''

        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Пароли не совпадают.')

        if password1:
            try:
                validate_password(password1)
            except forms.ValidationError as exc:
                self.add_error('password1', exc)

        return cleaned_data


class EmailLoginRequestForm(forms.Form):
    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={
            'placeholder': 'email@example.com',
            'autocomplete': 'email',
            'class': 'w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-3 text-white placeholder:text-gray-500 transition focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20',
        }),
    )

    def clean_email(self):
        email = normalize_email(self.cleaned_data.get('email') or '')
        if not email:
            raise forms.ValidationError('Введите корректный email.')
        return email


class EmailLoginVerifyForm(EmailLoginRequestForm):
    code = forms.CharField(
        label='Код на email',
        max_length=10,
        widget=forms.TextInput(attrs={
            'placeholder': '123456',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
            'class': 'w-full rounded-2xl border border-white/10 bg-dark-700/80 px-4 py-3 text-center tracking-widest text-white placeholder:text-gray-500 transition focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20',
        }),
    )

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip()
        if not code or not code.isdigit():
            raise forms.ValidationError('Введите цифровой код из email.')
        return code


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={
            'placeholder': 'email@example.com',
            'autocomplete': 'email',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        }),
    )

    def clean_email(self):
        email = normalize_email(self.cleaned_data.get('email') or '')
        if not email:
            raise forms.ValidationError('Введите корректный email.')
        return email


class PasswordResetPhoneVerifyForm(forms.Form):
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
        code = (self.cleaned_data.get('code') or '').strip()
        if not code or not code.isdigit():
            raise forms.ValidationError('Введите цифровой код из SMS.')
        return code


class PasswordSetupForm(DjangoSetPasswordForm):
    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields['new_password1'].label = 'Новый пароль'
        self.fields['new_password2'].label = 'Повторите новый пароль'
        self.fields['new_password1'].widget.attrs.update({
            'placeholder': 'Не менее 8 символов',
            'autocomplete': 'new-password',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        })
        self.fields['new_password2'].widget.attrs.update({
            'placeholder': 'Введите пароль ещё раз',
            'autocomplete': 'new-password',
            'class': 'w-full bg-dark-700 text-white rounded-lg py-2.5 px-4 focus:outline-none focus:ring-1 focus:ring-accent',
        })
