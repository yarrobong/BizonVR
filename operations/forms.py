import re

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import F
from django.utils import timezone

from catalog.models import Product
from manager_portal.forms import INPUT_CLASS, LinkOrderItemProductForm, StyledFormMixin
from manager_portal.models import Cargo, CargoItem, Purchase, PurchaseItem, Shipment, Warehouse
from orders.models import Order
from orders.models import OrderItem

from .selectors import PROBLEM_FILTER_CHOICES
from .services import purchase_item_cargo_available_quantity, reservation_candidates_for_deal


class OperationsDealFilterForm(forms.Form):
    q = forms.CharField(required=False, label='Поиск')
    status = forms.ChoiceField(required=False, label='Операционный статус')
    problem = forms.ChoiceField(required=False, label='Проблема', choices=PROBLEM_FILTER_CHOICES)
    responsible_manager = forms.ModelChoiceField(
        required=False,
        label='Ответственный',
        empty_label='Любой ответственный',
        queryset=get_user_model().objects.none(),
    )
    needs_link_products = forms.BooleanField(required=False, label='Нужно связать товары')
    needs_procurement = forms.BooleanField(required=False, label='Нужно закупить')
    ready_to_ship = forms.BooleanField(required=False, label='Готово к отправке')
    in_transit = forms.BooleanField(required=False, label='В пути')
    missing_delivery_data = forms.BooleanField(required=False, label='Нет адреса или получателя')

    def __init__(self, *args, status_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].choices = [('', 'Все статусы')] + list(status_choices or [])
        self.fields['responsible_manager'].queryset = get_user_model().objects.filter(is_staff=True).order_by('username')
        input_class = 'w-full rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white'
        self.fields['q'].widget.attrs.update(
            {
                'class': input_class,
                'placeholder': 'Bitrix ID, клиент, сделка, товар, SKU',
            }
        )
        self.fields['status'].widget.attrs.update({'class': input_class})
        self.fields['problem'].widget.attrs.update({'class': input_class})
        self.fields['responsible_manager'].widget.attrs.update({'class': input_class})
        for field_name in (
            'needs_link_products',
            'needs_procurement',
            'ready_to_ship',
            'in_transit',
            'missing_delivery_data',
        ):
            self.fields[field_name].widget.attrs.update(
                {'class': 'h-4 w-4 rounded border-slate-600 bg-slate-950 text-cyan-300'}
            )


class CustomOrderItemLinkForm(LinkOrderItemProductForm):
    item_id = forms.IntegerField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        product_queryset = self.fields['product'].queryset
        product_field_names = {field.name for field in product_queryset.model._meta.get_fields()}
        if 'tracks_stock' in product_field_names:
            product_queryset = product_queryset.filter(tracks_stock=True)
        self.fields['product'].queryset = product_queryset
        selected_product = None
        if self.is_bound:
            raw_product_id = (self.data.get(self.add_prefix('product')) or '').strip()
            if raw_product_id.isdigit():
                selected_product = self.fields['product'].queryset.filter(pk=int(raw_product_id)).first()
        else:
            selected_product = self.initial.get('product')
        if selected_product is not None:
            self.fields['variant'].queryset = selected_product.variants.order_by('order', 'id')
        self.fields['product'].widget.attrs.update(
            {
                'data-product-select': '1',
            }
        )
        self.fields['variant'].widget.attrs.update(
            {
                'data-variant-select': '1',
            }
        )


class ReceiveCargoItemChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        cargo_label = obj.cargo.cargo_number or f'CG #{obj.cargo_id}'
        variant_label = f' · {obj.variant.name}' if obj.variant_id else ''
        warehouse_label = obj.cargo.destination_warehouse.name if obj.cargo.destination_warehouse_id else 'Склад не указан'
        return (
            f'{cargo_label} · {obj.product.name}{variant_label} · '
            f'осталось принять {obj.remaining_quantity} из {obj.quantity} · {warehouse_label}'
        )


