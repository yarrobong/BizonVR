from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.forms.models import model_to_dict
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.text import slugify

from accounts.models import BalanceTransaction, Profile, normalize_phone
from catalog.models import (
    CatalogSection,
    Category,
    City,
    PickupPoint,
    Product,
    ProductStock,
    ProductTag,
    ProductVariant,
)
from orders.models import Order, OrderItem

from .access import FINANCE_ADMIN_GROUP, FINANCE_OPERATOR_GROUP
from .models import (
    ContractCompanyProfile,
    ContractDocument,
    ContractTemplate,
    FinanceDeal,
    FinanceDealType,
    FinanceExpense,
    FinanceExpenseCategory,
    FinancePayout,
    LegacyImportBatch,
    LegacyImportConflict,
    LegacyImportRecord,
    ManagerClient,
    ManagerDeal,
    ManagerDealParticipant,
    ManagerPersonAlias,
    Warehouse,
)
from .services import ensure_initial_deal_activity, recompute_deal_workflow


User = get_user_model()


LEGACY_CONTRACT_TYPE_MAP = {
    'Договор оказания услуг': ContractTemplate.DOC_TYPE_CONTRACT,
    'Договор поставки': ContractTemplate.DOC_TYPE_CONTRACT,
}
LEGACY_CONTRACT_STATUS_MAP = {
    'Черновик': ContractDocument.STATUS_DRAFT,
}
LEGACY_INVOICE_STATUS_MAP = {
    'Не оплачен': ContractDocument.STATUS_SENT,
}


@dataclass(frozen=True)
class PlannedTarget:
    model_label: str
    source_model: str
    source_pk: str


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, 'isoformat') and callable(value.isoformat):
        try:
            return value.isoformat()
        except TypeError:
            return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _row_payload(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, sqlite3.Row):
        return {key: _json_safe(row[key]) for key in row.keys()}
    if isinstance(row, dict):
        return {str(key): _json_safe(value) for key, value in row.items()}
    return {'value': _json_safe(row)}


def _load_json(value: Any, default: Any):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _parse_legacy_date(value: Any):
    if not value:
        return None
    value = str(value).strip()
    parsed = parse_date(value)
    if parsed:
        return parsed
    try:
        return datetime.strptime(value, '%d.%m.%Y').date()
    except ValueError:
        return None


def _parse_legacy_datetime(value: Any):
    if not value:
        return None
    if isinstance(value, datetime):
        return timezone.make_aware(value, timezone.get_default_timezone()) if timezone.is_naive(value) else value
    value = str(value).strip()
    parsed = parse_datetime(value.replace('Z', '+00:00'))
    if parsed:
        return timezone.make_aware(parsed, timezone.get_default_timezone()) if timezone.is_naive(parsed) else parsed
    parsed_date = _parse_legacy_date(value)
    if parsed_date:
        return datetime.combine(parsed_date, time.min, tzinfo=dt_timezone.utc)
    return None


