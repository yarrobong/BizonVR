import time

from django.contrib import messages
from django.shortcuts import redirect, render

from catalog.models import ContactRequest
from config.utils.spam_protection import is_spam_request

from ..forms import ContactForm
from ..legal_consent import build_legal_acceptance_payload


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
        if is_spam_request(request):
            messages.success(request, 'Спасибо! Ваше сообщение отправлено. Мы свяжемся с вами в ближайшее время.')
            return redirect('contacts')
        form = ContactForm(request.POST)
        if form.is_valid():
            ContactRequest.objects.create(
                name=form.cleaned_data['name'],
                email=form.cleaned_data.get('email', ''),
                phone=form.cleaned_data.get('phone', ''),
                message=form.cleaned_data['message'],
                **build_legal_acceptance_payload(request),
            )
            messages.success(request, 'Спасибо! Ваше сообщение отправлено. Мы свяжемся с вами в ближайшее время.')
            return redirect('contacts')
    return render(request, 'contacts.html', {'form': form, 'form_started_at': int(time.time())})
