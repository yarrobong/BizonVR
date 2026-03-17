from __future__ import annotations

from django.utils import timezone

from .models import Cargo, ContractDocument, ManagerClient, ManagerDeal, Reservation, Shipment

SEMANTIC_TONE_CRITICAL = 'critical'
SEMANTIC_TONE_ATTENTION = 'attention'
SEMANTIC_TONE_ACTIVE = 'active'
SEMANTIC_TONE_COMPLETE = 'complete'
SEMANTIC_TONE_UNKNOWN = 'unknown'

SEMANTIC_TONES = {
    SEMANTIC_TONE_CRITICAL,
    SEMANTIC_TONE_ATTENTION,
    SEMANTIC_TONE_ACTIVE,
    SEMANTIC_TONE_COMPLETE,
    SEMANTIC_TONE_UNKNOWN,
}


def normalize_semantic_tone(value):
    tone = (value or '').strip()
    return tone if tone in SEMANTIC_TONES else SEMANTIC_TONE_UNKNOWN


def build_semantic_status(label, *, tone=SEMANTIC_TONE_UNKNOWN, detail='', meta='', href=''):
    return {
        'label': label,
        'tone': normalize_semantic_tone(tone),
        'detail': detail,
        'meta': meta,
        'href': href,
    }


def _extract_tone(value):
    if isinstance(value, dict):
        return normalize_semantic_tone(value.get('tone'))
    return normalize_semantic_tone(value)


def semantic_badge_classes(value):
    tone = _extract_tone(value)
    return f'manager-semantic-badge manager-semantic-badge-{tone}'


def semantic_text_classes(value):
    tone = _extract_tone(value)
    return f'manager-semantic-text manager-semantic-text-{tone}'


def semantic_surface_classes(value):
    tone = _extract_tone(value)
    return f'manager-semantic-surface manager-semantic-surface-{tone}'


def semantic_risk_classes(value):
    tone = _extract_tone(value)
    return f'manager-risk-block manager-risk-block-{tone}'


def deal_case_status_tone(case_status):
    if case_status in {ManagerDeal.CASE_STATUS_COMPLETED, ManagerDeal.CASE_STATUS_READY_TO_SHIP}:
        return SEMANTIC_TONE_COMPLETE
    if case_status == ManagerDeal.CASE_STATUS_CANCELLED:
        return SEMANTIC_TONE_UNKNOWN
    return SEMANTIC_TONE_ACTIVE


def deal_primary_status(deal):
    return build_semantic_status(
        deal.get_case_status_display(),
        tone=deal_case_status_tone(deal.case_status),
        detail=deal.get_deal_type_display(),
    )


def _deal_secondary_tone(deal, *, now=None):
    now = now or timezone.now()
    if deal.case_status == ManagerDeal.CASE_STATUS_COMPLETED or deal.next_step_code == ManagerDeal.NEXT_STEP_COMPLETED:
        return SEMANTIC_TONE_COMPLETE
    if deal.case_status == ManagerDeal.CASE_STATUS_CANCELLED:
        return SEMANTIC_TONE_UNKNOWN
    if deal.sla_due_at:
        if deal.sla_breached_at or deal.sla_due_at <= now:
            return SEMANTIC_TONE_CRITICAL
        if timezone.localtime(deal.sla_due_at).date() <= timezone.localdate():
            return SEMANTIC_TONE_ATTENTION
        return SEMANTIC_TONE_ACTIVE
    return SEMANTIC_TONE_UNKNOWN


def deal_secondary_status(deal, *, now=None):
    now = now or timezone.now()
    tone = _deal_secondary_tone(deal, now=now)
    detail = 'SLA не задан'
    if deal.sla_due_at:
        detail = f'SLA до {timezone.localtime(deal.sla_due_at):%d.%m %H:%M}'
        if tone == SEMANTIC_TONE_CRITICAL:
            detail = f'Просрочено с {timezone.localtime(deal.sla_due_at):%d.%m %H:%M}'
    return build_semantic_status(
        deal.next_step_label or 'Следующий шаг не задан',
        tone=tone,
        detail=detail,
        meta='Ручной сценарий' if deal.next_step_source == ManagerDeal.NEXT_STEP_SOURCE_MANUAL else '',
    )