def _parse_decimal(value: Any, *, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    raw_value = str(value).strip().replace(' ', '')
    if not raw_value:
        return default
    raw_value = raw_value.replace(',', '.')
    return Decimal(raw_value)


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open('r', encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        return [{str(key).strip(): (value or '').strip() for key, value in row.items()} for row in reader]


def _load_json_file(path: Path) -> Any:
    with path.open('r', encoding='utf-8') as source:
        return json.load(source)


def _parse_tabular_date(value: Any):
    if not value:
        return None
    raw_value = str(value).strip()
    parsed = _parse_legacy_date(raw_value)
    if parsed:
        return parsed
    try:
        return datetime.strptime(raw_value, '%d.%m').date().replace(year=2026)
    except ValueError:
        return None


def _aware_datetime_for_date(value, *, hour=12):
    if value is None:
        return timezone.now()
    return timezone.make_aware(datetime.combine(value, time(hour=hour, minute=0)))


def _normalize_delivery_method(provider_name: str):
    raw_value = (provider_name or '').strip().lower()
    if not raw_value:
        return ManagerDeal.DELIVERY_OTHER_TRANSPORT
    if 'самовывоз' in raw_value:
        return ManagerDeal.DELIVERY_PICKUP
    if 'сдэк' in raw_value:
        return ManagerDeal.DELIVERY_CDEK_PVZ
    if 'яндекс' in raw_value:
        return ManagerDeal.DELIVERY_CITY
    if 'почта' in raw_value:
        return ManagerDeal.DELIVERY_OTHER_TRANSPORT
    if '5post' in raw_value:
        return ManagerDeal.DELIVERY_OTHER_TRANSPORT
    if 'авито' in raw_value:
        return ManagerDeal.DELIVERY_OTHER_TRANSPORT
    return ManagerDeal.DELIVERY_OTHER_TRANSPORT


def _placeholder_client_name(*, product_name: str, order_date) -> str:
    formatted_date = order_date.strftime('%d.%m.%Y') if order_date else 'без даты'
    return f'Avito · {product_name} · {formatted_date}'


def _is_business_customer(name: str) -> bool:
    normalized = (name or '').strip().lower()
    return normalized.startswith('ооо') or normalized.startswith('ип') or ' llc' in normalized or normalized.startswith('ooo ')


def _product_alias_entry(alias_map: dict[str, Any], product_name: str) -> dict[str, Any]:
    raw_entry = alias_map.get(product_name) or {}
    if isinstance(raw_entry, str):
        return {'product_slug': raw_entry}
    if isinstance(raw_entry, dict):
        return raw_entry
    return {}


def _people_alias_entry(alias_map: dict[str, Any], display_name: str) -> dict[str, Any]:
    raw_entry = alias_map.get(display_name) or {}
    if isinstance(raw_entry, str):
        return {'slug': raw_entry}
    if isinstance(raw_entry, dict):
        return raw_entry
    return {}


def _is_blank(value: Any) -> bool:
    return value is None or value == '' or value == [] or value == {}


def _merge_blank_fields(instance, incoming: dict[str, Any], fields: tuple[str, ...]):
    changed: list[str] = []
    conflicts: dict[str, Any] = {}
    for field_name in fields:
        if field_name not in incoming:
            continue
        new_value = incoming[field_name]
        if _is_blank(new_value):
            continue
        current_value = getattr(instance, field_name)
        if _is_blank(current_value):
            setattr(instance, field_name, new_value)
            changed.append(field_name)
            continue
        if _json_safe(current_value) != _json_safe(new_value):
            conflicts[field_name] = {
                'current': _json_safe(current_value),
                'incoming': _json_safe(new_value),
            }
    return changed, conflicts


def _model_snapshot(instance, fields: tuple[str, ...]):
    return {field_name: _json_safe(getattr(instance, field_name)) for field_name in fields}


def _update_timestamps(model_cls, pk, *, created_at=None, updated_at=None):
    updates = {}
    if created_at:
        updates['created_at'] = created_at
    if updated_at:
        updates['updated_at'] = updated_at
    if updates:
        model_cls.objects.filter(pk=pk).update(**updates)


class LegacyImportTracker:
    def __init__(self, *, source_system: str, source_ref: str, dry_run: bool):
        self.source_system = source_system
        self.dry_run = dry_run
        self.batch = LegacyImportBatch.objects.create(
            source_system=source_system,
            source_ref=source_ref,
            dry_run=dry_run,
            status=LegacyImportBatch.STATUS_RUNNING,
        )
        self.counters = Counter()

    def has_record(self, source_model: str, source_pk: Any):
        return LegacyImportRecord.objects.filter(
            source_system=self.source_system,
            source_model=source_model,
            source_pk=str(source_pk),
        ).first()

    def get_target_from_record(self, source_model: str, source_pk: Any, model_cls):
        record = self.has_record(source_model, source_pk)
        if not record:
            return None
        self.counters[LegacyImportRecord.STATUS_MATCHED] += 1
        if record.target_pk:
            target = model_cls.objects.filter(pk=record.target_pk).first()
            if target:
                return target
        return PlannedTarget(model_label=model_cls._meta.label_lower, source_model=source_model, source_pk=str(source_pk))

    def mark(self, source_model: str, source_pk: Any, *, status: str, target=None, source_payload=None, details=None):
        self.counters[status] += 1
        if self.dry_run:
            return
        LegacyImportRecord.objects.update_or_create(
            source_system=self.source_system,
            source_model=source_model,
            source_pk=str(source_pk),
            defaults={
                'batch': self.batch,
                'status': status,
                'target_model': getattr(getattr(target, '_meta', None), 'label_lower', ''),
                'target_pk': getattr(target, 'pk', None),
                'source_payload': _json_safe(source_payload or {}),
                'details': _json_safe(details or {}),
            },
        )

    def conflict(self, source_model: str, source_pk: Any, *, conflict_type: str, message: str, source_payload=None, target=None, target_payload=None):
        self.counters['conflicts'] += 1
        LegacyImportConflict.objects.create(
            batch=self.batch,
            source_system=self.source_system,
            source_model=source_model,
            source_pk=str(source_pk),
            target_model=getattr(getattr(target, '_meta', None), 'label_lower', ''),
            target_pk=getattr(target, 'pk', None),
            conflict_type=conflict_type,
            message=message,
            source_payload=_json_safe(source_payload or {}),
            target_payload=_json_safe(target_payload or {}),
        )

    def finish(self, *, status: str, error_text: str = ''):
        self.batch.status = status
        self.batch.error_text = error_text
        self.batch.summary = {key: int(value) for key, value in sorted(self.counters.items())}
        self.batch.finished_at = timezone.now()
        self.batch.save(update_fields=['status', 'error_text', 'summary', 'finished_at'])
        return self.batch


def _ensure_finance_groups():
    operator_group, _ = Group.objects.get_or_create(name=FINANCE_OPERATOR_GROUP)
    admin_group, _ = Group.objects.get_or_create(name=FINANCE_ADMIN_GROUP)
    return {
        'operator': operator_group,
        'admin': admin_group,
    }


def _safe_import_row(
    tracker: LegacyImportTracker,
    *,
    source_model: str,
    source_pk: Any,
    model_cls,
    lookup: dict[str, Any],
    defaults: dict[str, Any],
    merge_fields: tuple[str, ...],
    source_payload: dict[str, Any],
    duplicate_signature: dict[str, Any] | None = None,
    duplicate_message: str = '',
    created_at=None,
    updated_at=None,
):
    existing_from_record = tracker.get_target_from_record(source_model, source_pk, model_cls)
    if existing_from_record:
        return existing_from_record

    target = model_cls.objects.filter(**lookup).first()
    if not target and duplicate_signature:
        duplicate = model_cls.objects.filter(**duplicate_signature).first()
        if duplicate:
            tracker.conflict(
                source_model,
                source_pk,
                conflict_type='duplicate_signature',
                message=duplicate_message or 'Найдена существующая запись по сигнатуре.',
                source_payload=source_payload,
                target=duplicate,
                target_payload=_json_safe(model_to_dict(duplicate)),
            )
            return None
    if not target:
        if tracker.dry_run:
            tracker.mark(source_model, source_pk, status=LegacyImportRecord.STATUS_CREATED, source_payload=source_payload)
            return PlannedTarget(model_label=model_cls._meta.label_lower, source_model=source_model, source_pk=str(source_pk))
        target = model_cls.objects.create(**defaults)
        _update_timestamps(model_cls, target.pk, created_at=created_at, updated_at=updated_at)
        tracker.mark(
            source_model,
            source_pk,
            status=LegacyImportRecord.STATUS_CREATED,
            target=target,
            source_payload=source_payload,
        )
        return target

    changed, conflicts = _merge_blank_fields(target, defaults, merge_fields)
    if conflicts:
        tracker.conflict(
            source_model,
            source_pk,
            conflict_type='field_mismatch',
            message='Legacy-данные расходятся с текущей записью.',
            source_payload=source_payload,
            target=target,
            target_payload=conflicts,
        )
        return target
    if changed:
        if tracker.dry_run:
            tracker.mark(
                source_model,
                source_pk,
                status=LegacyImportRecord.STATUS_ENRICHED,
                source_payload=source_payload,
                details={'changed_fields': changed},
            )
            return target
        target.save(update_fields=changed)
        tracker.mark(
            source_model,
            source_pk,
            status=LegacyImportRecord.STATUS_ENRICHED,
            target=target,
            source_payload=source_payload,
            details={'changed_fields': changed},
        )
        return target

    tracker.mark(source_model, source_pk, status=LegacyImportRecord.STATUS_MATCHED, target=target, source_payload=source_payload)
    return target


def _docuflow_company_profile_defaults(raw_profile: dict[str, Any], *, name_fallback: str, active_profile_id: str | None):
    external_id = raw_profile.get('id') or name_fallback
    return {
        'external_id': external_id,
        'name': raw_profile.get('companyName') or raw_profile.get('fullName') or name_fallback,
        'legal_type': raw_profile.get('legalType') or ContractCompanyProfile.LEGAL_TYPE_OTHER,
        'company_name': raw_profile.get('companyName') or raw_profile.get('fullName') or name_fallback,
        'inn': raw_profile.get('inn', ''),
        'kpp': raw_profile.get('kpp', ''),
        'ogrn': raw_profile.get('ogrn', ''),
        'ogrnip': raw_profile.get('ogrnip', ''),
        'director_genitive': raw_profile.get('directorGenitive', ''),
        'legal_address': raw_profile.get('legalAddress', ''),
        'email': raw_profile.get('email', ''),
        'phone': raw_profile.get('phone', ''),
        'bank_name': raw_profile.get('bankName', ''),
        'checking_account': raw_profile.get('checkingAccount', ''),
        'correspondent_account': raw_profile.get('correspondentAccount', ''),
        'bik': raw_profile.get('bik', ''),
        'card_number': raw_profile.get('cardNumber', ''),
        'sbp_phone': raw_profile.get('sbpPhone', ''),
        'passport_series': raw_profile.get('passportSeries', ''),
        'passport_number': raw_profile.get('passportNumber', ''),
        'passport_issued_by': raw_profile.get('passportIssuedBy', ''),
        'passport_issued_date': _parse_legacy_date(raw_profile.get('passportIssuedDate')),
        'passport_department_code': raw_profile.get('passportDepartmentCode', ''),
        'registration_address': raw_profile.get('registrationAddress', ''),
        'residence_address': raw_profile.get('residenceAddress', ''),
        'bank_accounts': raw_profile.get('bankAccounts') or [],
        'legacy_payload': raw_profile,
        'is_active': external_id == active_profile_id or (not active_profile_id and name_fallback.endswith('1')),
    }


def import_legacy_docuflow(source: str | Path, *, dry_run: bool):
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f'Legacy DocuFlow DB not found: {source_path}')

    tracker = LegacyImportTracker(
        source_system=LegacyImportBatch.SOURCE_DOCUFLOW,
        source_ref=str(source_path),
        dry_run=dry_run,
    )
    try:
        conn = sqlite3.connect(f'file:{source_path}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute('SELECT payload_json FROM app_settings WHERE id = 1')
        settings_row = cur.fetchone()
        settings_payload = _load_json(settings_row['payload_json'], {}) if settings_row else {}
        raw_profiles = settings_payload.get('companyProfiles') or []
        active_profile_id = settings_payload.get('activeCompanyProfileId')
        if not raw_profiles and settings_payload:
            raw_profiles = [settings_payload]

        profile_map: dict[str, Any] = {}
        for index, raw_profile in enumerate(raw_profiles, start=1):
            defaults = _docuflow_company_profile_defaults(
                raw_profile,
                name_fallback=f'legacy-profile-{index}',
                active_profile_id=active_profile_id,
            )
            external_id = defaults['external_id']
            profile = _safe_import_row(
                tracker,
                source_model='app_settings.companyProfiles',
                source_pk=external_id,
                model_cls=ContractCompanyProfile,
                lookup={'external_id': external_id},
                defaults=defaults,
                merge_fields=(
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
                    'bank_accounts',
                    'legacy_payload',
                ),
                source_payload=raw_profile,
            )
            profile_map[external_id] = profile

        cur.execute('SELECT * FROM templates ORDER BY sort_order, id')
        template_map: dict[str, Any] = {}
        for row in cur.fetchall():
            payload = _row_payload(row)
            defaults = {
                'external_id': row['id'],
                'sort_order': row['sort_order'] or 0,
                'name': row['name'],
                'document_type': LEGACY_CONTRACT_TYPE_MAP.get(row['type'], ContractTemplate.DOC_TYPE_OTHER),
                'version': row['version'] or '1.0',
                'description': f'Импортировано из legacy DocuFlow ({row["type"]})',
                'is_active': bool(row['is_active']),
                'content_html': row['content_html'] or '',
                'css_text': row['css_text'] or '',
                'variables_schema': _load_json(row['variables_json'], []),
            }
            template = _safe_import_row(
                tracker,
                source_model='templates',
                source_pk=row['id'],
                model_cls=ContractTemplate,
                lookup={'external_id': row['id']},
                defaults=defaults,
                merge_fields=(
                    'sort_order',
                    'name',
                    'document_type',
                    'version',
                    'description',
                    'content_html',
                    'css_text',
                    'variables_schema',
                ),
                source_payload=payload,
                created_at=_parse_legacy_datetime(row['updated_at']),
                updated_at=_parse_legacy_datetime(row['updated_at']),
            )
            template_map[row['id']] = template

        cur.execute('SELECT * FROM counterparties')
        counterparties = {row['id']: dict(row) for row in cur.fetchall()}

        cur.execute('SELECT * FROM invoices')
        invoices = {row['id']: dict(row) for row in cur.fetchall()}
        invoices_in_contracts: set[str] = set()

        cur.execute('SELECT * FROM contracts ORDER BY sort_order, id')
        for row in cur.fetchall():
            payload = _row_payload(row)
            counterparty_data = _load_json(row['counterparty_json'], {})
            contract_data = _load_json(row['contract_data_json'], {})
            invoice_payload = invoices.get(row['invoice_id'])
            if row['invoice_id']:
                invoices_in_contracts.add(row['invoice_id'])
            issue_dt = _parse_legacy_datetime(row['created_at']) or timezone.now()
            company_profile = profile_map.get(row['supplier_profile_id']) or next(iter(profile_map.values()), None)
            defaults = {
                'external_id': row['id'],
                'source': ContractDocument.SOURCE_IMPORTED,
                'sort_order': row['sort_order'] or 0,
                'number': row['number'] or '',
                'title': row['title'] or '',
                'document_type': LEGACY_CONTRACT_TYPE_MAP.get(row['type'], ContractTemplate.DOC_TYPE_CONTRACT),
                'status': LEGACY_CONTRACT_STATUS_MAP.get(row['status'], ContractDocument.STATUS_DRAFT),
                'template': template_map.get(row['template_id']) if not isinstance(template_map.get(row['template_id']), PlannedTarget) else None,
                'company_profile': company_profile if not isinstance(company_profile, PlannedTarget) else None,
                'issue_date': issue_dt.date(),
                'amount': Decimal(str(row['amount'])) if row['amount'] is not None else None,
                'payment_terms': row['payment_terms'],
                'include_delivery': bool(row['include_delivery']),
                'delivery_date': _parse_legacy_date(row['delivery_date']),
                'vat_rate': row['vat_rate'] or 'none',
                'vat_mode': row['vat_mode'] or 'included',
                'markup_percent': Decimal(str(row['markup_percent'] if row['markup_percent'] is not None else 6)),
                'markup_mode': row['markup_mode'] or 'per_item',
                'markup_calc_mode': row['markup_calc_mode'] or 'simple',
                'subject': contract_data.get('subject', ''),
                'counterparty_name': counterparty_data.get('name', ''),
                'counterparty_email': counterparty_data.get('email', ''),
                'counterparty_phone': counterparty_data.get('phone', ''),
                'counterparty_inn': counterparty_data.get('inn', ''),
                'counterparty_kpp': counterparty_data.get('kpp', ''),
                'counterparty_ogrn': counterparty_data.get('ogrn', ''),
                'counterparty_ogrnip': counterparty_data.get('ogrnip', ''),
                'counterparty_address': counterparty_data.get('address', ''),
                'counterparty_data': counterparty_data,
                'document_data': contract_data,
                'invoice_data': invoice_payload or {},
                'html_snapshot': row['html_snapshot'] or '',
                'snapshot_css': row['snapshot_css'] or '',
                'notes': 'Импортировано из legacy DocuFlow',
            }
            _safe_import_row(
                tracker,
                source_model='contracts',
                source_pk=row['id'],
                model_cls=ContractDocument,
                lookup={'external_id': row['id']},
                defaults=defaults,
                merge_fields=(
                    'sort_order',
                    'number',
                    'title',
                    'document_type',
                    'status',
                    'template',
                    'company_profile',
                    'issue_date',
                    'amount',
                    'payment_terms',
                    'include_delivery',
                    'delivery_date',
                    'vat_rate',
                    'vat_mode',
                    'markup_percent',
                    'markup_mode',
                    'markup_calc_mode',
                    'subject',
                    'counterparty_name',
                    'counterparty_email',
                    'counterparty_phone',
                    'counterparty_inn',
                    'counterparty_kpp',
                    'counterparty_ogrn',
                    'counterparty_ogrnip',
                    'counterparty_address',
                    'counterparty_data',
                    'document_data',
                    'invoice_data',
                    'html_snapshot',
                    'snapshot_css',
                    'notes',
                ),
                source_payload=payload,
                duplicate_signature={'number': row['number']} if row['number'] else None,
                duplicate_message='Документ с тем же номером уже существует без provenance.',
                created_at=issue_dt,
                updated_at=issue_dt,
            )

        for invoice_id, row in invoices.items():
            if invoice_id in invoices_in_contracts:
                continue
            payload = _row_payload(row)
            counterparty_data = counterparties.get(row['counterparty_id'], {})
            issue_date = _parse_legacy_date(row['date']) or timezone.localdate()
            issue_dt = datetime.combine(issue_date, time.min, tzinfo=dt_timezone.utc)
            defaults = {
                'external_id': invoice_id,
                'source': ContractDocument.SOURCE_IMPORTED,
                'sort_order': row['sort_order'] or 0,
                'number': row['number'] or '',
                'title': f'Счет {row["number"]}',
                'document_type': ContractTemplate.DOC_TYPE_INVOICE,
                'status': LEGACY_INVOICE_STATUS_MAP.get(row['status'], ContractDocument.STATUS_DRAFT),
                'company_profile': profile_map.get(row['supplier_profile_id']) if not isinstance(profile_map.get(row['supplier_profile_id']), PlannedTarget) else None,
                'issue_date': issue_date,
                'amount': Decimal(str(row['amount'])) if row['amount'] is not None else None,
                'currency': row['currency'] or ContractDocument.CURRENCY_RUB,
                'vat_rate': row['vat_rate'] or 'none',
                'vat_mode': row['vat_mode'] or 'included',
                'subject': 'Импортированный счет из legacy DocuFlow',
                'counterparty_name': counterparty_data.get('name', ''),
                'counterparty_email': counterparty_data.get('email', ''),
                'counterparty_phone': counterparty_data.get('phone', ''),
                'counterparty_inn': counterparty_data.get('inn', ''),
                'counterparty_kpp': counterparty_data.get('kpp', ''),
                'counterparty_ogrn': counterparty_data.get('ogrn', ''),
                'counterparty_ogrnip': counterparty_data.get('ogrnip', ''),
                'counterparty_address': counterparty_data.get('address', ''),
                'counterparty_data': counterparty_data,
                'invoice_data': {
                    'items': _load_json(row['items_json'], []),
                    'commission_percent': row['commission_percent'],
                    'payment_due_date': row['payment_due_date'],
                },
                'notes': 'Импортировано из legacy DocuFlow',
            }
            _safe_import_row(
                tracker,
                source_model='invoices',
                source_pk=invoice_id,
                model_cls=ContractDocument,
                lookup={'external_id': invoice_id},
                defaults=defaults,
                merge_fields=(
                    'sort_order',
                    'number',
                    'title',
                    'document_type',
                    'status',
                    'company_profile',
                    'issue_date',
                    'amount',
                    'currency',
                    'vat_rate',
                    'vat_mode',
                    'subject',
                    'counterparty_name',
                    'counterparty_email',
                    'counterparty_phone',
                    'counterparty_inn',
                    'counterparty_kpp',
                    'counterparty_ogrn',
                    'counterparty_ogrnip',
                    'counterparty_address',
                    'counterparty_data',
                    'invoice_data',
                    'notes',
                ),
                source_payload=payload,
                duplicate_signature={'number': row['number']} if row['number'] else None,
                duplicate_message='Счет с тем же номером уже существует без provenance.',
                created_at=issue_dt,
                updated_at=issue_dt,
            )
        conn.close()
        return tracker.finish(status=LegacyImportBatch.STATUS_COMPLETED)
    except Exception as exc:
        return tracker.finish(status=LegacyImportBatch.STATUS_FAILED, error_text=str(exc))


def _finance_user_defaults(source_row: dict[str, Any], group_map: dict[str, Group]):
    legacy_username = (source_row.get('username') or '').strip() or f'user-{source_row["id"]}'
    username_stub = slugify(legacy_username) or f'user-{source_row["id"]}'
    django_username = f'legacy-finance-{source_row["id"]}-{username_stub}'[:150]
    return {
        'username': django_username,
        'email': '',
        'first_name': legacy_username[:150],
        'last_name': '',
        'is_staff': False,
        'is_active': False,
        'is_superuser': False,
        'group': group_map['admin' if source_row.get('role') == 'admin' else 'operator'],
    }


def import_legacy_business_finance(source_dsn: str, *, dry_run: bool):
    tracker = LegacyImportTracker(
        source_system=LegacyImportBatch.SOURCE_BUSINESS_FINANCE,
        source_ref=source_dsn,
        dry_run=dry_run,
    )
    groups = _ensure_finance_groups()
    finance_groups = {
        'admin': groups['admin'],
        'operator': groups['operator'],
    }
    try:
        conn = psycopg2.connect(source_dsn)
        cur = conn.cursor(cursor_factory=RealDictCursor)

        finance_user_map: dict[int, Any] = {}
        cur.execute('SELECT id, username, password_hash, role, created_at FROM users ORDER BY id')
        for row in cur.fetchall():
            payload = _row_payload(row)
            source_pk = row['id']
            existing = tracker.get_target_from_record('users', source_pk, User)
            if existing:
                finance_user_map[source_pk] = existing
                continue
            defaults = _finance_user_defaults(row, finance_groups)
            target = User.objects.filter(username=defaults['username']).first()
            if not target:
                if dry_run:
                    tracker.mark('users', source_pk, status=LegacyImportRecord.STATUS_CREATED, source_payload=payload)
                    finance_user_map[source_pk] = PlannedTarget(model_label=User._meta.label_lower, source_model='users', source_pk=str(source_pk))
                    continue
                target = User.objects.create(
                    username=defaults['username'],
                    email=defaults['email'],
                    first_name=defaults['first_name'],
                    last_name=defaults['last_name'],
                    is_staff=defaults['is_staff'],
                    is_active=defaults['is_active'],
                    is_superuser=defaults['is_superuser'],
                )
                target.set_unusable_password()
                target.save(update_fields=['password'])
                target.groups.add(defaults['group'])
                Profile.objects.get_or_create(user=target, defaults={'contact_name': defaults['first_name']})
                if row.get('created_at'):
                    User.objects.filter(pk=target.pk).update(date_joined=_parse_legacy_datetime(row['created_at']) or timezone.now())
                tracker.mark(
                    'users',
                    source_pk,
                    status=LegacyImportRecord.STATUS_CREATED,
                    target=target,
                    source_payload=payload,
                    details={
                        'legacy_username': row.get('username', ''),
                        'legacy_role': row.get('role', ''),
                        'activation': 'requires_admin_contact_assignment_and_password_reset',
                    },
                )
                finance_user_map[source_pk] = target
                continue

            target_group = defaults['group']
            changed = False
            if not dry_run and not target.groups.filter(pk=target_group.pk).exists():
                target.groups.add(target_group)
                changed = True
            if not target.first_name and defaults['first_name']:
                if not dry_run:
                    target.first_name = defaults['first_name']
                    target.save(update_fields=['first_name'])
                changed = True
            status = LegacyImportRecord.STATUS_ENRICHED if changed else LegacyImportRecord.STATUS_MATCHED
            tracker.mark(
                'users',
                source_pk,
                status=status,
                target=target,
                source_payload=payload,
                details={
                    'legacy_username': row.get('username', ''),
                    'legacy_role': row.get('role', ''),
                },
            )
            finance_user_map[source_pk] = target

        deal_type_map: dict[str, Any] = {}
        cur.execute('SELECT id, name, partner_share FROM deal_types ORDER BY id')
        for row in cur.fetchall():
            payload = _row_payload(row)
            defaults = {
                'name': row['name'],
                'partner_share': Decimal(str(row['partner_share'] or 0)),
                'is_active': True,
            }
            target = _safe_import_row(
                tracker,
                source_model='deal_types',
                source_pk=row['id'],
                model_cls=FinanceDealType,
                lookup={'name': row['name']},
                defaults=defaults,
                merge_fields=(),
                source_payload=payload,
            )
            deal_type_map[row['name']] = target

        category_map: dict[tuple[str, str], Any] = {}
        for table_name, expense_side in (
            ('our_expense_categories', FinanceExpenseCategory.SIDE_OURS),
            ('partner_expense_categories', FinanceExpenseCategory.SIDE_PARTNER),
        ):
            cur.execute(f'SELECT id, name FROM {table_name} ORDER BY id')
            for row in cur.fetchall():
                payload = _row_payload(row)
                defaults = {
                    'expense_side': expense_side,
                    'name': row['name'],
                    'is_active': True,
                }
                target = _safe_import_row(
                    tracker,
                    source_model=table_name,
                    source_pk=row['id'],
                    model_cls=FinanceExpenseCategory,
                    lookup={'expense_side': expense_side, 'name': row['name']},
                    defaults=defaults,
                    merge_fields=(),
                    source_payload=payload,
                )
                category_map[(expense_side, row['name'])] = target

        finance_deal_map: dict[int, Any] = {}
        cur.execute(
            'SELECT id, date, contract_number, deal_type, revenue, cost_price, direct_expenses, manager_bonus, margin, partner_share, comment FROM deals ORDER BY id'
        )
        for row in cur.fetchall():
            payload = _row_payload(row)
            deal_type = deal_type_map.get(row['deal_type']) or FinanceDealType.objects.filter(name=row['deal_type']).first()
            if not deal_type:
                tracker.conflict(
                    'deals',
                    row['id'],
                    conflict_type='missing_deal_type',
                    message=f'Не найден тип сделки "{row["deal_type"]}".',
                    source_payload=payload,
                )
                continue
            defaults = {
                'date': row['date'] or timezone.localdate(),
                'contract_number': row['contract_number'] or '',
                'deal_type': deal_type if not isinstance(deal_type, PlannedTarget) else None,
                'revenue': Decimal(str(row['revenue'] or 0)),
                'cost_price': Decimal(str(row['cost_price'] or 0)),
                'direct_expenses': Decimal(str(row['direct_expenses'] or 0)),
                'manager_bonus': Decimal(str(row['manager_bonus'] or 0)),
                'margin': Decimal(str(row['margin'] or 0)),
                'partner_share_amount': Decimal(str(row['partner_share'] or 0)),
                'comment': row['comment'] or '',
            }
            target = _safe_import_row(
                tracker,
                source_model='deals',
                source_pk=row['id'],
                model_cls=FinanceDeal,
                lookup={
                    'date': defaults['date'],
                    'contract_number': defaults['contract_number'],
                    'deal_type': defaults['deal_type'],
                    'revenue': defaults['revenue'],
                    'cost_price': defaults['cost_price'],
                    'direct_expenses': defaults['direct_expenses'],
                    'manager_bonus': defaults['manager_bonus'],
                    'comment': defaults['comment'],
                } if defaults['deal_type'] else {'pk': -1},
                defaults=defaults,
                merge_fields=(),
                source_payload=payload,
            )
            finance_deal_map[row['id']] = target

        cur.execute(
            'SELECT id, expense_side, date, category, amount, who_paid, partner_expense_share, comment, deal_id FROM expenses ORDER BY id'
        )
        for row in cur.fetchall():
            payload = _row_payload(row)
            category = category_map.get((row['expense_side'], row['category'])) or FinanceExpenseCategory.objects.filter(
                expense_side=row['expense_side'],
                name=row['category'],
            ).first()
            if not category:
                tracker.conflict(
                    'expenses',
                    row['id'],
                    conflict_type='missing_expense_category',
                    message=f'Не найдена категория расхода "{row["category"]}" ({row["expense_side"]}).',
                    source_payload=payload,
                )
                continue
            deal = None
            if row.get('deal_id'):
                deal = finance_deal_map.get(row['deal_id']) or tracker.get_target_from_record('deals', row['deal_id'], FinanceDeal)
                if not deal:
                    tracker.conflict(
                        'expenses',
                        row['id'],
                        conflict_type='missing_finance_deal',
                        message=f'Не найдена сделка {row["deal_id"]} для расхода.',
                        source_payload=payload,
                    )
                    continue
            defaults = {
                'expense_side': row['expense_side'],
                'date': row['date'] or timezone.localdate(),
                'category': category if not isinstance(category, PlannedTarget) else None,
                'amount': Decimal(str(row['amount'] or 0)),
                'who_paid': row['who_paid'] or '',
                'partner_expense_share': Decimal(str(row['partner_expense_share'] or 0)),
                'comment': row['comment'] or '',
                'deal': deal if not isinstance(deal, PlannedTarget) else None,
            }
            _safe_import_row(
                tracker,
                source_model='expenses',
                source_pk=row['id'],
                model_cls=FinanceExpense,
                lookup={
                    'expense_side': defaults['expense_side'],
                    'date': defaults['date'],
                    'category': defaults['category'],
                    'amount': defaults['amount'],
                    'who_paid': defaults['who_paid'],
                    'comment': defaults['comment'],
                    'deal': defaults['deal'],
                } if defaults['category'] else {'pk': -1},
                defaults=defaults,
                merge_fields=(),
                source_payload=payload,
            )

        cur.execute('SELECT id, date, amount, comment FROM payouts ORDER BY id')
        for row in cur.fetchall():
            payload = _row_payload(row)
            defaults = {
                'date': row['date'] or timezone.localdate(),
                'amount': Decimal(str(row['amount'] or 0)),
                'comment': row['comment'] or '',
            }
            _safe_import_row(
                tracker,
                source_model='payouts',
                source_pk=row['id'],
                model_cls=FinancePayout,
                lookup=defaults,
                defaults=defaults,
                merge_fields=(),
                source_payload=payload,
            )

        cur.execute("SELECT COUNT(*) AS count FROM information_schema.tables WHERE table_name = 'zenmoney_tokens'")
        if cur.fetchone()['count']:
            cur.execute('SELECT COUNT(*) AS count FROM zenmoney_tokens')
            tracker.counters[LegacyImportRecord.STATUS_SKIPPED] += int(cur.fetchone()['count'] or 0)

        conn.close()
        return tracker.finish(status=LegacyImportBatch.STATUS_COMPLETED)
    except Exception as exc:
        return tracker.finish(status=LegacyImportBatch.STATUS_FAILED, error_text=str(exc))


def _sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    )
    return cur.fetchone() is not None


def import_legacy_site_sqlite(source: str | Path, *, dry_run: bool):
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f'Legacy site SQLite DB not found: {source_path}')

    tracker = LegacyImportTracker(
        source_system=LegacyImportBatch.SOURCE_SITE_SQLITE,
        source_ref=str(source_path),
        dry_run=dry_run,
    )
    try:
        conn = sqlite3.connect(f'file:{source_path}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row

        user_map: dict[int, Any] = {}
        if _sqlite_table_exists(conn, 'auth_user'):
            for row in conn.execute('SELECT * FROM auth_user ORDER BY id'):
                payload = _row_payload(row)
                source_pk = row['id']
                existing = tracker.get_target_from_record('auth_user', source_pk, User)
                if existing:
                    user_map[source_pk] = existing
                    continue
                target = User.objects.filter(username=row['username']).first()
                if not target:
                    if dry_run:
                        tracker.mark('auth_user', source_pk, status=LegacyImportRecord.STATUS_CREATED, source_payload=payload)
                        user_map[source_pk] = PlannedTarget(model_label=User._meta.label_lower, source_model='auth_user', source_pk=str(source_pk))
                        continue
                    target = User.objects.create(
                        username=row['username'],
                        email=row['email'] or '',
                        first_name=row['first_name'] or '',
                        last_name=row['last_name'] or '',
                        is_staff=bool(row['is_staff']),
                        is_active=bool(row['is_active']),
                        is_superuser=bool(row['is_superuser']),
                    )
                    User.objects.filter(pk=target.pk).update(
                        password=row['password'],
                        last_login=_parse_legacy_datetime(row['last_login']),
                        date_joined=_parse_legacy_datetime(row['date_joined']) or timezone.now(),
                    )
                    tracker.mark('auth_user', source_pk, status=LegacyImportRecord.STATUS_CREATED, target=target, source_payload=payload)
                    user_map[source_pk] = target
                    continue
                changed, conflicts = _merge_blank_fields(
                    target,
                    {
                        'email': row['email'] or '',
                        'first_name': row['first_name'] or '',
                        'last_name': row['last_name'] or '',
                    },
                    ('email', 'first_name', 'last_name'),
                )
                if conflicts:
                    tracker.conflict(
                        'auth_user',
                        source_pk,
                        conflict_type='field_mismatch',
                        message='Legacy user расходится с текущим auth_user.',
                        source_payload=payload,
                        target=target,
                        target_payload=conflicts,
                    )
                elif changed:
                    if not dry_run:
                        target.save(update_fields=changed)
                    tracker.mark(
                        'auth_user',
                        source_pk,
                        status=LegacyImportRecord.STATUS_ENRICHED,
                        target=target,
                        source_payload=payload,
                        details={'changed_fields': changed},
                    )
                else:
                    tracker.mark('auth_user', source_pk, status=LegacyImportRecord.STATUS_MATCHED, target=target, source_payload=payload)
                user_map[source_pk] = target

        section_map: dict[int, Any] = {}
        if _sqlite_table_exists(conn, 'catalog_catalogsection'):
            for row in conn.execute('SELECT * FROM catalog_catalogsection ORDER BY id'):
                payload = _row_payload(row)
                defaults = {
                    'name': row['name'],
                    'slug': row['slug'],
                    'order': row['order'] or 0,
                }
                target = _safe_import_row(
                    tracker,
                    source_model='catalog_catalogsection',
                    source_pk=row['id'],
                    model_cls=CatalogSection,
                    lookup={'slug': row['slug']},
                    defaults=defaults,
                    merge_fields=('name',),
                    source_payload=payload,
                )
                section_map[row['id']] = target

        category_map: dict[int, Any] = {}
        if _sqlite_table_exists(conn, 'catalog_category'):
            for row in conn.execute('SELECT * FROM catalog_category ORDER BY id'):
                payload = _row_payload(row)
                section = section_map.get(row['section_id']) if row['section_id'] else None
                defaults = {
                    'name': row['name'],
                    'slug': row['slug'],
                    'section': section if not isinstance(section, PlannedTarget) else None,
                }
                target = _safe_import_row(
                    tracker,
                    source_model='catalog_category',
                    source_pk=row['id'],
                    model_cls=Category,
                    lookup={'slug': row['slug']},
                    defaults=defaults,
                    merge_fields=('name', 'section'),
                    source_payload=payload,
                )
                category_map[row['id']] = target

        tag_map: dict[int, Any] = {}
        if _sqlite_table_exists(conn, 'catalog_producttag'):
            for row in conn.execute('SELECT * FROM catalog_producttag ORDER BY id'):
                payload = _row_payload(row)
                defaults = {
                    'name': row['name'],
                    'slug': row['slug'],
                    'order': row['order'] or 0,
                }
                target = _safe_import_row(
                    tracker,
                    source_model='catalog_producttag',
                    source_pk=row['id'],
                    model_cls=ProductTag,
                    lookup={'slug': row['slug']},
                    defaults=defaults,
                    merge_fields=('name',),
                    source_payload=payload,
                )
                tag_map[row['id']] = target

        city_map: dict[int, Any] = {}
        if _sqlite_table_exists(conn, 'catalog_city'):
            for row in conn.execute('SELECT * FROM catalog_city ORDER BY id'):
                payload = _row_payload(row)
                defaults = {
                    'name': row['name'],
                    'slug': row['slug'],
                    'order': row['order'] or 0,
                }
                target = _safe_import_row(
                    tracker,
                    source_model='catalog_city',
                    source_pk=row['id'],
                    model_cls=City,
                    lookup={'slug': row['slug']},
                    defaults=defaults,
                    merge_fields=('name',),
                    source_payload=payload,
                )
                city_map[row['id']] = target

        pickup_map: dict[int, Any] = {}
        if _sqlite_table_exists(conn, 'catalog_pickuppoint'):
            for row in conn.execute('SELECT * FROM catalog_pickuppoint ORDER BY id'):
                payload = _row_payload(row)
                city = city_map.get(row['city_id'])
                if row['city_id'] and not city:
                    tracker.conflict(
                        'catalog_pickuppoint',
                        row['id'],
                        conflict_type='missing_city',
                        message=f'Не найден город {row["city_id"]} для ПВЗ.',
                        source_payload=payload,
                    )
                    continue
                defaults = {
                    'city': city if not isinstance(city, PlannedTarget) else None,
                    'name': row['name'],
                    'address': row['address'] or '',
                    'order': row['order'] or 0,
                }
                target = _safe_import_row(
                    tracker,
                    source_model='catalog_pickuppoint',
                    source_pk=row['id'],
                    model_cls=PickupPoint,
                    lookup={
                        'city': defaults['city'],
                        'name': row['name'],
                    } if defaults['city'] else {'pk': -1},
                    defaults=defaults,
                    merge_fields=('address',),
                    source_payload=payload,
                )
                pickup_map[row['id']] = target

        product_map: dict[int, Any] = {}
        if _sqlite_table_exists(conn, 'catalog_product'):
            for row in conn.execute('SELECT * FROM catalog_product ORDER BY id'):
                payload = _row_payload(row)
                category = category_map.get(row['category_id'])
                if row['category_id'] and not category:
                    tracker.conflict(
                        'catalog_product',
                        row['id'],
                        conflict_type='missing_category',
                        message=f'Не найдена категория {row["category_id"]} для товара.',
                        source_payload=payload,
                    )
                    continue
                defaults = {
                    'category': category if not isinstance(category, PlannedTarget) else None,
                    'name': row['name'],
                    'slug': row['slug'],
                    'description': row['description'] or '',
                    'price': Decimal(str(row['price'] or 0)),
                    'image': row['image'] or None,
                    'is_active': bool(row['is_active']),
                    'allow_order_on_request': bool(row['allow_order_on_request']),
                    'option_label': row['option_label'] or '',
                }
                target = _safe_import_row(
                    tracker,
                    source_model='catalog_product',
                    source_pk=row['id'],
                    model_cls=Product,
                    lookup={'slug': row['slug']},
                    defaults=defaults,
                    merge_fields=('name', 'description', 'image', 'option_label'),
                    source_payload=payload,
                    created_at=_parse_legacy_datetime(row['created_at']),
                    updated_at=_parse_legacy_datetime(row['updated_at']),
                )
                product_map[row['id']] = target

        variant_map: dict[int, Any] = {}
        if _sqlite_table_exists(conn, 'catalog_productvariant'):
            for row in conn.execute('SELECT * FROM catalog_productvariant ORDER BY id'):
                payload = _row_payload(row)
                product = product_map.get(row['product_id'])
                if not product:
                    tracker.conflict(
                        'catalog_productvariant',
                        row['id'],
                        conflict_type='missing_product',
                        message=f'Не найден товар {row["product_id"]} для варианта.',
                        source_payload=payload,
                    )
                    continue
                defaults = {
                    'product': product if not isinstance(product, PlannedTarget) else None,
                    'name': row['name'],
                    'image': row['image'] or None,
                    'price_override': Decimal(str(row['price_override'])) if row['price_override'] is not None else None,
                    'order': row['order'] or 0,
                }
                target = _safe_import_row(
                    tracker,
                    source_model='catalog_productvariant',
                    source_pk=row['id'],
                    model_cls=ProductVariant,
                    lookup={'product': defaults['product'], 'name': row['name']} if defaults['product'] else {'pk': -1},
                    defaults=defaults,
                    merge_fields=('image', 'price_override'),
                    source_payload=payload,
                )
                variant_map[row['id']] = target

        if _sqlite_table_exists(conn, 'catalog_product_tags'):
            for row in conn.execute('SELECT * FROM catalog_product_tags ORDER BY id'):
                payload = _row_payload(row)
                product = product_map.get(row['product_id'])
                tag = tag_map.get(row['producttag_id'])
                if not product or not tag:
                    tracker.conflict(
                        'catalog_product_tags',
                        row['id'],
                        conflict_type='missing_m2m_dependency',
                        message='Не найден товар или тег для M2M связи.',
                        source_payload=payload,
                    )
                    continue
                if not isinstance(product, PlannedTarget) and not isinstance(tag, PlannedTarget) and not product.tags.filter(pk=tag.pk).exists():
                    if not dry_run:
                        product.tags.add(tag)
                    tracker.mark('catalog_product_tags', row['id'], status=LegacyImportRecord.STATUS_CREATED, source_payload=payload, target=product)
                else:
                    tracker.mark('catalog_product_tags', row['id'], status=LegacyImportRecord.STATUS_MATCHED, source_payload=payload, target=product if not isinstance(product, PlannedTarget) else None)

        if _sqlite_table_exists(conn, 'catalog_productstock'):
            for row in conn.execute('SELECT * FROM catalog_productstock ORDER BY id'):
                payload = _row_payload(row)
                product = product_map.get(row['product_id'])
                pickup_point = pickup_map.get(row['pickup_point_id'])
                if not product or not pickup_point:
                    tracker.conflict(
                        'catalog_productstock',
                        row['id'],
                        conflict_type='missing_stock_dependency',
                        message='Не найден товар или ПВЗ для остатка.',
                        source_payload=payload,
                    )
                    continue
                defaults = {
                    'product': product if not isinstance(product, PlannedTarget) else None,
                    'pickup_point': pickup_point if not isinstance(pickup_point, PlannedTarget) else None,
                    'variant': None,
                    'quantity': row['quantity'] or 0,
                }
                _safe_import_row(
                    tracker,
                    source_model='catalog_productstock',
                    source_pk=row['id'],
                    model_cls=ProductStock,
                    lookup={
                        'product': defaults['product'],
                        'pickup_point': defaults['pickup_point'],
                        'variant__isnull': True,
                    } if defaults['product'] and defaults['pickup_point'] else {'pk': -1},
                    defaults=defaults,
                    merge_fields=(),
                    source_payload=payload,
                )

        order_map: dict[int, Any] = {}
        if _sqlite_table_exists(conn, 'orders_order'):
            for row in conn.execute('SELECT * FROM orders_order ORDER BY id'):
                payload = _row_payload(row)
                user = user_map.get(row['user_id']) if row['user_id'] else None
                created_at = _parse_legacy_datetime(row['created_at']) or timezone.now()
                updated_at = _parse_legacy_datetime(row['updated_at']) or created_at
                defaults = {
                    'user': user if not isinstance(user, PlannedTarget) else None,
                    'status': row['status'] or Order.STATUS_NEW,
                    'total': Decimal(str(row['total'] or 0)),
                    'phone': row['phone'] or '',
                    'email': row['email'] or '',
                    'first_name': row['first_name'] or '',
                    'last_name': row['last_name'] or '',
                    'address': row['address'] or '',
                    'comment': row['comment'] or '',
                    'delivery_type': Order.DELIVERY_COURIER if (row['address'] or '').strip() else Order.DELIVERY_PICKUP,
                    'payment_status': Order.PAYMENT_STATUS_UNPAID,
                }
                target = _safe_import_row(
                    tracker,
                    source_model='orders_order',
                    source_pk=row['id'],
                    model_cls=Order,
                    lookup={
                        'created_at': created_at,
                        'phone': defaults['phone'],
                        'email': defaults['email'],
                        'total': defaults['total'],
                    },
                    defaults=defaults,
                    merge_fields=('address', 'comment', 'first_name', 'last_name'),
                    source_payload=payload,
                    created_at=created_at,
                    updated_at=updated_at,
                )
                order_map[row['id']] = target

        if _sqlite_table_exists(conn, 'orders_orderitem'):
            for row in conn.execute('SELECT * FROM orders_orderitem ORDER BY id'):
                payload = _row_payload(row)
                order = order_map.get(row['order_id'])
                product = product_map.get(row['product_id'])
                if not order or not product:
                    tracker.conflict(
                        'orders_orderitem',
                        row['id'],
                        conflict_type='missing_orderitem_dependency',
                        message='Не найден заказ или товар для строки заказа.',
                        source_payload=payload,
                    )
                    continue
                defaults = {
                    'order': order if not isinstance(order, PlannedTarget) else None,
                    'product': product if not isinstance(product, PlannedTarget) else None,
                    'variant': None,
                    'quantity': row['quantity'] or 0,
                    'price': Decimal(str(row['price'] or 0)),
                    'variant_name': '',
                    'is_on_request': False,
                    'condition': OrderItem.CONDITION_NEW,
                }
                _safe_import_row(
                    tracker,
                    source_model='orders_orderitem',
                    source_pk=row['id'],
                    model_cls=OrderItem,
                    lookup={
                        'order': defaults['order'],
                        'product': defaults['product'],
                        'variant__isnull': True,
                        'quantity': defaults['quantity'],
                        'price': defaults['price'],
                    } if defaults['order'] and defaults['product'] else {'pk': -1},
                    defaults=defaults,
                    merge_fields=(),
                    source_payload=payload,
                )

        if _sqlite_table_exists(conn, 'accounts_profile'):
            for row in conn.execute('SELECT * FROM accounts_profile ORDER BY id'):
                payload = _row_payload(row)
                user = user_map.get(row['user_id'])
                if not user:
                    tracker.conflict(
                        'accounts_profile',
                        row['id'],
                        conflict_type='missing_user',
                        message=f'Не найден auth_user {row["user_id"]} для профиля.',
                        source_payload=payload,
                    )
                    continue
                phone = normalize_phone(row['phone'] or '')
                target = Profile.objects.filter(phone=phone).first() if phone else None
                if target and not isinstance(user, PlannedTarget) and target.user_id != user.pk:
                    tracker.conflict(
                        'accounts_profile',
                        row['id'],
                        conflict_type='profile_phone_taken',
                        message=f'Телефон {phone} уже привязан к другому пользователю.',
                        source_payload=payload,
                        target=target,
                        target_payload=_json_safe(model_to_dict(target)),
                    )
                    continue
                defaults = {
                    'user': user if not isinstance(user, PlannedTarget) else None,
                    'phone': phone or None,
                    'balance': Decimal(str(row['balance'] or 0)),
                    'contact_name': row['contact_name'] or '',
                    'privacy_agreed_at': _parse_legacy_datetime(row['privacy_agreed_at']),
                }
                lookup = {'user': defaults['user']} if defaults['user'] else {'pk': -1}
                if phone and not target:
                    lookup = {'phone': phone}
                _safe_import_row(
                    tracker,
                    source_model='accounts_profile',
                    source_pk=row['id'],
                    model_cls=Profile,
                    lookup=lookup,
                    defaults=defaults,
                    merge_fields=('phone', 'contact_name', 'privacy_agreed_at'),
                    source_payload=payload,
                )

        if _sqlite_table_exists(conn, 'accounts_balancetransaction'):
            for row in conn.execute('SELECT * FROM accounts_balancetransaction ORDER BY id'):
                payload = _row_payload(row)
                user = user_map.get(row['user_id'])
                order = order_map.get(row['order_id']) if row['order_id'] else None
                if not user:
                    tracker.conflict(
                        'accounts_balancetransaction',
                        row['id'],
                        conflict_type='missing_user',
                        message=f'Не найден auth_user {row["user_id"]} для операции баланса.',
                        source_payload=payload,
                    )
                    continue
                created_at = _parse_legacy_datetime(row['created_at']) or timezone.now()
                defaults = {
                    'user': user if not isinstance(user, PlannedTarget) else None,
                    'kind': row['kind'],
                    'amount': Decimal(str(row['amount'] or 0)),
                    'order': order if order and not isinstance(order, PlannedTarget) else None,
                }
                target = _safe_import_row(
                    tracker,
                    source_model='accounts_balancetransaction',
                    source_pk=row['id'],
                    model_cls=BalanceTransaction,
                    lookup={
                        'user': defaults['user'],
                        'kind': defaults['kind'],
                        'amount': defaults['amount'],
                        'order': defaults['order'],
                        'created_at': created_at,
                    } if defaults['user'] else {'pk': -1},
                    defaults=defaults,
                    merge_fields=(),
                    source_payload=payload,
                    created_at=created_at,
                )
                if target and not isinstance(target, PlannedTarget) and not dry_run:
                    BalanceTransaction.objects.filter(pk=target.pk).update(created_at=created_at)

        conn.close()
        return tracker.finish(status=LegacyImportBatch.STATUS_COMPLETED)
    except Exception as exc:
        return tracker.finish(status=LegacyImportBatch.STATUS_FAILED, error_text=str(exc))


TABULAR_FINANCE_TYPE_NAME = 'Импорт табличных продаж'
TABULAR_IMPORT_WAREHOUSE_NAME = 'Импорт: не указан'
TABULAR_IMPORT_CATEGORY_NAME = 'Импортированные товары'


def _require_files(source_dir: Path, *file_names: str) -> dict[str, Path]:
    paths = {}
    missing = []
    for file_name in file_names:
        path = source_dir / file_name
        if not path.exists():
            missing.append(file_name)
        else:
            paths[file_name] = path
    if missing:
        raise FileNotFoundError(f'Не найдены файлы импорта: {", ".join(sorted(missing))}')
    return paths


def _ensure_import_category(*, dry_run: bool):
    category = Category.objects.filter(name=TABULAR_IMPORT_CATEGORY_NAME).order_by('id').first()
    if category is not None or dry_run:
        return category
    return Category.objects.create(name=TABULAR_IMPORT_CATEGORY_NAME)


def _ensure_import_warehouse(*, dry_run: bool):
    warehouse = Warehouse.objects.filter(name=TABULAR_IMPORT_WAREHOUSE_NAME).order_by('id').first()
    if warehouse is not None or dry_run:
        return warehouse
    return Warehouse.objects.create(name=TABULAR_IMPORT_WAREHOUSE_NAME, is_active=True)


def _tabular_import_finance_type(*, dry_run: bool):
    finance_type = FinanceDealType.objects.filter(name=TABULAR_FINANCE_TYPE_NAME).order_by('id').first()
    if finance_type is not None or dry_run:
        return finance_type
    return FinanceDealType.objects.create(name=TABULAR_FINANCE_TYPE_NAME, partner_share=Decimal('1.0'))


def _resolve_person_alias(*, tracker: LegacyImportTracker, alias_map: dict[str, Any], display_name: str):
    display_name = (display_name or '').strip()
    if not display_name:
        return None
    config = _people_alias_entry(alias_map, display_name)
    username = (config.get('username') or '').strip()
    user = None
    if username:
        user = User.objects.filter(username=username).first()
        if user is None:
            tracker.conflict(
                'people_aliases',
                display_name,
                conflict_type='missing_user',
                message=f'Не найден пользователь {username} для алиаса {display_name}.',
                source_payload=config,
            )
    slug = (config.get('slug') or slugify(display_name, allow_unicode=True) or display_name.lower()).strip('-')[:255]
    is_active = bool(config.get('is_active', True))
    return _safe_import_row(
        tracker,
        source_model='people_aliases',
        source_pk=display_name,
        model_cls=ManagerPersonAlias,
        lookup={'display_name': display_name},
        defaults={
            'display_name': display_name,
            'slug': slug,
            'user': user,
            'is_active': is_active,
        },
        merge_fields=('slug', 'user', 'is_active'),
        source_payload={'display_name': display_name, **config},
    )


def _resolve_product(*, tracker: LegacyImportTracker, alias_map: dict[str, Any], product_name: str, sale_price: Decimal):
    product_name = (product_name or '').strip()
    if not product_name:
        raise ValueError('Не указано название товара.')
    config = _product_alias_entry(alias_map, product_name)
    product = None
    if config.get('product_slug'):
        product = Product.objects.filter(slug=config['product_slug']).first()
        if product is None:
            tracker.conflict(
                'product_aliases',
                product_name,
                conflict_type='missing_product',
                message=f'Не найден товар со slug {config["product_slug"]} для алиаса {product_name}.',
                source_payload=config,
            )
    elif config.get('product_id'):
        product = Product.objects.filter(pk=config['product_id']).first()
        if product is None:
            tracker.conflict(
                'product_aliases',
                product_name,
                conflict_type='missing_product',
                message=f'Не найден товар с id {config["product_id"]} для алиаса {product_name}.',
                source_payload=config,
            )
    if product is None:
        product = Product.objects.filter(name__iexact=product_name).order_by('id').first()
    if product is not None:
        return product
    category = _ensure_import_category(dry_run=tracker.dry_run)
    placeholder_payload = {'product_name': product_name, 'price': str(sale_price), **config}
    if tracker.dry_run:
        tracker.mark(
            'placeholder_products',
            product_name,
            status=LegacyImportRecord.STATUS_CREATED,
            source_payload=placeholder_payload,
        )
        return PlannedTarget(model_label=Product._meta.label_lower, source_model='placeholder_products', source_pk=product_name)
    if category is None:
        raise ValueError('Не удалось определить категорию для импортированного placeholder-товара.')
    return _safe_import_row(
        tracker,
        source_model='placeholder_products',
        source_pk=product_name,
        model_cls=Product,
        lookup={'name': product_name},
        defaults={
            'category': category,
            'name': product_name,
            'price': sale_price,
            'is_active': False,
            'allow_order_on_request': False,
            'description': 'Создано импортом табличных продаж.',
        },
        merge_fields=('price', 'description'),
        source_payload=placeholder_payload,
    )


def _find_or_create_client(*, name: str, phone: str = '', email: str = '', dry_run: bool = False):
    lookup = {'name__iexact': name}
    if phone:
        client = ManagerClient.objects.filter(phone=phone).order_by('id').first()
        if client is not None:
            return client
    client = ManagerClient.objects.filter(**lookup).order_by('id').first()
    if client is not None or dry_run:
        return client
    return ManagerClient.objects.create(name=name, phone=phone, email=email, status=ManagerClient.STATUS_ACTIVE)


def _order_status_for_import(*, payment_status: str, shipment_status: str):
    if shipment_status == 'delivered':
        return Order.STATUS_DONE
    if shipment_status == 'shipped':
        return Order.STATUS_SHIPPING
    if payment_status == Order.PAYMENT_STATUS_PAID:
        return Order.STATUS_CONFIRMED
    return Order.STATUS_NEW


def _deal_status_for_import(*, deal_type: str, payment_status: str, shipment_status: str):
    if shipment_status == 'delivered':
        return ManagerDeal.DEAL_STATUS_COMPLETED if deal_type != ManagerDeal.DEAL_AVITO else ManagerDeal.DEAL_STATUS_RECEIVED_BY_CUSTOMER
    if shipment_status == 'shipped':
        return ManagerDeal.DEAL_STATUS_SHIPPED
    if deal_type == ManagerDeal.DEAL_AVITO:
        return ManagerDeal.DEAL_STATUS_NEW
    return ManagerDeal.DEAL_STATUS_PAID if payment_status == Order.PAYMENT_STATUS_PAID else ManagerDeal.DEAL_STATUS_AWAITING_PAYMENT


def _set_model_timestamps(instance, *, created_at):
    model_cls = instance.__class__
    model_cls.objects.filter(pk=instance.pk).update(created_at=created_at, updated_at=created_at)
    instance.refresh_from_db()


def _create_import_order(
    *,
    order_date,
    customer_name: str,
    customer_phone: str,
    delivery_method: str,
    delivery_address: str,
    delivery_provider_name: str,
    payment_status: str,
    order_status: str,
    total: Decimal,
):
    order = Order.objects.create(
        user=None,
        status=order_status,
        total=total,
        payment_method=Order.PAYMENT_METHOD_MANAGER_PAYMENT,
        payment_status=payment_status,
        delivery_type=delivery_method,
        phone=customer_phone,
        first_name=customer_name[:150],
        recipient_name=customer_name[:255],
        recipient_phone=customer_phone[:20],
        city_text='',
        address=delivery_address,
        address_line=delivery_address,
        delivery_comment=delivery_provider_name,
        comment='Импортировано из tabular sales.',
    )
    _set_model_timestamps(order, created_at=_aware_datetime_for_date(order_date))
    return order


def _create_finance_deal_for_import(
    *,
    deal: ManagerDeal,
    finance_type: FinanceDealType,
    order_date,
    revenue: Decimal,
    cost_price: Decimal,
    direct_expenses: Decimal,
    created_by=None,
):
    finance_deal = FinanceDeal.objects.create(
        manager_deal=deal,
        responsible_manager=deal.responsible_manager,
        date=order_date,
        contract_number=deal.customer_name or deal.code or f'Сделка #{deal.order_id}',
        deal_type=finance_type,
        payment_method=deal.order.payment_method,
        payment_state=deal.order.payment_status,
        revenue=revenue,
        cost_price=cost_price,
        direct_expenses=direct_expenses,
        expected_margin_snapshot=revenue - cost_price - direct_expenses,
        comment='Создано импортом табличных продаж.',
        created_by=created_by,
    )
    FinanceDeal.objects.filter(pk=finance_deal.pk).update(created_at=_aware_datetime_for_date(order_date), updated_at=_aware_datetime_for_date(order_date))
    finance_deal.refresh_from_db()
    return finance_deal


def _participant_lookup(*, deal, role, person_alias, order_item=None):
    lookup = {
        'manager_deal': deal,
        'person_alias': person_alias,
        'role': role,
    }
    if order_item is None:
        lookup['order_item__isnull'] = True
    else:
        lookup['order_item'] = order_item
    return lookup


def _create_participant(
    tracker: LegacyImportTracker,
    *,
    source_model: str,
    source_pk: str,
    deal,
    role: str,
    person_alias,
    order_item=None,
    amount: Decimal | None = None,
    quantity_basis: int | None = None,
    note: str = '',
    source_payload: dict[str, Any] | None = None,
):
    if person_alias is None:
        return None
    if tracker.dry_run:
        tracker.mark(source_model, source_pk, status=LegacyImportRecord.STATUS_CREATED, source_payload=source_payload or {})
        return PlannedTarget(
            model_label=ManagerDealParticipant._meta.label_lower,
            source_model=source_model,
            source_pk=source_pk,
        )
    return _safe_import_row(
        tracker,
        source_model=source_model,
        source_pk=source_pk,
        model_cls=ManagerDealParticipant,
        lookup=_participant_lookup(deal=deal, role=role, person_alias=person_alias, order_item=order_item),
        defaults={
            'manager_deal': deal,
            'order_item': order_item,
            'person_alias': person_alias,
            'role': role,
            'amount': amount,
            'quantity_basis': quantity_basis,
            'note': note,
            'source_payload': source_payload or {},
        },
        merge_fields=('amount', 'quantity_basis', 'note', 'source_payload'),
        source_payload=source_payload or {},
    )


def _create_avito_deal(
    tracker: LegacyImportTracker,
    *,
    row: dict[str, str],
    alias_products: dict[str, Any],
    alias_people: dict[str, Any],
    finance_type: FinanceDealType | None,
):
    external_key = row.get('external_key') or ''
    if not external_key:
        raise ValueError('В avito_deals.csv отсутствует external_key.')
    if tracker.has_record('tabular_avito_deal', external_key):
        tracker.get_target_from_record('tabular_avito_deal', external_key, ManagerDeal)
        return
    order_date = _parse_tabular_date(row.get('date'))
    if order_date is None:
        tracker.conflict(
            'tabular_avito_deal',
            external_key,
            conflict_type='missing_date',
            message='Для Avito-сделки не удалось распарсить дату.',
            source_payload=row,
        )
        return
    quantity = int(row.get('quantity') or 1)
    cost_price_unit = _parse_decimal(row.get('cost_price_unit'), default=Decimal('0')) or Decimal('0')
    sale_price_unit = _parse_decimal(row.get('sale_price_unit'), default=Decimal('0')) or Decimal('0')
    expense_total = _parse_decimal(row.get('expense_total'), default=Decimal('0')) or Decimal('0')
    product = _resolve_product(
        tracker=tracker,
        alias_map=alias_products,
        product_name=row.get('product_name') or '',
        sale_price=sale_price_unit,
    )
    answered_alias = _resolve_person_alias(tracker=tracker, alias_map=alias_people, display_name=row.get('answered_by') or '')
    shipped_alias = _resolve_person_alias(tracker=tracker, alias_map=alias_people, display_name=row.get('shipped_by') or '')
    payment_status = Order.PAYMENT_STATUS_PAID
    received_at = _parse_tabular_date(row.get('received_at'))
    shipment_status = 'delivered' if received_at and received_at <= timezone.localdate() else 'shipped'
    delivery_provider_name = (row.get('delivery_provider_name') or '').strip()
    delivery_method = _normalize_delivery_method(delivery_provider_name)
    customer_name = _placeholder_client_name(product_name=row.get('product_name') or 'Товар', order_date=order_date)
    if tracker.dry_run:
        tracker.mark('tabular_avito_order', external_key, status=LegacyImportRecord.STATUS_CREATED, source_payload=row)
        tracker.mark('tabular_avito_deal', external_key, status=LegacyImportRecord.STATUS_CREATED, source_payload=row)
        tracker.mark('tabular_avito_item', external_key, status=LegacyImportRecord.STATUS_CREATED, source_payload=row)
        tracker.mark('tabular_avito_finance', external_key, status=LegacyImportRecord.STATUS_CREATED, source_payload=row)
        if row.get('answered_by'):
            tracker.mark('tabular_avito_answered', external_key, status=LegacyImportRecord.STATUS_CREATED, source_payload=row)
        if row.get('shipped_by'):
            tracker.mark('tabular_avito_shipped', external_key, status=LegacyImportRecord.STATUS_CREATED, source_payload=row)
        return
    if isinstance(product, PlannedTarget):
        raise ValueError(f'Не удалось получить товар для Avito-сделки {external_key}.')
    client = _find_or_create_client(name=customer_name, dry_run=False)
    order = _create_import_order(
        order_date=order_date,
        customer_name=customer_name,
        customer_phone='',
        delivery_method=delivery_method,
        delivery_address='',
        delivery_provider_name=delivery_provider_name,
        payment_status=payment_status,
        order_status=_order_status_for_import(payment_status=payment_status, shipment_status=shipment_status),
        total=sale_price_unit * quantity,
    )
    tracker.mark('tabular_avito_order', external_key, status=LegacyImportRecord.STATUS_CREATED, target=order, source_payload=row)
    client.orders.add(order)
    order_item = OrderItem.objects.create(
        order=order,
        product=product,
        quantity=quantity,
        price=sale_price_unit,
        purchase_price=cost_price_unit,
        is_on_request=False,
        variant_name='',
        condition=OrderItem.CONDITION_NEW,
    )
    tracker.mark('tabular_avito_item', external_key, status=LegacyImportRecord.STATUS_CREATED, target=order_item, source_payload=row)
    deal = ManagerDeal.objects.create(
        order=order,
        deal_type=ManagerDeal.DEAL_AVITO,
        deal_status=_deal_status_for_import(deal_type=ManagerDeal.DEAL_AVITO, payment_status=payment_status, shipment_status=shipment_status),
        case_status=ManagerDeal.CASE_STATUS_IN_PROGRESS if shipment_status != 'delivered' else ManagerDeal.CASE_STATUS_COMPLETED,
        payment_state=ManagerDeal.PAYMENT_STATE_PAID,
        buyer_type=ManagerDeal.BUYER_INDIVIDUAL,
        customer_source=ManagerDeal.SOURCE_AVITO,
        deal_created_at=_aware_datetime_for_date(order_date),
        individual_full_name=customer_name,
        customer_request=row.get('product_name') or '',
        delivery_method=delivery_method,
        delivery_provider_name=delivery_provider_name,
        tracking_number='',
        shipment_status=ManagerDeal.SHIPMENT_DELIVERED if shipment_status == 'delivered' else ManagerDeal.SHIPMENT_SENT,
        avito_listing_url=row.get('listing_url') or 'https://www.avito.ru/',
        avito_listing_id=row.get('listing_id') or external_key,
        avito_listing_title=row.get('listing_title') or row.get('product_name') or '',
        avito_contact_channel=row.get('contact_channel') or 'Avito',
        avito_list_price=sale_price_unit,
        avito_final_price=sale_price_unit,
        prepayment_amount=sale_price_unit * quantity,
        shipped_at=received_at or order_date,
        planned_receipt_at=received_at,
        last_activity_at=_aware_datetime_for_date(received_at or order_date),
    )
    tracker.mark('tabular_avito_deal', external_key, status=LegacyImportRecord.STATUS_CREATED, target=deal, source_payload=row)
    ensure_initial_deal_activity(deal)
    recompute_deal_workflow(deal)
    if finance_type is None:
        raise ValueError('Не найден тип финансовой сделки для tabular sales.')
    finance_deal = _create_finance_deal_for_import(
        deal=deal,
        finance_type=finance_type,
        order_date=order_date,
        revenue=sale_price_unit * quantity,
        cost_price=cost_price_unit * quantity,
        direct_expenses=expense_total,
    )
    tracker.mark('tabular_avito_finance', external_key, status=LegacyImportRecord.STATUS_CREATED, target=finance_deal, source_payload=row)
    _create_participant(
        tracker,
        source_model='tabular_avito_answered',
        source_pk=external_key,
        deal=deal,
        role=ManagerDealParticipant.ROLE_ANSWERED,
        person_alias=answered_alias if not isinstance(answered_alias, PlannedTarget) else None,
        source_payload=row,
    )
    _create_participant(
        tracker,
        source_model='tabular_avito_shipped',
        source_pk=external_key,
        deal=deal,
        role=ManagerDealParticipant.ROLE_SHIPPED,
        person_alias=shipped_alias if not isinstance(shipped_alias, PlannedTarget) else None,
        source_payload=row,
    )


def _create_supply_deal(
    tracker: LegacyImportTracker,
    *,
    deal_key: str,
    rows: list[dict[str, str]],
    allocations: list[dict[str, str]],
    alias_products: dict[str, Any],
    alias_people: dict[str, Any],
    finance_type: FinanceDealType | None,
):
    if tracker.has_record('tabular_supply_deal', deal_key):
        tracker.get_target_from_record('tabular_supply_deal', deal_key, ManagerDeal)
        return
    first_row = rows[0]
    order_date = _parse_tabular_date(first_row.get('order_date'))
    if order_date is None:
        tracker.conflict(
            'tabular_supply_deal',
            deal_key,
            conflict_type='missing_date',
            message='Для supply-сделки отсутствует обязательная order_date.',
            source_payload=first_row,
        )
        return
    client_name = (first_row.get('client_name') or '').strip()
    if not client_name:
        tracker.conflict(
            'tabular_supply_deal',
            deal_key,
            conflict_type='missing_client',
            message='Для supply-сделки отсутствует client_name.',
            source_payload=first_row,
        )
        return
    payment_status = first_row.get('payment_status') or 'paid'
    payment_status = Order.PAYMENT_STATUS_UNPAID if payment_status == 'unpaid' else Order.PAYMENT_STATUS_PAID
    shipping_status = (first_row.get('shipping_status') or '').strip().lower()
    shipment_state = 'shipped' if shipping_status == 'shipped' else 'pending'
    delivery_provider_name = (first_row.get('delivery_provider_name') or '').strip()
    delivery_method = _normalize_delivery_method(delivery_provider_name)
    total_revenue = Decimal('0')
    total_cost = Decimal('0')
    if tracker.dry_run:
        tracker.mark('tabular_supply_order', deal_key, status=LegacyImportRecord.STATUS_CREATED, source_payload=first_row)
        tracker.mark('tabular_supply_deal', deal_key, status=LegacyImportRecord.STATUS_CREATED, source_payload=first_row)
        for row in rows:
            tracker.mark(
                'tabular_supply_item',
                row.get('row_key') or f'{deal_key}:{row.get("product_name")}',
                status=LegacyImportRecord.STATUS_CREATED,
                source_payload=row,
            )
            if row.get('owner_name'):
                tracker.mark(
                    'tabular_supply_owner',
                    row.get('row_key') or f'{deal_key}:{row.get("owner_name")}',
                    status=LegacyImportRecord.STATUS_CREATED,
                    source_payload=row,
                )
        for allocation in allocations:
            tracker.mark(
                'tabular_supply_allocation',
                allocation.get('allocation_key') or f'{deal_key}:{allocation.get("person_name")}',
                status=LegacyImportRecord.STATUS_CREATED,
                source_payload=allocation,
            )
        tracker.mark('tabular_supply_finance', deal_key, status=LegacyImportRecord.STATUS_CREATED, source_payload=first_row)
        return
    client = _find_or_create_client(name=client_name, dry_run=False)
    import_warehouse = _ensure_import_warehouse(dry_run=False)
    order = _create_import_order(
        order_date=order_date,
        customer_name=client_name,
        customer_phone='',
        delivery_method=delivery_method,
        delivery_address='',
        delivery_provider_name=delivery_provider_name,
        payment_status=payment_status,
        order_status=_order_status_for_import(payment_status=payment_status, shipment_status=shipment_state),
        total=Decimal('0'),
    )
    tracker.mark('tabular_supply_order', deal_key, status=LegacyImportRecord.STATUS_CREATED, target=order, source_payload=first_row)
    client.orders.add(order)
    created_items: list[tuple[OrderItem, dict[str, str]]] = []
    for row in rows:
        quantity = int(row.get('quantity') or 1)
        sale_price = _parse_decimal(row.get('sale_price'), default=Decimal('0')) or Decimal('0')
        cost_price = _parse_decimal(row.get('cost_price'), default=Decimal('0')) or Decimal('0')
        total_revenue += sale_price * quantity
        total_cost += cost_price * quantity
        product = _resolve_product(
            tracker=tracker,
            alias_map=alias_products,
            product_name=row.get('product_name') or '',
            sale_price=sale_price,
        )
        if isinstance(product, PlannedTarget):
            raise ValueError(f'Не удалось получить товар для supply-сделки {deal_key}.')
        order_item = OrderItem.objects.create(
            order=order,
            product=product,
            quantity=quantity,
            price=sale_price,
            purchase_price=cost_price,
            is_on_request=False,
            variant_name='',
            condition=OrderItem.CONDITION_NEW,
        )
        created_items.append((order_item, row))
        tracker.mark(
            'tabular_supply_item',
            row.get('row_key') or f'{deal_key}:{order_item.pk}',
            status=LegacyImportRecord.STATUS_CREATED,
            target=order_item,
            source_payload=row,
        )
    order.total = total_revenue
    order.save(update_fields=['total', 'updated_at'])
    deal = ManagerDeal.objects.create(
        order=order,
        deal_type=ManagerDeal.DEAL_SALE_FROM_STOCK,
        deal_status=_deal_status_for_import(deal_type=ManagerDeal.DEAL_SALE_FROM_STOCK, payment_status=payment_status, shipment_status=shipment_state),
        case_status=ManagerDeal.CASE_STATUS_IN_PROGRESS if shipment_state == 'shipped' else ManagerDeal.CASE_STATUS_CONFIRMED,
        payment_state=ManagerDeal.PAYMENT_STATE_PAID if payment_status == Order.PAYMENT_STATUS_PAID else ManagerDeal.PAYMENT_STATE_UNPAID,
        buyer_type=ManagerDeal.BUYER_BUSINESS if _is_business_customer(client_name) else ManagerDeal.BUYER_INDIVIDUAL,
        customer_source=ManagerDeal.SOURCE_OTHER,
        deal_created_at=_aware_datetime_for_date(order_date),
        individual_full_name='' if _is_business_customer(client_name) else client_name,
        business_company_name=client_name if _is_business_customer(client_name) else '',
        customer_request=', '.join(row.get('product_name') or '' for row in rows if row.get('product_name')),
        delivery_method=delivery_method,
        delivery_provider_name=delivery_provider_name,
        stock_warehouse=import_warehouse,
        shipment_status=ManagerDeal.SHIPMENT_SENT if shipment_state == 'shipped' else ManagerDeal.SHIPMENT_DRAFT,
        prepayment_amount=total_revenue if payment_status == Order.PAYMENT_STATUS_PAID else Decimal('0'),
        last_activity_at=_aware_datetime_for_date(order_date),
    )
    tracker.mark('tabular_supply_deal', deal_key, status=LegacyImportRecord.STATUS_CREATED, target=deal, source_payload=first_row)
    ensure_initial_deal_activity(deal)
    recompute_deal_workflow(deal)
    if finance_type is None:
        raise ValueError('Не найден тип финансовой сделки для tabular sales.')
    finance_deal = _create_finance_deal_for_import(
        deal=deal,
        finance_type=finance_type,
        order_date=order_date,
        revenue=total_revenue,
        cost_price=total_cost,
        direct_expenses=Decimal('0'),
    )
    tracker.mark('tabular_supply_finance', deal_key, status=LegacyImportRecord.STATUS_CREATED, target=finance_deal, source_payload=first_row)
    for order_item, row in created_items:
        owner_alias = _resolve_person_alias(tracker=tracker, alias_map=alias_people, display_name=row.get('owner_name') or '')
        _create_participant(
            tracker,
            source_model='tabular_supply_owner',
            source_pk=row.get('row_key') or f'{deal_key}:{order_item.pk}:owner',
            deal=deal,
            role=ManagerDealParticipant.ROLE_ITEM_OWNER,
            person_alias=owner_alias if not isinstance(owner_alias, PlannedTarget) else None,
            order_item=order_item,
            quantity_basis=order_item.quantity,
            note=row.get('shipping_status') or '',
            source_payload=row,
        )
        answered_alias = _resolve_person_alias(tracker=tracker, alias_map=alias_people, display_name=row.get('answered_by') or '')
        if answered_alias is not None:
            _create_participant(
                tracker,
                source_model='tabular_supply_answered',
                source_pk=row.get('row_key') or f'{deal_key}:{order_item.pk}:answered',
                deal=deal,
                role=ManagerDealParticipant.ROLE_ANSWERED,
                person_alias=answered_alias if not isinstance(answered_alias, PlannedTarget) else None,
                source_payload=row,
            )
        shipped_alias = _resolve_person_alias(tracker=tracker, alias_map=alias_people, display_name=row.get('shipped_by') or '')
        if shipped_alias is not None:
            _create_participant(
                tracker,
                source_model='tabular_supply_shipped',
                source_pk=row.get('row_key') or f'{deal_key}:{order_item.pk}:shipped',
                deal=deal,
                role=ManagerDealParticipant.ROLE_SHIPPED,
                person_alias=shipped_alias if not isinstance(shipped_alias, PlannedTarget) else None,
                source_payload=row,
            )
    for allocation in allocations:
        amount = _parse_decimal(allocation.get('amount'), default=Decimal('0')) or Decimal('0')
        quantity_basis = int(allocation.get('quantity_basis') or 0) or None
        person_alias = _resolve_person_alias(tracker=tracker, alias_map=alias_people, display_name=allocation.get('person_name') or '')
        _create_participant(
            tracker,
            source_model='tabular_supply_allocation',
            source_pk=allocation.get('allocation_key') or f'{deal_key}:{allocation.get("person_name")}',
            deal=deal,
            role=ManagerDealParticipant.ROLE_PLANNED_PROFIT_SHARE,
            person_alias=person_alias if not isinstance(person_alias, PlannedTarget) else None,
            amount=amount,
            quantity_basis=quantity_basis,
            note='planned allocation',
            source_payload=allocation,
        )


def import_manager_tabular_sales(source: str | Path, *, dry_run: bool):
    source_dir = Path(source).expanduser().resolve()
    tracker = LegacyImportTracker(
        source_system=LegacyImportBatch.SOURCE_TABULAR_SALES,
        source_ref=str(source_dir),
        dry_run=dry_run,
    )
    try:
        file_map = _require_files(
            source_dir,
            'avito_deals.csv',
            'supply_deals.csv',
            'supply_allocations.csv',
            'product_aliases.json',
            'people_aliases.json',
        )
        avito_rows = _load_csv_rows(file_map['avito_deals.csv'])
        supply_rows = _load_csv_rows(file_map['supply_deals.csv'])
        allocation_rows = _load_csv_rows(file_map['supply_allocations.csv'])
        product_aliases = _load_json_file(file_map['product_aliases.json']) or {}
        people_aliases = _load_json_file(file_map['people_aliases.json']) or {}
        if not isinstance(product_aliases, dict) or not isinstance(people_aliases, dict):
            raise ValueError('product_aliases.json и people_aliases.json должны содержать JSON-object.')
        finance_type = _tabular_import_finance_type(dry_run=dry_run)
        grouped_supply_rows: dict[str, list[dict[str, str]]] = {}
        for row in supply_rows:
            deal_key = (row.get('deal_key') or '').strip()
            if not deal_key:
                tracker.conflict(
                    'tabular_supply_deal',
                    row.get('row_key') or 'missing-deal-key',
                    conflict_type='missing_deal_key',
                    message='В строке supply_deals.csv отсутствует deal_key.',
                    source_payload=row,
                )
                continue
            grouped_supply_rows.setdefault(deal_key, []).append(row)
        grouped_allocations: dict[str, list[dict[str, str]]] = {}
        for row in allocation_rows:
            deal_key = (row.get('deal_key') or '').strip()
            if not deal_key:
                tracker.conflict(
                    'tabular_supply_allocation',
                    row.get('allocation_key') or 'missing-deal-key',
                    conflict_type='missing_deal_key',
                    message='В строке supply_allocations.csv отсутствует deal_key.',
                    source_payload=row,
                )
                continue
            grouped_allocations.setdefault(deal_key, []).append(row)
        with transaction.atomic():
            for row in avito_rows:
                _create_avito_deal(
                    tracker,
                    row=row,
                    alias_products=product_aliases,
                    alias_people=people_aliases,
                    finance_type=finance_type,
                )
            for deal_key, rows in grouped_supply_rows.items():
                _create_supply_deal(
                    tracker,
                    deal_key=deal_key,
                    rows=rows,
                    allocations=grouped_allocations.get(deal_key, []),
                    alias_products=product_aliases,
                    alias_people=people_aliases,
                    finance_type=finance_type,
                )
            if dry_run:
                transaction.set_rollback(True)
        return tracker.finish(status=LegacyImportBatch.STATUS_COMPLETED)
    except Exception as exc:
        return tracker.finish(status=LegacyImportBatch.STATUS_FAILED, error_text=str(exc))
