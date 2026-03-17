from django import forms
from django.contrib.auth import get_user_model
from django.forms import BaseFormSet, formset_factory
from django.utils import timezone

from catalog.models import Product, ProductVariant
from orders.models import Order, OrderItem

from .models import (
    Cargo,
    CargoItem,
    CargoPhoto,
    DealSavedView,
    ContractCompanyProfile,
    ContractDocument,
    ContractTemplate,
    Expense,
    FinanceDeal,
    FinanceDealType,
    FinanceExpense,
    FinanceExpenseCategory,
    FinancePayout,
    InventoryBalance,
    ManagerDeal,
    ManagerClient,
    ManagerPersonAlias,
    ManagerDealParticipant,
    Purchase,
    PurchaseItem,
    Reservation,
    ReservationItem,
    TradeInItem,
    TransportLeg,
    Warehouse,
)
from .services import finance_month_label


INPUT_CLASS = (
    'w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white '
    'focus:outline-none focus:ring-2 focus:ring-teal-400'
)
TEXTAREA_CLASS = INPUT_CLASS
CHECKBOX_CLASS = 'h-4 w-4 rounded border-slate-600 bg-slate-950 text-cyan-400 focus:outline-none focus:ring-2 focus:ring-teal-400'
FILTER_DATE_INPUT_CLASS = (
    'w-full rounded border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white '
    'placeholder:text-slate-400 focus:border-cyan-400 focus:outline-none focus:ring-2 focus:ring-cyan-400/20'
)
FILTER_DATE_INPUT_FORMATS = ('%d.%m.%Y', '%Y-%m-%d')
DATETIME_INPUT_FORMATS = ('%Y-%m-%dT%H:%M', '%d.%m.%Y %H:%M')


def manager_date_picker_widget(attrs=None):
    widget_attrs = {
        'type': 'text',
        'autocomplete': 'off',
        'placeholder': 'ДД.ММ.ГГГГ',
        'inputmode': 'numeric',
        'data-manager-date-picker': 'true',
        'class': f'{INPUT_CLASS} manager-date-picker-input',
    }
    if attrs:
        attrs = dict(attrs)
        extra_classes = attrs.pop('class', '')
        if extra_classes:
            widget_attrs['class'] = f"{widget_attrs['class']} {extra_classes}".strip()
        widget_attrs.update(attrs)
    return forms.DateInput(format='%Y-%m-%d', attrs=widget_attrs)


def filter_date_picker_widget():
    return forms.DateInput(
        format='%Y-%m-%d',
        attrs={
            'type': 'text',
            'autocomplete': 'off',
            'placeholder': 'ДД.ММ.ГГГГ',
            'inputmode': 'numeric',
            'data-manager-date-picker': 'true',
            'class': f'{FILTER_DATE_INPUT_CLASS} manager-date-picker-input',
        },
    )


def filter_date_picker_field(*, label):
    return forms.DateField(
        required=False,
        label=label,
        input_formats=FILTER_DATE_INPUT_FORMATS,
        widget=filter_date_picker_widget(),
    )


class StyledFormMixin:
    compact_form_fields = False
    field_metadata = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.compact_form_fields = bool(getattr(self, 'compact_form_fields', False))
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', CHECKBOX_CLASS)
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('class', TEXTAREA_CLASS)
                widget.attrs.setdefault('rows', 3)
            elif isinstance(widget, forms.SelectMultiple):
                widget.attrs.setdefault('class', INPUT_CLASS)
            else:
                widget.attrs.setdefault('class', INPUT_CLASS)
            self._configure_field(field_name, field)

    def full_clean(self):
        super().full_clean()
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            if field_name in self.errors:
                field.widget.attrs['aria-invalid'] = 'true'
            else:
                field.widget.attrs.pop('aria-invalid', None)

    def clean(self):
        cleaned_data = super().clean()
        for field_name, field in self.fields.items():
            if field_name not in cleaned_data:
                continue
            value = cleaned_data.get(field_name)
            if value in (None, '') or not isinstance(value, str):
                continue
            mask_kind = field.widget.attrs.get('data-manager-mask')
            normalized = value.strip()
            if mask_kind == 'email':
                normalized = normalized.lower()
            elif mask_kind in {'telegram', 'telegram-loose'}:
                normalized = self._normalize_telegram(normalized)
            cleaned_data[field_name] = normalized
        return cleaned_data

    def _configure_field(self, field_name, field):
        metadata = dict(self._infer_field_metadata(field_name, field))
        field.manager_status_label = 'Обязательно' if field.required else 'Можно пропустить'
        field.manager_status_tone = 'required' if field.required else 'optional'
        field.manager_autofill_note = metadata.get('autofill_note', '')
        helper_text = metadata.get('helper_text')
        if not helper_text:
            helper_text = metadata.get('help_text')
        field.manager_helper_text = helper_text or field.help_text or ''
        if field.manager_helper_text:
            field.help_text = field.manager_helper_text

        if isinstance(field, forms.DateTimeField):
            field.input_formats = DATETIME_INPUT_FORMATS
            field.widget.attrs.setdefault('autocomplete', 'off')
            field.widget.attrs.setdefault('step', 60)
        elif isinstance(field, forms.DateField):
            field.input_formats = FILTER_DATE_INPUT_FORMATS
            if not field.widget.attrs.get('data-manager-date-picker'):
                field.widget = manager_date_picker_widget(field.widget.attrs)

        placeholder = metadata.get('placeholder') or self._infer_placeholder(field_name, field, metadata)
        if placeholder and not isinstance(field.widget, (forms.Select, forms.SelectMultiple, forms.CheckboxInput, forms.HiddenInput)):
            field.widget.attrs.setdefault('placeholder', placeholder)

        mask_kind = metadata.get('mask')
        if mask_kind:
            field.widget.attrs['data-manager-mask'] = mask_kind

        autocomplete = metadata.get('autocomplete')
        if autocomplete:
            field.widget.attrs.setdefault('autocomplete', autocomplete)

        inputmode = metadata.get('inputmode')
        if inputmode:
            field.widget.attrs.setdefault('inputmode', inputmode)

        if not self.compact_form_fields and not isinstance(field.widget, forms.HiddenInput):
            field.widget.attrs['data-manager-status'] = field.manager_status_tone

    def _infer_field_metadata(self, field_name, field):
        metadata = {}
        shared = self._shared_metadata_for_field(field_name, field)
        metadata.update(shared)
        metadata.update(getattr(self, 'field_metadata', {}).get(field_name, {}))
        return metadata

    def _shared_metadata_for_field(self, field_name, field):
        normalized_name = field_name.lower()
        label = (field.label or '').lower()
        metadata = {}

        if 'phone' in normalized_name:
            metadata.update(
                {
                    'mask': 'phone',
                    'placeholder': '+7 (999) 123-45-67',
                    'autocomplete': 'tel',
                    'inputmode': 'tel',
                }
            )
        elif 'email' in normalized_name:
            metadata.update(
                {
                    'mask': 'email',
                    'placeholder': 'manager@bizonvr.ru',
                    'autocomplete': 'email',
                    'inputmode': 'email',
                }
            )
        elif normalized_name == 'telegram':
            metadata.update(
                {
                    'mask': 'telegram',
                    'placeholder': '@bizon_manager',
                }
            )
        elif 'messenger' in normalized_name:
            metadata.update(
                {
                    'mask': 'telegram-loose',
                    'placeholder': '@client_username или WhatsApp +7 (999) 123-45-67',
                }
            )
        elif 'date' in normalized_name or isinstance(field, forms.DateField):
            metadata.update(
                {
                    'mask': 'date',
                    'placeholder': 'ДД.ММ.ГГГГ',
                    'inputmode': 'numeric',
                }
            )

        if normalized_name in {'inn', 'business_inn', 'counterparty_inn'}:
            metadata.update({'placeholder': 'Например: 667907832209', 'inputmode': 'numeric'})
        if normalized_name in {'kpp', 'business_kpp', 'counterparty_kpp'}:
            metadata.update({'placeholder': 'Например: 667901001', 'inputmode': 'numeric'})
        if normalized_name in {'ogrn', 'ogrnip', 'business_ogrn', 'counterparty_ogrn', 'counterparty_ogrnip'}:
            metadata.update({'placeholder': 'Например: 1234567890123', 'inputmode': 'numeric'})
        if normalized_name in {'bik', 'passport_department_code'}:
            metadata.update({'placeholder': 'Например: 123456789', 'inputmode': 'numeric'})
        if normalized_name in {'card_number', 'checking_account', 'correspondent_account', 'passport_series', 'passport_number'}:
            metadata.update({'placeholder': 'Только цифры', 'inputmode': 'numeric'})

        if 'comment' in normalized_name and 'placeholder' not in metadata:
            metadata['placeholder'] = 'Кратко опишите детали'
        if 'address' in normalized_name and 'placeholder' not in metadata:
            metadata['placeholder'] = 'Например: ул. Малышева, 12'
        if 'city' in normalized_name and 'placeholder' not in metadata:
            metadata['placeholder'] = 'Например: Екатеринбург'
        if 'name' in normalized_name and 'placeholder' not in metadata and isinstance(field, forms.CharField):
            if 'company' in normalized_name:
                metadata['placeholder'] = 'Например: ООО Виртуальный Мир'
            elif 'counterparty' in normalized_name:
                metadata['placeholder'] = 'Например: ООО VR Партнер'
            elif 'contact' in normalized_name:
                metadata['placeholder'] = 'Например: Иван Петров'
            else:
                metadata['placeholder'] = 'Например: Основной профиль'
        if 'title' in normalized_name and 'placeholder' not in metadata:
            metadata['placeholder'] = 'Например: Договор поставки VR-оборудования'
        if 'number' in normalized_name and 'placeholder' not in metadata and 'phone' not in normalized_name:
            metadata['placeholder'] = 'Например: 123456'
        if 'url' in normalized_name and 'placeholder' not in metadata:
            metadata['placeholder'] = 'https://example.com'
        if 'request' in normalized_name and 'placeholder' not in metadata:
            metadata['placeholder'] = 'Например: Нужен Meta Quest 3 для клуба'
        if 'supplier' in normalized_name and 'placeholder' not in metadata:
            metadata['placeholder'] = 'Например: Shenzhen VR Tech'
        if 'quantity' in normalized_name and 'placeholder' not in metadata:
            metadata['placeholder'] = 'Например: 2'
        if any(token in normalized_name for token in ('price', 'amount', 'cost', 'commission', 'estimate', 'share', 'paid')) and 'placeholder' not in metadata:
            metadata['placeholder'] = 'Например: 15000'
            metadata.setdefault('inputmode', 'decimal')
        if isinstance(field, forms.DecimalField):
            metadata.setdefault('inputmode', 'decimal')
        if isinstance(field, forms.IntegerField):
            metadata.setdefault('inputmode', 'numeric')
        if 'description' in label and 'placeholder' not in metadata:
            metadata['placeholder'] = 'Кратко опишите содержимое поля'
        return metadata

    def _infer_placeholder(self, field_name, field, metadata):
        if isinstance(field.widget, (forms.Select, forms.SelectMultiple, forms.CheckboxInput, forms.HiddenInput)):
            return ''
        if isinstance(field.widget, forms.Textarea):
            return metadata.get('placeholder', '')
        return metadata.get('placeholder', '')

    def _normalize_telegram(self, value):
        normalized = value.strip()
        lower_value = normalized.lower()
        if lower_value.startswith('https://t.me/'):
            normalized = normalized.split('t.me/', 1)[1]
        elif lower_value.startswith('http://t.me/'):
            normalized = normalized.split('t.me/', 1)[1]
        elif lower_value.startswith('t.me/'):
            normalized = normalized.split('t.me/', 1)[1]
        normalized = normalized.strip().lstrip('@')
        if not normalized:
            return ''
        if ' ' in normalized:
            return value.strip()
        return f'@{normalized}'


