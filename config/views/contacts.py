import logging
import time

from django.contrib import messages
from django.shortcuts import redirect, render
try:
    from django_ratelimit.decorators import ratelimit
except ImportError:
    def ratelimit(*args, **kwargs):
        def decorator(view):
            return view
        return decorator

from catalog.models import ContactRequest
from config.crm_leads import send_crm_lead_email
from config.utils.spam_protection import check_spam_submission, log_blocked_submission
from integrations.bitrix_site_requests import (
    BitrixSiteRequestSyncError,
    create_site_lead_request,
    send_site_request_to_bitrix,
    summarize_spam_check,
)
from integrations.models import SiteLeadRequest

from ..forms import ContactForm
from ..legal_consent import build_legal_acceptance_payload

logger = logging.getLogger(__name__)


def _build_prefilled_contact_message(request):
    direct_message = (request.GET.get('message') or '').strip()
    if direct_message:
        return direct_message

    site_context = (request.GET.get('site_context') or '').strip()
    site_comment = (request.GET.get('site_comment') or '').strip()
    parts = []
    if site_context:
        parts.append(f'Город и тип площадки: {site_context}')
    if site_comment:
        if parts:
            parts.append('')
        parts.append(f'Комментарий: {site_comment}')
    return '\n'.join(parts)


@ratelimit(key='ip', rate='10/m', method='POST', block=False)
def contacts_view(request):
    """Страница контактов: форма обратной связи и контактная информация."""
    initial = {
        'name': (request.GET.get('name') or '').strip(),
        'email': (request.GET.get('email') or '').strip(),
        'phone': (request.GET.get('phone') or '').strip(),
        'message': _build_prefilled_contact_message(request),
    }
    form = ContactForm(initial=initial)
    if request.method == 'POST':
        spam_result = check_spam_submission(request)
        if spam_result.is_spam:
            log_blocked_submission(request, source='contacts', result=spam_result)
            spam_status, spam_reason = summarize_spam_check(spam_result)
            create_site_lead_request(
                request=request,
                source_type=SiteLeadRequest.SOURCE_CONTACTS,
                name=request.POST.get('name', ''),
                phone=request.POST.get('phone', ''),
                email=request.POST.get('email', ''),
                message=request.POST.get('message', ''),
                spam_status=spam_status,
                spam_reason=spam_reason,
            )
            messages.success(request, 'Спасибо! Ваше сообщение отправлено. Мы свяжемся с вами в ближайшее время.')
            return redirect('contacts')
        form = ContactForm(request.POST)
        if form.is_valid():
            contact_request = ContactRequest.objects.create(
                name=form.cleaned_data['name'],
                email=form.cleaned_data.get('email', ''),
                phone=form.cleaned_data.get('phone', ''),
                message=form.cleaned_data['message'],
                **build_legal_acceptance_payload(request),
            )
            spam_status, spam_reason = summarize_spam_check(spam_result)
            site_request = create_site_lead_request(
                request=request,
                source_type=SiteLeadRequest.SOURCE_CONTACTS,
                name=contact_request.name,
                phone=contact_request.phone,
                email=contact_request.email,
                message=contact_request.message,
                spam_status=spam_status,
                spam_reason=spam_reason,
            )
            try:
                send_site_request_to_bitrix(site_request)
            except BitrixSiteRequestSyncError:
                logger.exception('Bitrix sync failed for contacts site request %s.', site_request.pk)
            send_crm_lead_email(
                request=request,
                form_type='Контакты',
                name=contact_request.name,
                phone=contact_request.phone,
                email=contact_request.email,
                comment=contact_request.message,
                created_at=contact_request.created_at,
            )
            messages.success(request, 'Спасибо! Ваше сообщение отправлено. Мы свяжемся с вами в ближайшее время.')
            return redirect('contacts')
    return render(request, 'contacts.html', {'form': form, 'form_started_at': int(time.time())})