DEAL_PROBLEM_TONES = {
    ManagerDeal.PROBLEM_FLAG_SLA_OVERDUE: SEMANTIC_TONE_CRITICAL,
    ManagerDeal.PROBLEM_FLAG_STOCK_CONFLICT: SEMANTIC_TONE_CRITICAL,
    ManagerDeal.PROBLEM_FLAG_PAYMENT_BLOCKED: SEMANTIC_TONE_CRITICAL,
    ManagerDeal.PROBLEM_FLAG_SHIPMENT_BLOCKED: SEMANTIC_TONE_CRITICAL,
    ManagerDeal.PROBLEM_FLAG_MISSING_DOCUMENTS: SEMANTIC_TONE_ATTENTION,
    ManagerDeal.PROBLEM_FLAG_NO_ASSIGNEE: SEMANTIC_TONE_ATTENTION,
}


def deal_problem_tone(flag):
    return DEAL_PROBLEM_TONES.get(flag, SEMANTIC_TONE_ATTENTION)


def aggregate_risk_summary(*, labels, tone, detail=''):
    label = labels[0] if labels else 'Рисков нет'
    if labels and len(labels) > 1:
        detail = f'{detail} Еще {len(labels) - 1}.' if detail else f'Еще {len(labels) - 1}.'
    return build_semantic_status(label, tone=tone, detail=detail)


def deal_risk_summary(deal, *, blockers=None):
    blockers = blockers or []
    if deal.case_status == ManagerDeal.CASE_STATUS_CANCELLED:
        return build_semantic_status('Риски не отслеживаются', tone=SEMANTIC_TONE_UNKNOWN)

    if blockers:
        tones = [_extract_tone(blocker.get('tone')) for blocker in blockers]
        if SEMANTIC_TONE_CRITICAL in tones:
            tone = SEMANTIC_TONE_CRITICAL
        elif SEMANTIC_TONE_ATTENTION in tones:
            tone = SEMANTIC_TONE_ATTENTION
        else:
            tone = SEMANTIC_TONE_COMPLETE
        labels = [blocker['text'] for blocker in blockers if blocker.get('text')]
        return aggregate_risk_summary(labels=labels, tone=tone, detail='Нужна проверка')

    problem_labels = list(deal.problem_flag_labels or [])
    if problem_labels:
        tones = [deal_problem_tone(flag) for flag in (deal.problem_flags or [])]
        tone = SEMANTIC_TONE_CRITICAL if SEMANTIC_TONE_CRITICAL in tones else SEMANTIC_TONE_ATTENTION
        return aggregate_risk_summary(labels=problem_labels, tone=tone, detail='Есть открытые сигналы')

    if deal.responsible_manager_id is None:
        return build_semantic_status('Без ответственного', tone=SEMANTIC_TONE_ATTENTION, detail='Назначьте менеджера')

    if deal.customer_deadline and deal.customer_deadline < timezone.localdate():
        return build_semantic_status(
            'Дедлайн клиента истек',
            tone=SEMANTIC_TONE_ATTENTION,
            detail=f'{deal.customer_deadline:%d.%m.%Y}',
        )

    if deal.case_status == ManagerDeal.CASE_STATUS_COMPLETED:
        return build_semantic_status('Рисков нет', tone=SEMANTIC_TONE_COMPLETE, detail='Сделка завершена')

    return build_semantic_status('Рисков нет', tone=SEMANTIC_TONE_COMPLETE, detail='Критичных блокеров нет')


def manager_client_status(client):
    tone = SEMANTIC_TONE_ACTIVE if client.status == ManagerClient.STATUS_ACTIVE else SEMANTIC_TONE_UNKNOWN
    return build_semantic_status(client.get_status_display(), tone=tone)