class BaseVariantAwareForm(StyledFormMixin, forms.ModelForm):
    def clean(self):
        cleaned = super().clean()
        product = cleaned.get('product')
        variant = cleaned.get('variant')
        if product and variant and variant.product_id != product.id:
            self.add_error('variant', 'Вариант должен относиться к выбранному товару.')
        return cleaned


class OrderFilterForm(StyledFormMixin, forms.Form):
    compact_form_fields = True
    q = forms.CharField(required=False, label='Поиск')
    status = forms.ChoiceField(required=False, label='Статус', choices=[('', 'Все статусы')] + list(Order.STATUS_CHOICES))
    payment_status = forms.ChoiceField(
        required=False,
        label='Статус оплаты',
        choices=[('', 'Любая оплата')] + list(Order.PAYMENT_STATUS_CHOICES),
    )
    delivery_type = forms.ChoiceField(
        required=False,
        label='Способ доставки',
        choices=[('', 'Любая доставка')] + list(Order.DELIVERY_CHOICES),
    )
    date_from = filter_date_picker_field(label='Дата от')
    date_to = filter_date_picker_field(label='Дата до')


DEAL_PROBLEM_VIEW_CHOICES = [
    ('', 'Все проблемные срезы'),
    ('sla_overdue', 'SLA просрочен'),
    ('eta_overdue', 'ETA просрочен'),
    ('stock_conflict', 'Конфликт по остаткам'),
    ('reservations_expiring', 'Истекают брони'),
    ('missing_b2b_documents', 'Нет документов для B2B'),
    ('reserved_unpaid', 'Не оплачен, но зарезервирован'),
]


class DealFilterForm(StyledFormMixin, forms.Form):
    compact_form_fields = True
    q = forms.CharField(
        required=False,
        label='Поиск',
        widget=forms.TextInput(attrs={'placeholder': '№ заказа, клиент, телефон, SKU, трек'}),
    )
    sort = forms.ChoiceField(
        required=False,
        label='Сортировка',
        choices=[
            ('sla_due_at', 'SLA: ближе дедлайн'),
            ('-sla_due_at', 'SLA: позже дедлайн'),
            ('-last_activity_at', 'Последняя активность: свежие'),
            ('last_activity_at', 'Последняя активность: старые'),
        ],
        initial='sla_due_at',
    )
    queue = forms.ChoiceField(
        required=False,
        label='Очередь',
        choices=[('', 'Все очереди')] + list(ManagerDeal.NEXT_STEP_CHOICES),
    )
    overlay = forms.ChoiceField(
        required=False,
        label='Сигнал',
        choices=[('', 'Все сигналы')] + list(ManagerDeal.PROBLEM_FLAG_LABELS.items()),
    )
    problem_view = forms.ChoiceField(
        required=False,
        label='Проблемный срез',
        choices=DEAL_PROBLEM_VIEW_CHOICES,
    )
    case_status = forms.ChoiceField(
        required=False,
        label='Этап заказа',
        choices=[('', 'Любой этап')] + list(ManagerDeal.CASE_STATUS_CHOICES),
    )
    payment_state = forms.ChoiceField(
        required=False,
        label='Оплата',
        choices=[('', 'Любая оплата')] + list(ManagerDeal.PAYMENT_STATE_CHOICES),
    )
    fulfillment_status = forms.ChoiceField(
        required=False,
        label='Обеспечение',
        choices=[('', 'Любое обеспечение')] + list(ManagerDeal.FULFILLMENT_STATUS_CHOICES),
    )
    documents_status = forms.ChoiceField(
        required=False,
        label='Документы',
        choices=[('', 'Любые документы')] + list(ManagerDeal.DOCUMENTS_STATUS_CHOICES),
    )
    deal_type = forms.ChoiceField(
        required=False,
        label='Тип сделки',
        choices=[('', 'Любой тип')] + list(ManagerDeal.DEAL_TYPE_CHOICES),
    )
    sla_status = forms.ChoiceField(
        required=False,
        label='SLA',
        choices=[
            ('', 'Любой SLA'),
            ('today', 'Требуют действия сегодня'),
            ('overdue', 'Просрочен'),
            ('missing', 'Не задан'),
        ],
    )
    responsible_manager = forms.ModelChoiceField(
        required=False,
        queryset=get_user_model().objects.filter(is_staff=True).order_by('username'),
        empty_label='Любой менеджер',
        label='Ответственный',
    )
    mine = forms.BooleanField(required=False, label='Только мои')
    only_unassigned = forms.BooleanField(required=False, label='Без ответственного')
    only_problematic = forms.BooleanField(required=False, label='Проблемные')
    action_today = forms.BooleanField(required=False, label='Требуют действия сегодня')


class DealSavedViewForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DealSavedView
        fields = ['name']


class DealBulkAssignForm(StyledFormMixin, forms.Form):
    deal_ids = forms.CharField(widget=forms.HiddenInput())
    responsible_manager = forms.ModelChoiceField(
        queryset=get_user_model().objects.filter(is_staff=True).order_by('username'),
        label='Назначить менеджера',
    )

    def clean_deal_ids(self):
        raw_value = self.cleaned_data['deal_ids']
        deal_ids = [value for value in raw_value.split(',') if value.strip()]
        if not deal_ids:
            raise forms.ValidationError('Выберите хотя бы один заказ.')
        return raw_value

    def selected_ids(self):
        return [int(value) for value in self.cleaned_data['deal_ids'].split(',') if value.strip().isdigit()]


class DealBulkCaseStatusForm(StyledFormMixin, forms.Form):
    deal_ids = forms.CharField(widget=forms.HiddenInput())
    case_status = forms.ChoiceField(
        label='Перевести этап',
        choices=ManagerDeal.CASE_STATUS_CHOICES,
    )

    def clean_deal_ids(self):
        raw_value = self.cleaned_data['deal_ids']
        deal_ids = [value for value in raw_value.split(',') if value.strip()]
        if not deal_ids:
            raise forms.ValidationError('Выберите хотя бы один заказ.')
        return raw_value

    def selected_ids(self):
        return [int(value) for value in self.cleaned_data['deal_ids'].split(',') if value.strip().isdigit()]


class DealWorkflowForm(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['case_status'].label = 'Этап заказа'
        self.fields['customer_deadline'].label = 'Дедлайн клиента'

    class Meta:
        model = ManagerDeal
        fields = ['case_status', 'responsible_manager', 'customer_deadline']
        widgets = {
            'customer_deadline': forms.DateInput(attrs={'type': 'date'}),
        }


class DealNextStepOverrideForm(StyledFormMixin, forms.Form):
    next_step_code = forms.ChoiceField(label='Следующий шаг', choices=ManagerDeal.NEXT_STEP_CHOICES)
    reason = forms.CharField(label='Комментарий', required=False, widget=forms.Textarea())


class DealManagementForm(StyledFormMixin, forms.Form):
    case_status = forms.ChoiceField(label='Этап', choices=ManagerDeal.CASE_STATUS_CHOICES)
    responsible_manager = forms.ModelChoiceField(
        queryset=get_user_model().objects.filter(is_staff=True).order_by('username'),
        required=False,
        label='Ответственный',
        empty_label='Не назначен',
    )
    customer_deadline = forms.DateField(
        required=False,
        label='Дедлайн',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    answered_person_alias = forms.ModelChoiceField(
        queryset=ManagerPersonAlias.objects.filter(is_active=True).order_by('display_name'),
        required=False,
        label='Кто общался',
        empty_label='Не выбрано',
    )
    shipped_person_alias = forms.ModelChoiceField(
        queryset=ManagerPersonAlias.objects.filter(is_active=True).order_by('display_name'),
        required=False,
        label='Кто выдал / отнес',
        empty_label='Не выбрано',
    )
    next_step_code = forms.ChoiceField(
        required=False,
        label='Ручной следующий шаг',
        choices=[],
        help_text='Оставьте пустым, чтобы использовать системный сценарий.',
    )
    manager_comment = forms.CharField(
        required=False,
        label='Комментарий менеджера',
        help_text='Сохраняется вместе с ручным выбором следующего шага.',
        widget=forms.Textarea(),
    )

    def __init__(self, *args, **kwargs):
        deal = kwargs.pop('deal', None)
        super().__init__(*args, **kwargs)
        self.deal = deal
        self.fields['next_step_code'].choices = [('', 'Системный workflow')] + list(ManagerDeal.NEXT_STEP_CHOICES)
        if deal is not None:
            self.fields['case_status'].initial = deal.case_status
            self.fields['responsible_manager'].initial = deal.responsible_manager
            self.fields['customer_deadline'].initial = deal.customer_deadline
            answered = (
                deal.participants.select_related('person_alias')
                .filter(role=ManagerDealParticipant.ROLE_ANSWERED, order_item__isnull=True)
                .first()
            )
            shipped = (
                deal.participants.select_related('person_alias')
                .filter(role=ManagerDealParticipant.ROLE_SHIPPED, order_item__isnull=True)
                .first()
            )
            self.fields['answered_person_alias'].initial = answered.person_alias if answered else None
            self.fields['shipped_person_alias'].initial = shipped.person_alias if shipped else None
            if deal.next_step_source == ManagerDeal.NEXT_STEP_SOURCE_MANUAL:
                self.fields['next_step_code'].initial = deal.next_step_code
                self.fields['manager_comment'].initial = deal.next_step_reason_snapshot


class DealCommentForm(StyledFormMixin, forms.Form):
    comment = forms.CharField(label='Комментарий', widget=forms.Textarea())


class GlobalSearchForm(StyledFormMixin, forms.Form):
    compact_form_fields = True
    q = forms.CharField(label='Глобальный поиск')


class FinancePeriodForm(StyledFormMixin, forms.Form):
    compact_form_fields = True
    period = forms.ChoiceField(
        label='Период',
        required=False,
        choices=(),
        widget=forms.Select(attrs={'class': 'manager-finance-period-select'}),
    )
    year = forms.IntegerField(min_value=2020, max_value=2100, required=False, widget=forms.HiddenInput())
    month = forms.IntegerField(min_value=0, max_value=12, required=False, widget=forms.HiddenInput())

    min_year = 2020

    def __init__(self, *args, **kwargs):
        args = list(args)
        bound_data = kwargs.get('data')
        if bound_data is None and args:
            bound_data = args[0]
        if bound_data is not None:
            normalized_data = self._normalize_bound_data(bound_data)
            if 'data' in kwargs:
                kwargs['data'] = normalized_data
            elif args:
                args[0] = normalized_data

        super().__init__(*args, **kwargs)

        selected_period = self._selected_period(data=self.data if self.is_bound else None, initial=self.initial)
        self.fields['period'].choices = self._period_choices(selected_period=selected_period)

        if not self.is_bound and selected_period:
            year, month = self._parse_period_value(selected_period)
            self.initial.setdefault('period', selected_period)
            self.initial.setdefault('year', year)
            self.initial.setdefault('month', month)

    @classmethod
    def _format_period_value(cls, year, month):
        return f'{int(year):04d}-{int(month):02d}'

    @classmethod
    def _parse_period_value(cls, value):
        period_value = str(value or '').strip()
        year_text, separator, month_text = period_value.partition('-')
        if not separator:
            raise ValueError('invalid period value')
        return int(year_text), int(month_text)

    @classmethod
    def _normalize_bound_data(cls, data):
        if 'period' in data:
            return data
        year = str(data.get('year') or '').strip()
        month = str(data.get('month') or '').strip()
        if not year or month == '':
            return data
        normalized = data.copy()
        normalized['period'] = cls._format_period_value(year, month)
        return normalized

    @classmethod
    def _period_choices(cls, *, selected_period=None):
        today = timezone.localdate()
        choices = []
        seen = set()
        for year in range(today.year, cls.min_year - 1, -1):
            start_month = today.month if year == today.year else 12
            for month in range(start_month, 0, -1):
                value = cls._format_period_value(year, month)
                choices.append((value, finance_month_label(year=year, month=month).capitalize()))
                seen.add(value)
            year_value = cls._format_period_value(year, 0)
            choices.append((year_value, finance_month_label(year=year, month=0)))
            seen.add(year_value)
        if selected_period and selected_period not in seen:
            year, month = cls._parse_period_value(selected_period)
            choices.insert(0, (selected_period, finance_month_label(year=year, month=month).capitalize()))
        return choices

    @classmethod
    def _selected_period(cls, *, data, initial):
        if data is not None:
            period = str(data.get('period') or '').strip()
            if period:
                return period
            year = str(data.get('year') or '').strip()
            month = str(data.get('month') or '').strip()
            if year and month != '':
                return cls._format_period_value(year, month)
        year = (initial or {}).get('year', timezone.localdate().year)
        month = (initial or {}).get('month', timezone.localdate().month)
        return cls._format_period_value(year, month)

    def clean(self):
        cleaned_data = super().clean()
        period_value = cleaned_data.get('period') or self._selected_period(data=self.data, initial=self.initial)
        try:
            year, month = self._parse_period_value(period_value)
        except (TypeError, ValueError):
            self.add_error('period', 'Выберите период.')
            return cleaned_data
        if year < self.min_year or year > 2100 or month < 0 or month > 12:
            self.add_error('period', 'Период указан некорректно.')
            return cleaned_data
        cleaned_data['period'] = self._format_period_value(year, month)
        cleaned_data['year'] = year
        cleaned_data['month'] = month
        return cleaned_data


class FinanceDealForm(StyledFormMixin, forms.ModelForm):
    field_metadata = {
        'contract_number': {'placeholder': 'Например: ФД-2026-015'},
        'comment': {'help_text': 'Коротко зафиксируйте, что включено в выручку и себестоимость.'},
    }

    class Meta:
        model = FinanceDeal
        fields = ['date', 'contract_number', 'deal_type', 'revenue', 'cost_price', 'direct_expenses', 'manager_bonus', 'comment']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}


class FinanceExpenseForm(StyledFormMixin, forms.ModelForm):
    field_metadata = {
        'comment': {'help_text': 'Если расход относится к конкретной сделке, добавьте краткий контекст.'},
    }

    class Meta:
        model = FinanceExpense
        fields = ['expense_side', 'date', 'category', 'amount', 'comment']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.deal = deal
        self.fields['category'].queryset = FinanceExpenseCategory.objects.filter(is_active=True).order_by('expense_side', 'name')
        if deal is not None:
            self.instance.deal = deal

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get('category')
        expense_side = cleaned.get('expense_side')
        if category and expense_side and category.expense_side != expense_side:
            self.add_error('category', 'Категория должна совпадать со стороной расхода.')
        return cleaned


class FinancePayoutForm(StyledFormMixin, forms.ModelForm):
    field_metadata = {
        'comment': {'help_text': 'Добавьте назначение выплаты или ссылку на основание.'},
    }

    class Meta:
        model = FinancePayout
        fields = ['date', 'amount', 'comment']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}


