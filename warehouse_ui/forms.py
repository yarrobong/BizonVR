from django import forms

from catalog.models import City, Product, ProductVariant
from manager_portal.models import ManagerDeal, Warehouse
from orders.models import Order


INPUT_CLASS = 'w-full rounded-2xl border border-cyan-500/20 bg-slate-950/90 px-4 py-3 text-sm text-slate-100 shadow-sm outline-none transition placeholder:text-slate-500 focus:border-cyan-400/60 focus:ring-2 focus:ring-cyan-400/20'
CHECKBOX_CLASS = 'h-4 w-4 rounded border-slate-600 bg-slate-950 text-cyan-400 focus:ring-cyan-400/30'


STATUS_CHOICES = [
    ('all', 'Все'),
    ('available', 'В наличии'),
    ('out', 'Нет в наличии'),
    ('low', 'Низкий остаток'),
    ('reserve', 'Есть резерв'),
    ('inbound', 'В пути'),
    ('problematic', 'Проблемные'),
    ('mismatch', 'Расхождения'),
]


ADJUSTMENT_REASON_CHOICES = [
    ('inventory_count', 'Инвентаризация'),
    ('recount', 'Пересчёт'),
    ('damage_fix', 'Исправление ошибки / брака'),
    ('other', 'Другое'),
]


WRITE_OFF_REASON_CHOICES = [
    ('damage', 'Повреждение'),
    ('loss', 'Утеря'),
    ('defect', 'Брак'),
    ('internal_use', 'Внутреннее использование'),
    ('other', 'Другое'),
]


def _order_label(order):
    customer = order.shipping_contact_name or order.business_company_name or 'Клиент'
    return f'Заказ #{order.pk} · {customer}'


def _deal_label(deal):
    customer = deal.customer_name or deal.code or 'Сделка'
    return f'{deal.code or f"Сделка #{deal.pk}"} · {customer}'


class WarehouseUiFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = CHECKBOX_CLASS
            else:
                widget.attrs['class'] = INPUT_CLASS


class WarehouseMatrixFilterForm(WarehouseUiFormMixin, forms.Form):
    q = forms.CharField(
        required=False,
        label='Поиск',
        widget=forms.TextInput(attrs={'placeholder': 'Товар, вариант или SKU'}),
    )
    city = forms.ModelChoiceField(
        queryset=City.objects.order_by('order', 'name'),
        required=False,
        label='Город',
        empty_label='Все города',
    )
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.filter(is_active=True).select_related('pickup_point__city').order_by('name'),
        required=False,
        label='Склад',
        empty_label='Все склады',
    )
    status = forms.ChoiceField(required=False, label='Статус', choices=STATUS_CHOICES, initial='all')
    compact = forms.ChoiceField(
        required=False,
        label='Режим',
        choices=[('compact', 'Компактно'), ('detailed', 'Подробно')],
        initial='compact',
        widget=forms.HiddenInput(),
    )
    in_stock = forms.BooleanField(required=False, label='В наличии')
    out_of_stock = forms.BooleanField(required=False, label='Нет в наличии')
    has_reserve = forms.BooleanField(required=False, label='Есть резерв')
    inbound = forms.BooleanField(required=False, label='В пути')
    low_stock = forms.BooleanField(required=False, label='Низкий остаток')
    problematic = forms.BooleanField(required=False, label='Проблемные')
    only_mismatch = forms.BooleanField(required=False, label='Только с расхождениями')
    stale = forms.BooleanField(required=False, label='Без движения 30+ дней')
    page = forms.IntegerField(required=False, min_value=1, initial=1, widget=forms.HiddenInput())


class WarehouseSkuActionForm(WarehouseUiFormMixin, forms.Form):
    sku_key = forms.CharField(widget=forms.HiddenInput())
    product = forms.ModelChoiceField(queryset=Product.objects.order_by('name'), widget=forms.HiddenInput())
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.select_related('product').order_by('product__name', 'name'), required=False, widget=forms.HiddenInput())

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get('product')
        variant = cleaned.get('variant')
        if variant and product and variant.product_id != product.id:
            self.add_error('variant', 'Вариант должен относиться к выбранному товару.')
        return cleaned


