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
        required=False,
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
    agree_personal_data = forms.BooleanField(
        label='Согласие на обработку персональных данных',
        required=True,
        error_messages={'required': 'Необходимо согласие на обработку персональных данных.'},
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 rounded border-white/20 bg-transparent text-accent focus:ring-accent',
        }),
    )

    def clean_phone(self):
        value = (self.cleaned_data.get('phone') or '').strip()
        if value:
            digits = re.sub(r'\D', '', value)
            if len(digits) < 10:
                raise forms.ValidationError('Введите корректный номер телефона.')
        return value

    def clean(self):
        cleaned_data = super().clean()
        phone = (cleaned_data.get('phone') or '').strip()
        email = (cleaned_data.get('email') or '').strip()
        if not phone and not email:
            raise forms.ValidationError('Оставьте телефон или email, чтобы мы могли связаться с вами.')
        return cleaned_data


class CallbackForm(forms.Form):
    """Форма заявки на обратный звонок (страница аренды)."""
    name = forms.CharField(
        label='Имя',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Ваше имя',
            'class': 'arenda-callback-input',
        }),
    )
    phone = forms.CharField(
        label='Телефон',
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={
            'placeholder': '+7 (999) 999-99-99',
            'inputmode': 'tel',
            'class': 'arenda-callback-input',
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
        if not value:
            raise forms.ValidationError('Укажите номер телефона.')
        digits = re.sub(r'\D', '', value)
        if len(digits) < 10:
            raise forms.ValidationError('Введите корректный номер телефона.')
        return value


class CompactVRForm(forms.Form):
    """Форма лида с лендинга Compact VR-арены."""
    name = forms.CharField(label='Имя', max_length=150, required=True)
    contact = forms.CharField(label='Телефон или Telegram', max_length=100, required=True)
    city = forms.CharField(label='Город', max_length=150, required=True)
    format = forms.ChoiceField(
        label='Формат',
        choices=[('Start', 'Start'), ('Core', 'Core'), ('Scale', 'Scale')],
        required=True,
    )
    email = forms.EmailField(label='Email', required=False)
    premises = forms.CharField(label='Площадь / тип помещения', max_length=300, required=False)
    comment = forms.CharField(label='Комментарий', required=False, widget=forms.Textarea())
    agree_personal_data = forms.BooleanField(
        label='Согласие на обработку персональных данных',
        required=True,
        error_messages={'required': 'Необходимо согласие на обработку персональных данных.'},
    )