class FinanceDealTypeForm(StyledFormMixin, forms.ModelForm):
    field_metadata = {
        'name': {'placeholder': 'Например: Партнерская сделка'},
        'partner_share': {
            'placeholder': 'Например: 0.35',
            'help_text': 'Укажите долю партнера числом от 0 до 1.',
        },
    }

    class Meta:
        model = FinanceDealType
        fields = ['name', 'partner_share', 'is_active']


class FinanceExpenseCategoryForm(StyledFormMixin, forms.ModelForm):
    field_metadata = {
        'name': {'placeholder': 'Например: Логистика'},
        'expense_side': {'help_text': 'Выберите, на чьей стороне учитывается расход.'},
    }

    class Meta:
        model = FinanceExpenseCategory
        fields = ['expense_side', 'name', 'is_active']


class ContractDocumentFilterForm(StyledFormMixin, forms.Form):
    compact_form_fields = True
    q = forms.CharField(required=False, label='Поиск')
    document_type = forms.ChoiceField(
        required=False,
        label='Тип документа',
        choices=[('', 'Все типы')] + list(ContractTemplate.DOCUMENT_TYPE_CHOICES),
    )
    status = forms.ChoiceField(
        required=False,
        label='Статус',
        choices=[('', 'Любой статус')] + list(ContractDocument.STATUS_CHOICES),
    )


class ContractDocumentForm(StyledFormMixin, forms.ModelForm):
    field_metadata = {
        'document_type': {'help_text': 'Тип задаёт набор реквизитов и доступных шаблонов.'},
        'template': {
            'help_text': 'Шаблон должен совпадать с типом документа.',
            'autofill_note': 'Подтянется автоматически при создании из сделки, если шаблон уже определён.',
        },
        'company_profile': {
            'help_text': 'Профиль компании подставит ваши реквизиты в документ.',
            'autofill_note': 'Подтянется автоматически, если в контуре настроен основной профиль.',
        },
        'manager_client': {
            'autofill_note': 'Подтянется из выбранной сделки или связанного клиента, если они уже известны.',
        },
        'linked_order': {
            'autofill_note': 'Подтянется автоматически, если документ создаётся из карточки сделки.',
        },
        'number': {
            'placeholder': 'Например: ДОГ-2026-015',
            'autofill_note': 'Можно оставить пустым, если номер присвоите позже.',
        },
        'title': {
            'placeholder': 'Например: Договор поставки VR-оборудования',
            'autofill_note': 'Можно оставить пустым, если заголовок сформируется из шаблона.',
        },
        'issue_date': {'help_text': 'Дата документа, которая попадёт в печатную форму.'},
        'effective_until': {'help_text': 'Заполняйте, если у документа есть срок действия.'},
        'payment_terms': {'placeholder': 'Например: 100% предоплата в течение 3 рабочих дней'},
        'subject': {'help_text': 'Коротко опишите предмет договора понятным языком.'},
        'counterparty_name': {'placeholder': 'Например: ООО VR Партнер'},
        'counterparty_email': {'help_text': 'Нужен, если по документу будут отправляться согласования или копии.'},
        'counterparty_phone': {'help_text': 'Основной рабочий номер контрагента или контактного лица.'},
        'counterparty_address': {'help_text': 'Юридический или почтовый адрес в том виде, как он должен быть в документе.'},
        'notes': {'help_text': 'Внутренняя заметка только для менеджеров. В документ не попадёт.'},
    }

    class Meta:
        model = ContractDocument
        fields = [
            'document_type',
            'status',
            'template',
            'company_profile',
            'manager_client',
            'linked_order',
            'responsible_manager',
            'number',
            'title',
            'issue_date',
            'effective_until',
            'amount',
            'currency',
            'payment_terms',
            'subject',
            'counterparty_name',
            'counterparty_email',
            'counterparty_phone',
            'counterparty_inn',
            'counterparty_kpp',
            'counterparty_ogrn',
            'counterparty_ogrnip',
            'counterparty_address',
            'notes',
        ]
        widgets = {
            'issue_date': forms.DateInput(attrs={'type': 'date'}),
            'effective_until': forms.DateInput(attrs={'type': 'date'}),
            'subject': forms.Textarea(),
            'counterparty_address': forms.Textarea(),
            'notes': forms.Textarea(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['template'].queryset = ContractTemplate.objects.filter(is_active=True).order_by('sort_order', 'name')
        self.fields['company_profile'].queryset = ContractCompanyProfile.objects.filter(is_active=True).order_by('name')
        self.fields['manager_client'].queryset = ManagerClient.objects.order_by('name')
        self.fields['linked_order'].queryset = Order.objects.order_by('-created_at')
        self.fields['responsible_manager'].queryset = get_user_model().objects.filter(is_staff=True).order_by('username')
        self.fields['number'].required = False
        self.fields['title'].required = False

    def clean(self):
        cleaned = super().clean()
        template = cleaned.get('template')
        document_type = cleaned.get('document_type')
        if template and document_type and template.document_type != document_type:
            self.add_error('template', 'Тип шаблона должен совпадать с типом документа.')
        return cleaned


class ContractTemplateForm(StyledFormMixin, forms.ModelForm):
    field_metadata = {
        'name': {'placeholder': 'Например: Договор поставки v2'},
        'version': {'placeholder': 'Например: 2.1'},
        'description': {'help_text': 'Коротко поясните, когда менеджеру использовать этот шаблон.'},
        'content_html': {'help_text': 'HTML печатной формы. Изменяйте только если понимаете структуру документа.'},
        'css_text': {'help_text': 'Стили печатной формы. Поле можно пропустить, если хватает базового оформления.'},
    }

    class Meta:
        model = ContractTemplate
        fields = ['name', 'document_type', 'version', 'description', 'is_active', 'content_html', 'css_text']
        widgets = {
            'description': forms.Textarea(),
            'content_html': forms.Textarea(attrs={'rows': 10}),
            'css_text': forms.Textarea(attrs={'rows': 8}),
        }


class ContractCompanyProfileForm(StyledFormMixin, forms.ModelForm):
    field_metadata = {
        'name': {'placeholder': 'Например: Основной профиль BizonVR'},
        'company_name': {'placeholder': 'Например: ИП Едигарьев Я.А.'},
        'director_genitive': {'placeholder': 'Например: Едигарьева Ярослава Александровича'},
        'legal_address': {'help_text': 'Используется в договорах и счетах как официальный адрес компании.'},
        'bank_name': {'placeholder': 'Например: ПАО Сбербанк'},
        'card_number': {'help_text': 'Заполняйте, если компания принимает оплату на карту.'},
        'sbp_phone': {'help_text': 'Номер для СБП, если этот способ используется в реквизитах.'},
        'passport_issued_by': {'placeholder': 'Например: ОВД Ленинского района г. Екатеринбурга'},
        'registration_address': {'help_text': 'Адрес регистрации для ИП или физлица.'},
        'residence_address': {'help_text': 'Фактический адрес проживания, если он отличается от регистрации.'},
    }

    class Meta:
        model = ContractCompanyProfile
        fields = [
            'name',
            'legal_type',
            'company_name',
            'inn',
            'kpp',
            'ogrn',
            'ogrnip',
            'director_genitive',
            'legal_address',
            'email',
            'phone',
            'bank_name',
            'checking_account',
            'correspondent_account',
            'bik',
            'card_number',
            'sbp_phone',
            'passport_series',
            'passport_number',
            'passport_issued_by',
            'passport_issued_date',
            'passport_department_code',
            'registration_address',
            'residence_address',
            'is_active',
        ]
        widgets = {
            'legal_address': forms.Textarea(),
            'passport_issued_date': forms.DateInput(attrs={'type': 'date'}),
            'registration_address': forms.Textarea(),
            'residence_address': forms.Textarea(),
        }


class ClientFilterForm(StyledFormMixin, forms.Form):
    compact_form_fields = True
    q = forms.CharField(
        required=False,
        label='Поиск',
        widget=forms.TextInput(attrs={'placeholder': 'Имя, телефон, email, Telegram'}),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'Любой статус')] + list(ManagerClient.STATUS_CHOICES),
        label='Статус',
    )
    has_orders = forms.TypedChoiceField(
        required=False,
        choices=[('', 'Заказы: любые'), ('1', 'Есть заказы'), ('0', 'Без заказов')],
        coerce=lambda value: value == '1',
        empty_value='',
        label='Заказы',
    )
    has_reservations = forms.TypedChoiceField(
        required=False,
        choices=[('', 'Брони: любые'), ('1', 'Есть брони'), ('0', 'Без броней')],
        coerce=lambda value: value == '1',
        empty_value='',
        label='Брони',
    )
    buyer_type = forms.ChoiceField(
        required=False,
        choices=[('', 'Любой тип')] + list(ManagerDeal.BUYER_TYPE_CHOICES),
        label='Тип клиента',
    )
    customer_source = forms.ChoiceField(
        required=False,
        choices=[('', 'Любой источник')] + list(ManagerDeal.CUSTOMER_SOURCE_CHOICES),
        label='Источник',
    )
    responsible_manager = forms.ModelChoiceField(
        required=False,
        queryset=get_user_model().objects.filter(is_staff=True).order_by('username'),
        empty_label='Любой менеджер',
        label='Ответственный',
    )