class WarehouseReceiptForm(WarehouseSkuActionForm):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).order_by('name'), label='Склад')
    quantity = forms.IntegerField(min_value=1, label='Количество')
    unit_cost = forms.DecimalField(required=False, min_value=0, decimal_places=2, label='Себестоимость')
    comment = forms.CharField(required=False, label='Комментарий', widget=forms.Textarea(attrs={'rows': 3}))


class WarehouseAdjustmentForm(WarehouseSkuActionForm):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).order_by('name'), label='Склад')
    actual_quantity = forms.IntegerField(min_value=0, label='Фактический остаток')
    reason = forms.ChoiceField(label='Причина', choices=ADJUSTMENT_REASON_CHOICES)
    comment = forms.CharField(required=False, label='Комментарий', widget=forms.Textarea(attrs={'rows': 3}))


class WarehouseTransferForm(WarehouseSkuActionForm):
    source_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).order_by('name'), label='Откуда')
    target_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).order_by('name'), label='Куда')
    quantity = forms.IntegerField(min_value=1, label='Количество')
    comment = forms.CharField(required=False, label='Комментарий', widget=forms.Textarea(attrs={'rows': 3}))

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get('source_warehouse')
        target = cleaned.get('target_warehouse')
        if source and target and source.pk == target.pk:
            self.add_error('target_warehouse', 'Склад назначения должен отличаться от склада-источника.')
        return cleaned


class WarehouseReserveForm(WarehouseSkuActionForm):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).order_by('name'), label='Склад')
    order = forms.ModelChoiceField(
        queryset=Order.objects.exclude(status=Order.STATUS_CANCELLED).order_by('-created_at'),
        required=False,
        label='Заказ',
    )
    deal = forms.ModelChoiceField(
        queryset=ManagerDeal.objects.exclude(deal_status__in=[ManagerDeal.DEAL_STATUS_CANCELLED, ManagerDeal.DEAL_STATUS_COMPLETED]).order_by('-deal_created_at', '-id'),
        required=False,
        label='Сделка',
    )
    quantity = forms.IntegerField(min_value=1, label='Количество')
    comment = forms.CharField(required=False, label='Комментарий', widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['order'].label_from_instance = _order_label
        self.fields['deal'].label_from_instance = _deal_label

    def clean(self):
        cleaned = super().clean()
        order = cleaned.get('order')
        deal = cleaned.get('deal')
        if not order and not deal:
            raise forms.ValidationError('Выберите заказ или сделку, под которую создаётся резерв.')
        if order and deal and getattr(deal, 'order_id', None) and deal.order_id != order.id:
            self.add_error('deal', 'Сделка должна относиться к выбранному заказу.')
        return cleaned


class WarehouseExpenseForm(WarehouseSkuActionForm):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).order_by('name'), label='Склад')
    order = forms.ModelChoiceField(
        queryset=Order.objects.exclude(status=Order.STATUS_CANCELLED).order_by('-created_at'),
        required=False,
        label='Заказ',
    )
    deal = forms.ModelChoiceField(
        queryset=ManagerDeal.objects.exclude(deal_status__in=[ManagerDeal.DEAL_STATUS_CANCELLED, ManagerDeal.DEAL_STATUS_COMPLETED]).order_by('-deal_created_at', '-id'),
        required=False,
        label='Сделка',
    )
    quantity = forms.IntegerField(min_value=1, label='Количество')
    comment = forms.CharField(required=True, label='Комментарий', widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['order'].label_from_instance = _order_label
        self.fields['deal'].label_from_instance = _deal_label

    def clean(self):
        cleaned = super().clean()
        order = cleaned.get('order')
        deal = cleaned.get('deal')
        if order and deal and getattr(deal, 'order_id', None) and deal.order_id != order.id:
            self.add_error('deal', 'Сделка должна относиться к выбранному заказу.')
        return cleaned


class WarehouseWriteOffForm(WarehouseSkuActionForm):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).order_by('name'), label='Склад')
    quantity = forms.IntegerField(min_value=1, label='Количество')
    reason = forms.ChoiceField(label='Причина списания', choices=WRITE_OFF_REASON_CHOICES)
    comment = forms.CharField(required=True, label='Комментарий', widget=forms.Textarea(attrs={'rows': 3}))
