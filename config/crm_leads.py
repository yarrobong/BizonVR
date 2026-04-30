"""Plain text lead notifications for external CRM mailboxes."""
import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

logger = logging.getLogger(__name__)


def _clean(value):
    return str(value or '').strip()


def _build_subject_identity(*, name='', phone='', email=''):
    parts = []
    if _clean(phone):
        parts.append(_clean(phone))
    elif _clean(email):
        parts.append(_clean(email))
    if _clean(name):
        parts.append(_clean(name))
    if not parts and _clean(email):
        parts.append(_clean(email))
    return ' — '.join(parts) if parts else 'без контактов'


def _build_page_url(request, page_url=''):
    page_url = _clean(page_url)
    if page_url.startswith(('http://', 'https://')):
        return page_url
    if request is None:
        return page_url
    if page_url:
        return request.build_absolute_uri(page_url)
    return request.build_absolute_uri(request.path)


def _format_date(value=None):
    dt = value or timezone.now()
    return timezone.localtime(dt).strftime('%d.%m.%Y %H:%M:%S %Z')


def build_crm_lead_email_body(
    *,
    form_type,
    name='',
    phone='',
    email='',
    city='',
    product_or_service='',
    comment='',
    page_url='',
    created_at=None,
):
    lines = [
        f'Тип формы: {_clean(form_type)}',
        f'Имя: {_clean(name)}',
        f'Телефон: {_clean(phone)}',
        f'Email: {_clean(email)}',
        f'Город: {_clean(city)}',
        f'Товар/услуга: {_clean(product_or_service)}',
        f'Страница: {_clean(page_url)}',
        f'Дата: {_format_date(created_at)}',
        '',
        'Комментарий:',
        _clean(comment),
    ]
    return '\n'.join(lines)


def send_crm_lead_email(
    *,
    request=None,
    form_type,
    name='',
    phone='',
    email='',
    city='',
    product_or_service='',
    comment='',
    page_url='',
    created_at=None,
):
    recipient = _clean(getattr(settings, 'CRM_LEADS_EMAIL', ''))
    if not recipient:
        return False

    resolved_page_url = _build_page_url(request, page_url)
    subject_identity = _build_subject_identity(name=name, phone=phone, email=email)
    message = EmailMessage(
        subject=f'Заявка с сайта BizonVR: {subject_identity}',
        body=build_crm_lead_email_body(
            form_type=form_type,
            name=name,
            phone=phone,
            email=email,
            city=city,
            product_or_service=product_or_service,
            comment=comment,
            page_url=resolved_page_url,
            created_at=created_at,
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        reply_to=[_clean(email)] if _clean(email) else None,
    )
    try:
        message.send(fail_silently=False)
    except Exception:
        logger.exception('Failed to send CRM lead email.')
        return False
    return True
