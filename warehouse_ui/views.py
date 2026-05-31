import csv
import json

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from .forms import (
    WarehouseAdjustmentForm,
    WarehouseExpenseForm,
    WarehouseMatrixFilterForm,
    WarehouseReceiptForm,
    WarehouseReserveForm,
    WarehouseTransferForm,
    WarehouseWriteOffForm,
)
from .services import (
    build_bulk_rows,
    build_drawer_context,
    build_history_context,
    build_matrix_context,
    create_adjustment,
    create_manual_expense,
    create_receipt,
    create_reserve,
    create_transfer,
    create_writeoff,
)


def _is_htmx(request):
    return request.headers.get('HX-Request') == 'true'


def _warehouse_permissions(user):
    can_manage = user.is_superuser or user.has_perm('manager_portal.add_inventorymovement')
    can_adjust = user.is_superuser
    return {
        'can_manage': can_manage,
        'can_adjust': can_adjust,
        'can_writeoff': can_adjust,
    }


def _guard_permission(request, *, allowed, message):
    if allowed:
        return None
    if _is_htmx(request):
        return HttpResponseForbidden(message)
    messages.error(request, message)
    return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))


def _filter_form(request):
    form = WarehouseMatrixFilterForm(request.GET or None)
    form.is_valid()
    cleaned = dict(form.cleaned_data) if hasattr(form, 'cleaned_data') else {}
    cleaned.setdefault('q', '')
    cleaned.setdefault('city', None)
    cleaned.setdefault('warehouse', None)
    cleaned.setdefault('status', 'all')
    cleaned.setdefault('compact', 'compact')
    cleaned.setdefault('in_stock', False)
    cleaned.setdefault('out_of_stock', False)
    cleaned.setdefault('has_reserve', False)
    cleaned.setdefault('inbound', False)
    cleaned.setdefault('low_stock', False)
    cleaned.setdefault('problematic', False)
    cleaned.setdefault('only_mismatch', False)
    cleaned.setdefault('stale', False)
    return form, cleaned


def _drawer_forms(
    context,
    *,
    receipt_form=None,
    adjustment_form=None,
    transfer_form=None,
    reserve_form=None,
    expense_form=None,
    writeoff_form=None,
):
    context['receipt_form_obj'] = receipt_form or WarehouseReceiptForm(initial=context['receipt_form'])
    context['adjustment_form_obj'] = adjustment_form or WarehouseAdjustmentForm(initial=context['adjustment_form'])
    context['transfer_form_obj'] = transfer_form or WarehouseTransferForm(initial=context['transfer_form'])
    context['reserve_form_obj'] = reserve_form or WarehouseReserveForm(initial=context['reserve_form'])
    context['expense_form_obj'] = expense_form or WarehouseExpenseForm(initial=context['expense_form'])
    context['writeoff_form_obj'] = writeoff_form or WarehouseWriteOffForm(initial=context['writeoff_form'])
    return context


def _render_drawer(
    request,
    sku_key,
    cleaned_data,
    *,
    receipt_form=None,
    adjustment_form=None,
    transfer_form=None,
    reserve_form=None,
    expense_form=None,
    writeoff_form=None,
    status=200,
):
    context = build_drawer_context(sku_key, cleaned_data)
    context = _drawer_forms(
        context,
        receipt_form=receipt_form,
        adjustment_form=adjustment_form,
        transfer_form=transfer_form,
        reserve_form=reserve_form,
        expense_form=expense_form,
        writeoff_form=writeoff_form,
    )
    context['permissions'] = _warehouse_permissions(request.user)
    return render(request, 'admin/warehouse/_drawer.html', context, status=status)


def _trigger_headers(response, *, sku_key=None, toast=None):
    payload = {}
    if sku_key:
        payload['warehouse:refresh'] = {'skuKey': sku_key}
    if toast:
        payload['warehouse:notify'] = toast
    if payload:
        response.headers['HX-Trigger'] = json.dumps(payload)
    return response


def _action_error(form, error):
    if isinstance(error, ValidationError):
        message = '; '.join(error.messages) if hasattr(error, 'messages') else str(error)
    else:
        message = str(error)
    form.add_error(None, message)


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
        'permissions': _warehouse_permissions(request.user),
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
        'permissions': _warehouse_permissions(request.user),
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


