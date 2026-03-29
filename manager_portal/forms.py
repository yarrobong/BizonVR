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
    FinanceDealLine,
    FinanceDealShare,
    FinanceDealType,
    FinanceDistributionRule,
    FinanceDistributionScheme,
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


INPUT_CLASS = 'w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white'
TEXTAREA_CLASS = INPUT_CLASS
CHECKBOX_CLASS = 'h-4 w-4 rounded border-slate-600 bg-slate-950 text-cyan-400'


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = CHECKBOX_CLASS
            elif isinstance(widget, forms.Textarea):
                widget.attrs['class'] = TEXTAREA_CLASS
                widget.attrs.setdefault('rows', 3)
            elif isinstance(widget, forms.SelectMultiple):
                widget.attrs['class'] = INPUT_CLASS
            else:
                widget.attrs['class'] = INPUT_CLASS


class BaseVariantAwareForm(StyledFormMixin, forms.ModelForm):
    def clean(self):
        cleaned = super().clean()
        product = cleaned.get('product')
        variant = cleaned.get('variant')
        if product and variant and variant.product_id != product.id:
            self.add_error('variant', 'Вариант должен относиться к выбранному товару.')
        if product and product.variants.exists() and not variant:
            self.add_error('variant', 'Для товара с вариантами выберите конкретный вариант.')
        return cleaned


class OrderFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(required=False, label='Поиск')
    status = forms.ChoiceField(required=False, choices=[('', 'Все статусы')] + list(Order.STATUS_CHOICES))
    payment_status = forms.ChoiceField(
        required=False,
        choices=[('', 'Любая оплата')] + list(Order.PAYMENT_STATUS_CHOICES),
    )
    delivery_type = forms.ChoiceField(
        required=False,
        choices=[('', 'Любая доставка')] + list(Order.DELIVERY_CHOICES),
    )
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))


DEAL_PROBLEM_VIEW_CHOICES = [
    ('', 'Все проблемные срезы'),
    ('sla_overdue', 'SLA просрочен'),
    ('stale_updates', 'Нет обновлений 48 ч'),
    ('eta_overdue', 'ETA просрочен'),
    ('stock_conflict', 'Конфликт по остаткам'),
    ('missing_contacts', 'Нет контактов'),
    ('reservations_expiring', 'Истекают брони'),
    ('missing_b2b_documents', 'Нет документов для B2B'),
    ('reserved_unpaid', 'Не оплачен, но зарезервирован'),
]


class DealFilterForm(StyledFormMixin, forms.Form):
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
            ('-prepayment_amount', 'Сумма: больше'),
            ('prepayment_amount', 'Сумма: меньше'),
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
    only_active = forms.BooleanField(required=False, label='Только активные')
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
    q = forms.CharField(label='Глобальный поиск')


class FinancePeriodForm(StyledFormMixin, forms.Form):
    year = forms.IntegerField(min_value=2020, max_value=2100, label='Год')
    month = forms.TypedChoiceField(
        label='Период',
        coerce=int,
        choices=[(0, 'Весь год')] + [(index, f'{index:02d}') for index in range(1, 13)],
    )


class FinanceDealForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinanceDeal
        fields = ['date', 'contract_number', 'deal_type', 'revenue', 'cost_of_goods', 'manager_bonus', 'comment']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}


class FinanceDealLineForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinanceDealLine
        fields = [
            'sort_order',
            'product_name',
            'quantity',
            'unit_cost_price',
            'unit_sale_price',
            'owner_alias',
            'line_status',
            'delivery_status',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['owner_alias'].queryset = ManagerPersonAlias.objects.filter(is_active=True).order_by('display_name')
        self.fields['owner_alias'].required = False


class FinanceDealShareOverrideForm(StyledFormMixin, forms.ModelForm):
    override_percent = forms.DecimalField(
        label='Переопределить процент',
        required=False,
        decimal_places=4,
        max_digits=7,
        min_value=0,
    )
    override_owner_alias = forms.ModelChoiceField(
        label='Переопределить владельца строк',
        required=False,
        queryset=ManagerPersonAlias.objects.none(),
        empty_label='Без изменения',
    )

    class Meta:
        model = FinanceDealShare
        fields = ['manual_amount_override']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['override_owner_alias'].queryset = ManagerPersonAlias.objects.filter(is_active=True).order_by('display_name')
        override_payload = self.instance.rule_params_override or {}
        if 'percent' in override_payload:
            self.fields['override_percent'].initial = override_payload.get('percent')
        override_owner_alias_id = override_payload.get('owner_alias_id')
        if override_owner_alias_id:
            self.fields['override_owner_alias'].initial = override_owner_alias_id

    def save(self, commit=True):
        instance = super().save(commit=False)
        override_payload = dict(instance.rule_params_override or {})
        percent = self.cleaned_data.get('override_percent')
        owner_alias = self.cleaned_data.get('override_owner_alias')
        if percent in (None, ''):
            override_payload.pop('percent', None)
        else:
            override_payload['percent'] = str(percent)
        if owner_alias is None:
            override_payload.pop('owner_alias_id', None)
        else:
            override_payload['owner_alias_id'] = owner_alias.pk
        instance.rule_params_override = override_payload
        instance.is_manual_override = instance.manual_amount_override is not None or bool(override_payload)
        if commit:
            instance.save()
        return instance


class FinanceExpenseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinanceExpense
        fields = [
            'expense_side',
            'date',
            'category',
            'finance_line',
            'amount',
            'affects_direct_expenses',
            'refund_policy',
            'comment',
        ]
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.deal = deal
        self.fields['category'].queryset = FinanceExpenseCategory.objects.filter(is_active=True).order_by('expense_side', 'name')
        self.fields['finance_line'].required = False
        if deal is not None:
            self.instance.deal = deal
            self.fields['finance_line'].queryset = deal.lines.order_by('sort_order', 'id')
        else:
            self.fields['finance_line'].queryset = FinanceDealLine.objects.none()

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get('category')
        expense_side = cleaned.get('expense_side')
        finance_line = cleaned.get('finance_line')
        if category and expense_side and category.expense_side != expense_side:
            self.add_error('category', 'Категория должна совпадать со стороной расхода.')
        if finance_line and self.deal is not None and finance_line.finance_deal_id != self.deal.id:
            self.add_error('finance_line', 'Строка должна принадлежать текущему кейсу.')
        return cleaned


class FinancePayoutForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinancePayout
        fields = ['date', 'amount', 'comment']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}


class FinanceDealTypeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinanceDealType
        fields = ['name', 'partner_share', 'is_active']


class FinanceDistributionSchemeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinanceDistributionScheme
        fields = ['name', 'description', 'is_active']


class FinanceDistributionRuleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinanceDistributionRule
        fields = [
            'scheme',
            'participant_alias',
            'position',
            'rule_type',
            'percent',
            'owner_alias',
            'reference_rule',
            'note',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_people = ManagerPersonAlias.objects.filter(is_active=True).order_by('display_name')
        self.fields['scheme'].queryset = FinanceDistributionScheme.objects.order_by('name', '-version')
        self.fields['participant_alias'].queryset = active_people
        self.fields['owner_alias'].queryset = active_people
        current_scheme = None
        if self.instance.pk and self.instance.scheme_id:
            current_scheme = self.instance.scheme
        elif self.initial.get('scheme'):
            current_scheme = self.initial.get('scheme')
        if isinstance(current_scheme, FinanceDistributionScheme):
            self.fields['reference_rule'].queryset = current_scheme.rules.order_by('position', 'id')
        else:
            self.fields['reference_rule'].queryset = FinanceDistributionRule.objects.order_by('scheme__name', 'position', 'id')
        if self.instance.pk:
            self.fields['reference_rule'].queryset = self.fields['reference_rule'].queryset.exclude(pk=self.instance.pk)
        self.fields['owner_alias'].required = False
        self.fields['reference_rule'].required = False


class FinanceExpenseCategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinanceExpenseCategory
        fields = ['expense_side', 'name', 'is_active']


class ContractDocumentFilterForm(StyledFormMixin, forms.Form):
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
    class Meta:
        model = ContractTemplate
        fields = ['name', 'document_type', 'version', 'description', 'is_active', 'content_html', 'css_text']
        widgets = {
            'description': forms.Textarea(),
            'content_html': forms.Textarea(attrs={'rows': 10}),
            'css_text': forms.Textarea(attrs={'rows': 8}),
        }


class ContractCompanyProfileForm(StyledFormMixin, forms.ModelForm):
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
    has_inbound = forms.BooleanField(required=False, label='Есть приход в пути')
    has_signals = forms.BooleanField(required=False, label='Есть сигналы')
    only_active = forms.BooleanField(required=False, label='Активные')


class OrderStateForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(choices=Order.STATUS_CHOICES)
    payment_status = forms.ChoiceField(choices=Order.PAYMENT_STATUS_CHOICES)


class ManualOrderForm(StyledFormMixin, forms.Form):
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
    business_email = forms.EmailField(label='Email', required=False)
    business_city = forms.CharField(label='Город', required=False)
    business_delivery_address = forms.CharField(label='Адрес доставки / ПВЗ СДЭК', required=False, widget=forms.Textarea())
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
        delivery_method = cleaned.get('delivery_method')
        is_avito_workflow = ManagerDeal.uses_avito_workflow(deal_type, customer_source)

        if buyer_type == ManagerDeal.BUYER_INDIVIDUAL:
            if not is_avito_workflow and not (cleaned.get('individual_full_name') or '').strip():
                self.add_error('individual_full_name', 'Укажите ФИО клиента.')
            if not (cleaned.get('individual_phone') or '').strip():
                self.add_error('individual_phone', 'Укажите номер телефона клиента.')
            if not (cleaned.get('individual_city') or '').strip():
                self.add_error('individual_city', 'Укажите город клиента.')
        elif buyer_type == ManagerDeal.BUYER_BUSINESS:
            if not (cleaned.get('business_company_name') or '').strip():
                self.add_error('business_company_name', 'Укажите название компании.')
            if not (cleaned.get('business_inn') or '').strip():
                self.add_error('business_inn', 'Укажите ИНН.')
            if not (cleaned.get('business_contact_person') or '').strip():
                self.add_error('business_contact_person', 'Укажите контактное лицо.')
            if not (cleaned.get('business_phone') or '').strip():
                self.add_error('business_phone', 'Укажите телефон контактного лица.')
            if not (cleaned.get('business_email') or '').strip():
                self.add_error('business_email', 'Укажите email.')
            if not (cleaned.get('business_city') or '').strip():
                self.add_error('business_city', 'Укажите город.')

        if deal_type and cleaned.get('deal_status') and cleaned['deal_status'] not in dict(ManagerDeal.allowed_status_choices(deal_type, customer_source)):
            self.add_error('deal_status', 'Статус не подходит для выбранного сценария.')

        if delivery_method == ManagerDeal.DELIVERY_CDEK_PVZ and not (cleaned.get('delivery_pickup_address') or '').strip():
            self.add_error('delivery_pickup_address', 'Укажите адрес ПВЗ.')
        if delivery_method in {
            ManagerDeal.DELIVERY_CDEK_COURIER,
            ManagerDeal.DELIVERY_CITY,
            ManagerDeal.DELIVERY_OTHER_TRANSPORT,
        } and not (cleaned.get('delivery_full_address') or '').strip():
            self.add_error('delivery_full_address', 'Укажите полный адрес доставки.')
        if deal_type == ManagerDeal.DEAL_SALE_ON_REQUEST:
            if not (cleaned.get('customer_request') or '').strip():
                self.add_error('customer_request', 'Опишите запрос клиента.')
            if not (cleaned.get('procurement_origin') or '').strip():
                self.add_error('procurement_origin', 'Укажите, откуда заказываем.')
            if not (cleaned.get('supplier_agent') or cleaned.get('supplier_name') or '').strip():
                self.add_error('supplier_agent', 'Укажите поставщика или агента.')
        if deal_type == ManagerDeal.DEAL_SALE_FROM_STOCK and not cleaned.get('stock_warehouse'):
            self.add_error('stock_warehouse', 'Для продажи из наличия выберите склад.')
        if is_avito_workflow:
            cleaned['customer_deadline'] = None
            if deal_type == ManagerDeal.DEAL_AVITO:
                if not (cleaned.get('avito_listing_url') or '').strip():
                    self.add_error('avito_listing_url', 'Укажите ссылку на объявление.')
                if not (cleaned.get('avito_listing_title') or '').strip():
                    self.add_error('avito_listing_title', 'Укажите название объявления.')
        if deal_type == ManagerDeal.DEAL_SALE_ON_REQUEST and cleaned.get('deal_status') == ManagerDeal.DEAL_STATUS_SUPPLIER_ORDERED:
            required = cleaned.get('prepayment_required_amount') or 0
            paid = cleaned.get('prepayment_amount') or 0
            if required > 0 and paid < required:
                self.add_error('prepayment_amount', 'Нельзя запускать закупку без требуемой предоплаты.')
        return cleaned


class QuickDealForm(StyledFormMixin, forms.Form):
    client = forms.ModelChoiceField(
        label='Клиент',
        queryset=ManagerClient.objects.filter(status=ManagerClient.STATUS_ACTIVE).order_by('name'),
    )
    deal_type = forms.ChoiceField(label='Тип сделки', choices=ManagerDeal.DEAL_TYPE_CHOICES)
    customer_source = forms.ChoiceField(label='Источник', choices=ManagerDeal.CUSTOMER_SOURCE_CHOICES)
    responsible_manager = forms.ModelChoiceField(
        label='Ответственный',
        queryset=get_user_model().objects.filter(is_staff=True).order_by('username'),
    )
    next_step_code = forms.ChoiceField(label='Следующий шаг', choices=ManagerDeal.NEXT_STEP_CHOICES)


class ManualOrderItemForm(StyledFormMixin, forms.Form):
    line_type = forms.ChoiceField(label='Тип строки', choices=OrderItem.LINE_TYPE_CHOICES, initial=OrderItem.LINE_TYPE_CATALOG)
    product = forms.ModelChoiceField(
        label='Товар',
        queryset=Product.objects.order_by('name'),
        required=False,
    )
    variant = forms.ModelChoiceField(
        label='Вариант',
        queryset=ProductVariant.objects.order_by('product__name', 'name'),
        required=False,
    )
    product_name = forms.CharField(
        label='Название произвольного товара',
        required=False,
        widget=forms.TextInput(),
    )
    custom_sku = forms.CharField(label='Произвольный SKU', required=False)
    configuration = forms.CharField(label='Конфигурация / модификация', required=False)
    condition = forms.ChoiceField(label='Состояние', choices=OrderItem.CONDITION_CHOICES, initial=OrderItem.CONDITION_NEW)
    quantity = forms.IntegerField(label='Количество', min_value=1, required=False, initial=1)
    planned_unit_cost = forms.DecimalField(label='Плановая себестоимость', min_value=0, decimal_places=2, required=False, initial=0)
    purchase_price = forms.DecimalField(label='Плановая себестоимость', min_value=0, decimal_places=2, required=False, initial=0, widget=forms.HiddenInput())
    sale_price = forms.DecimalField(label='Цена продажи за единицу', min_value=0, decimal_places=2, required=False, initial=0)
    discount_amount = forms.DecimalField(label='Скидка', min_value=0, decimal_places=2, required=False, initial=0)
    comment = forms.CharField(label='Комментарий', required=False, widget=forms.Textarea())

    def has_item_data(self):
        data = getattr(self, 'cleaned_data', {})
        return any(
            data.get(key)
            for key in ('product_name', 'custom_sku', 'product', 'variant', 'configuration', 'quantity', 'planned_unit_cost', 'sale_price', 'discount_amount', 'comment')
        )

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(key) for key in ('product_name', 'custom_sku', 'product', 'variant', 'configuration', 'quantity', 'planned_unit_cost', 'sale_price', 'discount_amount', 'comment')):
            return cleaned
        line_type = cleaned.get('line_type') or OrderItem.LINE_TYPE_CATALOG
        product = cleaned.get('product')
        product_name = (cleaned.get('product_name') or '').strip()
        custom_sku = (cleaned.get('custom_sku') or '').strip()
        if line_type == OrderItem.LINE_TYPE_CATALOG:
            if not product:
                self.add_error('product', 'Выберите товар.')
            if product is not None:
                cleaned['product_name'] = product.name
                if product.variants.exists() and not cleaned.get('variant'):
                    self.add_error('variant', 'Для товара с вариантами выберите конкретный вариант.')
            if custom_sku:
                self.add_error('custom_sku', 'Для каталоговой строки произвольный SKU не используется.')
        else:
            cleaned['product'] = None
            cleaned['variant'] = None
            if not product_name:
                self.add_error('product_name', 'Введите название позиции.')
        if cleaned.get('product') and cleaned.get('variant') and cleaned['variant'].product_id != cleaned['product'].id:
            self.add_error('variant', 'Вариант должен относиться к выбранному товару.')
        if cleaned.get('quantity') in (None, ''):
            self.add_error('quantity', 'Укажите количество.')
        if cleaned.get('planned_unit_cost') in (None, '') and cleaned.get('purchase_price') not in (None, ''):
            cleaned['planned_unit_cost'] = cleaned.get('purchase_price')
        if cleaned.get('sale_price') in (None, ''):
            if cleaned.get('product'):
                cleaned['sale_price'] = cleaned['variant'].price if cleaned.get('variant') else cleaned['product'].price
            else:
                self.add_error('sale_price', 'Укажите цену продажи.')
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