def cargo_status(cargo):
    tone_map = {
        Cargo.STATUS_CREATED: SEMANTIC_TONE_UNKNOWN,
        Cargo.STATUS_IN_TRANSIT: SEMANTIC_TONE_ACTIVE,
        Cargo.STATUS_ARRIVED_RF: SEMANTIC_TONE_ACTIVE,
        Cargo.STATUS_DELIVERY_RF: SEMANTIC_TONE_ACTIVE,
        Cargo.STATUS_AWAITING_RECEIPT: SEMANTIC_TONE_ATTENTION,
        Cargo.STATUS_RECEIVED: SEMANTIC_TONE_COMPLETE,
        Cargo.STATUS_CANCELLED: SEMANTIC_TONE_UNKNOWN,
    }
    return build_semantic_status(cargo.get_status_display(), tone=tone_map.get(cargo.status))


def reservation_status(reservation):
    tone_map = {
        Reservation.STATUS_DRAFT: SEMANTIC_TONE_UNKNOWN,
        Reservation.STATUS_ACTIVE: SEMANTIC_TONE_ACTIVE,
        Reservation.STATUS_PARTIAL: SEMANTIC_TONE_ATTENTION,
        Reservation.STATUS_FULFILLED: SEMANTIC_TONE_COMPLETE,
        Reservation.STATUS_CANCELLED: SEMANTIC_TONE_UNKNOWN,
        Reservation.STATUS_EXPIRED: SEMANTIC_TONE_UNKNOWN,
    }
    return build_semantic_status(reservation.get_status_display(), tone=tone_map.get(reservation.status))


def shipment_status(shipment):
    tone_map = {
        Shipment.STATUS_DRAFT: SEMANTIC_TONE_UNKNOWN,
        Shipment.STATUS_PENDING: SEMANTIC_TONE_ACTIVE,
        Shipment.STATUS_SHIPPED: SEMANTIC_TONE_ACTIVE,
        Shipment.STATUS_DELIVERED: SEMANTIC_TONE_COMPLETE,
        Shipment.STATUS_CANCELLED: SEMANTIC_TONE_UNKNOWN,
    }
    return build_semantic_status(shipment.get_status_display(), tone=tone_map.get(shipment.status))


def contract_document_status(document):
    tone_map = {
        ContractDocument.STATUS_DRAFT: SEMANTIC_TONE_ATTENTION,
        ContractDocument.STATUS_REVIEW: SEMANTIC_TONE_ACTIVE,
        ContractDocument.STATUS_SENT: SEMANTIC_TONE_ACTIVE,
        ContractDocument.STATUS_SIGNED: SEMANTIC_TONE_COMPLETE,
        ContractDocument.STATUS_PAID: SEMANTIC_TONE_COMPLETE,
        ContractDocument.STATUS_ARCHIVED: SEMANTIC_TONE_UNKNOWN,
    }
    return build_semantic_status(document.get_status_display(), tone=tone_map.get(document.status))


def semantic_status_for_value(value, *, kind=''):
    if isinstance(value, dict) and 'label' in value and 'tone' in value:
        return build_semantic_status(
            value['label'],
            tone=value.get('tone'),
            detail=value.get('detail', ''),
            meta=value.get('meta', ''),
            href=value.get('href', ''),
        )

    if isinstance(value, ManagerDeal) or kind == 'deal_primary':
        return deal_primary_status(value)
    if isinstance(value, ManagerClient) or kind == 'client':
        return manager_client_status(value)
    if isinstance(value, Cargo) or kind == 'cargo':
        return cargo_status(value)
    if isinstance(value, Reservation) or kind == 'reservation':
        return reservation_status(value)
    if isinstance(value, Shipment) or kind == 'shipment':
        return shipment_status(value)
    if isinstance(value, ContractDocument) or kind == 'contract_document':
        return contract_document_status(value)

    return build_semantic_status(str(value or '—'), tone=SEMANTIC_TONE_UNKNOWN)