class WarehouseFilterForm(StyledFormMixin, forms.Form):
    compact_form_fields = True
    q = forms.CharField(
        required=False,
        label='Поиск',
        widget=forms.TextInput(attrs={'placeholder': 'Название склада или адрес'}),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'Любой статус'), ('active', 'Активные'), ('inactive', 'Неактивные')],
    )
    public_link = forms.ChoiceField(
        required=False,
        choices=[('', 'Связь с сайтом: любая'), ('linked', 'Есть PickupPoint'), ('unlinked', 'Без связи')],
    )
    only_problematic = forms.BooleanField(required=False, label='Только проблемные')
    only_unlinked = forms.BooleanField(required=False, label='Без связи с сайтом')
    only_missing_address = forms.BooleanField(required=False, label='Без адреса')
    has_inbound = forms.BooleanField(required=False, label='Есть приход в пути')
    has_signals = forms.BooleanField(required=False, label='Есть сигналы')
    only_active = forms.BooleanField(required=False, label='Активные')


class OrderStateForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(choices=Order.STATUS_CHOICES)
    payment_status = forms.ChoiceField(choices=Order.PAYMENT_STATUS_CHOICES)


class ManualOrderForm(StyledFormMixin, forms.Form):
    field_metadata = {
        'deal_type': {'help_text': 'От сценария зависит набор обязательных полей и авто-логика после сохранения.'},
        'deal_status': {'help_text': 'Статус доступен только в рамках выбранного сценария.'},
        'buyer_type': {'help_text': 'Выберите, кто покупает: физлицо или юрлицо.'},
        'responsible_manager': {
            'autofill_note': 'Подтянется автоматически текущим менеджером, если заказ создаётся вручную.',
        },
        'deal_created_at': {'help_text': 'Дата и время регистрации заказа в менеджерском контуре.'},
        'customer_source': {
            'autofill_note': 'Подтянется из клиента, если открываете форму из его карточки.',
        },
        'deal_comment': {'help_text': 'Внутренняя заметка для команды. Клиент её не увидит.'},
        'individual_full_name': {'placeholder': 'Например: Иван Петров'},
        'individual_phone': {'help_text': 'Основной номер для связи по заказу.'},
        'individual_additional_phone': {'help_text': 'Заполняйте только если у клиента есть резервный номер.'},
        'individual_messenger': {'help_text': 'Можно указать Telegram или другой удобный канал связи.'},
        'business_company_name': {'placeholder': 'Например: ООО VR Клуб'},
        'business_inn': {'help_text': 'Используется для поиска клиента и реквизитов.'},
        'business_legal_address': {'help_text': 'Юридический адрес для документов и счёта.'},
        'business_contact_person': {'placeholder': 'Например: Анна Петрова'},
        'business_phone': {'help_text': 'Телефон контактного лица по заказу.'},
        'business_telegram': {'help_text': 'Telegram клиента или ответственного сотрудника.'},
        'business_whatsapp': {'help_text': 'WhatsApp клиента или ответственного сотрудника.'},
        'business_email': {'help_text': 'На этот адрес можно отправить счёт, договор или подтверждение.'},
        'business_checking_account': {'help_text': 'Расчётный счёт клиента для документов и сверки реквизитов.'},
        'business_bank_name': {'placeholder': 'Например: ПАО Сбербанк'},
        'business_correspondent_account': {'help_text': 'Корреспондентский счёт банка клиента.'},
        'customer_request': {'help_text': 'Опишите запрос клиента, если товар идёт под заказ.'},
        'customer_request_comment': {'help_text': 'Любые дополнительные пожелания клиента по срокам или комплектации.'},
        'prepayment_required_amount': {
            'help_text': 'Минимум, который нужен до запуска закупки или резерва.',
            'autofill_note': 'Учитывается в правом блоке авторасчёта.',
        },
        'prepayment_amount': {
            'help_text': 'Сколько клиент уже оплатил на текущий момент.',
            'autofill_note': 'Влияет на расчёт остатка или доплаты.',
        },
    }

    deal_type = forms.ChoiceField(label='Сценарий заказа', choices=ManagerDeal.DEAL_TYPE_CHOICES)
    deal_status = forms.ChoiceField(label='Статус заказа', choices=ManagerDeal.allowed_status_choices(ManagerDeal.DEAL_SALE_FROM_STOCK))
    buyer_type = forms.ChoiceField(label='Тип покупателя', choices=ManagerDeal.BUYER_TYPE_CHOICES)
    responsible_manager = forms.ModelChoiceField(
        label='Ответственный менеджер',
        queryset=get_user_model().objects.filter(is_staff=True).order_by('username'),
    )
    deal_created_at = forms.DateTimeField(
        label='Дата создания заказа',
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )
    customer_source = forms.ChoiceField(label='Источник клиента', choices=ManagerDeal.CUSTOMER_SOURCE_CHOICES)
    deal_comment = forms.CharField(label='Комментарий по заказу', required=False, widget=forms.Textarea())
    answered_person_alias = forms.ModelChoiceField(
        queryset=ManagerPersonAlias.objects.filter(is_active=True).order_by('display_name'),
        required=False,
        label='Кто общался',
        empty_label='Не выбрано',
    )
    shipped_person_alias = forms.ModelChoiceField(
        queryset=ManagerPersonAlias.objects.filter(is_active=True).order_by('display_name'),
        required=False,
        label='Кто выдал / отнес',
        empty_label='Не выбрано',
    )

    individual_full_name = forms.CharField(label='ФИО', required=False)
    individual_phone = forms.CharField(label='Номер телефона', required=False)
    individual_additional_phone = forms.CharField(label='Доп. номер телефона', required=False)
    individual_city = forms.CharField(label='Город', required=False)
    individual_pickup_address = forms.CharField(label='Адрес ПВЗ СДЭК', required=False, widget=forms.Textarea())
    individual_delivery_address = forms.CharField(label='Полный адрес доставки', required=False, widget=forms.Textarea())
    individual_messenger = forms.CharField(label='Telegram / WhatsApp', required=False)
    individual_comment = forms.CharField(label='Комментарий по клиенту', required=False, widget=forms.Textarea())

    business_company_name = forms.CharField(label='Название компании', required=False)
    business_inn = forms.CharField(label='ИНН', required=False)
    business_kpp = forms.CharField(label='КПП', required=False)
    business_ogrn = forms.CharField(label='ОГРН / ОГРНИП', required=False)
    business_legal_address = forms.CharField(label='Юридический адрес', required=False, widget=forms.Textarea())
    business_contact_person = forms.CharField(label='Контактное лицо', required=False)
    business_phone = forms.CharField(label='Телефон', required=False)
    business_telegram = forms.CharField(label='Telegram', required=False)
    business_whatsapp = forms.CharField(label='WhatsApp', required=False)
    business_email = forms.EmailField(label='Email', required=False)
    business_city = forms.CharField(label='Город', required=False)
    business_delivery_address = forms.CharField(label='Адрес доставки / ПВЗ СДЭК', required=False, widget=forms.Textarea())
    business_checking_account = forms.CharField(label='Номер счёта', required=False)
    business_bank_name = forms.CharField(label='Банк', required=False)
    business_bik = forms.CharField(label='БИК', required=False)
    business_correspondent_account = forms.CharField(label='Корр. счёт банка', required=False)
    business_comment = forms.CharField(label='Комментарий', required=False, widget=forms.Textarea())
    customer_request = forms.CharField(label='Что именно хочет клиент', required=False, widget=forms.Textarea())
    customer_deadline = forms.DateField(label='Есть ли дедлайн по срокам', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    customer_request_comment = forms.CharField(label='Комментарий клиента', required=False, widget=forms.Textarea())

    delivery_method = forms.ChoiceField(label='Способ доставки', choices=ManagerDeal.DELIVERY_METHOD_CHOICES)
    delivery_from_city = forms.CharField(label='Город отправки', required=False)
    delivery_to_city = forms.CharField(label='Город получения', required=False)
    delivery_pickup_address = forms.CharField(label='Адрес ПВЗ СДЭК', required=False, widget=forms.Textarea())
    delivery_full_address = forms.CharField(label='Полный адрес доставки', required=False, widget=forms.Textarea())
    delivery_cost = forms.DecimalField(label='Стоимость доставки', min_value=0, decimal_places=2, initial=0)
    delivery_payer = forms.ChoiceField(label='Кто оплачивает доставку', choices=ManagerDeal.DELIVERY_PAYER_CHOICES)
    tracking_number = forms.CharField(label='Номер заказа / отправления СДЭК', required=False)
    shipping_comment = forms.CharField(label='Комментарий по отправке', required=False, widget=forms.Textarea())
    shipment_status = forms.ChoiceField(label='Статус отправки', choices=ManagerDeal.SHIPMENT_STATUS_CHOICES)
    shipped_at = forms.DateField(label='Дата отправки', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    planned_receipt_at = forms.DateField(label='Плановая дата получения', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    prepayment_required_amount = forms.DecimalField(label='Размер предоплаты', min_value=0, decimal_places=2, initial=0)
    prepayment_amount = forms.DecimalField(label='Сколько уже оплачено клиентом', min_value=0, decimal_places=2, initial=0)
    stock_warehouse = forms.ModelChoiceField(
        label='Конкретный склад',
        required=False,
        queryset=Warehouse.objects.filter(is_active=True).order_by('name'),
    )
    procurement_origin = forms.CharField(label='Откуда заказываем', required=False)
    supplier_name = forms.CharField(label='Поставщик', required=False)
    supplier_agent = forms.CharField(label='Поставщик / агент', required=False)
    planned_purchase_date = forms.DateField(label='Плановая дата закупки', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    expected_arrival_date = forms.DateField(label='Ожидаемая дата поступления', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    expected_customer_ship_date = forms.DateField(label='Ожидаемая дата отправки клиенту', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    avito_listing_url = forms.URLField(label='Ссылка на объявление Avito', required=False)
    avito_listing_id = forms.CharField(label='ID объявления', required=False)
    avito_listing_title = forms.CharField(label='Название объявления', required=False)
    avito_contact_channel = forms.CharField(label='Канал обращения', required=False)
    avito_list_price = forms.DecimalField(label='Цена в объявлении', min_value=0, decimal_places=2, required=False, initial=0)
    avito_final_price = forms.DecimalField(label='Финальная цена продажи', min_value=0, decimal_places=2, required=False, initial=0)
    avito_commission = forms.DecimalField(label='Комиссия Avito', min_value=0, decimal_places=2, required=False, initial=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get('deal_created_at'):
            self.initial['deal_created_at'] = timezone.localtime().replace(second=0, microsecond=0).strftime('%Y-%m-%dT%H:%M')
        deal_type = self.data.get('deal_type') or self.initial.get('deal_type') or ManagerDeal.DEAL_SALE_FROM_STOCK
        customer_source = self.data.get('customer_source') or self.initial.get('customer_source') or ''
        self.fields['deal_status'].choices = ManagerDeal.allowed_status_choices(deal_type, customer_source)

    def clean(self):
        cleaned = super().clean()
        deal_type = cleaned.get('deal_type')
        customer_source = cleaned.get('customer_source') or ''
        buyer_type = cleaned.get('buyer_type')
        is_avito_workflow = ManagerDeal.uses_avito_workflow(deal_type, customer_source)

        if buyer_type == ManagerDeal.BUYER_INDIVIDUAL:
            if not (cleaned.get('individual_full_name') or '').strip():
                self.add_error('individual_full_name', 'Введите ФИО клиента, чтобы заказ можно было связать с покупателем.')
            if not (cleaned.get('individual_phone') or '').strip():
                self.add_error('individual_phone', 'Введите основной номер телефона клиента для связи по заказу.')
            if not (cleaned.get('individual_city') or '').strip():
                self.add_error('individual_city', 'Укажите город клиента, чтобы менеджеру было понятно направление доставки.')
        elif buyer_type == ManagerDeal.BUYER_BUSINESS:
            if not (cleaned.get('business_company_name') or '').strip():
                self.add_error('business_company_name', 'Введите название компании-покупателя.')
            if not (cleaned.get('business_inn') or '').strip():
                self.add_error('business_inn', 'Введите ИНН компании, чтобы можно было подготовить документы.')
            if not (cleaned.get('business_contact_person') or '').strip():
                self.add_error('business_contact_person', 'Введите имя контактного лица со стороны клиента.')
            if not (cleaned.get('business_phone') or '').strip():
                self.add_error('business_phone', 'Введите телефон контактного лица.')
            if not (cleaned.get('business_email') or '').strip():
                self.add_error('business_email', 'Введите рабочий email, на который можно отправить счёт или договор.')
            if not (cleaned.get('business_city') or '').strip():
                self.add_error('business_city', 'Укажите город компании или точки доставки.')

        if deal_type and cleaned.get('deal_status') and cleaned['deal_status'] not in dict(ManagerDeal.allowed_status_choices(deal_type, customer_source)):
            self.add_error('deal_status', 'Статус не подходит для выбранного сценария.')

        if is_avito_workflow:
            cleaned['customer_deadline'] = None
        if deal_type == ManagerDeal.DEAL_SALE_ON_REQUEST and cleaned.get('deal_status') == ManagerDeal.DEAL_STATUS_SUPPLIER_ORDERED:
            required = cleaned.get('prepayment_required_amount') or 0
            paid = cleaned.get('prepayment_amount') or 0
            if required > 0 and paid < required:
                self.add_error('prepayment_amount', 'Закупку нельзя запускать, пока фактическая предоплата меньше требуемой.')
        return cleaned


class ManualOrderItemForm(StyledFormMixin, forms.Form):
    field_metadata = {
        'product_name': {
            'help_text': 'Введите название. Если товар есть в каталоге, система подтянет его цену и превью.',
            'placeholder': 'Например: Meta Quest 3 512 GB',
        },
        'variant': {'autofill_note': 'Можно оставить пустым, если вариант не принципиален.'},
        'configuration': {'placeholder': 'Например: 128 GB, серый, EU'},
        'comment': {'help_text': 'Внутренняя заметка по позиции: комплект, состояние, особенности.'},
    }

    product_name = forms.CharField(
        label='Название товара / позиции',
        required=False,
        widget=forms.TextInput(attrs={'list': 'manual-order-product-names'}),
    )
    product = forms.ModelChoiceField(
        label='Товар',
        queryset=Product.objects.order_by('name'),
        required=False,
        widget=forms.HiddenInput(),
    )
    variant = forms.ModelChoiceField(
        label='Вариант',
        queryset=ProductVariant.objects.order_by('product__name', 'name'),
        required=False,
    )
    configuration = forms.CharField(label='Конфигурация / модификация', required=False)
    condition = forms.ChoiceField(label='Состояние', choices=OrderItem.CONDITION_CHOICES, initial=OrderItem.CONDITION_NEW)
    quantity = forms.IntegerField(label='Количество', min_value=1, required=False, initial=1)
    purchase_price = forms.DecimalField(label='Закупочная цена', min_value=0, decimal_places=2, required=False, initial=0)
    sale_price = forms.DecimalField(label='Цена продажи за единицу', min_value=0, decimal_places=2, required=False, initial=0)
    discount_amount = forms.DecimalField(label='Скидка', min_value=0, decimal_places=2, required=False, initial=0)
    comment = forms.CharField(label='Комментарий', required=False, widget=forms.Textarea())

    def has_item_data(self):
        data = getattr(self, 'cleaned_data', {})
        return any(
            data.get(key)
            for key in ('product_name', 'product', 'variant', 'configuration', 'quantity', 'purchase_price', 'sale_price', 'discount_amount', 'comment')
        )

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(key) for key in ('product_name', 'product', 'variant', 'configuration', 'quantity', 'purchase_price', 'sale_price', 'discount_amount', 'comment')):
            return cleaned
        product_name = (cleaned.get('product_name') or '').strip()
        product = cleaned.get('product')
        if product is None and product_name:
            matches = list(Product.objects.filter(name__iexact=product_name).order_by('name')[:2])
            if len(matches) == 1:
                product = matches[0]
                cleaned['product'] = product
        if product is not None and not product_name:
            product_name = product.name
            cleaned['product_name'] = product_name
        if not product and not product_name:
            self.add_error('product_name', 'Введите название позиции.')
        if cleaned.get('product') and cleaned.get('variant') and cleaned['variant'].product_id != cleaned['product'].id:
            self.add_error('variant', 'Вариант должен относиться к выбранному товару.')
        if cleaned.get('quantity') in (None, ''):
            self.add_error('quantity', 'Укажите количество по этой позиции.')
        if cleaned.get('sale_price') in (None, ''):
            if cleaned.get('product'):
                cleaned['sale_price'] = cleaned['product'].price
            else:
                self.add_error('sale_price', 'Введите цену продажи за единицу.')
        return cleaned


class BaseManualOrderItemFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active_forms = [
            form
            for form in self.forms
            if not form.cleaned_data.get('DELETE') and form.has_item_data()
        ]
        if not active_forms:
            raise forms.ValidationError('Добавьте хотя бы одну позицию в заказ.')


ManualOrderItemFormSet = formset_factory(
    ManualOrderItemForm,
    formset=BaseManualOrderItemFormSet,
    extra=1,
    can_delete=True,
)


class TradeInItemForm(StyledFormMixin, forms.Form):
    field_metadata = {
        'device_type': {'placeholder': 'Например: VR-шлем'},
        'model_name': {'placeholder': 'Например: Meta Quest 2'},
        'version': {'placeholder': 'Например: 128 GB'},
        'kit_description': {'help_text': 'Опишите, что клиент сдаёт вместе с устройством.'},
        'condition': {'placeholder': 'Например: Есть следы использования, экран без дефектов'},
        'defects': {'help_text': 'Перечислите заметные повреждения, чтобы оценка не потерялась.'},
        'preliminary_estimate': {'help_text': 'Ориентир до осмотра устройства.'},
        'final_estimate': {'help_text': 'Заполняйте после проверки, если оценка изменилась.'},
    }

    device_type = forms.CharField(label='Тип устройства', required=False)
    model_name = forms.CharField(label='Модель', required=False)
    version = forms.CharField(label='Версия', required=False)
    kit_description = forms.CharField(label='Комплектация', required=False, widget=forms.Textarea())
    condition = forms.CharField(label='Состояние', required=False)
    is_working = forms.BooleanField(label='Работает', required=False)
    has_box = forms.BooleanField(label='Есть коробка', required=False)
    has_controllers = forms.BooleanField(label='Есть контроллеры', required=False)
    has_accessories = forms.BooleanField(label='Есть ремешок / маска / доп. аксессуары', required=False)
    defects = forms.CharField(label='Дефекты', required=False, widget=forms.Textarea())
    preliminary_estimate = forms.DecimalField(label='Предварительная оценка', min_value=0, decimal_places=2, required=False, initial=0)
    final_estimate = forms.DecimalField(label='Финальная оценка после проверки', min_value=0, decimal_places=2, required=False, initial=0)

    def has_item_data(self):
        data = getattr(self, 'cleaned_data', {})
        return any(
            data.get(key)
            for key in ('device_type', 'model_name', 'version', 'kit_description', 'condition', 'defects', 'preliminary_estimate', 'final_estimate')
        )

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(key) for key in ('device_type', 'model_name', 'version', 'kit_description', 'condition', 'defects', 'preliminary_estimate', 'final_estimate')):
            return cleaned
        for required_field, message in (
            ('model_name', 'Введите модель сдаваемого устройства.'),
            ('condition', 'Опишите состояние устройства, чтобы оценка не потерялась.'),
            ('kit_description', 'Опишите комплектацию: что идёт вместе с устройством.'),
        ):
            if not (cleaned.get(required_field) or '').strip():
                self.add_error(required_field, message)
        if cleaned.get('preliminary_estimate') in (None, ''):
            self.add_error('preliminary_estimate', 'Укажите предварительную оценку, даже если она ещё ориентировочная.')
        return cleaned


class BaseTradeInItemFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active_forms = [
            form
            for form in self.forms
            if not form.cleaned_data.get('DELETE') and form.has_item_data()
        ]
        if not active_forms:
            raise forms.ValidationError('Для trade-in добавьте хотя бы одну принимаемую позицию.')


TradeInItemFormSet = formset_factory(
    TradeInItemForm,
    formset=BaseTradeInItemFormSet,
    extra=1,
    can_delete=True,
)


class ManagerDealStateForm(StyledFormMixin, forms.Form):
    deal_status = forms.ChoiceField(label='Статус заказа', choices=ManagerDeal.DEAL_STATUS_CHOICES)
    payment_status = forms.ChoiceField(label='Статус оплаты', choices=Order.PAYMENT_STATUS_CHOICES)
    paid_amount = forms.DecimalField(label='Оплачено клиентом', min_value=0, decimal_places=2, required=False, initial=0)
    tracking_number = forms.CharField(label='Номер отправления', required=False)

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.deal = deal
        if deal is not None:
            self.fields['deal_status'].choices = ManagerDeal.allowed_status_choices(deal.deal_type, deal.customer_source)


class ManagerClientForm(StyledFormMixin, forms.ModelForm):
    field_metadata = {
        'name': {'placeholder': 'Например: ООО VR Клуб или Иван Петров'},
        'telegram': {'help_text': 'Введите @username или ссылку t.me/username.'},
        'address': {'help_text': 'Краткий адрес клиента или удобная точка отгрузки.'},
        'comments': {'help_text': 'Внутренние заметки о клиенте, договорённостях или предпочтениях.'},
        'orders': {'help_text': 'Можно связать клиента с уже существующими заказами.'},
    }

    orders = forms.ModelMultipleChoiceField(
        queryset=Order.objects.order_by('-created_at'),
        required=False,
        widget=forms.SelectMultiple(attrs={'size': 6}),
        label='Связанные заказы',
    )

    class Meta:
        model = ManagerClient
        fields = ['user', 'name', 'email', 'phone', 'telegram', 'address', 'comments', 'status', 'orders']


class ManagerClientQuickCommentForm(StyledFormMixin, forms.Form):
    comment = forms.CharField(
        label='Новый комментарий',
        widget=forms.Textarea(
            attrs={
                'rows': 5,
                'placeholder': 'Что важно зафиксировать по клиенту',
            }
        ),
    )


class ManagerClientQuickAssignForm(StyledFormMixin, forms.Form):
    responsible_manager = forms.ModelChoiceField(
        queryset=get_user_model().objects.filter(is_staff=True).order_by('username'),
        label='Ответственный менеджер',
    )


class WarehouseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ['name', 'address', 'pickup_point', 'is_active']


class InventoryReceiptForm(StyledFormMixin, forms.Form):
    field_metadata = {
        'comment': {'help_text': 'Коротко опишите причину прихода или номер документа.'},
    }

    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.order_by('name'))
    product = forms.ModelChoiceField(queryset=Product.objects.order_by('name'))
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.order_by('product__name', 'name'), required=False)
    quantity = forms.IntegerField(min_value=1)
    comment = forms.CharField(required=False)

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get('product')
        variant = cleaned.get('variant')
        if product and variant and variant.product_id != product.id:
            self.add_error('variant', 'Вариант должен относиться к выбранному товару.')
        return cleaned


class PurchaseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ['date', 'supplier_name', 'agent', 'status', 'currency', 'total_amount', 'comments']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}


class PurchaseFilterForm(StyledFormMixin, forms.Form):
    compact_form_fields = True
    q = forms.CharField(required=False, label='Поиск')
    status = forms.ChoiceField(required=False, label='Статус', choices=[('', 'Любой статус')] + list(Purchase.STATUS_CHOICES))
    date_from = filter_date_picker_field(label='Дата от')
    date_to = filter_date_picker_field(label='Дата до')


class PurchaseItemForm(BaseVariantAwareForm):
    order_item = forms.ModelChoiceField(
        required=False,
        queryset=OrderItem.objects.select_related('order', 'product', 'variant').order_by('-order__created_at', '-id'),
        label='Строка заказа',
    )

    class Meta:
        model = PurchaseItem
        fields = ['product', 'variant', 'order_item', 'quantity', 'price']


class CargoForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Cargo
        fields = ['cargo_number', 'purchase', 'status', 'eta', 'destination_warehouse', 'comments']
        widgets = {'eta': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cargo_number'].required = False


class CargoFilterForm(StyledFormMixin, forms.Form):
    compact_form_fields = True
    q = forms.CharField(required=False, label='Поиск')
    status = forms.ChoiceField(required=False, label='Статус', choices=[('', 'Любой статус')] + list(Cargo.STATUS_CHOICES))
    date_from = filter_date_picker_field(label='Дата от')
    date_to = filter_date_picker_field(label='Дата до')
    destination_warehouse = forms.ModelChoiceField(
        required=False,
        label='Склад назначения',
        queryset=Warehouse.objects.order_by('name'),
        empty_label='Любой склад',
    )
    overdue = forms.BooleanField(required=False, label='Просрочен по ETA')
    has_reservations = forms.BooleanField(required=False, label='Есть брони')


class CargoItemForm(BaseVariantAwareForm):
    purchase_item = forms.ModelChoiceField(
        required=False,
        queryset=PurchaseItem.objects.select_related('purchase', 'product', 'variant', 'order_item__order').order_by('-purchase__date', '-id'),
        label='Позиция закупки',
    )

    class Meta:
        model = CargoItem
        fields = ['product', 'variant', 'purchase_item', 'quantity']


class CargoReceiveForm(StyledFormMixin, forms.Form):
    quantity = forms.IntegerField(min_value=1)


class CargoSplitForm(StyledFormMixin, forms.Form):
    cargo_number = forms.CharField(max_length=120, required=False)
    item = forms.ModelChoiceField(queryset=CargoItem.objects.none())
    quantity = forms.IntegerField(min_value=1)

    def __init__(self, *args, cargo=None, **kwargs):
        super().__init__(*args, **kwargs)
        if cargo is not None:
            self.fields['item'].queryset = cargo.items.select_related('product', 'variant').order_by('id')


class CargoPhotoForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CargoPhoto
        fields = ['image', 'caption']


class TransportLegForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TransportLeg
        fields = ['from_location', 'to_warehouse', 'method', 'track_number', 'cost', 'status', 'departed_at', 'arrived_at', 'comments']
        widgets = {
            'departed_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'arrived_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class ExpenseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['category', 'name', 'amount', 'date']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}


class ReservationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ['client', 'linked_order', 'status', 'source_type', 'source_warehouse', 'source_cargo', 'target_warehouse', 'comments']


class ReservationFilterForm(StyledFormMixin, forms.Form):
    compact_form_fields = True
    q = forms.CharField(required=False, label='Поиск')
    status = forms.ChoiceField(required=False, label='Статус', choices=[('', 'Любой статус')] + list(Reservation.STATUS_CHOICES))
    date_from = filter_date_picker_field(label='Дата от')
    date_to = filter_date_picker_field(label='Дата до')
    source_type = forms.ChoiceField(required=False, label='Тип источника', choices=[('', 'Любой источник')] + list(Reservation.SOURCE_CHOICES))
    source_warehouse = forms.ModelChoiceField(
        required=False,
        label='Склад-источник',
        queryset=Warehouse.objects.order_by('name'),
        empty_label='Любой склад-источник',
    )
    target_warehouse = forms.ModelChoiceField(
        required=False,
        label='Склад назначения',
        queryset=Warehouse.objects.order_by('name'),
        empty_label='Любой склад назначения',
    )
    client = forms.ModelChoiceField(
        required=False,
        label='Клиент',
        queryset=ManagerClient.objects.order_by('name'),
        empty_label='Любой клиент',
    )


class ReservationItemForm(BaseVariantAwareForm):
    order_item = forms.ModelChoiceField(
        required=False,
        queryset=OrderItem.objects.select_related('order', 'product', 'variant').order_by('-order__created_at', '-id'),
        label='Строка заказа',
    )

    class Meta:
        model = ReservationItem
        fields = ['product', 'variant', 'order_item', 'quantity']


class ReservationStatusForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(choices=Reservation.STATUS_CHOICES)


class ShipmentFilterForm(StyledFormMixin, forms.Form):
    compact_form_fields = True
    date_from = filter_date_picker_field(label='Дата от')
    date_to = filter_date_picker_field(label='Дата до')
    warehouse = forms.ModelChoiceField(
        required=False,
        label='Склад-источник',
        queryset=Warehouse.objects.order_by('name'),
        empty_label='Любой склад-источник',
    )
    target_warehouse = forms.ModelChoiceField(
        required=False,
        label='Склад назначения',
        queryset=Warehouse.objects.order_by('name'),
        empty_label='Любой склад назначения',
    )
    client = forms.ModelChoiceField(
        required=False,
        label='Клиент',
        queryset=ManagerClient.objects.order_by('name'),
        empty_label='Любой клиент',
    )
    view_mode = forms.ChoiceField(
        required=False,
        label='Режим отображения',
        choices=[('reservation', 'По броням'), ('items', 'По позициям')],
        initial='reservation',
    )
