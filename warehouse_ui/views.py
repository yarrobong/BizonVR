import json

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from .forms import (
    WarehouseAdjustmentForm,
    WarehouseMatrixFilterForm,
    WarehouseReceiptForm,
    WarehouseTransferForm,
)
from .services import (
    build_drawer_context,
    build_history_context,
    build_matrix_context,
    create_adjustment,
    create_receipt,
    create_transfer,
)


def _is_htmx(request):
    return request.headers.get('HX-Request') == 'true'


def _filter_form(request):
    form = WarehouseMatrixFilterForm(request.GET or None)
    form.is_valid()
    cleaned = dict(form.cleaned_data) if hasattr(form, 'cleaned_data') else {}
    cleaned.setdefault('q', '')
    cleaned.setdefault('warehouses', form.fields['warehouses'].queryset.none())
    cleaned.setdefault('city', None)
    cleaned.setdefault('in_stock', False)
    cleaned.setdefault('out_of_stock', False)
    cleaned.setdefault('has_reserve', False)
    cleaned.setdefault('inbound', False)
    return form, cleaned


def _drawer_forms(context, *, receipt_form=None, adjustment_form=None, transfer_form=None):
    context['receipt_form_obj'] = receipt_form or WarehouseReceiptForm(initial=context['receipt_form'])
    context['adjustment_form_obj'] = adjustment_form or WarehouseAdjustmentForm(initial=context['adjustment_form'])
    context['transfer_form_obj'] = transfer_form or WarehouseTransferForm(initial=context['transfer_form'])
    return context


def _render_drawer(request, sku_key, cleaned_data, *, receipt_form=None, adjustment_form=None, transfer_form=None, toast=None, status=200):
    context = build_drawer_context(sku_key, cleaned_data)
    context = _drawer_forms(
        context,
        receipt_form=receipt_form,
        adjustment_form=adjustment_form,
        transfer_form=transfer_form,
    )
    context['toast'] = toast
    response = render(request, 'admin/warehouse/_drawer.html', context, status=status)
    return response


def _refresh_response_headers(response, sku_key):
    response.headers['HX-Trigger'] = json.dumps({'warehouse:refresh': {'skuKey': sku_key}})
    return response


@staff_member_required
def warehouse_index_view(request):
    filter_form, cleaned_data = _filter_form(request)
    matrix_context = build_matrix_context(cleaned_data, page_number=request.GET.get('page') or 1)
    context = {
        **admin.site.each_context(request),
        'title': 'Склад',
        'filter_form': filter_form,
        'matrix': matrix_context,
        'drawer_open': False,
    }
    return render(request, 'admin/warehouse/index.html', context)


@staff_member_required
def warehouse_matrix_view(request):
    filter_form, cleaned_data = _filter_form(request)
    matrix_context = build_matrix_context(cleaned_data, page_number=request.GET.get('page') or 1)
    context = {
        'filter_form': filter_form,
        'matrix': matrix_context,
        'matrix_oob_summary': True,
    }
    return render(request, 'admin/warehouse/_matrix.html', context)


@staff_member_required
def warehouse_drawer_view(request, sku_key):
    _, cleaned_data = _filter_form(request)
    return _render_drawer(request, sku_key, cleaned_data)


@staff_member_required
def warehouse_history_view(request, sku_key):
    context = build_history_context(sku_key)
    return render(request, 'admin/warehouse/_history.html', context)


def _action_error(form, error):
    if isinstance(error, ValidationError):
        message = '; '.join(error.messages) if hasattr(error, 'messages') else str(error)
    else:
        message = str(error)
    form.add_error(None, message)


@staff_member_required
def warehouse_receipt_action_view(request):
    if request.method != 'POST':
        return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))
    form = WarehouseReceiptForm(request.POST)
    _, cleaned_data = _filter_form(request)
    if form.is_valid():
        try:
            create_receipt(
                warehouse=form.cleaned_data['warehouse'],
                product=form.cleaned_data['product'],
                variant=form.cleaned_data.get('variant'),
                quantity=form.cleaned_data['quantity'],
                unit_cost=form.cleaned_data.get('unit_cost'),
                author=request.user,
                comment=form.cleaned_data.get('comment') or '',
            )
            if _is_htmx(request):
                response = _render_drawer(
                    request,
                    form.cleaned_data['sku_key'],
                    cleaned_data,
                    toast={'level': 'success', 'message': 'Приход записан.'},
                )
                return _refresh_response_headers(response, form.cleaned_data['sku_key'])
            messages.success(request, 'Приход записан.')
        except ValidationError as exc:
            _action_error(form, exc)
    if not form.is_valid() or form.errors:
        if _is_htmx(request):
            return _render_drawer(request, request.POST.get('sku_key', ''), cleaned_data, receipt_form=form, status=400)
        messages.error(request, 'Не удалось записать приход.')
    return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))


@staff_member_required
def warehouse_adjustment_action_view(request):
    if request.method != 'POST':
        return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))
    form = WarehouseAdjustmentForm(request.POST)
    _, cleaned_data = _filter_form(request)
    if form.is_valid():
        try:
            create_adjustment(
                warehouse=form.cleaned_data['warehouse'],
                product=form.cleaned_data['product'],
                variant=form.cleaned_data.get('variant'),
                quantity_delta=form.cleaned_data['quantity_delta'],
                author=request.user,
                comment=form.cleaned_data.get('comment') or '',
            )
            if _is_htmx(request):
                response = _render_drawer(
                    request,
                    form.cleaned_data['sku_key'],
                    cleaned_data,
                    toast={'level': 'success', 'message': 'Корректировка проведена.'},
                )
                return _refresh_response_headers(response, form.cleaned_data['sku_key'])
            messages.success(request, 'Корректировка проведена.')
        except ValidationError as exc:
            _action_error(form, exc)
    if not form.is_valid() or form.errors:
        if _is_htmx(request):
            return _render_drawer(request, request.POST.get('sku_key', ''), cleaned_data, adjustment_form=form, status=400)
        messages.error(request, 'Не удалось провести корректировку.')
    return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))


@staff_member_required
def warehouse_transfer_action_view(request):
    if request.method != 'POST':
        return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))
    form = WarehouseTransferForm(request.POST)
    _, cleaned_data = _filter_form(request)
    if form.is_valid():
        try:
            create_transfer(
                source_warehouse=form.cleaned_data['source_warehouse'],
                target_warehouse=form.cleaned_data['target_warehouse'],
                product=form.cleaned_data['product'],
                variant=form.cleaned_data.get('variant'),
                quantity=form.cleaned_data['quantity'],
                author=request.user,
                comment=form.cleaned_data.get('comment') or '',
            )
            if _is_htmx(request):
                response = _render_drawer(
                    request,
                    form.cleaned_data['sku_key'],
                    cleaned_data,
                    toast={'level': 'success', 'message': 'Перемещение сохранено.'},
                )
                return _refresh_response_headers(response, form.cleaned_data['sku_key'])
            messages.success(request, 'Перемещение сохранено.')
        except ValidationError as exc:
            _action_error(form, exc)
    if not form.is_valid() or form.errors:
        if _is_htmx(request):
            return _render_drawer(request, request.POST.get('sku_key', ''), cleaned_data, transfer_form=form, status=400)
        messages.error(request, 'Не удалось сохранить перемещение.')
    return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))