class QuickOrderItemForm(StyledFormMixin, forms.Form):
    line_type = forms.ChoiceField(label='Тип строки', choices=OrderItem.LINE_TYPE_CHOICES, initial=OrderItem.LINE_TYPE_CATALOG)
    product = forms.ModelChoiceField(label='Товар', queryset=Product.objects.order_by('name'), required=False)
    variant = forms.ModelChoiceField(
        label='Вариант',
        queryset=ProductVariant.objects.order_by('product__name', 'name'),
        required=False,
    )
    product_name = forms.CharField(label='Название произвольного товара', required=False)
    custom_sku = forms.CharField(label='Произвольный SKU', required=False)
    configuration = forms.CharField(label='Конфигурация / модификация', required=False)
    quantity = forms.IntegerField(label='Количество', min_value=1, required=False, initial=1)
    planned_unit_cost = forms.DecimalField(label='Плановая себестоимость', min_value=0, decimal_places=2, required=False, initial=0)
    purchase_price = forms.DecimalField(label='Плановая себестоимость', min_value=0, decimal_places=2, required=False, initial=0, widget=forms.HiddenInput())
    sale_price = forms.DecimalField(label='Сумма за единицу', min_value=0, decimal_places=2, required=False, initial=0)
    comment = forms.CharField(label='Комментарий', required=False, widget=forms.Textarea())

    def has_item_data(self):
        data = getattr(self, 'cleaned_data', {})
        return any(
            data.get(key)
            for key in ('product', 'variant', 'product_name', 'custom_sku', 'configuration', 'quantity', 'planned_unit_cost', 'sale_price', 'comment')
        )

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(key) for key in ('product', 'variant', 'product_name', 'custom_sku', 'configuration', 'quantity', 'planned_unit_cost', 'sale_price', 'comment')):
            return cleaned
        line_type = cleaned.get('line_type') or OrderItem.LINE_TYPE_CATALOG
        if line_type == OrderItem.LINE_TYPE_CATALOG:
            if not cleaned.get('product'):
                self.add_error('product', 'Выберите товар.')
            elif cleaned['product'].variants.exists() and not cleaned.get('variant'):
                self.add_error('variant', 'Для товара с вариантами выберите конкретный вариант.')
            cleaned['product_name'] = cleaned['product'].name if cleaned.get('product') else ''
            if cleaned.get('custom_sku'):
                self.add_error('custom_sku', 'Для каталоговой строки произвольный SKU не используется.')
        else:
            cleaned['product'] = None
            cleaned['variant'] = None
            if not (cleaned.get('product_name') or '').strip():
                self.add_error('product_name', 'Введите название позиции.')
        if cleaned.get('product') and cleaned.get('variant') and cleaned['variant'].product_id != cleaned['product'].id:
            self.add_error('variant', 'Вариант должен относиться к выбранному товару.')
        if cleaned.get('quantity') in (None, ''):
            self.add_error('quantity', 'Укажите количество.')
        if cleaned.get('planned_unit_cost') in (None, '') and cleaned.get('purchase_price') not in (None, ''):
            cleaned['planned_unit_cost'] = cleaned.get('purchase_price')
        if cleaned.get('sale_price') in (None, ''):
            self.add_error('sale_price', 'Укажите сумму.')
        return cleaned