def _post_or_redirect(request):
    if request.method != 'POST':
        return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))
    return None


@staff_member_required
def warehouse_receipt_action_view(request):
    redirect = _post_or_redirect(request)
    if redirect:
        return redirect
    denied = _guard_permission(request, allowed=_warehouse_permissions(request.user)['can_manage'], message='Недостаточно прав для прихода.')
    if denied:
        return denied
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
                response = _render_drawer(request, form.cleaned_data['sku_key'], cleaned_data)
                return _trigger_headers(
                    response,
                    sku_key=form.cleaned_data['sku_key'],
                    toast={'level': 'success', 'message': 'Приход записан.'},
                )
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
    redirect = _post_or_redirect(request)
    if redirect:
        return redirect
    denied = _guard_permission(request, allowed=_warehouse_permissions(request.user)['can_adjust'], message='Корректировки доступны только с расширенными правами.')
    if denied:
        return denied
    form = WarehouseAdjustmentForm(request.POST)
    _, cleaned_data = _filter_form(request)
    if form.is_valid():
        try:
            result = create_adjustment(
                warehouse=form.cleaned_data['warehouse'],
                product=form.cleaned_data['product'],
                variant=form.cleaned_data.get('variant'),
                actual_quantity=form.cleaned_data['actual_quantity'],
                reason=form.cleaned_data['reason'],
                author=request.user,
                comment=form.cleaned_data.get('comment') or '',
            )
            if _is_htmx(request):
                response = _render_drawer(request, form.cleaned_data['sku_key'], cleaned_data)
                return _trigger_headers(
                    response,
                    sku_key=form.cleaned_data['sku_key'],
                    toast={
                        'level': 'success',
                        'message': f'Корректировка проведена: {result["before"]} -> {result["after"]} ({result["delta"]:+d}).',
                    },
                )
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
    redirect = _post_or_redirect(request)
    if redirect:
        return redirect
    denied = _guard_permission(request, allowed=_warehouse_permissions(request.user)['can_manage'], message='Недостаточно прав для перемещений.')
    if denied:
        return denied
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
                response = _render_drawer(request, form.cleaned_data['sku_key'], cleaned_data)
                return _trigger_headers(
                    response,
                    sku_key=form.cleaned_data['sku_key'],
                    toast={'level': 'success', 'message': 'Перемещение сохранено.'},
                )
            messages.success(request, 'Перемещение сохранено.')
        except ValidationError as exc:
            _action_error(form, exc)
    if not form.is_valid() or form.errors:
        if _is_htmx(request):
            return _render_drawer(request, request.POST.get('sku_key', ''), cleaned_data, transfer_form=form, status=400)
        messages.error(request, 'Не удалось сохранить перемещение.')
    return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))


@staff_member_required
def warehouse_reserve_action_view(request):
    redirect = _post_or_redirect(request)
    if redirect:
        return redirect
    denied = _guard_permission(request, allowed=_warehouse_permissions(request.user)['can_manage'], message='Недостаточно прав для резервирования.')
    if denied:
        return denied
    form = WarehouseReserveForm(request.POST)
    _, cleaned_data = _filter_form(request)
    if form.is_valid():
        try:
            reservation = create_reserve(
                warehouse=form.cleaned_data['warehouse'],
                product=form.cleaned_data['product'],
                variant=form.cleaned_data.get('variant'),
                quantity=form.cleaned_data['quantity'],
                order=form.cleaned_data.get('order'),
                deal=form.cleaned_data.get('deal'),
                author=request.user,
                comment=form.cleaned_data.get('comment') or '',
            )
            if _is_htmx(request):
                response = _render_drawer(request, form.cleaned_data['sku_key'], cleaned_data)
                return _trigger_headers(
                    response,
                    sku_key=form.cleaned_data['sku_key'],
                    toast={'level': 'success', 'message': f'Резерв {reservation.code or reservation.pk} создан.'},
                )
            messages.success(request, 'Резерв создан.')
        except (ValidationError, ValueError) as exc:
            _action_error(form, exc)
    if not form.is_valid() or form.errors:
        if _is_htmx(request):
            return _render_drawer(request, request.POST.get('sku_key', ''), cleaned_data, reserve_form=form, status=400)
        messages.error(request, 'Не удалось создать резерв.')
    return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))


