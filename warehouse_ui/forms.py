from django import forms

from catalog.models import City, Product, ProductVariant
from manager_portal.models import Warehouse


INPUT_CLASS = 'w-full rounded-2xl border border-cyan-500/20 bg-slate-950/90 px-4 py-3 text-sm text-slate-100 shadow-sm outline-none transition placeholder:text-slate-500 focus:border-cyan-400/60 focus:ring-2 focus:ring-cyan-400/20'
CHECKBOX_CLASS = 'h-4 w-4 rounded border-slate-600 bg-slate-950 text-cyan-400 focus:ring-cyan-400/30'


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
    warehouses = forms.ModelMultipleChoiceField(
        queryset=Warehouse.objects.filter(is_active=True).select_related('pickup_point__city').order_by('name'),
        required=False,
        label='Склады',
        widget=forms.SelectMultiple(attrs={'size': 6}),
    )
    in_stock = forms.BooleanField(required=False, label='В наличии')
    out_of_stock = forms.BooleanField(required=False, label='Нет в наличии')
    has_reserve = forms.BooleanField(required=False, label='Есть резерв')
    inbound = forms.BooleanField(required=False, label='В пути')
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
    comment = forms.CharField(required=False, label='Комментарий')


class WarehouseAdjustmentForm(WarehouseSkuActionForm):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).order_by('name'), label='Склад')
    quantity_delta = forms.IntegerField(label='Изменение')
    comment = forms.CharField(required=False, label='Комментарий')

    def clean_quantity_delta(self):
        value = self.cleaned_data['quantity_delta']
        if value == 0:
            raise forms.ValidationError('Изменение не должно быть нулевым.')
        return value


class WarehouseTransferForm(WarehouseSkuActionForm):
    source_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).order_by('name'), label='Откуда')
    target_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(is_active=True).order_by('name'), label='Куда')
    quantity = forms.IntegerField(min_value=1, label='Количество')
    comment = forms.CharField(required=False, label='Комментарий')

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get('source_warehouse')
        target = cleaned.get('target_warehouse')
        if source and target and source.pk == target.pk:
            self.add_error('target_warehouse', 'Склад назначения должен отличаться от склада-источника.')
        return cleaned