class BaseQuickOrderItemFormSet(BaseFormSet):
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
            raise forms.ValidationError('Добавьте хотя бы одну позицию в сделку.')


QuickOrderItemFormSet = formset_factory(
    QuickOrderItemForm,
    formset=BaseQuickOrderItemFormSet,
    extra=1,
    can_delete=True,
)


class TradeInItemForm(StyledFormMixin, forms.Form):
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
            ('model_name', 'Укажите модель сдаваемого устройства.'),
            ('condition', 'Укажите состояние устройства.'),
            ('kit_description', 'Опишите комплектацию.'),
        ):
            if not (cleaned.get(required_field) or '').strip():
                self.add_error(required_field, message)
        if cleaned.get('preliminary_estimate') in (None, ''):
            self.add_error('preliminary_estimate', 'Укажите оценочную стоимость.')
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
    orders = forms.ModelMultipleChoiceField(
        queryset=Order.objects.order_by('-created_at'),
        required=False,
        widget=forms.SelectMultiple(attrs={'size': 6}),
        label='Связанные заказы',
    )

    class Meta:
        model = ManagerClient
        fields = ['user', 'name', 'email', 'phone', 'telegram', 'address', 'comments', 'status', 'orders']


class WarehouseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ['name', 'address', 'pickup_point', 'is_active']