class OperationsCargoAcceptanceForm(StyledFormMixin, forms.Form):
    cargo_item = ReceiveCargoItemChoiceField(label='CargoItem', queryset=CargoItem.objects.none())
    quantity = forms.IntegerField(min_value=1, label='Принятое количество')
    warehouse = forms.ModelChoiceField(label='Склад приемки', queryset=Warehouse.objects.order_by('name'))
    received_date = forms.DateField(
        label='Дата приемки',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    comment = forms.CharField(required=False, label='Комментарий', widget=forms.Textarea(attrs={'rows': 4}))

    def __init__(self, *args, deal, cargo_item=None, **kwargs):
        self.deal = deal
        self.selected_cargo_item = cargo_item
        super().__init__(*args, **kwargs)
        queryset = (
            CargoItem.objects.filter(
                purchase_item__order_item__order=deal.order,
                quantity__gt=F('received_quantity'),
            )
            .exclude(cargo__status=Cargo.STATUS_CANCELLED)
            .select_related(
                'cargo',
                'cargo__destination_warehouse',
                'product',
                'variant',
                'purchase_item',
                'purchase_item__order_item',
            )
            .order_by('cargo__eta', 'cargo_id', 'id')
        )
        self.fields['cargo_item'].queryset = queryset
        if not self.is_bound:
            initial_cargo_item = cargo_item or queryset.first()
            self.fields['received_date'].initial = timezone.localdate()
            if initial_cargo_item is not None:
                self.fields['cargo_item'].initial = initial_cargo_item.pk
                self.fields['quantity'].initial = initial_cargo_item.remaining_quantity
                self.fields['warehouse'].initial = initial_cargo_item.cargo.destination_warehouse or deal.stock_warehouse

    def clean_comment(self):
        return (self.cleaned_data.get('comment') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        cargo_item = cleaned_data.get('cargo_item')
        quantity = cleaned_data.get('quantity')
        warehouse = cleaned_data.get('warehouse')
        if cargo_item is None:
            return cleaned_data
        if cargo_item.purchase_item_id is None or cargo_item.purchase_item.order_item_id is None:
            self.add_error('cargo_item', 'У выбранной позиции груза нет связи со строкой заказа.')
            return cleaned_data
        if cargo_item.purchase_item.order_item.order_id != self.deal.order_id:
            self.add_error('cargo_item', 'Позиция груза не относится к этой сделке.')
        if quantity is not None and quantity > cargo_item.remaining_quantity:
            self.add_error('quantity', f'Можно принять не больше {cargo_item.remaining_quantity} шт.')
        if warehouse is None and cargo_item.cargo.destination_warehouse_id is None:
            self.add_error('warehouse', 'Укажите склад приемки.')
        return cleaned_data


class PurchaseItemChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        purchase_label = obj.purchase.code or f'PO #{obj.purchase_id}'
        variant_label = f' · {obj.variant.name}' if obj.variant_id else ''
        available_quantity = purchase_item_cargo_available_quantity(obj)
        return f'{purchase_label} · {obj.product.name}{variant_label} · доступно {available_quantity} из {obj.active_quantity}'


class OperationsCargoCreateForm(StyledFormMixin, forms.Form):
    OPS_STATUS_CHOICES = [
        (Cargo.STATUS_CREATED, 'Создан'),
        (Cargo.STATUS_IN_TRANSIT, 'В пути'),
        (Cargo.STATUS_ARRIVED_RF, 'Прибыл'),
        (Cargo.STATUS_AWAITING_RECEIPT, 'Ожидает приемки'),
        (Cargo.STATUS_RECEIVED, 'Принят'),
        (Cargo.STATUS_CANCELLED, 'Отменен'),
    ]

    purchase_item = PurchaseItemChoiceField(
        label='Позиция закупки',
        queryset=PurchaseItem.objects.none(),
    )
    quantity = forms.IntegerField(min_value=1, label='Количество в грузе')
    destination_warehouse = forms.ModelChoiceField(
        label='Склад назначения',
        queryset=Warehouse.objects.order_by('name'),
    )
    eta = forms.DateField(
        required=False,
        label='Ожидаемая дата прихода',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    status = forms.ChoiceField(label='Статус груза', choices=OPS_STATUS_CHOICES)
    comments = forms.CharField(required=False, label='Комментарий', widget=forms.Textarea())
    cargo_number = forms.CharField(required=False, label='Номер груза', max_length=120)

    def __init__(self, *args, deal, purchase=None, purchase_item=None, **kwargs):
        self.deal = deal
        self.purchase = purchase
        self.selected_purchase_item = purchase_item
        super().__init__(*args, **kwargs)
        purchase_items = (
            PurchaseItem.objects.filter(order_item__order=deal.order)
            .exclude(purchase__status=Purchase.STATUS_CANCELLED)
            .select_related('purchase', 'product', 'variant', 'order_item')
            .prefetch_related('cargo_items__cargo')
            .order_by('-purchase__date', '-purchase_id', 'id')
        )
        if purchase is not None:
            purchase_items = purchase_items.filter(purchase=purchase)
        self.fields['purchase_item'].queryset = purchase_items
        if not self.is_bound:
            self.fields['status'].initial = Cargo.STATUS_CREATED
            self.fields['destination_warehouse'].initial = deal.stock_warehouse
            self.fields['eta'].initial = deal.expected_arrival_date
            if purchase_item is not None:
                self.fields['purchase_item'].initial = purchase_item.pk
                available_quantity = purchase_item_cargo_available_quantity(purchase_item)
                if available_quantity > 0:
                    self.fields['quantity'].initial = available_quantity
        self.fields['comments'].widget.attrs.update(
            {'rows': 4, 'placeholder': 'Например: идет первой партией, ожидаем сверку по коробкам'}
        )
        self.fields['cargo_number'].widget.attrs.update({'placeholder': 'Можно оставить пустым'})

    def clean_cargo_number(self):
        cargo_number = (self.cleaned_data.get('cargo_number') or '').strip()
        if cargo_number and Cargo.objects.filter(cargo_number=cargo_number).exists():
            raise forms.ValidationError('Груз с таким номером уже существует.')
        return cargo_number

    def clean_comments(self):
        return (self.cleaned_data.get('comments') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        purchase_item = cleaned_data.get('purchase_item')
        quantity = cleaned_data.get('quantity')
        status = (cleaned_data.get('status') or '').strip()
        eta = cleaned_data.get('eta')
        if status and status != Cargo.STATUS_CREATED and eta is None:
            self.add_error('eta', 'Укажите ETA для груза, если он уже не в статусе "Создан".')
        if purchase_item is None:
            return cleaned_data
        if purchase_item.order_item_id is None or purchase_item.order_item.order_id != self.deal.order_id:
            self.add_error('purchase_item', 'Позиция закупки не относится к этой сделке.')
            return cleaned_data
        available_quantity = purchase_item_cargo_available_quantity(purchase_item)
        if available_quantity <= 0:
            self.add_error('purchase_item', 'По выбранной позиции закупки больше нечего добавлять в грузы.')
        elif quantity is not None and quantity > available_quantity:
            self.add_error('quantity', f'Можно добавить не больше {available_quantity} шт.')
        return cleaned_data


class ReservationOrderItemChoiceField(forms.ModelChoiceField):
    def __init__(self, *args, candidate_map=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.candidate_map = candidate_map or {}

    def label_from_instance(self, obj):
        candidate = self.candidate_map.get(obj.id, {})
        missing_quantity = int(candidate.get('missing_quantity') or 0)
        total_available = int(candidate.get('total_available') or 0)
        return f'{obj.display_name} · не хватает {missing_quantity} · доступно на складах {total_available}'


class ReservationWarehouseChoiceField(forms.ModelChoiceField):
    def __init__(self, *args, availability_by_warehouse=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.availability_by_warehouse = availability_by_warehouse or {}

    def label_from_instance(self, obj):
        available = int(self.availability_by_warehouse.get(obj.id, 0))
        return f'{obj.name} · доступно {available}'


class OperationsReservationCreateForm(StyledFormMixin, forms.Form):
    order_item = ReservationOrderItemChoiceField(label='Позиция заказа', queryset=OrderItem.objects.none())
    product = forms.ModelChoiceField(label='Товар', queryset=Product.objects.none())
    warehouse = ReservationWarehouseChoiceField(label='Склад', queryset=Warehouse.objects.none())
    quantity = forms.IntegerField(min_value=1, label='Количество')
    comment = forms.CharField(required=False, label='Комментарий', widget=forms.Textarea(attrs={'rows': 4}))

    def __init__(self, *args, deal, selected_order_item=None, **kwargs):
        self.deal = deal
        self.reservation_candidates = reservation_candidates_for_deal(deal)
        self.selected_order_item = selected_order_item
        super().__init__(*args, **kwargs)

        order_items = [candidate['order_item'] for candidate in self.reservation_candidates.values()]
        order_item_queryset = OrderItem.objects.filter(id__in=[item.id for item in order_items]).select_related('product', 'variant')
        self.fields['order_item'] = ReservationOrderItemChoiceField(
            label=self.fields['order_item'].label,
            queryset=order_item_queryset.order_by('id'),
            candidate_map=self.reservation_candidates,
        )
        self.fields['comment'].widget.attrs.update(
            {'placeholder': 'Например: резервируем под оплату и подготовку к отгрузке'}
        )

        selected_candidate = self._selected_candidate()
        product_queryset = Product.objects.none()
        warehouse_queryset = Warehouse.objects.none()
        availability_by_warehouse = {}
        if selected_candidate is not None:
            product_queryset = Product.objects.filter(pk=selected_candidate['product'].pk)
            availability_by_warehouse = {
                int(entry['warehouse_id']): int(entry['available'] or 0)
                for entry in selected_candidate['warehouses']
            }
            warehouse_queryset = Warehouse.objects.filter(id__in=list(availability_by_warehouse.keys())).order_by('name')
        self.fields['product'].queryset = product_queryset
        self.fields['warehouse'] = ReservationWarehouseChoiceField(
            label=self.fields['warehouse'].label,
            queryset=warehouse_queryset,
            availability_by_warehouse=availability_by_warehouse,
        )
        self.fields['order_item'].widget.attrs.update({'class': INPUT_CLASS})
        self.fields['warehouse'].widget.attrs.update({'class': INPUT_CLASS})

        if not self.is_bound and selected_candidate is not None:
            self.fields['order_item'].initial = selected_candidate['order_item'].pk
            self.fields['product'].initial = selected_candidate['product'].pk
            default_warehouse_id = self._default_warehouse_id(selected_candidate)
            if default_warehouse_id:
                self.fields['warehouse'].initial = default_warehouse_id
                default_available = int(availability_by_warehouse.get(default_warehouse_id, 0))
                self.fields['quantity'].initial = min(
                    int(selected_candidate['missing_quantity'] or 0),
                    default_available,
                )

    def _selected_candidate(self):
        raw_order_item_id = ''
        if self.is_bound:
            raw_order_item_id = str(self.data.get(self.add_prefix('order_item')) or '').strip()
        elif self.selected_order_item is not None:
            raw_order_item_id = str(self.selected_order_item.pk)
        if raw_order_item_id.isdigit():
            return self.reservation_candidates.get(int(raw_order_item_id))
        return next(iter(self.reservation_candidates.values()), None)

    def _default_warehouse_id(self, candidate):
        warehouse_ids = [int(entry['warehouse_id']) for entry in candidate['warehouses']]
        if self.deal.stock_warehouse_id in warehouse_ids:
            return self.deal.stock_warehouse_id
        return warehouse_ids[0] if warehouse_ids else None

    @property
    def has_candidates(self):
        return bool(self.reservation_candidates)

    @property
    def current_candidate(self):
        return self._selected_candidate()

    def clean_comment(self):
        return (self.cleaned_data.get('comment') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        order_item = cleaned_data.get('order_item')
        product = cleaned_data.get('product')
        warehouse = cleaned_data.get('warehouse')
        quantity = cleaned_data.get('quantity')
        if order_item is None:
            return cleaned_data

        candidate = self.reservation_candidates.get(order_item.id)
        if candidate is None:
            self.add_error('order_item', 'По выбранной позиции сейчас нельзя создать резерв.')
            return cleaned_data
        if product is not None and product.id != candidate['product'].id:
            self.add_error('product', 'Товар должен совпадать с выбранной строкой заказа.')
        cleaned_data['product'] = candidate['product']

        availability_by_warehouse = {
            int(entry['warehouse_id']): int(entry['available'] or 0)
            for entry in candidate['warehouses']
        }
        if warehouse is None:
            self.add_error('warehouse', 'Выберите склад для резерва.')
            return cleaned_data
        available = int(availability_by_warehouse.get(warehouse.id, 0))
        if available <= 0:
            self.add_error('warehouse', 'На выбранном складе нет свободного остатка под эту позицию.')
        if quantity is not None:
            if quantity > int(candidate['missing_quantity'] or 0):
                self.add_error('quantity', f'Можно зарезервировать не больше {candidate["missing_quantity"]} шт.')
            elif quantity > available:
                self.add_error('quantity', f'На выбранном складе доступно только {available} шт.')
        return cleaned_data


class OperationsOrderDeliveryForm(StyledFormMixin, forms.ModelForm):
    recipient_name = forms.CharField(label='Получатель', max_length=255, required=True)
    recipient_phone = forms.CharField(label='Телефон получателя', max_length=20, required=True)
    delivery_type = forms.ChoiceField(label='Способ доставки', choices=Order.DELIVERY_CHOICES, required=True)
    city_text = forms.CharField(label='Город', max_length=120, required=False)
    address = forms.CharField(label='Адрес / ПВЗ', required=False, widget=forms.Textarea(attrs={'rows': 3}))
    delivery_comment = forms.CharField(
        label='Комментарий для доставки',
        required=False,
        widget=forms.Textarea(attrs={'rows': 4}),
    )

    class Meta:
        model = Order
        fields = (
            'recipient_name',
            'recipient_phone',
            'delivery_type',
            'city_text',
            'address',
            'delivery_comment',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and not self.is_bound:
            self.initial.setdefault('address', self.instance.display_address)

    def clean_recipient_name(self):
        return ' '.join((self.cleaned_data.get('recipient_name') or '').split())

    def clean_recipient_phone(self):
        value = (self.cleaned_data.get('recipient_phone') or '').strip()
        digits = re.sub(r'\D', '', value)
        if len(digits) < 10:
            raise forms.ValidationError('Введите корректный номер телефона получателя.')
        return value

    def clean_delivery_type(self):
        return (self.cleaned_data.get('delivery_type') or '').strip()

    def clean_city_text(self):
        return (self.cleaned_data.get('city_text') or '').strip()

    def clean_address(self):
        return (self.cleaned_data.get('address') or '').strip()

    def clean_delivery_comment(self):
        return (self.cleaned_data.get('delivery_comment') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        delivery_type = cleaned_data.get('delivery_type') or ''
        address = cleaned_data.get('address') or ''
        if delivery_type != Order.DELIVERY_PICKUP and not address:
            self.add_error('address', 'Укажите адрес доставки или адрес ПВЗ.')
        return cleaned_data

    def save(self, commit=True):
        order = super().save(commit=False)
        address = (self.cleaned_data.get('address') or '').strip()
        order.address = address
        order.address_line = address
        if order.delivery_type != Order.DELIVERY_CDEK_PVZ:
            order.cdek_office_snapshot = {}
            order.cdek_tariff_snapshot = {}
        if commit:
            order.save()
        return order


class OperationsShipmentDispatchForm(StyledFormMixin, forms.Form):
    carrier = forms.CharField(label='Служба доставки', max_length=255, required=True)
    tracking_number = forms.CharField(label='Трек-номер', max_length=120, required=True)
    shipped_at = forms.DateField(
        label='Дата отправки',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    comment = forms.CharField(
        required=False,
        label='Комментарий',
        widget=forms.Textarea(attrs={'rows': 4}),
    )

    def __init__(self, *args, shipment=None, **kwargs):
        self.shipment = shipment
        super().__init__(*args, **kwargs)
        if shipment is not None and not self.is_bound:
            initial_shipped_at = timezone.localdate()
            if shipment.shipped_at is not None:
                initial_shipped_at = timezone.localtime(shipment.shipped_at).date()
            self.fields['carrier'].initial = shipment.delivery_provider_name
            self.fields['tracking_number'].initial = shipment.tracking_number
            self.fields['shipped_at'].initial = initial_shipped_at
            self.fields['comment'].initial = shipment.comments
        self.fields['comment'].widget.attrs.update(
            {'placeholder': 'Например: передали в СДЭК, коробка без внешних повреждений'}
        )

    def clean_carrier(self):
        value = ' '.join((self.cleaned_data.get('carrier') or '').split())
        if not value:
            raise forms.ValidationError('Укажите службу доставки.')
        return value

    def clean_tracking_number(self):
        value = (self.cleaned_data.get('tracking_number') or '').strip()
        if not value:
            raise forms.ValidationError('Укажите трек-номер.')
        return value

    def clean_comment(self):
        return (self.cleaned_data.get('comment') or '').strip()


class OperationsPurchaseForm(forms.Form):
    DEFAULT_CURRENCY_CHOICES = [('CNY', 'CNY'), ('RUB', 'RUB')]

    supplier_name = forms.CharField(required=True, label='Поставщик', max_length=255)
    quantity = forms.IntegerField(min_value=1, label='Количество')
    unit_cost = forms.DecimalField(min_value=0, decimal_places=2, label='Цена закупки за шт.')
    currency = forms.ChoiceField(label='Валюта')
    status = forms.ChoiceField(label='Статус закупки', choices=Purchase.STATUS_CHOICES)
    comments = forms.CharField(required=False, label='Комментарий', widget=forms.Textarea(attrs={'rows': 4}))

    def __init__(self, *args, currency_value=None, **kwargs):
        super().__init__(*args, **kwargs)
        input_class = 'w-full rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white'
        select_class = f'{input_class} appearance-none'
        textarea_class = 'w-full rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white resize-y'
        for field_name in ('supplier_name', 'quantity', 'unit_cost'):
            self.fields[field_name].widget.attrs.update({'class': input_class})
        self.fields['currency'].widget.attrs.update({'class': select_class})
        self.fields['status'].widget.attrs.update({'class': select_class})
        self.fields['comments'].widget.attrs.update(
            {'class': textarea_class, 'placeholder': 'Например: запросили счёт у поставщика'}
        )

        allowed_currencies = list(self.DEFAULT_CURRENCY_CHOICES)
        current_currency = (
            currency_value
            or self.initial.get('currency')
            or Purchase._meta.get_field('currency').default
        )
        allowed_codes = {code for code, _label in allowed_currencies}
        if current_currency and current_currency not in allowed_codes:
            allowed_currencies.insert(0, (current_currency, current_currency))
        self.fields['currency'].choices = allowed_currencies

    def clean_supplier_name(self):
        value = (self.cleaned_data.get('supplier_name') or '').strip()
        if not value:
            raise forms.ValidationError('Укажите поставщика.')
        return value

    def clean_currency(self):
        return (self.cleaned_data.get('currency') or '').strip()

    def clean_status(self):
        return (self.cleaned_data.get('status') or '').strip()

    def clean_comments(self):
        return (self.cleaned_data.get('comments') or '').strip()