@staff_member_required
def warehouse_expense_action_view(request):
    redirect = _post_or_redirect(request)
    if redirect:
        return redirect
    denied = _guard_permission(request, allowed=_warehouse_permissions(request.user)['can_manage'], message='Недостаточно прав для расхода.')
    if denied:
        return denied
    form = WarehouseExpenseForm(request.POST)
    _, cleaned_data = _filter_form(request)
    if form.is_valid():
        try:
            create_manual_expense(
                warehouse=form.cleaned_data['warehouse'],
                product=form.cleaned_data['product'],
                variant=form.cleaned_data.get('variant'),
                quantity=form.cleaned_data['quantity'],
                order=form.cleaned_data.get('order'),
                deal=form.cleaned_data.get('deal'),
                author=request.user,
                comment=form.cleaned_data['comment'],
            )
            if _is_htmx(request):
                response = _render_drawer(request, form.cleaned_data['sku_key'], cleaned_data)
                return _trigger_headers(
                    response,
                    sku_key=form.cleaned_data['sku_key'],
                    toast={'level': 'success', 'message': 'Ручной расход записан.'},
                )
            messages.success(request, 'Ручной расход записан.')
        except ValidationError as exc:
            _action_error(form, exc)
    if not form.is_valid() or form.errors:
        if _is_htmx(request):
            return _render_drawer(request, request.POST.get('sku_key', ''), cleaned_data, expense_form=form, status=400)
        messages.error(request, 'Не удалось записать расход.')
    return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))


@staff_member_required
def warehouse_writeoff_action_view(request):
    redirect = _post_or_redirect(request)
    if redirect:
        return redirect
    denied = _guard_permission(request, allowed=_warehouse_permissions(request.user)['can_writeoff'], message='Списание доступно только суперпользователю.')
    if denied:
        return denied
    form = WarehouseWriteOffForm(request.POST)
    _, cleaned_data = _filter_form(request)
    if form.is_valid():
        try:
            create_writeoff(
                warehouse=form.cleaned_data['warehouse'],
                product=form.cleaned_data['product'],
                variant=form.cleaned_data.get('variant'),
                quantity=form.cleaned_data['quantity'],
                reason=form.cleaned_data['reason'],
                author=request.user,
                comment=form.cleaned_data['comment'],
            )
            if _is_htmx(request):
                response = _render_drawer(request, form.cleaned_data['sku_key'], cleaned_data)
                return _trigger_headers(
                    response,
                    sku_key=form.cleaned_data['sku_key'],
                    toast={'level': 'success', 'message': 'Списание проведено.'},
                )
            messages.success(request, 'Списание проведено.')
        except ValidationError as exc:
            _action_error(form, exc)
    if not form.is_valid() or form.errors:
        if _is_htmx(request):
            return _render_drawer(request, request.POST.get('sku_key', ''), cleaned_data, writeoff_form=form, status=400)
        messages.error(request, 'Не удалось провести списание.')
    return HttpResponseRedirect(reverse('admin:warehouse_ui_index'))


@staff_member_required
def warehouse_export_view(request):
    _, cleaned_data = _filter_form(request)
    payload = build_bulk_rows(cleaned_data, selected_sku_keys=request.GET.getlist('sku'))
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="warehouse-export.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['SKU ключ', 'Товар', 'Вариант', 'SKU', 'Итого', 'Доступно', 'Резерв', 'В пути'])
    for row in payload['rows']:
        writer.writerow(
            [
                row['sku_key'],
                row['product_name'],
                row['variant_name'],
                row['sku'],
                row['totals']['on_hand'],
                row['totals']['available'],
                row['totals']['reserved'],
                row['totals']['inbound'],
            ]
        )
    return response


@staff_member_required
def warehouse_print_view(request):
    _, cleaned_data = _filter_form(request)
    payload = build_bulk_rows(cleaned_data, selected_sku_keys=request.GET.getlist('sku'))
    context = {
        **admin.site.each_context(request),
        'title': 'Складской список',
        'print_payload': payload,
    }
    return render(request, 'admin/warehouse/print_list.html', context)