class InventoryReceiptForm(StyledFormMixin, forms.Form):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.order_by('name'))
    product = forms.ModelChoiceField(queryset=Product.objects.order_by('name'))
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.order_by('product__name', 'name'), required=False)
    quantity = forms.IntegerField(min_value=1)
    unit_cost = forms.DecimalField(label='Себестоимость за единицу', min_value=0, decimal_places=2)
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
    q = forms.CharField(required=False, label='Поиск')
    status = forms.ChoiceField(required=False, choices=[('', 'Любой статус')] + list(Purchase.STATUS_CHOICES))
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))


class PurchaseItemForm(BaseVariantAwareForm):
    order_item = forms.ModelChoiceField(
        required=False,
        queryset=OrderItem.objects.filter(line_type=OrderItem.LINE_TYPE_CATALOG).select_related('order', 'product', 'variant').order_by('-order__created_at', '-id'),
        label='Строка заказа',
    )

    class Meta:
        model = PurchaseItem
        fields = ['product', 'variant', 'order_item', 'quantity', 'unit_cost']


class CargoForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Cargo
        fields = ['cargo_number', 'purchase', 'status', 'eta', 'destination_warehouse', 'comments']
        widgets = {'eta': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cargo_number'].required = False


class CargoFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(required=False, label='Поиск')
    status = forms.ChoiceField(required=False, choices=[('', 'Любой статус')] + list(Cargo.STATUS_CHOICES))
    destination_warehouse = forms.ModelChoiceField(
        required=False,
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
    q = forms.CharField(required=False, label='Поиск')
    status = forms.ChoiceField(required=False, choices=[('', 'Любой статус')] + list(Reservation.STATUS_CHOICES))
    source_type = forms.ChoiceField(required=False, choices=[('', 'Любой источник')] + list(Reservation.SOURCE_CHOICES))
    source_warehouse = forms.ModelChoiceField(
        required=False,
        queryset=Warehouse.objects.order_by('name'),
        empty_label='Любой склад-источник',
    )
    target_warehouse = forms.ModelChoiceField(
        required=False,
        queryset=Warehouse.objects.order_by('name'),
        empty_label='Любой склад назначения',
    )
    client = forms.ModelChoiceField(
        required=False,
        queryset=ManagerClient.objects.order_by('name'),
        empty_label='Любой клиент',
    )


class ReservationItemForm(BaseVariantAwareForm):
    order_item = forms.ModelChoiceField(
        required=False,
        queryset=OrderItem.objects.filter(line_type=OrderItem.LINE_TYPE_CATALOG).select_related('order', 'product', 'variant').order_by('-order__created_at', '-id'),
        label='Строка заказа',
    )

    class Meta:
        model = ReservationItem
        fields = ['product', 'variant', 'order_item', 'quantity']


class ReservationStatusForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(
        choices=[
            (Reservation.STATUS_DRAFT, 'Черновик'),
            (Reservation.STATUS_ACTIVE, 'Активно'),
            (Reservation.STATUS_PARTIAL, 'Частично выдано'),
            (Reservation.STATUS_RELEASED, 'Освобождено'),
            (Reservation.STATUS_CANCELLED, 'Отменено'),
            (Reservation.STATUS_EXPIRED, 'Истекло'),
        ]
    )


class ShipmentFilterForm(StyledFormMixin, forms.Form):
    warehouse = forms.ModelChoiceField(
        required=False,
        queryset=Warehouse.objects.order_by('name'),
        empty_label='Любой склад-источник',
    )
    target_warehouse = forms.ModelChoiceField(
        required=False,
        queryset=Warehouse.objects.order_by('name'),
        empty_label='Любой склад назначения',
    )
    client = forms.ModelChoiceField(
        required=False,
        queryset=ManagerClient.objects.order_by('name'),
        empty_label='Любой клиент',
    )
    view_mode = forms.ChoiceField(
        required=False,
        choices=[('reservation', 'По броням'), ('items', 'По позициям')],
        initial='reservation',
    )
